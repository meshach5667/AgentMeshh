"""The adapter loop: report health, lease inference requests from the control plane, answer them with the
local model, and post results back. All connections are outbound.

Load protection: the adapter takes work only while Ollama answers, the configured model is present, and the
machine has memory and CPU to spare. When it is busy it simply stops leasing (requests wait in the control
plane's queue); it never restarts Ollama and never runs more than AI_MAX_CONCURRENT_REQUESTS calls at once.
"""

import asyncio
import contextlib
import logging
import random
from typing import Any

import httpx

from .config import ADAPTER_VERSION, AdapterSettings
from .ollama import InferenceProvider, OllamaProvider, ProviderError, ProviderStatus
from .system import GEMMA4_CHOICES, LoadMonitor

logger = logging.getLogger("ai_adapter")

LOAD_HEADROOM_MB = 1536  # beyond the weights, when the model still has to be loaded


class Adapter:
    def __init__(
        self,
        settings: AdapterSettings,
        provider: InferenceProvider | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        monitor: LoadMonitor | None = None,
    ):
        self.s = settings
        self.provider = provider or OllamaProvider(settings)
        self.monitor = monitor or LoadMonitor()
        self.stop_event = asyncio.Event()
        self.in_flight: set[asyncio.Task] = set()
        self.status = ProviderStatus(ok=False)
        self.accepting = False
        self.reason: str | None = "starting"
        self.heartbeat_interval = 15.0
        self._http = httpx.AsyncClient(
            base_url=settings.control_plane,
            timeout=httpx.Timeout(40.0, connect=10.0),
            transport=transport,
            headers={
                "Authorization": f"Bearer {settings.AI_INFERENCE_TOKEN}",
                "X-AgentMesh-Inference-Node": settings.AI_INFERENCE_NODE_ID,
                "User-Agent": f"agentmesh-ai-adapter/{ADAPTER_VERSION}",
            },
        )

    # --- health ----------------------------------------------------------------------------------------

    def _model_bytes(self) -> int:
        if self.status.model_size_bytes:
            return self.status.model_size_bytes
        return next((size for tag, size, _ in GEMMA4_CHOICES if tag == self.s.OLLAMA_MODEL), 0)

    def evaluate(self, status: ProviderStatus, metrics: dict) -> tuple[bool, str | None]:
        """Whether to take new work now, and why not."""
        if not status.ok:
            return False, status.error or "Ollama is not reachable"
        if not status.ready:
            return False, status.error or f"model {self.s.OLLAMA_MODEL} cannot generate text"
        if len(self.in_flight) >= self.s.AI_MAX_CONCURRENT_REQUESTS:
            return False, "busy"
        available = metrics.get("mem_available_mb")
        if available is not None:
            needed = self.s.AI_MIN_AVAILABLE_MEMORY_MB
            if not status.model_loaded:
                needed = self._model_bytes() // 2**20 + LOAD_HEADROOM_MB
            if available < needed:
                return False, f"low memory: {available} MB available, {needed} MB wanted"
        load = metrics.get("load_per_cpu")
        if load is not None and load > self.s.AI_MAX_LOAD_PER_CPU:
            return False, f"CPU busy: load {load} per CPU"
        return True, None

    async def refresh(self) -> dict:
        self.status = await self.provider.status()
        metrics = self.monitor.sample()
        self.accepting, self.reason = self.evaluate(self.status, metrics)
        return metrics

    async def heartbeat(self) -> None:
        metrics = await self.refresh()
        body = {
            "model": self.s.OLLAMA_MODEL,
            "ollama_version": self.status.version,
            "ollama_ok": self.status.ok,
            "model_ready": self.status.ready,
            "accepting": self.accepting,
            "reason": (self.reason or "")[:200] or None,
            "in_flight": len(self.in_flight),
            "metrics": {k: v for k, v in metrics.items() if k != "sampled_at" and v is not None},
        }
        resp = await self._http.post("/api/v1/ai/inference/heartbeat", json=body)
        if resp.status_code == 401:
            raise PermissionError("The control plane rejected the inference token (AI_INFERENCE_TOKEN)")
        resp.raise_for_status()
        data = resp.json()
        self.heartbeat_interval = float(data.get("heartbeat_interval_seconds") or 15)
        if not data.get("accepted"):
            self.accepting = False
            self.reason = data.get("reason") or self.reason

    # --- work ------------------------------------------------------------------------------------------

    async def handle(self, job: dict[str, Any]) -> None:
        result: dict[str, Any]
        if job.get("model") != self.s.OLLAMA_MODEL:
            # Never answer with a different model than the one requested.
            result = {"error_code": "MODEL_MISMATCH", "error": f"this machine serves {self.s.OLLAMA_MODEL}"}
        else:
            timeout = max(10.0, min(float(job.get("timeout_seconds") or 0) - 5, self.s.AI_REQUEST_TIMEOUT))
            try:
                out = await self.provider.chat(
                    job.get("messages") or [],
                    schema=job.get("format"),
                    options=job.get("options") or {},
                    timeout=timeout,
                )
                result = {
                    "content": out.content,
                    "model": out.model,
                    "latency_ms": out.latency_ms,
                    "prompt_tokens": out.prompt_tokens,
                    "output_tokens": out.output_tokens,
                }
                logger.info("Answered request %s in %d ms", job["id"], out.latency_ms)
            except ProviderError as exc:
                logger.warning("Request %s failed: %s", job["id"], exc.code)
                result = {"error_code": exc.code, "error": exc.message[:500], "retryable": exc.retryable}
        await self._post_result(job["id"], result)

    async def _post_result(self, request_id: str, result: dict) -> None:
        for attempt in range(5):
            try:
                resp = await self._http.post(f"/api/v1/ai/inference/requests/{request_id}/result", json=result)
                if resp.status_code < 500:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(min(30.0, 2.0**attempt))
        logger.error("Could not deliver the result of %s; the control plane will re-queue it", request_id)

    async def lease_once(self, wait_seconds: float = 20.0) -> int:
        free = self.s.AI_MAX_CONCURRENT_REQUESTS - len(self.in_flight)
        if free <= 0 or not self.accepting:
            return 0
        resp = await self._http.post(
            "/api/v1/ai/inference/lease", json={"max_requests": free, "wait_seconds": wait_seconds}
        )
        resp.raise_for_status()
        jobs = resp.json()
        for job in jobs:
            task = asyncio.create_task(self.handle(job))
            self.in_flight.add(task)
            task.add_done_callback(self.in_flight.discard)
        return len(jobs)

    # --- main loop -------------------------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                await self.heartbeat()
                backoff = 1.0
                wait = self.heartbeat_interval
            except PermissionError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Heartbeat failed (%s); retrying", type(exc).__name__)
                self.accepting = False
                wait = backoff + random.random()
                backoff = min(60.0, backoff * 2)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=wait)

    async def _work_loop(self) -> None:
        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                if self.accepting and len(self.in_flight) < self.s.AI_MAX_CONCURRENT_REQUESTS:
                    await self.lease_once()
                    backoff = 1.0
                    continue
                wait = 2.0
            except httpx.HTTPError as exc:
                logger.warning("Lease failed (%s); retrying", type(exc).__name__)
                wait = backoff + random.random()
                backoff = min(60.0, backoff * 2)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=wait)

    async def run(self) -> int:
        logger.info(
            "AI adapter %s serving %s for %s as %s",
            ADAPTER_VERSION,
            self.s.OLLAMA_MODEL,
            self.s.control_plane,
            self.s.AI_INFERENCE_NODE_ID,
        )
        tasks = [asyncio.create_task(self._heartbeat_loop()), asyncio.create_task(self._work_loop())]
        try:
            done, _ = await asyncio.wait(
                [*tasks, asyncio.create_task(self.stop_event.wait())], return_when=asyncio.FIRST_COMPLETED
            )
            for t in done:
                if t in tasks and t.exception():
                    logger.error("%s", t.exception())
                    return 2
            return 0
        finally:
            self.stop_event.set()
            for t in tasks:
                t.cancel()
            # Let answers in progress finish (bounded by the request timeout); unfinished leases are re-queued.
            if self.in_flight:
                await asyncio.wait(self.in_flight, timeout=self.s.AI_REQUEST_TIMEOUT)
            await self._http.aclose()
