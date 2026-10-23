"""AI inference adapter: Ollama provider (mocked HTTP), load protection, configuration, model selection, and
the adapter talking to the real control plane in-process.

The optional integration test at the end uses a real Ollama only when AGENTMESH_TEST_OLLAMA_URL and
AGENTMESH_TEST_OLLAMA_MODEL are set. It never pulls a model.
"""

import asyncio
import json
import os
import uuid

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import inspect

from ai_adapter.config import AdapterSettings
from ai_adapter.ollama import ChatResult, OllamaProvider, ProviderError, ProviderStatus
from ai_adapter.service import Adapter
from ai_adapter.system import Hardware, pull_problems, recommend
from app.core.config import settings
from app.main import app
from app.models import AiRun

TOKEN = "t" * 40
MODEL = "gemma4:e2b-it-qat"


def make_settings(**over) -> AdapterSettings:
    base = {"OLLAMA_MODEL": MODEL, "AI_INFERENCE_TOKEN": TOKEN, "AGENTMESH_CONTROL_PLANE_URL": "http://localhost"}
    return AdapterSettings(**(base | over))


class FakeOllama:
    """Records requests and answers like Ollama's HTTP API."""

    def __init__(self, *, present=True, loaded=False, reply='{"status": "ok"}', fail=None):
        self.present, self.loaded, self.reply, self.fail = present, loaded, reply, fail
        self.requests: list[tuple[str, dict]] = []
        self.chat_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append((request.url.path, body))
        path = request.url.path
        if path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.6"})
        if path == "/api/tags":
            models = [{"name": MODEL, "model": MODEL, "size": 4_336_357_640}] if self.present else []
            return httpx.Response(200, json={"models": models})
        if path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": MODEL, "model": MODEL}] if self.loaded else []})
        if path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "vision", "tools", "thinking"]})
        if path == "/api/chat":
            self.chat_calls += 1
            if self.fail == "connect":
                raise httpx.ConnectError("refused")
            if self.fail == "timeout":
                raise httpx.ReadTimeout("slow")
            if self.fail == "404":
                return httpx.Response(404, json={"error": "model not found"})
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "message": {"role": "assistant", "content": self.reply},
                    "done": True,
                    "prompt_eval_count": 50,
                    "eval_count": 7,
                },
            )
        return httpx.Response(404)

    def provider(self, **over) -> OllamaProvider:
        return OllamaProvider(make_settings(**over), transport=httpx.MockTransport(self.handler))


# --- Provider ------------------------------------------------------------------------------------------


async def test_status_reports_presence_residency_and_capabilities():
    status = await FakeOllama(loaded=True).provider().status()
    assert status.ok and status.ready and status.model_loaded and status.version == "0.40.6"
    assert "completion" in status.capabilities and status.model_size_bytes == 4_336_357_640
    missing = await FakeOllama(present=False).provider().status()
    assert missing.ok and not missing.ready and "not pulled" in missing.error


async def test_status_when_ollama_is_down():
    def down(request):
        raise httpx.ConnectError("refused")

    status = await OllamaProvider(make_settings(), transport=httpx.MockTransport(down)).status()
    assert not status.ok and not status.ready


async def test_chat_sends_schema_and_clamped_limits():
    fake = FakeOllama()
    out = await fake.provider(AI_NUM_CTX=4096, AI_MAX_TOKENS=256).chat(
        [{"role": "user", "content": "hi", "extra": "dropped"}],
        schema={"type": "object"},
        options={"num_ctx": 999_999, "num_predict": 99_999, "temperature": 0},
        timeout=30,
    )
    assert out.content == '{"status": "ok"}' and out.model == MODEL and out.output_tokens == 7
    _, body = fake.requests[-1]
    assert body["format"] == {"type": "object"} and body["stream"] is False and body["think"] is False
    assert body["options"] == {"num_ctx": 4096, "num_predict": 256, "temperature": 0.0}
    assert body["keep_alive"] == "30m"  # reuse the loaded model
    assert body["messages"] == [{"role": "user", "content": "hi"}]


