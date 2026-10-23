"""HTTP helpers for a worker-managed Ollama instance. Never used against the provider's own Ollama."""

import asyncio
import json
import re
import time

import httpx

from .base import ProgressCallback, WorkloadError

_TRANSIENT = re.compile(
    r"\b5\d\d\b|timeout|timed out|connection|reset|EOF|temporar|unavailable|too many requests|429", re.IGNORECASE
)


def is_transient(text: str) -> bool:
    """Registry and network hiccups are retried; "model does not exist" style errors are not."""
    return bool(_TRANSIENT.search(text))


def tag_names(tag: str) -> set[str]:
    return {tag, f"{tag}:latest"} if ":" not in tag else {tag}


ALLOWED_PATHS = frozenset({"/api/chat", "/api/generate", "/v1/chat/completions", "/v1/completions"})


async def wait_api(base_url: str, timeout: float = 60.0, is_alive=None) -> str:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=5.0) as client:
        while time.monotonic() < deadline:
            if is_alive is not None and not await is_alive():
                raise WorkloadError("RUNTIME_START_FAILED", "Runtime process exited during startup")
            try:
                resp = await client.get(f"{base_url}/api/version")
                if resp.status_code == 200:
                    return str(resp.json().get("version", ""))
            except (httpx.HTTPError, ValueError):
                pass
            await asyncio.sleep(0.5)
    raise WorkloadError("RUNTIME_START_FAILED", "Runtime API did not become available")


async def pull(base_url: str, tag: str, progress: ProgressCallback, stall_timeout: float = 300.0) -> None:
    last_report = 0.0
    last_pct = -10
    timeout = httpx.Timeout(connect=10.0, read=stall_timeout, write=30.0, pool=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{base_url}/api/pull", json={"model": tag, "name": tag, "stream": True}
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread())[:300].decode(errors="ignore")
                    raise WorkloadError(
                        "MODEL_PULL_FAILED",
                        f"Model download failed ({resp.status_code}): {body}",
                        transient=resp.status_code >= 500 or is_transient(body),
                    )
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if "error" in msg:
                        err = str(msg["error"])[:300]
                        raise WorkloadError(
                            "MODEL_PULL_FAILED", f"Model download failed: {err}", transient=is_transient(err)
                        )
                    status = str(msg.get("status", ""))
                    total, done = msg.get("total"), msg.get("completed")
                    now = time.monotonic()
                    if total and done is not None:
                        pct = int(done * 100 / total)
                        if pct >= last_pct + 10 or now - last_report > 15:
                            last_pct, last_report = pct, now
                            await progress(f"Downloading model: {pct}%")
                    if status == "success":
                        return
    except httpx.ReadTimeout:
        raise WorkloadError("MODEL_PULL_STALLED", "Model download stalled", transient=True) from None
    except httpx.HTTPError as exc:
        raise WorkloadError(
            "MODEL_PULL_FAILED", f"Model download failed: {type(exc).__name__}", transient=True
        ) from None
    raise WorkloadError("MODEL_PULL_FAILED", "Model download ended without success")


async def verify_ready(base_url: str, tag: str, num_ctx: int, timeout: float = 300.0) -> str | None:
    """Ready means the model answers a real generation request, not merely that a process is running."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                f"{base_url}/api/generate",
                json={
                    "model": tag,
                    "prompt": "Reply with OK.",
                    "stream": False,
                    "options": {"num_predict": 2, "num_ctx": num_ctx},
                },
            )
        except httpx.HTTPError as exc:
            raise WorkloadError("HEALTHCHECK_FAILED", f"Test generation failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise WorkloadError(
                "HEALTHCHECK_FAILED", f"Test generation returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        if not data.get("done"):
            raise WorkloadError("HEALTHCHECK_FAILED", "Test generation did not complete")
        return await model_digest(client, base_url, tag)


async def model_digest(client: httpx.AsyncClient, base_url: str, tag: str) -> str | None:
    resp = await client.get(f"{base_url}/api/tags")
    for m in resp.json().get("models", []):
        if {m.get("name"), m.get("model")} & tag_names(tag):
            digest = str(m.get("digest") or "")
            return digest if digest.replace(":", "").isalnum() else None
    return None


async def health(base_url: str, tag: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            names = {m.get("name") for m in resp.json().get("models", [])} | {
                m.get("model") for m in resp.json().get("models", [])
            }
            return resp.status_code == 200 and bool(names & tag_names(tag))
    except (httpx.HTTPError, ValueError):
        return False
