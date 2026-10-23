"""Model artifacts downloaded from an allowlisted source (Hugging Face) and verified before use.

Security properties:

* Only https URLs on allowlisted hosts are fetched, including every redirect hop, so a malicious catalog
  entry or control plane cannot make the worker request internal addresses (no SSRF).
* Repository ids, file names, and revisions are validated; revisions must be pinned 40-hex commits.
* GGUF files are verified against the catalog's SHA-256 and size before any runtime loads them, and are
  stored content-addressed (``<sha256>.gguf``) so a cached file cannot be swapped silently.
* Gated or private models are refused: no access tokens are sent to provider machines.
"""

import hashlib
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .base import WorkloadError

DEFAULT_ALLOWED_HOSTS = ("huggingface.co", "*.huggingface.co", "*.hf.co")
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.gguf$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_REDIRECTS = 5


def validate_source(source: dict | None, needs_file: bool) -> dict:
    """Validate a Hugging Face source dict from a DEPLOY command. Returns a clean copy."""
    if not isinstance(source, dict) or source.get("type") != "huggingface":
        raise WorkloadError("INVALID_MODEL", "Unsupported model source")
    repo, revision = str(source.get("repo", "")), str(source.get("revision", ""))
    if not REPO_RE.fullmatch(repo) or ".." in repo:
        raise WorkloadError("INVALID_MODEL", "Invalid repository id")
    if not REVISION_RE.fullmatch(revision):
        raise WorkloadError("INVALID_MODEL", "Revision must be a pinned 40-character commit")
    clean = {"type": "huggingface", "repo": repo, "revision": revision}
    if needs_file:
        file, sha = str(source.get("file", "")), str(source.get("sha256", ""))
        if not FILE_RE.fullmatch(file):
            raise WorkloadError("INVALID_MODEL", "Invalid GGUF file name")
        if not SHA256_RE.fullmatch(sha):
            raise WorkloadError("INVALID_MODEL", "Missing or invalid SHA-256")
        try:
            size = int(source.get("size", 0))
        except (TypeError, ValueError):
            size = 0
        clean.update(file=file, sha256=sha, size=size)
    return clean


def host_allowed(url: str, allowed: tuple[str, ...]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower()
    for pattern in allowed:
        pattern = pattern.lower()
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]):
                return True
        elif host == pattern:
            return True
    return False


class ModelStore:
    def __init__(
        self,
        root: Path,
        allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = "https://huggingface.co",
    ):
        self.root = root
        self.allowed = allowed_hosts
        self._transport = transport
        self.base_url = base_url.rstrip("/")

    def path_for(self, sha256: str) -> Path:
        return self.root / f"{sha256}.gguf"

    def is_cached(self, source: dict) -> bool:
        path = self.path_for(source["sha256"])
        return path.is_file() and (not source.get("size") or path.stat().st_size == source["size"])

    async def fetch_gguf(self, source: dict, progress: Callable[[str], Awaitable[None]]) -> Path:
        """Download (or reuse) a verified GGUF file. Raises WorkloadError with transient=True for retryable
        network failures."""
        target = self.path_for(source["sha256"])
        if self.is_cached(source):
            return target
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        url = f"{self.base_url}/{source['repo']}/resolve/{source['revision']}/{source['file']}"
        part = target.with_suffix(".part")
        digest = hashlib.sha256()
        offset = 0
        if part.exists():  # resume an interrupted download
            with open(part, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
            offset = part.stat().st_size
        expected = int(source.get("size") or 0)
        timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport, follow_redirects=False) as client:
                resp = await self._open(client, url, offset)
                try:
                    if resp.status_code == 200 and offset:
                        # Server ignored the range request: start over.
                        part.unlink(missing_ok=True)
                        digest, offset = hashlib.sha256(), 0
                    total = expected or (offset + int(resp.headers.get("content-length", 0) or 0))
                    done, last_pct = offset, -10
                    with open(part, "ab") as fh:
                        async for chunk in resp.aiter_bytes(1 << 20):
                            done += len(chunk)
                            if expected and done > expected:
                                raise WorkloadError(
                                    "MODEL_INTEGRITY_FAILED", "Download is larger than the catalog says"
                                )
                            digest.update(chunk)
                            fh.write(chunk)
                            if total:
                                pct = done * 100 // total
                                if pct >= last_pct + 10:
                                    last_pct = pct
                                    await progress(f"Downloading model: {pct}%")
                finally:
                    await resp.aclose()
        except httpx.TimeoutException:
            raise WorkloadError("MODEL_PULL_STALLED", "Model download stalled", transient=True) from None
        except httpx.HTTPError as exc:
            raise WorkloadError(
                "MODEL_PULL_FAILED", f"Model download failed: {type(exc).__name__}", transient=True
            ) from None
        if digest.hexdigest() != source["sha256"] or (expected and done != expected):
            part.unlink(missing_ok=True)
            raise WorkloadError("MODEL_INTEGRITY_FAILED", "Downloaded file does not match the catalog's SHA-256")
        os.replace(part, target)
        return target

    async def _open(self, client: httpx.AsyncClient, url: str, offset: int) -> httpx.Response:
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        for _ in range(MAX_REDIRECTS + 1):
            if not host_allowed(url, self.allowed):
                raise WorkloadError("MODEL_SOURCE_REJECTED", f"Refusing to download from {urlparse(url).hostname}")
            request = client.build_request("GET", url, headers=headers)
            resp = await client.send(request, stream=True)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                await resp.aclose()
                url = str(httpx.URL(url).join(location))
                continue
            if resp.status_code in (401, 403):
                await resp.aclose()
                raise WorkloadError(
                    "MODEL_ACCESS_DENIED", "Model is gated or private; AgentMesh does not send access tokens to nodes"
                )
            if resp.status_code == 404:
                await resp.aclose()
                raise WorkloadError("MODEL_PULL_FAILED", "Model file not found at the pinned revision")
            if resp.status_code >= 500 or resp.status_code == 429:
                await resp.aclose()
                raise WorkloadError("MODEL_PULL_FAILED", f"Source returned HTTP {resp.status_code}", transient=True)
            if resp.status_code not in (200, 206):
                await resp.aclose()
                raise WorkloadError("MODEL_PULL_FAILED", f"Source returned HTTP {resp.status_code}")
            return resp
        raise WorkloadError("MODEL_SOURCE_REJECTED", "Too many redirects")
