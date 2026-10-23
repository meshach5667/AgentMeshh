"""Inference providers. ``OllamaProvider`` talks to the local Ollama HTTP API; anything implementing
``InferenceProvider`` can replace it (another runtime, or the same adapter on another machine).

Only these Ollama endpoints are used: /api/version, /api/tags, /api/ps, /api/show, /api/chat. Pulling a model
is a separate, explicit command (see cli.py) and never happens implicitly.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .config import AdapterSettings


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"{code}: {message}")


@dataclass
class ProviderStatus:
    ok: bool  # the runtime answers
    version: str | None = None
    model_present: bool = False  # pulled locally
    model_loaded: bool = False  # resident in memory right now
    model_size_bytes: int | None = None
    capabilities: list[str] | None = None
    error: str | None = None

    @property
    def ready(self) -> bool:
        return self.ok and self.model_present and (self.capabilities is None or "completion" in self.capabilities)


@dataclass
class ChatResult:
    content: str
    model: str
    latency_ms: int
    prompt_tokens: int | None
    output_tokens: int | None


class InferenceProvider(Protocol):
    model: str

    async def status(self) -> ProviderStatus: ...

    async def chat(
        self, messages: list[dict], *, schema: dict | None, options: dict[str, Any], timeout: float
    ) -> ChatResult: ...


def _names(tag: str) -> set[str]:
    return {tag, f"{tag}:latest"} if ":" not in tag else {tag}


class OllamaProvider:
    def __init__(self, settings: AdapterSettings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.model = settings.OLLAMA_MODEL
        self.base = settings.ollama
        self._transport = transport

    def _client(self, timeout: httpx.Timeout | float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, timeout=timeout, transport=self._transport)

    async def status(self) -> ProviderStatus:
        try:
            async with self._client(5.0) as client:
                version = (await client.get("/api/version")).json().get("version")
                tags = (await client.get("/api/tags")).json().get("models", [])
                present = next((m for m in tags if {m.get("name"), m.get("model")} & _names(self.model)), None)
                ps = (await client.get("/api/ps")).json().get("models", [])
                loaded = any({m.get("name"), m.get("model")} & _names(self.model) for m in ps)
                caps = None
                if present is not None:
                    show = await client.post("/api/show", json={"model": self.model})
                    if show.status_code == 200:
                        caps = show.json().get("capabilities")
                        caps = [str(c) for c in caps] if isinstance(caps, list) else None
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            return ProviderStatus(ok=False, error=f"Ollama is not reachable ({type(exc).__name__})")
        return ProviderStatus(
            ok=True,
            version=str(version) if version else None,
            model_present=present is not None,
            model_loaded=loaded,
            model_size_bytes=int(present.get("size") or 0) if present else None,
            capabilities=caps,
            error=None if present is not None else f"model {self.model} is not pulled",
        )

    def _options(self, requested: dict[str, Any]) -> dict[str, Any]:
        """The control plane's options, clamped to this machine's own limits."""
        s = self.settings
        return {
            "num_ctx": min(int(requested.get("num_ctx") or s.AI_NUM_CTX), s.AI_NUM_CTX),
            "num_predict": min(int(requested.get("num_predict") or s.AI_MAX_TOKENS), s.AI_MAX_TOKENS),
            "temperature": float(requested.get("temperature", 0)),
        }

    async def chat(
        self, messages: list[dict], *, schema: dict | None, options: dict[str, Any], timeout: float
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": str(m.get("role")), "content": str(m.get("content"))} for m in messages],
            "stream": False,
            "think": False,
            "keep_alive": self.settings.OLLAMA_KEEP_ALIVE,
            "options": self._options(options),
        }
        if schema:
            body["format"] = schema
        attempts = 1 + max(0, self.settings.AI_MAX_RETRIES)
        t0 = time.monotonic()
        for attempt in range(attempts):
            try:
                # Cancelling the calling task closes the connection, and Ollama stops generating.
                async with self._client(httpx.Timeout(timeout, connect=5.0)) as client:
                    resp = await client.post("/api/chat", json=body)
                break
            except httpx.ConnectError:
                if attempt + 1 >= attempts:
                    raise ProviderError("OLLAMA_UNREACHABLE", "Ollama is not reachable", retryable=True) from None
                await asyncio.sleep(2.0 * (attempt + 1))
            except httpx.TimeoutException:
                # Not retried here: a second long generation would double the load on a busy machine.
                raise ProviderError("TIMEOUT", f"no answer within {timeout:g}s", retryable=True) from None
            except httpx.HTTPError as exc:
                raise ProviderError("OLLAMA_ERROR", type(exc).__name__, retryable=True) from None
        latency = int((time.monotonic() - t0) * 1000)
        if resp.status_code == 404:
            raise ProviderError("MODEL_UNAVAILABLE", f"model {self.model} is not available in Ollama")
        if resp.status_code != 200:
            text = resp.text[:200]
            raise ProviderError("OLLAMA_ERROR", f"HTTP {resp.status_code}: {text}", retryable=resp.status_code >= 500)
        try:
            data = resp.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise ProviderError("BAD_RESPONSE", "Ollama returned an unexpected response") from None
        if not isinstance(content, str) or not data.get("done", True):
            raise ProviderError("BAD_RESPONSE", "generation did not complete")
        return ChatResult(
            content=content,
            model=str(data.get("model") or self.model),
            latency_ms=latency,
            prompt_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )
