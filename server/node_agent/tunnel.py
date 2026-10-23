"""Worker side of the inference tunnel: forwards gateway requests to this worker's own managed runtime."""

import asyncio
import json
import logging

import httpx

logger = logging.getLogger(__name__)
CHUNK_LIMIT = 256 * 1024


class TunnelHandler:
    def __init__(self, resolve_workload, max_concurrent: int, request_timeout: float):
        """``resolve_workload(deployment_id)`` returns (base_url, served_model_name, allowed_paths) for a running
        workload, or None. Each runtime has its own allowlist (only Ollama serves /api/*)."""
        self.resolve = resolve_workload
        self.max_concurrent = max_concurrent
        self.timeout = request_timeout
        self._tasks: dict[str, asyncio.Task] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    async def on_frame(self, frame: dict, send) -> None:
        kind = frame.get("type")
        rid = str(frame.get("id", ""))[:64]
        if kind == "cancel":
            task = self._tasks.pop(rid, None)
            if task:
                task.cancel()
        elif kind == "request" and rid:
            self._tasks[rid] = asyncio.create_task(self._handle(rid, frame, send))

    def cancel_all(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    async def _handle(self, rid: str, frame: dict, send) -> None:
        try:
            await self._forward(rid, frame, send)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("request_id=%s tunnel request failed: %s", rid, type(exc).__name__)
            await _try_send(
                send, {"type": "error", "id": rid, "code": "runtime_error", "message": "Runtime request failed"}
            )
        finally:
            self._tasks.pop(rid, None)

    async def _forward(self, rid: str, frame: dict, send) -> None:
        dep_id = str(frame.get("deployment_id", ""))
        path = frame.get("path")
        body = frame.get("body")
        target = self.resolve(dep_id)
        # Defence in depth: the gateway already enforces these, but the worker never trusts the wire blindly.
        if target is None:
            await send(
                {"type": "error", "id": rid, "code": "deployment_not_running", "message": "Workload not running"}
            )
            return
        base_url, model_tag, allowed_paths = target
        logger.info("request_id=%s deployment=%s path=%s", rid, dep_id, path)
        if frame.get("method") != "POST" or path not in allowed_paths or not isinstance(body, dict):
            await send({"type": "error", "id": rid, "code": "rejected", "message": "Request not allowed"})
            return
        body = {**body, "model": model_tag}

        sem = self._semaphores.setdefault(dep_id, asyncio.Semaphore(self.max_concurrent))
        async with sem:
            timeout = httpx.Timeout(connect=5.0, read=self.timeout, write=30.0, pool=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{base_url}{path}", json=body) as resp:
                    ctype = resp.headers.get("content-type", "application/json").split(";")[0].strip()
                    await send({"type": "response_start", "id": rid, "status": resp.status_code, "content_type": ctype})
                    async for text in resp.aiter_text():
                        for i in range(0, len(text), CHUNK_LIMIT):
                            await send({"type": "chunk", "id": rid, "data": text[i : i + CHUNK_LIMIT]})
            await send({"type": "response_end", "id": rid})


async def _try_send(send, frame: dict) -> None:
    try:
        await send(frame)
    except Exception:  # noqa: BLE001
        pass


async def run_tunnel(url: str, headers: dict, handler: TunnelHandler, stop: asyncio.Event) -> None:
    """Keep the tunnel connected, reconnecting with backoff, until ``stop`` is set."""
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    from .protocol import CredentialRevoked, backoff

    attempt = 0
    while not stop.is_set():
        try:
            async with connect(url, additional_headers=headers, max_size=2 * 1024 * 1024, ping_interval=20) as ws:
                attempt = 0
                logger.info("Inference tunnel connected")
                lock = asyncio.Lock()

                async def send(frame: dict) -> None:
                    async with lock:
                        await ws.send(json.dumps(frame))

                async for message in ws:
                    try:
                        frame = json.loads(message)
                    except ValueError:
                        continue
                    if isinstance(frame, dict):
                        await handler.on_frame(frame, send)
        except InvalidStatus as exc:
            if exc.response.status_code in (401, 403):
                raise CredentialRevoked("Tunnel rejected credentials") from None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "rcvd", None) is not None and exc.rcvd.code == 4401:
                raise CredentialRevoked("Tunnel rejected credentials") from None
            logger.warning("Inference tunnel disconnected: %s", type(exc).__name__)
        handler.cancel_all()
        if stop.is_set():
            break
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff(attempt, cap=30))
        except TimeoutError:
            pass
        attempt += 1
