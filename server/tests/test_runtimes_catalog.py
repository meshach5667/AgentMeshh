"""Phase 5: explicit model/runtime compatibility, runtime-aware scheduling, and per-runtime gateway routes."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Model, ModelArtifact, NodeCommand
from tests.conftest import HARDWARE
from tests.test_gateway import FakeWorker

REV = "9217f5db79a29953eb74d5343926648285ec7e67"
SHA = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"
GPU_HW = {**HARDWARE, "gpus": [{"vendor": "NVIDIA", "model": "RTX 4090", "vram_mb": 24576}]}
ALL_RUNTIMES = [
    {"name": "ollama", "version": "1", "backend": "process", "available": True},
    {"name": "llamacpp", "version": "1", "backend": "process", "available": True},
    {"name": "vllm", "version": "1", "backend": "process", "available": True},
]


def rt(*names):
    return [r for r in ALL_RUNTIMES if r["name"] in names]


@pytest.fixture
async def multi_model(db):
    model = Model(
        name="Qwen2.5 0.5B",
        runtime="ollama",
        model_tag="qwen2.5:0.5b",
        min_ram_mb=1024,
        min_disk_mb=768,
        is_approved=True,
    )
    db.add(model)
    await db.flush()
    db.add_all(
        [
            ModelArtifact(
                model_id=model.id,
                runtime="ollama",
                source_type="ollama",
                reference="qwen2.5:0.5b",
                min_ram_mb=1024,
                min_disk_mb=768,
            ),
            ModelArtifact(
                model_id=model.id,
                runtime="llamacpp",
                source_type="huggingface",
                reference="Qwen/Qwen2.5-0.5B-Instruct-GGUF",
                revision=REV,
                file="qwen2.5-0.5b-instruct-q4_k_m.gguf",
                sha256=SHA,
                size_bytes=491400032,
                format="gguf",
                min_ram_mb=900,
                min_disk_mb=640,
            ),
            ModelArtifact(
                model_id=model.id,
                runtime="vllm",
                source_type="huggingface",
                reference="Qwen/Qwen2.5-0.5B-Instruct",
                revision="7" * 40,
                format="safetensors",
                min_ram_mb=4096,
                min_disk_mb=2048,
                min_vram_mb=4096,
                min_cpu_cores=2,
                gpu_required=True,
            ),
        ]
    )
    await db.commit()
    return model


async def _deploy(client, headers, model, **body):
    return await client.post("/api/v1/deployments", json={"model_id": str(model.id), **body}, headers=headers)


async def _payload(db, dep_id):
    cmd = (await db.execute(select(NodeCommand).where(NodeCommand.deployment_id == uuid.UUID(dep_id)))).scalars().one()
    return cmd.payload


async def test_requested_llamacpp_gets_pinned_source_and_its_own_requirements(
    client, db, make_user, enroll_node, multi_model
):
    node = await enroll_node(runtimes=rt("ollama", "llamacpp"))
    _, customer = await make_user("customer")
    resp = await _deploy(client, customer, multi_model, runtime="llamacpp")
    assert resp.status_code == 201, resp.text
    dep = resp.json()
    assert dep["runtime"] == "llamacpp" and dep["model_tag"] == "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
    payload = await _payload(db, dep["id"])
    assert payload["runtime"] == "llamacpp"
    assert payload["source"] == {
        "type": "huggingface",
        "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "revision": REV,
        "file": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "sha256": SHA,
        "size": 491400032,
    }
    assert payload["resources"]["ram_mb"] == 900  # the GGUF artifact's figure, not the Ollama one
    shown = (await client.get(f"/api/v1/nodes/{node['node_id']}", headers=node["provider_headers"])).json()
    assert shown["reserved_ram_mb"] == 900


async def test_automatic_choice_falls_back_to_a_runtime_the_node_offers(client, make_user, enroll_node, multi_model):
    await enroll_node(runtimes=rt("llamacpp"))  # no Ollama on this node
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, multi_model)).json()
    assert dep["runtime"] == "llamacpp"


async def test_default_preference_is_ollama(client, make_user, enroll_node, multi_model):
    await enroll_node(runtimes=rt("ollama", "llamacpp"))
    _, customer = await make_user("customer")
    assert (await _deploy(client, customer, multi_model)).json()["runtime"] == "ollama"


async def test_vllm_needs_a_gpu_node(client, db, make_user, enroll_node, multi_model):
    await enroll_node(runtimes=rt("vllm"), ram_mb=8192)
    _, customer = await make_user("customer")
    resp = await _deploy(client, customer, multi_model, runtime="vllm")
    assert resp.status_code == 503 and resp.json()["detail"]["reasons"] == {"incompatible_hardware": 1}

    await enroll_node(runtimes=rt("vllm"), ram_mb=8192, vram_mb=8192, hardware=GPU_HW)
    resp = await _deploy(client, customer, multi_model, runtime="vllm")
    assert resp.status_code == 201, resp.text
    payload = await _payload(db, resp.json()["id"])
    assert payload["resources"]["gpu"] is True and payload["resources"]["vram_mb"] == 4096
    assert payload["source"] == {"type": "huggingface", "repo": "Qwen/Qwen2.5-0.5B-Instruct", "revision": "7" * 40}


async def test_reasons_are_reported_per_runtime(client, make_user, enroll_node, multi_model):
    await enroll_node(runtimes=rt("ollama"), ram_mb=512)
    _, customer = await make_user("customer")
    resp = await _deploy(client, customer, multi_model)
    detail = resp.json()["detail"]
    assert resp.status_code == 503
    assert set(detail["by_runtime"]) == {"ollama", "llamacpp", "vllm"}
    assert detail["by_runtime"]["ollama"]["reasons"] == {"insufficient_capacity": 1}
    assert detail["by_runtime"]["llamacpp"]["reasons"] == {"unsupported_runtime": 1}


async def test_runtime_the_model_lacks_is_rejected_with_alternatives(client, make_user, enroll_node, ollama_model):
    await enroll_node()
    _, customer = await make_user("customer")
    resp = await _deploy(client, customer, ollama_model, runtime="vllm")
    assert resp.status_code == 422 and "Available runtimes: ollama" in resp.json()["detail"]
    bad = await _deploy(client, customer, ollama_model, runtime="tgi")
    assert bad.status_code == 422


async def test_disabled_artifact_is_not_deployable(client, db, make_user, enroll_node, multi_model):
    await enroll_node(runtimes=rt("llamacpp"))
    _, operator = await make_user("operator")
    art = (
        await db.execute(
            select(ModelArtifact).where(ModelArtifact.model_id == multi_model.id, ModelArtifact.runtime == "llamacpp")
        )
    ).scalar_one()
    resp = await client.patch(
        f"/api/v1/models/{multi_model.id}/artifacts/{art.id}", json={"is_enabled": False}, headers=operator
    )
    assert resp.status_code == 200 and resp.json()["is_enabled"] is False
    _, customer = await make_user("customer")
    assert (await _deploy(client, customer, multi_model, runtime="llamacpp")).status_code == 422


@pytest.mark.parametrize(
    "override,problem",
    [
        ({"revision": "main"}, "pinned"),
        ({"sha256": None}, "SHA-256"),
        ({"file": "model.bin"}, "GGUF"),
        ({"reference": "https://evil.example/x"}, "repository"),
    ],
)
async def test_operator_artifact_validation(client, make_user, ollama_model, override, problem):
    _, operator = await make_user("operator")
    body = {
        "runtime": "llamacpp",
        "source_type": "huggingface",
        "reference": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "revision": REV,
        "file": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "sha256": SHA,
        "format": "gguf",
        "min_ram_mb": 900,
        "min_disk_mb": 640,
    } | override
    resp = await client.post(f"/api/v1/models/{ollama_model.id}/artifacts", json=body, headers=operator)
    assert resp.status_code == 422 and problem in resp.json()["detail"]


async def test_operator_adds_valid_artifact_once(client, make_user, ollama_model):
    _, operator = await make_user("operator")
    _, customer = await make_user("customer")
    body = {
        "runtime": "llamacpp",
        "source_type": "huggingface",
        "reference": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "revision": REV,
        "file": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "sha256": SHA,
        "format": "gguf",
        "min_ram_mb": 900,
        "min_disk_mb": 640,
    }
    url = f"/api/v1/models/{ollama_model.id}/artifacts"
    assert (await client.post(url, json=body, headers=customer)).status_code == 403
    assert (await client.post(url, json=body, headers=operator)).status_code == 201
    assert (await client.post(url, json=body, headers=operator)).status_code == 409
    listed = (await client.get(f"/api/v1/models/{ollama_model.id}")).json()
    assert sorted(a["runtime"] for a in listed["artifacts"]) == ["llamacpp", "ollama"]


async def test_vllm_artifact_must_require_gpu(client, make_user, ollama_model):
    _, operator = await make_user("operator")
    body = {
        "runtime": "vllm",
        "source_type": "huggingface",
        "reference": "Qwen/Qwen2.5-0.5B-Instruct",
        "revision": "7" * 40,
        "min_ram_mb": 4096,
        "min_disk_mb": 2048,
        "gpu_required": False,
    }
    resp = await client.post(f"/api/v1/models/{ollama_model.id}/artifacts", json=body, headers=operator)
    assert resp.status_code == 422


@pytest.fixture
async def ready_llamacpp(client, db, make_user, enroll_node, multi_model):
    from app.services.tunnel import broker

    node = await enroll_node(runtimes=rt("llamacpp"))
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, multi_model, runtime="llamacpp")).json()
    resp = await client.post(
        f"/api/v1/worker/deployments/{dep['id']}/status",
        json={"state": "READY", "model_digest": f"sha256:{SHA}"},
        headers=node["headers"],
    )
    assert resp.status_code == 200
    worker = FakeWorker(node["node_id"])
    await broker.register(worker.conn)
    dep = (await client.get(f"/api/v1/deployments/{dep['id']}", headers=customer)).json()
    yield dep, customer, worker
    broker.unregister(worker.conn)


async def test_llamacpp_endpoint_and_readiness_evidence(db, ready_llamacpp, multi_model):
    dep, _, _ = ready_llamacpp
    assert dep["endpoint"].endswith(f"/deployments/{dep['id']}/v1")
    assert dep["openai_base_url"] == dep["endpoint"]
    art = (
        await db.execute(select(ModelArtifact).where(ModelArtifact.id == uuid.UUID(dep["artifact_id"])))
    ).scalar_one()
    await db.refresh(art)
    assert art.last_ready_at is not None  # evidence the combination really serves


async def test_llamacpp_gateway_routes(client, ready_llamacpp):
    dep, customer, worker = ready_llamacpp
    base = f"/api/v1/deployments/{dep['id']}"
    refused = await client.post(f"{base}/ollama/api/chat", json={}, headers=customer)
    assert refused.status_code == 404 and "/v1/" in refused.json()["error"]["message"]
    assert (await client.post(f"{base}/v1/api/chat", json={}, headers=customer)).status_code == 404
    assert (await client.get(f"{base}/v1/models", headers=customer)).json()["data"][0]["id"] == dep["model_tag"]

    ok = await client.post(
        f"{base}/v1/chat/completions", headers=customer, json={"model": "anything", "messages": [], "stream": True}
    )
    assert ok.status_code == 200
    sent = worker.received[-1]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["body"]["model"] == "Qwen/Qwen2.5-0.5B-Instruct-GGUF"  # pinned to the deployment
    assert sent["body"]["stream_options"] == {"include_usage": True}  # so streamed usage can be metered
    assert "options" not in sent["body"]  # Ollama-only knob is not sent to llama.cpp


async def test_ollama_deployment_still_offers_both_route_families(client, make_user, enroll_node, ollama_model):
    from app.services.tunnel import broker

    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await client.post(
        f"/api/v1/worker/deployments/{dep['id']}/status", json={"state": "READY"}, headers=node["headers"]
    )
    worker = FakeWorker(node["node_id"])
    await broker.register(worker.conn)
    try:
        base = f"/api/v1/deployments/{dep['id']}"
        assert (await client.post(f"{base}/ollama/api/chat", json={}, headers=customer)).status_code == 200
        assert (await client.post(f"{base}/v1/chat/completions", json={}, headers=customer)).status_code == 200
        shown = (await client.get(base, headers=customer)).json()
        assert shown["endpoint"].endswith("/ollama") and shown["openai_base_url"].endswith(f"{dep['id']}/v1")
    finally:
        broker.unregister(worker.conn)


async def test_worker_may_report_every_runtime(client, enroll_node):
    node = await enroll_node(runtimes=ALL_RUNTIMES)
    hb = await client.post(
        "/api/v1/worker/heartbeat", json={"worker_version": "t", "runtimes": ALL_RUNTIMES}, headers=node["headers"]
    )
    assert hb.status_code == 200
    bad = await client.post(
        "/api/v1/worker/heartbeat",
        json={
            "worker_version": "t",
            "runtimes": [{"name": "shell", "version": "1", "backend": "process", "available": True}],
        },
        headers=node["headers"],
    )
    assert bad.status_code == 422


@pytest.mark.parametrize(
    "code,moves",
    [
        ("RUNTIME_UNAVAILABLE", True),
        ("WORKER_ERROR", True),
        ("MODEL_INTEGRITY_FAILED", False),
        ("MODEL_ACCESS_DENIED", False),
    ],
)
async def test_which_runtime_failures_move_the_deployment(client, make_user, enroll_node, multi_model, code, moves):
    _, provider = await make_user("provider")
    a = await enroll_node(provider=provider, runtimes=rt("llamacpp"), ram_mb=8192)
    await enroll_node(provider=provider, runtimes=rt("llamacpp"), ram_mb=4096)
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, multi_model, runtime="llamacpp")).json()
    resp = await client.post(
        f"/api/v1/worker/deployments/{dep['id']}/status",
        json={"state": "FAILED", "error_code": code},
        headers=a["headers"],
    )
    assert resp.json()["status"] == ("SCHEDULED" if moves else "FAILED")