async def test_unreachable_ollama_is_retried_boundedly(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    fake = FakeOllama(fail="connect")
    with pytest.raises(ProviderError) as exc:
        await fake.provider(AI_MAX_RETRIES=1).chat([], schema=None, options={}, timeout=5)
    assert exc.value.code == "OLLAMA_UNREACHABLE" and exc.value.retryable and fake.chat_calls == 2


async def test_timeout_is_not_retried_locally():
    fake = FakeOllama(fail="timeout")
    with pytest.raises(ProviderError) as exc:
        await fake.provider(AI_MAX_RETRIES=3).chat([], schema=None, options={}, timeout=5)
    assert exc.value.code == "TIMEOUT" and fake.chat_calls == 1


async def test_missing_model_is_not_substituted():
    with pytest.raises(ProviderError) as exc:
        await FakeOllama(fail="404").provider().chat([], schema=None, options={}, timeout=5)
    assert exc.value.code == "MODEL_UNAVAILABLE" and not exc.value.retryable


async def _no_sleep(_seconds):
    return None


# --- Configuration and hardware ------------------------------------------------------------------------


def test_configuration_refuses_exposed_or_insecure_endpoints():
    with pytest.raises(ValidationError):
        make_settings(OLLAMA_BASE_URL="http://192.168.1.20:11434")
    assert make_settings(OLLAMA_BASE_URL="http://10.0.0.2:11434", ALLOW_REMOTE_OLLAMA=True)
    with pytest.raises(ValidationError):
        make_settings(AGENTMESH_CONTROL_PLANE_URL="http://agentmesh.example.com")
    assert make_settings(AGENTMESH_CONTROL_PLANE_URL="https://agentmesh.example.com")
    with pytest.raises(ValidationError):
        make_settings(AI_INFERENCE_NODE_ID="hp 15; rm -rf")
    with pytest.raises(ValidationError):
        make_settings(AI_MAX_CONCURRENT_REQUESTS=50)


def _hw(**over) -> Hardware:
    base = dict(
        cpu_model="Intel i5-1035G1",
        logical_cpus=8,
        cpu_flags=["avx", "avx2", "avx512f"],
        mem_total_mb=15159,
        mem_available_mb=6000,
        swap_free_mb=0,
        disk_free_mb=400_000,
        models_dir="/usr/share/ollama/.ollama/models",
    )
    return Hardware(**(base | over))


def test_model_recommendation_for_cpu_laptops():
    assert recommend(_hw()).tag == "gemma4:e2b-it-qat"  # the HP 15: 15 GB, CPU only
    assert recommend(_hw(mem_total_mb=4096)).tag is None
    assert recommend(_hw(cpu_flags=["avx"])).tag is None
    assert recommend(_hw(accelerators=["nvidia"], mem_total_mb=32768)).tag == "gemma4:e4b-it-qat"


def test_pull_is_refused_without_space_or_for_unverified_tags():
    assert pull_problems(_hw(), "gemma4:e2b-it-qat") == []
    assert "free disk" in pull_problems(_hw(disk_free_mb=1000), "gemma4:e2b-it-qat")[0]
    assert "RAM" in pull_problems(_hw(mem_total_mb=4000), "gemma4:e2b-it-qat")[0]
    assert "not a verified variant" in pull_problems(_hw(), "gemma4:31b")[0]


# --- Load protection -----------------------------------------------------------------------------------


def test_load_protection():
    a = Adapter(make_settings(AI_MIN_AVAILABLE_MEMORY_MB=1024, AI_MAX_LOAD_PER_CPU=1.5))
    ready = ProviderStatus(ok=True, model_present=True, capabilities=["completion"], model_size_bytes=4_336_357_640)
    loaded = ProviderStatus(**{**ready.__dict__, "model_loaded": True})
    assert a.evaluate(ready, {"mem_available_mb": 8000, "load_per_cpu": 0.3}) == (True, None)
    # Loading the model needs room for the weights; once loaded only a small reserve is required.
    ok, why = a.evaluate(ready, {"mem_available_mb": 2000, "load_per_cpu": 0.3})
    assert not ok and "low memory" in why
    assert a.evaluate(loaded, {"mem_available_mb": 2000, "load_per_cpu": 0.3}) == (True, None)
    ok, why = a.evaluate(loaded, {"mem_available_mb": 2000, "load_per_cpu": 3.0})
    assert not ok and "CPU busy" in why
    assert not a.evaluate(ProviderStatus(ok=False, error="down"), {})[0]
    assert not a.evaluate(ProviderStatus(ok=True, model_present=True, capabilities=["embedding"]), {})[0]


# --- Adapter <-> control plane -------------------------------------------------------------------------


class ScriptedProvider:
    """Stands in for Ollama with scripted model answers."""

    def __init__(self, replies, *, model=MODEL):
        self.model = model
        self.replies = list(replies)
        self.seen: list[list[dict]] = []

    async def status(self):
        return ProviderStatus(
            ok=True, version="test", model_present=True, model_loaded=True, capabilities=["completion"]
        )

    async def chat(self, messages, *, schema, options, timeout):
        self.seen.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(content=json.dumps(reply), model=self.model, latency_ms=5, prompt_tokens=10, output_tokens=5)


class QuietMonitor:
    def sample(self):
        return {"cpu_percent": 5.0, "load_per_cpu": 0.1, "mem_available_mb": 9000, "mem_total_mb": 15159}


@pytest.fixture
def control_plane(monkeypatch):
    monkeypatch.setattr(settings, "AI_INFERENCE_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "OLLAMA_MODEL", MODEL)
    return httpx.ASGITransport(app=app)


async def _drain(adapter):
    while adapter.in_flight:
        await asyncio.gather(*adapter.in_flight)


async def test_adapter_serves_a_run_end_to_end(client, db, make_user, enroll_node, ollama_model, control_plane):
    await enroll_node(cpu=4, ram_mb=8192)
    _, customer = await make_user("customer")
    model_id = str(inspect(ollama_model).identity[0])
    run = (
        await client.post(
            "/api/v1/ai/deployments",
            json={"request": "a tiny qwen chat model", "limits": {"max_spend": "100", "max_duration_hours": 1}},
            headers=customer,
        )
    ).json()
    plan = {"model_id": model_id, "runtime": "any", "num_ctx": 2048, "require_gpu": False, "duration_hours": 1}
    provider = ScriptedProvider([{"action": "final_plan", "plan": plan, "explanation": "Qwen 0.5B fits."}])
    adapter = Adapter(make_settings(), provider=provider, transport=control_plane, monitor=QuietMonitor())
    await adapter.heartbeat()
    assert adapter.accepting
    assert await adapter.lease_once(wait_seconds=0) == 1
    await _drain(adapter)
    assert "CUSTOMER REQUEST" in provider.seen[0][1]["content"]
    db.expire_all()
    got = await db.get(AiRun, uuid.UUID(run["id"]))
    assert got.status == "DEPLOYING" and got.explanation == "Qwen 0.5B fits."
    await adapter._http.aclose()


async def test_adapter_reports_failures_for_retry(client, db, make_user, ollama_model, control_plane):
    _, customer = await make_user("customer")
    await client.post(
        "/api/v1/ai/deployments",
        json={"request": "anything small", "limits": {"max_spend": "100", "max_duration_hours": 1}},
        headers=customer,
    )
    provider = ScriptedProvider([ProviderError("OLLAMA_UNREACHABLE", "down", retryable=True)])
    adapter = Adapter(make_settings(), provider=provider, transport=control_plane, monitor=QuietMonitor())
    await adapter.heartbeat()
    assert await adapter.lease_once(wait_seconds=0) == 1
    await _drain(adapter)
    from sqlalchemy import select

    from app.models import AiInferenceRequest

    db.expire_all()
    req = (await db.execute(select(AiInferenceRequest))).scalar_one()
    assert req.status == "PENDING" and req.error_code == "OLLAMA_UNREACHABLE"  # queued again, not lost
    await adapter._http.aclose()


async def test_adapter_refuses_a_job_for_another_model(client, make_user, control_plane, db):
    adapter = Adapter(make_settings(), provider=ScriptedProvider([]), transport=control_plane, monitor=QuietMonitor())
    sent = []

    async def capture(request_id, result):
        sent.append(result)

    adapter._post_result = capture  # type: ignore[method-assign]
    await adapter.handle({"id": "x", "model": "llama3.2:1b", "messages": []})
    assert sent[0]["error_code"] == "MODEL_MISMATCH"
    await adapter._http.aclose()


async def test_bad_token_stops_the_adapter(control_plane):
    adapter = Adapter(
        make_settings(AI_INFERENCE_TOKEN="w" * 40),
        provider=ScriptedProvider([]),
        transport=control_plane,
        monitor=QuietMonitor(),
    )
    with pytest.raises(PermissionError):
        await adapter.heartbeat()
    await adapter._http.aclose()


# --- Optional: real Ollama -----------------------------------------------------------------------------

REAL_URL = os.environ.get("AGENTMESH_TEST_OLLAMA_URL")
REAL_MODEL = os.environ.get("AGENTMESH_TEST_OLLAMA_MODEL")


@pytest.mark.skipif(not (REAL_URL and REAL_MODEL), reason="set AGENTMESH_TEST_OLLAMA_URL and _MODEL to run")
async def test_real_ollama_structured_output():
    provider = OllamaProvider(make_settings(OLLAMA_BASE_URL=REAL_URL, OLLAMA_MODEL=REAL_MODEL, AI_MAX_TOKENS=64))
    status = await provider.status()
    if not status.model_present:
        pytest.skip(f"{REAL_MODEL} is not pulled (this test never pulls models)")
    schema = {"type": "object", "properties": {"status": {"type": "string", "enum": ["ok"]}}, "required": ["status"]}
    out = await provider.chat(
        [{"role": "user", "content": 'Reply with {"status": "ok"}.'}], schema=schema, options={}, timeout=600
    )
    assert json.loads(out.content)["status"] == "ok"
