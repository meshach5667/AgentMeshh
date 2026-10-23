"""Broker for the worker inference tunnel.

Workers keep one outbound WebSocket to *some* control-plane replica. The gateway sends a ``request`` frame for
each customer request; the worker forwards it to its own managed runtime and streams ``response_start``,
``chunk`` and ``response_end`` (or ``error``) frames back. Nodes never accept inbound connections and
customers never learn node addresses.

With one API process everything is local. With several replicas (``COORDINATION_BACKEND=redis``):

* each replica records which nodes it holds in Redis (``tunnel:node:<id>`` -> replica id, with a TTL that
  is refreshed while the socket is open);
* a replica that receives a gateway request for a node held elsewhere publishes the request to the owner's
  channel (``tunnel:replica:<id>``); the owner forwards it to the worker and publishes the worker's frames
  back to the requester's channel, in order;
* cancellations and node revocations travel the same way.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

MAX_FRAME_BYTES = 1024 * 1024
OWNERSHIP_TTL_SECONDS = 60
OWNERSHIP_REFRESH_SECONDS = 20


class NodeUnavailable(Exception):  # noqa: N818
    pass


class FrameSink(Protocol):
    def put_nowait(self, frame: dict) -> None: ...


@dataclass
class WorkerConnection:
    node_id: uuid.UUID
    send_json: Callable[[dict], Awaitable[Any]]
    close: Callable[[], Awaitable[Any]]
    pending: dict[str, FrameSink] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, frame: dict) -> None:
        async with self.lock:
            await self.send_json(frame)

    def dispatch(self, frame: dict) -> None:
        sink = self.pending.get(str(frame.get("id")))
        if sink is not None:
            sink.put_nowait(frame)
            if frame.get("type") in ("response_end", "error") and not isinstance(sink, asyncio.Queue):
                self.pending.pop(str(frame.get("id")), None)

    def fail_all(self, message: str) -> None:
        for sink in list(self.pending.values()):
            sink.put_nowait({"type": "error", "code": "node_disconnected", "message": message})


@dataclass
class RequestHandle:
    """What the gateway holds for an in-flight request: where to send a cancel, and how to clean up."""

    pending: dict[str, Any]
    send: Callable[[dict], Awaitable[Any]]


class _RemoteSink:
    """Pending entry on the owning replica that relays worker frames to the requesting replica."""

    def __init__(self, coordinator: "RedisCoordinator", reply_to: str, request_id: str):
        self.coordinator, self.reply_to, self.request_id = coordinator, reply_to, request_id

    def put_nowait(self, frame: dict) -> None:
        frame = {**frame, "id": self.request_id}
        self.coordinator.spawn(self.coordinator.publish(self.reply_to, {"kind": "frame", "frame": frame}))


class TunnelBroker:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, WorkerConnection] = {}
        self.coordinator: RedisCoordinator | None = None
        # Requests this replica is waiting on whose worker lives on another replica.
        self._remote_waiting: dict[str, asyncio.Queue] = {}

    def is_local(self, node_id) -> bool:
        return node_id in self._connections

    async def register(self, conn: WorkerConnection) -> None:
        old = self._connections.get(conn.node_id)
        self._connections[conn.node_id] = conn
        if old is not None and old is not conn:
            old.fail_all("Worker reconnected")
            with contextlib.suppress(Exception):
                await old.close()
        if self.coordinator:
            await self.coordinator.claim(conn.node_id)

    def unregister(self, conn: WorkerConnection) -> None:
        if self._connections.get(conn.node_id) is conn:
            del self._connections[conn.node_id]
            if self.coordinator:
                self.coordinator.spawn(self.coordinator.release(conn.node_id))
        conn.fail_all("Worker disconnected")

    async def close_node(self, node_id) -> None:
        """Disconnect a node's tunnel wherever it is held (used when a node is revoked)."""
        conn = self._connections.get(node_id)
        if conn is not None:
            self.unregister(conn)
            with contextlib.suppress(Exception):
                await conn.close()
        elif self.coordinator:
            owner = await self.coordinator.owner(node_id)
            if owner:
                await self.coordinator.publish(owner, {"kind": "close_node", "node_id": str(node_id)})

    async def open_request(self, node_id, frame: dict) -> tuple[RequestHandle, str, asyncio.Queue]:
        request_id = frame["id"]
        queue: asyncio.Queue = asyncio.Queue()
        conn = self._connections.get(node_id)
        if conn is not None:
            conn.pending[request_id] = queue
            try:
                await conn.send(frame)
            except Exception as exc:
                conn.pending.pop(request_id, None)
                raise NodeUnavailable("Could not reach node") from exc
            return RequestHandle(conn.pending, conn.send), request_id, queue

        if self.coordinator is None:
            raise NodeUnavailable("Node is not connected")
        owner = await self.coordinator.owner(node_id)
        if not owner:
            raise NodeUnavailable("Node is not connected")
        self._remote_waiting[request_id] = queue
        delivered = await self.coordinator.publish(
            owner, {"kind": "request", "node_id": str(node_id), "frame": frame, "reply_to": self.coordinator.replica_id}
        )
        if not delivered:
            self._remote_waiting.pop(request_id, None)
            raise NodeUnavailable("Node is not connected")
        coordinator = self.coordinator

        async def send_remote(f: dict) -> None:
            await coordinator.publish(owner, {"kind": "cancel", "node_id": str(node_id), "id": f.get("id")})

        return RequestHandle(self._remote_waiting, send_remote), request_id, queue

    @staticmethod
    def close_request(handle: RequestHandle, request_id: str) -> None:
        handle.pending.pop(request_id, None)

    async def handle_messages(self, conn: WorkerConnection, receive_text: Callable[[], Awaitable[str]]) -> None:
        """Read frames from a worker until it disconnects."""
        while True:
            text = await receive_text()
            if len(text) > MAX_FRAME_BYTES:
                logger.warning("Dropping oversized tunnel frame from node %s", conn.node_id)
                continue
            try:
                frame = json.loads(text)
            except ValueError:
                continue
            if isinstance(frame, dict) and frame.get("type") in ("response_start", "chunk", "response_end", "error"):
                conn.dispatch(frame)

    # --- messages from other replicas -------------------------------------------------------------------

    async def on_coordination_message(self, msg: dict) -> None:
        kind = msg.get("kind")
        if kind == "frame":
            frame = msg.get("frame") or {}
            queue = self._remote_waiting.get(str(frame.get("id")))
            if queue is not None:
                queue.put_nowait(frame)
            return
        try:
            node_id = uuid.UUID(str(msg.get("node_id")))
        except ValueError:
            return
        conn = self._connections.get(node_id)
        if kind == "request":
            frame, reply_to = msg.get("frame") or {}, str(msg.get("reply_to"))
            rid = str(frame.get("id"))
            if conn is None or self.coordinator is None:
                if self.coordinator:
                    await self.coordinator.publish(
                        reply_to,
                        {
                            "kind": "frame",
                            "frame": {
                                "type": "error",
                                "id": rid,
                                "code": "node_disconnected",
                                "message": "Node is not connected",
                            },
                        },
                    )
                return
            conn.pending[rid] = _RemoteSink(self.coordinator, reply_to, rid)
            try:
                await conn.send(frame)
            except Exception:  # noqa: BLE001
                conn.pending.pop(rid, None)
                await self.coordinator.publish(
                    reply_to,
                    {
                        "kind": "frame",
                        "frame": {
                            "type": "error",
                            "id": rid,
                            "code": "node_disconnected",
                            "message": "Could not reach node",
                        },
                    },
                )
        elif kind == "cancel" and conn is not None:
            rid = str(msg.get("id"))
            conn.pending.pop(rid, None)
            with contextlib.suppress(Exception):
                await conn.send({"type": "cancel", "id": rid})
        elif kind == "close_node" and conn is not None:
            self.unregister(conn)
            with contextlib.suppress(Exception):
                await conn.close()


