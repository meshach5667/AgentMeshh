"""Outbound client for worker protocol v1."""

import asyncio
import logging
import random

import httpx

from .config import PROTOCOL_VERSION, WORKER_VERSION

logger = logging.getLogger(__name__)


class CredentialRevoked(Exception):  # noqa: N818
    pass


class ProtocolError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def backoff(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    return min(cap, base * 2**attempt) * (0.5 + random.random() / 2)


class ControlPlaneClient:
    def __init__(
        self,
        base_url: str,
        node_id: str | None = None,
        credential: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api = f"{self.base_url}/api/v1/worker"
        self.node_id = node_id
        self.credential = credential
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=40.0), transport=transport)

    @property
    def headers(self) -> dict[str, str]:
        h = {"X-AgentMesh-Protocol": str(PROTOCOL_VERSION), "User-Agent": f"agentmesh-worker/{WORKER_VERSION}"}
        if self.node_id and self.credential:
            h["Authorization"] = f"Bearer {self.credential}"
            h["X-AgentMesh-Node-Id"] = self.node_id
        return h

    async def close(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict, *, retries: int = 0) -> dict:
        attempt = 0
        while True:
            try:
                resp = await self._client.post(f"{self.api}{path}", json=payload, headers=self.headers)
            except httpx.HTTPError as exc:
                if attempt >= retries:
                    raise ProtocolError(0, f"{type(exc).__name__}") from None
                await asyncio.sleep(backoff(attempt))
                attempt += 1
                continue
            if resp.status_code == 401 and self.node_id:
                raise CredentialRevoked(resp.text[:200])
            if resp.status_code >= 500 and attempt < retries:
                await asyncio.sleep(backoff(attempt))
                attempt += 1
                continue
            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("detail", resp.text)
                except ValueError:
                    detail = resp.text
                raise ProtocolError(resp.status_code, str(detail)[:500])
            return resp.json()

    async def enroll(self, payload: dict) -> dict:
        return await self._post("/enroll", payload)

    async def heartbeat(self, payload: dict) -> dict:
        return await self._post("/heartbeat", payload)

    async def whoami(self) -> dict:
        resp = await self._client.get(f"{self.api}/whoami", headers=self.headers)
        if resp.status_code == 401:
            raise CredentialRevoked(resp.text[:200])
        if resp.status_code >= 400:
            raise ProtocolError(resp.status_code, resp.text[:300])
        return resp.json()

    async def disconnect(self) -> None:
        await self._post("/disconnect", {})

    async def poll(self, wait_seconds: int = 20, max_commands: int = 5) -> list[dict]:
        data = await self._post("/commands/poll", {"wait_seconds": wait_seconds, "max_commands": max_commands})
        return data.get("commands", [])

    async def ack(self, command_id: str, status: str, error: str | None = None) -> None:
        await self._post(f"/commands/{command_id}/ack", {"status": status, "error": error}, retries=5)

    async def report(
        self,
        deployment_id: str,
        state: str,
        message: str | None = None,
        error_code: str | None = None,
        model_digest: str | None = None,
    ) -> dict | None:
        payload = {
            "state": state,
            "message": (message or None) and message[:500],
            "error_code": error_code,
            "model_digest": model_digest,
        }
        try:
            return await self._post(f"/deployments/{deployment_id}/status", payload, retries=5)
        except ProtocolError as exc:
            if exc.status in (404, 409):
                # The control plane no longer wants this transition (e.g. stopped meanwhile). Not retryable.
                logger.info("Status %s for %s not applied: %s", state, deployment_id, exc.detail)
                return None
            raise

    def tunnel_url(self) -> str:
        return self.api.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/tunnel"
