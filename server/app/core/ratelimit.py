"""Rate and concurrency limits for the inference gateway.

``memory`` (default) keeps counters in-process: correct for a single API process. ``redis`` shares them
across replicas (COORDINATION_BACKEND=redis). Concurrency slots in Redis expire, so a replica that crashes
mid-request cannot leak a slot forever.
"""

import time
from collections import defaultdict, deque
from typing import Protocol

CONCURRENCY_SLOT_TTL_SECONDS = 900


class RateLimiter(Protocol):
    async def allow(self, key: str, limit: int) -> tuple[bool, float]: ...
    def reset(self) -> None: ...


class ConcurrencyLimiter(Protocol):
    async def acquire(self, key: str, limit: int) -> bool: ...
    async def release(self, key: str) -> None: ...
    def reset(self) -> None: ...


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0):
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def allow(self, key: str, limit: int) -> tuple[bool, float]:
        """Record a hit if under ``limit``. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= limit:
            return False, max(0.0, self.window - (now - hits[0]))
        hits.append(now)
        return True, 0.0

    def reset(self) -> None:
        self._hits.clear()


class InProcessConcurrencyLimiter:
    def __init__(self) -> None:
        self._active: dict[str, int] = defaultdict(int)

    async def acquire(self, key: str, limit: int) -> bool:
        if self._active[key] >= limit:
            return False
        self._active[key] += 1
        return True

    async def release(self, key: str) -> None:
        self._active[key] = max(0, self._active[key] - 1)
        if not self._active[key]:
            del self._active[key]

    def reset(self) -> None:
        self._active.clear()


class RedisWindowLimiter:
    """Fixed one-minute windows shared by all replicas."""

    def __init__(self, redis, window_seconds: int = 60):
        self.redis = redis
        self.window = window_seconds

    async def allow(self, key: str, limit: int) -> tuple[bool, float]:
        now = time.time()
        bucket = int(now // self.window)
        rkey = f"rl:{key}:{bucket}"
        count = await self.redis.incr(rkey)
        if count == 1:
            await self.redis.expire(rkey, self.window + 5)
        if count > limit:
            return False, self.window - (now % self.window)
        return True, 0.0

    def reset(self) -> None:  # state lives in Redis
        pass


class RedisConcurrencyLimiter:
    _ACQUIRE = """
    local n = redis.call('INCR', KEYS[1])
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    if n > tonumber(ARGV[1]) then
        redis.call('DECR', KEYS[1])
        return 0
    end
    return 1
    """
    _RELEASE = """
    local n = redis.call('DECR', KEYS[1])
    if n <= 0 then redis.call('DEL', KEYS[1]) end
    return n
    """

    def __init__(self, redis):
        self.redis = redis

    async def acquire(self, key: str, limit: int) -> bool:
        ok = await self.redis.eval(self._ACQUIRE, 1, f"cc:{key}", limit, CONCURRENCY_SLOT_TTL_SECONDS)
        return bool(int(ok))

    async def release(self, key: str) -> None:
        await self.redis.eval(self._RELEASE, 1, f"cc:{key}")

    def reset(self) -> None:
        pass


class _Limiters:
    """Holds the active implementations so they can be swapped at startup (or in tests)."""

    def __init__(self) -> None:
        self.requests: RateLimiter = SlidingWindowLimiter()
        self.concurrency: ConcurrencyLimiter = InProcessConcurrencyLimiter()

    def use_redis(self, redis) -> None:
        self.requests = RedisWindowLimiter(redis)
        self.concurrency = RedisConcurrencyLimiter(redis)

    def use_memory(self) -> None:
        self.requests = SlidingWindowLimiter()
        self.concurrency = InProcessConcurrencyLimiter()


limiters = _Limiters()
