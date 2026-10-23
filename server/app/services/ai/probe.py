"""Control-plane inference check for a READY deployment.

The worker already runs a test generation before reporting READY. Before the agent publishes an endpoint it
also sends one tiny completion through the same tunnel customers use, so "ready" means the control plane has
itself seen the model answer, not only that the worker said so.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass

from app.models.deployment import Deployment
from app.services.tunnel import NodeUnavailable, broker

PROBE_TIMEOUT_SECONDS = 120.0
MAX_PROBE_BYTES = 64 * 1024


@dataclass
class ProbeResult:
    ok: bool
    detail: str
    latency_ms: int


async def probe_deployment(dep: Deployment, timeout: float = PROBE_TIMEOUT_SECONDS) -> ProbeResult:
    t0 = time.monotonic()
    request_id = f"probe-{uuid.uuid4().hex}"
    frame = {
        "type": "request",
        "id": request_id,
        "deployment_id": str(dep.id),
        "method": "POST",
        "path": "/v1/chat/completions",
        "body": {
            "model": dep.model_tag,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "max_tokens": 4,
            "temperature": 0,
            "stream": False,
        },
    }

    def result(ok: bool, detail: str) -> ProbeResult:
        return ProbeResult(ok, detail, int((time.monotonic() - t0) * 1000))

    if dep.node_id is None:
        return result(False, "deployment has no node")
    try:
        handle, rid, queue = await broker.open_request(dep.node_id, frame)
    except NodeUnavailable:
        return result(False, "the node serving the deployment is not connected")
    body = bytearray()
    status = None
    try:
        async with asyncio.timeout(timeout):
            while True:
                msg = await queue.get()
                kind = msg.get("type")
                if kind == "response_start":
                    status = int(msg.get("status", 502))
                elif kind == "chunk":
                    body.extend(str(msg.get("data", "")).encode())
                    if len(body) > MAX_PROBE_BYTES:
                        return result(False, "response too large")
                elif kind == "response_end":
                    break
                else:
                    return result(False, f"runtime error: {str(msg.get('message') or msg.get('code'))[:200]}")
    except TimeoutError:
        try:
            await handle.send({"type": "cancel", "id": rid})
        except Exception:  # noqa: BLE001
            pass
        return result(False, "the model did not answer in time")
    finally:
        broker.close_request(handle, rid)
    if status != 200:
        return result(False, f"runtime returned HTTP {status}")
    try:
        data = json.loads(bytes(body))
        choice = data["choices"][0]
        content = (choice.get("message") or {}).get("content")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return result(False, "runtime returned a malformed completion")
    if not isinstance(content, str) or not choice.get("finish_reason"):
        return result(False, "completion did not finish")
    return result(True, "the model answered a test completion")
