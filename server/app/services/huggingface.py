"""Read-only lookups of public Hugging Face model metadata, used to import community models.

The control plane only ever calls ``{HUGGINGFACE_URL}/api/models/<repo>/revision/<revision>`` with validated
path segments, never follows redirects, and caps the response size. Every value that ends up in a worker
command (commit, file, SHA-256, size) comes from this response, not from the customer. No access token is
sent: gated and private models are refused, as they are on workers.
"""

import json
import re
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.services.catalog_service import GGUF_FILE_RE, HF_REPO_RE, HF_REVISION_RE, SHA256_RE

MAX_RESPONSE_BYTES = 10 * 2**20
REVISION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
HF_HOSTS = frozenset({"huggingface.co", "www.huggingface.co", "hf.co"})
# Split GGUFs need every part, and mmproj files are vision projectors, not language models.
SPLIT_GGUF_RE = re.compile(r"-\d{5}-of-\d{5}\.gguf$")
QUANT_RE = re.compile(r"(?i)(?:^|[-_.])(I?Q\d(?:_[A-Z0-9]+)*|BF16|F16|F32)$")
# Hosting on AgentMesh is paid (providers earn from it), so licenses that forbid commercial use are refused.
NON_COMMERCIAL_RE = re.compile(r"(^|-)nc(-|$)|non-?commercial|research-only")

_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def _reject(detail: str, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


@dataclass(frozen=True)
class HfReference:
    repo: str
    revision: str = "main"
    file: str | None = None


def parse_reference(text: str, file: str | None = None, revision: str | None = None) -> HfReference:
    """Accept ``owner/name`` or a huggingface.co URL to a repository, branch, or file."""
    text = text.strip()
    url_revision = url_file = None
    if "://" in text:
        parsed = urlparse(text)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in HF_HOSTS or parsed.port:
            raise _reject("Only https://huggingface.co links are supported")
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise _reject("The link does not point to a model repository")
        text = f"{parts[0]}/{parts[1]}"
        if len(parts) >= 4 and parts[2] in ("blob", "resolve", "tree"):
            url_revision = parts[3]
            if parts[2] != "tree" and len(parts) == 5:
                url_file = parts[4]
    if not HF_REPO_RE.fullmatch(text) or ".." in text:
        raise _reject("Repository must look like owner/name")
    rev = (revision or url_revision or "main").strip()
    if not REVISION_NAME_RE.fullmatch(rev) or ".." in rev:
        raise _reject("Invalid revision")
    chosen = (file or url_file or "").strip() or None
    if chosen is not None and not GGUF_FILE_RE.fullmatch(chosen):
        raise _reject("Choose a single .gguf file from the repository root")
    return HfReference(repo=text, revision=rev, file=chosen)


@dataclass(frozen=True)
class GgufFile:
    name: str
    sha256: str
    size: int
    quantization: str | None


@dataclass(frozen=True)
class RepoInfo:
    repo: str
    commit: str
    license: str | None
    license_name: str | None
    architecture: str | None
    context_length: int | None
    files: list[GgufFile]

    def file(self, name: str) -> GgufFile | None:
        return next((f for f in self.files if f.name == name), None)


def quantization_of(file: str) -> str | None:
    match = QUANT_RE.search(file[: -len(".gguf")])
    return match.group(1).upper() if match else None


def license_problem(license_id: str | None) -> str | None:
    if not license_id or license_id.lower() in ("unknown", "none"):
        return "The model card declares no license, so AgentMesh cannot host it"
    if NON_COMMERCIAL_RE.search(license_id.lower()):
        return f"The license ({license_id}) does not allow commercial hosting"
    return None


async def _get_json(url: str) -> dict:
    timeout = httpx.Timeout(15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=_transport, follow_redirects=False) as client:
            async with client.stream("GET", url, headers={"Accept": "application/json"}) as resp:
                if resp.status_code in (301, 302, 307, 308):
                    raise _reject("The repository has moved on Hugging Face; use its new name")
                if resp.status_code in (401, 403, 404):
                    raise _reject("Model not found on Hugging Face, or it is private or gated", 404)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise _reject("Hugging Face is not responding right now; try again shortly", 503)
                if resp.status_code != 200:
                    raise _reject(f"Hugging Face returned HTTP {resp.status_code}", 502)
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise _reject("Hugging Face response is too large", 502)
    except httpx.HTTPError:
        raise _reject("Could not reach Hugging Face; try again shortly", 503) from None
    try:
        data = json.loads(bytes(body))
    except ValueError:
        raise _reject("Hugging Face returned an unreadable response", 502) from None
    if not isinstance(data, dict):
        raise _reject("Hugging Face returned an unexpected response", 502)
    return data


async def fetch_repo(ref: HfReference) -> RepoInfo:
    """Resolve ``ref`` to a pinned commit and list its root-level GGUF files with their LFS SHA-256."""
    base = settings.HUGGINGFACE_URL.rstrip("/")
    data = await _get_json(f"{base}/api/models/{ref.repo}/revision/{quote(ref.revision, safe='')}?blobs=true")
    if data.get("private") or data.get("disabled"):
        raise _reject("Model not found on Hugging Face, or it is private or gated", 404)
    if data.get("gated"):
        raise _reject("This model is gated on Hugging Face; AgentMesh does not send access tokens to providers")
    commit = str(data.get("sha") or "")
    if not HF_REVISION_RE.fullmatch(commit):
        raise _reject("Hugging Face did not return a commit for this revision", 502)

    card: dict = data["cardData"] if isinstance(data.get("cardData"), dict) else {}
    license_id = card.get("license")
    if isinstance(license_id, list):  # some cards list several; the first is the primary one
        license_id = license_id[0] if license_id else None
    if not isinstance(license_id, str):
        license_id = next(
            (t.split(":", 1)[1] for t in data.get("tags") or [] if isinstance(t, str) and t.startswith("license:")),
            None,
        )
    license_name = card.get("license_name") if isinstance(card.get("license_name"), str) else None

    gguf: dict = data["gguf"] if isinstance(data.get("gguf"), dict) else {}
    ctx = gguf.get("context_length")
    arch = gguf.get("architecture")

    files = []
    for s in data.get("siblings") or []:
        if not isinstance(s, dict):
            continue
        name, lfs = s.get("rfilename"), s.get("lfs")
        if not isinstance(name, str) or not GGUF_FILE_RE.fullmatch(name) or not isinstance(lfs, dict):
            continue
        sha, size = str(lfs.get("sha256") or ""), lfs.get("size")
        if SHA256_RE.fullmatch(sha) and isinstance(size, int) and size > 0:
            files.append(GgufFile(name=name, sha256=sha, size=size, quantization=quantization_of(name)))
    return RepoInfo(
        repo=ref.repo,
        commit=commit,
        license=license_id[:255] if isinstance(license_id, str) else None,
        license_name=license_name[:255] if license_name else None,
        architecture=arch[:100] if isinstance(arch, str) else None,
        context_length=ctx if isinstance(ctx, int) and ctx > 0 else None,
        files=sorted(files, key=lambda f: f.size),
    )


def file_problem(f: GgufFile) -> str | None:
    if SPLIT_GGUF_RE.search(f.name):
        return "Split GGUF files are not supported; choose a single-file quantization"
    if f.name.lower().startswith("mmproj"):
        return "This is a vision projector file, not a language model"
    if f.size > settings.COMMUNITY_MODEL_MAX_BYTES:
        return f"The file is larger than the {settings.COMMUNITY_MODEL_MAX_BYTES // 2**30} GB limit"
    return None
