"""Community models: customers import public Hugging Face GGUF files, private to them, and only providers who
opted in serve them."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import Model, NodeCommand
from app.services import huggingface
from app.services.huggingface import license_problem, parse_reference, quantization_of

REPO = "bartowski/SmolLM2-135M-Instruct-GGUF"
COMMIT = "09816acd5d99df7be770d85ea30822623dab342c"
FILE = "SmolLM2-135M-Instruct-Q4_K_M.gguf"
SHA = "e8a0e942fe93529b7601a7620c8aa1bdc1bede40ff668ed9d6339686384392d7"
SIZE = 105_454_400
LLAMACPP = [{"name": "llamacpp", "version": "1", "backend": "process", "available": True}]


def repo_json(**overrides) -> dict:
    data = {
        "id": REPO,
        "private": False,
        "gated": False,
        "disabled": False,
        "sha": COMMIT,
        "tags": ["gguf", "license:apache-2.0"],
        "cardData": {"license": "apache-2.0"},
        "gguf": {"architecture": "llama", "context_length": 8192},
        "siblings": [
            {"rfilename": "README.md", "size": 10039},
            {"rfilename": FILE, "size": SIZE, "lfs": {"sha256": SHA, "size": SIZE}},
            {"rfilename": "big-Q8_0-00001-of-00002.gguf", "size": 9, "lfs": {"sha256": "a" * 64, "size": 9}},
            {"rfilename": "sub/hidden-Q4_0.gguf", "size": 9, "lfs": {"sha256": "b" * 64, "size": 9}},
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
def hf():
    """Fake Hugging Face API. ``state['json']``/``state['status']`` control the reply; requests are recorded."""
    state: dict = {"json": repo_json(), "status": 200, "requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"error": "x"}, headers=state.get("headers", {}))
        return httpx.Response(200, content=json.dumps(state["json"]).encode())

    huggingface.set_transport(httpx.MockTransport(handler))
    yield state
    huggingface.set_transport(None)


async def _import(client, headers, **body):
    payload = {"repo": REPO, "file": FILE, "accept_terms": True, **body}
    return await client.post("/api/v1/models/community", json=payload, headers=headers)


async def _opt_in(client, node, accept=True):
    return await client.patch(
        f"/api/v1/nodes/{node['node_id']}",
        json={"accepts_community_models": accept},
        headers=node["provider_headers"],
    )


# --- parsing and policy ---------------------------------------------------------------------------------------


def test_reference_parsing():
    assert parse_reference(REPO).repo == REPO
    ref = parse_reference(f"https://huggingface.co/{REPO}/blob/main/{FILE}")
    assert (ref.repo, ref.revision, ref.file) == (REPO, "main", FILE)
    assert parse_reference(f"https://hf.co/{REPO}/tree/v1").revision == "v1"
    for bad in (
        "http://huggingface.co/a/b",
        "https://evil.example/a/b",
        "https://huggingface.co:8443/a/b",
        "a/../b",
        "just-a-name",
        "https://huggingface.co/a",
    ):
        with pytest.raises(Exception):  # noqa: B017
            parse_reference(bad)
    with pytest.raises(Exception):  # noqa: B017
        parse_reference(REPO, file="model.bin")
    with pytest.raises(Exception):  # noqa: B017
        parse_reference(REPO, revision="../x")


def test_license_policy_and_quantization():
    assert license_problem("apache-2.0") is None
    assert license_problem("llama3.2") is None
    assert license_problem("other") is None
    assert license_problem(None) and license_problem("unknown")
    for nc in ("cc-by-nc-4.0", "cc-by-nc-sa-4.0", "cc-by-nc-nd-4.0"):
        assert "commercial" in license_problem(nc)
    assert quantization_of(FILE) == "Q4_K_M"
    assert quantization_of("model.IQ3_M.gguf") == "IQ3_M"
    assert quantization_of("model-f16.gguf") == "F16"
    assert quantization_of("model.gguf") is None


# --- import ------------------------------------------------------------------------------------------------


async def test_import_pins_commit_and_hash_from_hugging_face(client, db, make_user, hf):
    user, customer = await make_user("customer")
    resp = await _import(client, customer, revision="main")
    assert resp.status_code == 201, resp.text
    model = resp.json()
    assert model["is_community"] and not model["is_approved"]
    assert model["name"] == "SmolLM2-135M-Instruct-GGUF Q4_K_M"
    assert model["license"] == "apache-2.0" and model["context_length"] == 8192
    assert model["source_url"] == f"https://huggingface.co/{REPO}/blob/{COMMIT}/{FILE}"
    (art,) = model["artifacts"]
    assert art["runtime"] == "llamacpp" and art["revision"] == COMMIT
    assert art["sha256"] == SHA and art["size_bytes"] == SIZE and art["requirements_estimated"]
    assert art["min_ram_mb"] == 101 * 12 // 10 + 1 + 512

    (req,) = hf["requests"]
    assert str(req.url) == f"https://huggingface.co/api/models/{REPO}/revision/main?blobs=true"
    assert "authorization" not in req.headers

    # Importing the same pinned file again returns the existing model instead of a duplicate.
    again = await _import(client, customer)
    assert again.json()["id"] == model["id"]
    assert len((await db.execute(select(Model))).scalars().all()) == 1


async def test_import_requires_customer_and_terms(client, make_user, hf):
    _, provider = await make_user("provider")
    assert (await _import(client, provider)).status_code == 403
    _, customer = await make_user("customer")
    resp = await _import(client, customer, accept_terms=False)
    assert resp.status_code == 422 and "license" in resp.json()["detail"]
    assert hf["requests"] == []  # refused before contacting Hugging Face


@pytest.mark.parametrize(
    ("overrides", "file", "status", "fragment"),
    [
        ({"gated": "manual"}, FILE, 422, "gated"),
        ({"private": True}, FILE, 404, "private"),
        ({"disabled": True}, FILE, 404, "not found"),
        ({"cardData": {"license": "cc-by-nc-4.0"}, "tags": []}, FILE, 422, "commercial"),
        ({"cardData": {}, "tags": []}, FILE, 422, "no license"),
        ({"sha": "main"}, FILE, 502, "commit"),
        ({}, "missing-Q4_0.gguf", 422, "not a GGUF file"),
        ({}, "big-Q8_0-00001-of-00002.gguf", 422, "Split"),
    ],
)
async def test_import_refusals(client, make_user, hf, overrides, file, status, fragment):
    hf["json"] = repo_json(**overrides)
    _, customer = await make_user("customer")
    resp = await _import(client, customer, file=file)
    assert resp.status_code == status, resp.text
    assert fragment in resp.json()["detail"]


async def test_size_limit(client, make_user, hf, monkeypatch):
    monkeypatch.setattr(settings, "COMMUNITY_MODEL_MAX_BYTES", SIZE - 1)
    _, customer = await make_user("customer")
    resp = await _import(client, customer)
    assert resp.status_code == 422 and "limit" in resp.json()["detail"]


@pytest.mark.parametrize(("status", "expected"), [(401, 404), (404, 404), (307, 422), (429, 503), (500, 503)])
async def test_hugging_face_errors(client, make_user, hf, status, expected):
    hf["status"] = status
    _, customer = await make_user("customer")
    assert (await _import(client, customer)).status_code == expected


async def test_per_customer_cap_and_rate_limit(client, make_user, hf, monkeypatch):
    monkeypatch.setattr(settings, "COMMUNITY_MODELS_PER_CUSTOMER", 1)
    _, customer = await make_user("customer")
    assert (await _import(client, customer)).status_code == 201
    hf["json"] = repo_json(sha="1" * 40)  # a new commit: a different pinned file
    resp = await _import(client, customer)
    assert resp.status_code == 409

    monkeypatch.setattr(settings, "COMMUNITY_MODEL_IMPORTS_PER_MINUTE", 2)
    _, other = await make_user("customer")
    codes = [(await _import(client, other)).status_code for _ in range(3)]
    assert codes[-1] == 429


async def test_disabled_by_setting(client, make_user, hf, monkeypatch):
    monkeypatch.setattr(settings, "COMMUNITY_MODELS_ENABLED", False)
    _, customer = await make_user("customer")
    assert (await _import(client, customer)).status_code == 403


async def test_preview_lists_importable_files(client, make_user, hf):
    _, customer = await make_user("customer")
    resp = await client.get("/api/v1/models/community/preview", params={"repo": REPO}, headers=customer)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["revision"] == COMMIT and body["license"] == "apache-2.0" and body["license_problem"] is None
    files = {f["name"]: f for f in body["files"]}
    assert set(files) == {FILE, "big-Q8_0-00001-of-00002.gguf"}  # files in subfolders are not offered
    assert files[FILE]["problem"] is None and files[FILE]["quantization"] == "Q4_K_M"
    assert "Split" in files["big-Q8_0-00001-of-00002.gguf"]["problem"]


# --- privacy -------------------------------------------------------------------------------------------------


async def test_community_models_are_private(client, make_user, enroll_node, hf):
    _, owner = await make_user("customer")
    _, other = await make_user("customer")
    model_id = (await _import(client, owner)).json()["id"]

    assert (await client.get("/api/v1/models")).json() == []
    assert (await client.get(f"/api/v1/models/{model_id}")).status_code == 404
    assert [m["id"] for m in (await client.get("/api/v1/models/community", headers=owner)).json()] == [model_id]
    assert (await client.get("/api/v1/models/community", headers=other)).json() == []
    assert (await client.get(f"/api/v1/models/community/{model_id}", headers=other)).status_code == 404
    assert (await client.delete(f"/api/v1/models/community/{model_id}", headers=other)).status_code == 404

    node = await enroll_node(runtimes=LLAMACPP)
    await _opt_in(client, node)
    resp = await client.post("/api/v1/deployments", json={"model_id": model_id}, headers=other)
    assert resp.status_code == 404


# --- provider opt-in -------------------------------------------------------------------------------------------


async def test_only_opted_in_nodes_serve_community_models(client, db, make_user, enroll_node, hf):
    _, customer = await make_user("customer")
    model_id = (await _import(client, customer)).json()["id"]
    node = await enroll_node(runtimes=LLAMACPP)
    shown = (await client.get(f"/api/v1/nodes/{node['node_id']}", headers=node["provider_headers"])).json()
    assert shown["accepts_community_models"] is False  # off by default

    resp = await client.post("/api/v1/deployments", json={"model_id": model_id}, headers=customer)
    assert resp.status_code == 503
    assert resp.json()["detail"]["reasons"] == {"community_not_accepted": 1}

    assert (await _opt_in(client, node)).json()["accepts_community_models"] is True
    resp = await client.post("/api/v1/deployments", json={"model_id": model_id}, headers=customer)
    assert resp.status_code == 201, resp.text
    cmd = (
        await db.execute(select(NodeCommand).where(NodeCommand.deployment_id == uuid.UUID(resp.json()["id"])))
    ).scalar_one()
    assert cmd.payload["source"] == {
        "type": "huggingface",
        "repo": REPO,
        "revision": COMMIT,
        "file": FILE,
        "sha256": SHA,
        "size": SIZE,
    }


async def test_reviewed_models_need_no_opt_in(client, make_user, enroll_node, hf, db):
    _, customer = await make_user("customer")
    model_id = (await _import(client, customer)).json()["id"]
    _, operator = await make_user("operator")
    assert (await client.post(f"/api/v1/models/{model_id}/approval", headers=operator)).status_code == 200
    await enroll_node(runtimes=LLAMACPP)  # not opted in
    _, other = await make_user("customer")
    resp = await client.post("/api/v1/deployments", json={"model_id": model_id}, headers=other)
    assert resp.status_code == 201, resp.text


async def test_staff_cannot_opt_in_for_a_provider(client, make_user, enroll_node):
    node = await enroll_node(runtimes=LLAMACPP)
    _, admin = await make_user("admin")
    url = f"/api/v1/nodes/{node['node_id']}"
    assert (await client.patch(url, json={"accepts_community_models": True}, headers=admin)).status_code == 403
    assert (await client.patch(url, json={"accepts_community_models": False}, headers=admin)).status_code == 200
    assert (await client.patch(url, json={}, headers=node["provider_headers"])).status_code == 422
    # Pausing still works on its own and leaves the opt-in alone.
    paused = await client.patch(url, json={"accepting_workloads": False}, headers=node["provider_headers"])
    assert paused.json()["accepting_workloads"] is False and paused.json()["accepts_community_models"] is False


# --- withdrawal ----------------------------------------------------------------------------------------------


async def test_withdraw(client, make_user, enroll_node, hf):
    _, customer = await make_user("customer")
    model_id = (await _import(client, customer)).json()["id"]
    node = await enroll_node(runtimes=LLAMACPP)
    await _opt_in(client, node)
    dep = (await client.post("/api/v1/deployments", json={"model_id": model_id}, headers=customer)).json()

    assert (await client.delete(f"/api/v1/models/community/{model_id}", headers=customer)).status_code == 409
    await client.post(f"/api/v1/deployments/{dep['id']}/stop", headers=customer)  # cancelled before delivery
    assert (await client.delete(f"/api/v1/models/community/{model_id}", headers=customer)).status_code == 204
    assert (await client.get("/api/v1/models/community", headers=customer)).json() == []
    resp = await client.post("/api/v1/deployments", json={"model_id": model_id}, headers=customer)
    assert resp.status_code == 404
