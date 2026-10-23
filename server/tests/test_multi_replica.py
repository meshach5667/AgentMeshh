"""Multi-replica coordination over Redis (fakeredis here; CI also runs two real API replicas on real Redis).

Replica A receives the gateway request; the worker's tunnel is held by replica B.
"""

import asyncio
import json
import uuid

import fakeredis
import pytest

from app.core.ratelimit import RedisConcurrencyLimiter, RedisWindowLimiter, limiters
from app.services.tunnel import NodeUnavailable, RedisCoordinator, TunnelBroker, WorkerConnection

NODE = uuid.uuid4()


class Worker:
    """Fake worker attached to one replica's broker."""

    def __init__(self, node_id=NODE, chunks=3, delay=0.0):
        self.received: list[dict] = []
        self.cancelled: list[str] = []
        self.closed = False
        self.chunks = chunks
        self.delay = delay
        self.conn = WorkerConnection(node_id=node_id, send_json=self._on_send, close=self._close)

    async def _close(self):
        self.closed = True

    async def _on_send(self, frame):
        if frame["type"] == "cancel":
            self.cancelled.append(frame["id"])
            return
        self.received.append(frame)
        asyncio.get_running_loop().create_task(self._respond(frame["id"]))

    async def _respond(self, rid):
        self.conn.dispatch({"type": "response_start", "id": rid, "status": 200, "content_type": "application/x-ndjson"})
        for i in range(self.chunks):
            await asyncio.sleep(self.delay)
            if rid not in self.conn.pending:
                return  # cancelled
            self.conn.dispatch({"type": "chunk", "id": rid, "data": f"{i}\n"})
        self.conn.dispatch({"type": "response_end", "id": rid})


@pytest.fixture
async def replicas():
    server = fakeredis.FakeServer()
    redis_a = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    redis_b = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    a, b = TunnelBroker(), TunnelBroker()
    a.coordinator = RedisCoordinator(redis_a, a, "replica-a")
    b.coordinator = RedisCoordinator(redis_b, b, "replica-b")
    await a.coordinator.start()
    await b.coordinator.start()
    yield a, b, redis_a
    await a.coordinator.stop()
    await b.coordinator.stop()


async def _collect(queue, timeout=2.0):
    frames = []
    while True:
        frame = await asyncio.wait_for(queue.get(), timeout)
        frames.append(frame)
        if frame["type"] in ("response_end", "error"):
            return frames


async def test_request_is_routed_to_the_replica_holding_the_worker(replicas):
    a, b, redis = replicas
    worker = Worker(chunks=50)
    await b.register(worker.conn)
    assert await redis.get(f"tunnel:node:{NODE}") == "replica-b"

    handle, rid, queue = await a.open_request(NODE, {"type": "request", "id": "r1", "path": "/api/chat"})
    frames = await _collect(queue)
    assert worker.received[0]["id"] == "r1"
    assert [f["type"] for f in frames][0] == "response_start" and frames[-1]["type"] == "response_end"
    assert "".join(f["data"] for f in frames if f["type"] == "chunk") == "".join(f"{i}\n" for i in range(50))
    a.close_request(handle, rid)
    assert "r1" not in b._connections[NODE].pending  # owner cleaned up after the end frame


async def test_cancel_crosses_replicas(replicas):
    a, b, _ = replicas
    worker = Worker(chunks=100, delay=0.01)
    await b.register(worker.conn)
    handle, rid, queue = await a.open_request(NODE, {"type": "request", "id": "r2"})
    await asyncio.wait_for(queue.get(), 2)  # response_start
    await handle.send({"type": "cancel", "id": rid})
    for _ in range(50):
        if worker.cancelled:
            break
        await asyncio.sleep(0.02)
    assert worker.cancelled == ["r2"]


async def test_worker_disconnect_on_owner_fails_remote_request(replicas):
    a, b, _ = replicas
    worker = Worker(chunks=100, delay=0.05)
    await b.register(worker.conn)
    _, _, queue = await a.open_request(NODE, {"type": "request", "id": "r3"})
    await asyncio.wait_for(queue.get(), 2)
    b.unregister(worker.conn)
    frames = await _collect(queue)
    assert frames[-1]["code"] == "node_disconnected"