class RedisCoordinator:
    """Cross-replica routing for the tunnel broker. One instance per API process."""

    def __init__(self, redis, broker: TunnelBroker, replica_id: str | None = None):
        self.redis = redis
        self.broker = broker
        self.replica_id = replica_id or uuid.uuid4().hex
        self._tasks: set[asyncio.Task] = set()
        self._listener: asyncio.Task | None = None
        self._refresher: asyncio.Task | None = None
        self._ready = asyncio.Event()

    def channel(self, replica_id: str) -> str:
        return f"tunnel:replica:{replica_id}"

    @staticmethod
    def key(node_id) -> str:
        return f"tunnel:node:{node_id}"

    def spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def start(self) -> None:
        self._listener = asyncio.create_task(self._listen())
        self._refresher = asyncio.create_task(self._refresh())
        await asyncio.wait_for(self._ready.wait(), timeout=10)

    async def stop(self) -> None:
        for task in (self._listener, self._refresher, *self._tasks):
            if task:
                task.cancel()
        for node_id in list(self.broker._connections):
            await self.release(node_id)

    async def claim(self, node_id) -> None:
        await self.redis.set(self.key(node_id), self.replica_id, ex=OWNERSHIP_TTL_SECONDS)

    async def release(self, node_id) -> None:
        # Delete only if this replica still owns it (another replica may hold a newer connection).
        if await self.redis.get(self.key(node_id)) == self.replica_id:
            await self.redis.delete(self.key(node_id))

    async def owner(self, node_id) -> str | None:
        value = await self.redis.get(self.key(node_id))
        return value if value else None

    async def publish(self, replica_id: str, message: dict) -> int:
        """Returns the number of replicas that received the message (0 means the owner is gone)."""
        return int(await self.redis.publish(self.channel(replica_id), json.dumps(message)))

    async def _listen(self) -> None:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.channel(self.replica_id))
        self._ready.set()
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                except (ValueError, TypeError):
                    continue
                try:
                    await self.broker.on_coordination_message(payload)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to handle coordination message")
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(self.channel(self.replica_id))

    async def _refresh(self) -> None:
        while True:
            await asyncio.sleep(OWNERSHIP_REFRESH_SECONDS)
            for node_id in list(self.broker._connections):
                with contextlib.suppress(Exception):
                    await self.claim(node_id)


broker = TunnelBroker()
