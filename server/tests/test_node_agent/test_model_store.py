"""Hugging Face model store: allowlisted hosts on every hop, pinned revisions, SHA-256 verification."""

import hashlib

import httpx
import pytest

from node_agent.runtime.base import WorkloadError
from node_agent.runtime.model_store import ModelStore, host_allowed, validate_source

DATA = b"GGUF" + b"x" * 5000
SHA = hashlib.sha256(DATA).hexdigest()
REV = "a" * 40


def source(**over):
    s = {
        "type": "huggingface",
        "repo": "org/model-GGUF",
        "revision": REV,
        "file": "model-Q8_0.gguf",
        "sha256": SHA,
        "size": len(DATA),
    }
    s.update(over)
    return s


def store(tmp_path, handler, **kw):
    return ModelStore(tmp_path / "gguf", transport=httpx.MockTransport(handler), **kw)


async def _noop(_msg):
    return None


def cdn_handler(seen=None, data=DATA):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        if request.url.host == "huggingface.co":
            return httpx.Response(302, headers={"location": "https://cdn-lfs.hf.co/blob/abc"})
        rng = request.headers.get("range")
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
            return httpx.Response(206, content=data[start:])
        return httpx.Response(200, content=data)

    return handler


async def test_download_follows_allowed_redirect_verifies_and_caches(tmp_path):
    seen = []
    st = store(tmp_path, cdn_handler(seen))
    path = await st.fetch_gguf(source(), _noop)
    assert path.read_bytes() == DATA and path.name == f"{SHA}.gguf"
    assert seen[0] == f"https://huggingface.co/org/model-GGUF/resolve/{REV}/model-Q8_0.gguf"
    await st.fetch_gguf(source(), _noop)
    assert len(seen) == 2  # second call served from the verified cache


@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data",
        "https://169.254.169.254/latest/meta-data",
        "http://cdn-lfs.hf.co/blob",  # downgrade to plain http
        "https://evil.example.com/model.gguf",
        "https://huggingface.co.evil.example/x",
    ],
)
async def test_redirect_to_disallowed_host_is_refused(tmp_path, location):
    def handler(request):
        return httpx.Response(302, headers={"location": location})

    with pytest.raises(WorkloadError) as err:
        await store(tmp_path, handler).fetch_gguf(source(), _noop)
    assert err.value.code == "MODEL_SOURCE_REJECTED"


async def test_hash_mismatch_is_rejected_and_nothing_kept(tmp_path):
    st = store(tmp_path, cdn_handler(data=b"GGUF" + b"y" * 5000))
    with pytest.raises(WorkloadError) as err:
        await st.fetch_gguf(source(), _noop)
    assert err.value.code == "MODEL_INTEGRITY_FAILED"
    assert not list((tmp_path / "gguf").iterdir())


@pytest.mark.parametrize(
    "status,code,transient",
    [
        (401, "MODEL_ACCESS_DENIED", False),
        (403, "MODEL_ACCESS_DENIED", False),
        (404, "MODEL_PULL_FAILED", False),
        (503, "MODEL_PULL_FAILED", True),
        (429, "MODEL_PULL_FAILED", True),
    ],
)
async def test_error_statuses(tmp_path, status, code, transient):
    with pytest.raises(WorkloadError) as err:
        await store(tmp_path, lambda r: httpx.Response(status)).fetch_gguf(source(), _noop)
    assert (err.value.code, err.value.transient) == (code, transient)


async def test_interrupted_download_resumes(tmp_path):
    st = store(tmp_path, cdn_handler())
    (tmp_path / "gguf").mkdir()
    (tmp_path / "gguf" / f"{SHA}.part").write_bytes(DATA[:1000])
    path = await st.fetch_gguf(source(), _noop)
    assert path.read_bytes() == DATA


@pytest.mark.parametrize(
    "bad",
    [
        {"revision": "main"},
        {"revision": "a" * 39},
        {"repo": "../etc/passwd"},
        {"repo": "org/../x"},
        {"file": "model.bin"},
        {"file": "../model.gguf"},
        {"sha256": "abc"},
        {"type": "url"},
    ],
)
def test_source_validation(bad):
    with pytest.raises(WorkloadError):
        validate_source(source(**bad), needs_file=True)


def test_host_allowlist():
    hosts = ("huggingface.co", "*.hf.co")
    assert host_allowed("https://huggingface.co/x", hosts)
    assert host_allowed("https://cas-bridge.xethub.hf.co/x", hosts)
    assert not host_allowed("https://hf.co.evil.com/x", hosts)
    assert not host_allowed("https://user:pw@huggingface.co/x", hosts)
    assert not host_allowed("ftp://huggingface.co/x", hosts)