async def test_unknown_or_stale_owner_is_unavailable(replicas):
    a, _, redis = replicas
    with pytest.raises(NodeUnavailable):
        await a.open_request(uuid.uuid4(), {"type": "request", "id": "r4"})
    ghost = uuid.uuid4()
    await redis.set(f"tunnel:node:{ghost}", "replica-that-crashed")  # nobody subscribed to its channel
    with pytest.raises(NodeUnavailable):
        await a.open_request(ghost, {"type": "request", "id": "r5"})


async def test_release_only_by_current_owner(replicas):
    a, b, redis = replicas
    worker_b = Worker()
    await b.register(worker_b.conn)
    worker_a = Worker()
    await a.register(worker_a.conn)  # worker reconnected to replica A
    assert await redis.get(f"tunnel:node:{NODE}") == "replica-a"
    b.unregister(worker_b.conn)  # B's stale connection closing must not erase A's claim
    await asyncio.sleep(0.05)
    assert await redis.get(f"tunnel:node:{NODE}") == "replica-a"


async def test_close_node_reaches_the_owner(replicas):
    a, b, _ = replicas
    worker = Worker()
    await b.register(worker.conn)
    await a.close_node(NODE)
    for _ in range(50):
        if worker.closed:
            break
        await asyncio.sleep(0.02)
    assert worker.closed and NODE not in b._connections


async def test_redis_rate_limit_is_shared_across_replicas():
    server = fakeredis.FakeServer()
    a = RedisWindowLimiter(fakeredis.FakeAsyncRedis(server=server, decode_responses=True))
    b = RedisWindowLimiter(fakeredis.FakeAsyncRedis(server=server, decode_responses=True))
    results = [await (a if i % 2 else b).allow("key:1", 3) for i in range(4)]
    assert [r[0] for r in results] == [True, True, True, False]
    assert results[-1][1] > 0


async def test_redis_concurrency_is_shared_and_expires():
    server = fakeredis.FakeServer()
    redis = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    a = RedisConcurrencyLimiter(redis)
    b = RedisConcurrencyLimiter(fakeredis.FakeAsyncRedis(server=server, decode_responses=True))
    assert await a.acquire("dep", 2) and await b.acquire("dep", 2)
    assert not await a.acquire("dep", 2)
    await b.release("dep")
    assert await a.acquire("dep", 2)
    assert await redis.ttl("cc:dep") > 0  # a crashed replica cannot leak slots forever


async def test_gateway_streams_through_another_replica(client, db, make_user, enroll_node, ollama_model):
    """Full gateway path: the app's broker is replica A, the worker is connected to replica B."""
    from sqlalchemy import select

    from app.models import UsageRecord
    from app.services.tunnel import broker as app_broker

    server = fakeredis.FakeServer()
    redis_a = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    other = TunnelBroker()
    other.coordinator = RedisCoordinator(fakeredis.FakeAsyncRedis(server=server, decode_responses=True), other, "b")
    app_broker.coordinator = RedisCoordinator(redis_a, app_broker, "a")
    limiters.use_redis(redis_a)
    await app_broker.coordinator.start()
    await other.coordinator.start()
    try:
        node = await enroll_node()
        _, customer = await make_user("customer")
        dep = (
            await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)
        ).json()
        await client.post(
            f"/api/v1/worker/deployments/{dep['id']}/status", json={"state": "READY"}, headers=node["headers"]
        )
        worker = Worker(node_id=uuid.UUID(node["node_id"]), chunks=3)
        worker.conn.send_json = worker._on_send
        await other.register(worker.conn)

        resp = await client.post(
            f"/api/v1/deployments/{dep['id']}/ollama/api/chat", json={"messages": []}, headers=customer
        )
        assert resp.status_code == 200 and resp.text == "0\n1\n2\n"
        assert worker.received[0]["body"]["model"] == "qwen2.5:0.5b"
        rows = (await db.execute(select(UsageRecord))).scalars().all()
        assert len(rows) == 1 and rows[0].outcome == "success"
        assert json.loads(json.dumps(rows[0].request_id))  # recorded under the gateway's request id
    finally:
        await app_broker.coordinator.stop()
        await other.coordinator.stop()
        app_broker.coordinator = None
        limiters.use_memory()
