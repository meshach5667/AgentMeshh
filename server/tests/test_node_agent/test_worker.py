"""Worker logic with a fake runtime and a fake control-plane client."""

import asyncio
import json

import pytest

from node_agent.config import WorkerSettings
from node_agent.protocol import CredentialRevoked
from node_agent.runtime.base import RuntimeCapabilities, WorkloadError, WorkloadHandle
from node_agent.worker import Worker

DEP = "11111111-2222-3333-4444-555555555555"


def deploy_cmd(cmd_id="c1", dep=DEP, tag="qwen2.5:0.5b"):
    return {
        "id": cmd_id,
        "type": "DEPLOY",
        "deployment_id": dep,
        "payload": {
            "deployment_id": dep,
            "runtime": "ollama",
            "model_tag": tag,
            "num_ctx": 2048,
            "resources": {"cpu_cores": 1, "ram_mb": 64, "disk_mb": 0, "vram_mb": 0, "gpu": False},
        },
    }


class FakeRuntime:
    name, backend = "ollama", "process"
    allowed_paths = frozenset({"/api/chat", "/api/generate", "/v1/chat/completions", "/v1/completions"})

    def __init__(self, fail_at=None, pull_delay=0.0):
        self.fail_at = fail_at
        self.pull_delay = pull_delay
        self.started, self.removed = [], []
        self.alive: set[str] = set()

    async def capabilities(self):
        return RuntimeCapabilities("ollama", "1", "process", True, False, True)

    async def start(self, spec):
        if self.fail_at == "start":
            raise WorkloadError("RUNTIME_START_FAILED", "boom")
        self.started.append(spec.deployment_id)
        self.alive.add(spec.deployment_id)
        return WorkloadHandle(spec.deployment_id, "http://127.0.0.1:1", "process", {"pid": 1})

    async def prepare_model(self, handle, spec, progress):
        await progress("Downloading model: 50%")
        await asyncio.sleep(self.pull_delay)
        if self.fail_at == "pull":
            raise WorkloadError("MODEL_PULL_FAILED", "manifest not found")

    async def verify_ready(self, handle, spec):
        if self.fail_at == "ready":
            raise WorkloadError("HEALTHCHECK_FAILED", "no answer")
        return "sha256:abc"

    async def health(self, handle, spec):
        return handle.deployment_id in self.alive

    async def is_alive(self, handle):
        return handle.deployment_id in self.alive

    async def remove(self, handle):
        self.removed.append(handle.deployment_id)
        self.alive.discard(handle.deployment_id)


class FakeClient:
    headers: dict = {}

    def tunnel_url(self):
        return "ws://localhost:1/tunnel"

    def __init__(self):
        self.reports, self.acks = [], []
        self.revoked = False
        self.heartbeat_response = {"stop_deployments": [], "heartbeat_interval_seconds": 15}

    async def report(self, dep, state, message=None, error_code=None, model_digest=None):
        self.reports.append((dep, state, error_code))

    async def ack(self, cmd_id, status, error=None):
        self.acks.append((cmd_id, status))

    async def heartbeat(self, payload):
        if self.revoked:
            raise CredentialRevoked("revoked")
        self.last_heartbeat = payload
        return self.heartbeat_response

    async def disconnect(self):
        pass

    async def close(self):
        pass


@pytest.fixture
def make_worker(tmp_path):
    def _make(runtime=None):
        settings = WorkerSettings(DATA_DIR=str(tmp_path), CONTROL_PLANE_URL="http://localhost:1")
        return Worker(settings, runtime=runtime or FakeRuntime(), client=FakeClient())

    return _make


async def _settle(worker):
    for _ in range(50):
        if not worker.deploy_tasks:
            return
        await asyncio.sleep(0.01)


async def test_deploy_reports_full_lifecycle(make_worker):
    w = make_worker()
    await w.handle_command(deploy_cmd())
    await _settle(w)
    states = [s for _, s, _ in w.client.reports]
    assert states == ["PROVISIONING", "PROVISIONING", "STARTING", "READY"]
    assert w.client.acks == [("c1", "accepted")]
    assert w._resolve(DEP)[:2] == ("http://127.0.0.1:1", "qwen2.5:0.5b")


async def test_duplicate_command_is_not_executed_twice(make_worker):
    w = make_worker()
    await w.handle_command(deploy_cmd("c1"))
    await w.handle_command(deploy_cmd("c1"))  # redelivered after a lost ack
    await w.handle_command(deploy_cmd("c2"))  # different command, same deployment
    await _settle(w)
    assert w.runtime.started == [DEP]
    assert [a for a in w.client.acks] == [("c1", "accepted"), ("c1", "accepted"), ("c2", "accepted")]


async def test_processed_commands_survive_restart(make_worker):
    w = make_worker()
    await w.handle_command(deploy_cmd("c1"))
    await _settle(w)
    w2 = make_worker()
    await w2.handle_command(deploy_cmd("c1"))
    assert w2.runtime.started == []


@pytest.mark.parametrize(
    "stage,code", [("start", "RUNTIME_START_FAILED"), ("pull", "MODEL_PULL_FAILED"), ("ready", "HEALTHCHECK_FAILED")]
)
async def test_failures_are_reported_and_cleaned_up(make_worker, stage, code):
    rt = FakeRuntime(fail_at=stage)
    w = make_worker(rt)
    await w.handle_command(deploy_cmd())
    await _settle(w)
    assert w.client.reports[-1] == (DEP, "FAILED", code)
    assert DEP not in w.workloads and DEP not in w.state.workloads
    if stage != "start":
        assert rt.removed == [DEP]


async def test_unsafe_command_rejected_without_starting_anything(make_worker):
    w = make_worker()
    await w.handle_command(deploy_cmd(tag="evil; rm -rf ~"))
    assert w.runtime.started == []
    assert w.client.acks[0][1] == "failed"


async def test_stop_during_download_cancels_and_cleans_up(make_worker):
    rt = FakeRuntime(pull_delay=5)
    w = make_worker(rt)
    await w.handle_command(deploy_cmd())
    await asyncio.sleep(0.05)
    await w.handle_command({"id": "s1", "type": "STOP", "deployment_id": DEP, "payload": {"deployment_id": DEP}})
    assert rt.removed == [DEP]
    assert w.client.reports[-1] == (DEP, "STOPPED", None)
    assert ("s1", "succeeded") in w.client.acks
    assert "READY" not in [s for _, s, _ in w.client.reports]


async def test_heartbeat_reconciliation_stops_workload(make_worker):
    w = make_worker()
    await w.handle_command(deploy_cmd())
    await _settle(w)
    w.client.heartbeat_response = {"stop_deployments": [DEP]}
    await w.heartbeat_once()
    assert DEP not in w.workloads
    assert w.runtime.removed == [DEP]
    sent = w.client.last_heartbeat["deployments"]
    assert sent == [{"deployment_id": DEP, "state": "running", "healthy": True}]


async def test_restart_readopts_live_and_restarts_dead_workloads(make_worker):
    rt = FakeRuntime()
    w = make_worker(rt)
    await w.handle_command(deploy_cmd())
    await _settle(w)

    # Worker restarts while the runtime keeps running: re-adopted without a new start.
    w2 = make_worker(rt)
    await w2.adopt_existing()
    assert w2.workloads[DEP]["state"] == "running" and rt.started == [DEP]

    # Runtime died while the worker was down: restarted from the persisted spec.
    rt.alive.clear()
    w3 = make_worker(rt)
    await w3.adopt_existing()
    await _settle(w3)
    assert rt.started == [DEP, DEP]
    assert w3.workloads[DEP]["state"] == "running"


async def test_revoked_credential_stops_everything_and_forgets_credentials(make_worker, tmp_path):
    w = make_worker()
    w.state.save_credentials("n", "secret", "http://localhost:1")
    await w.handle_command(deploy_cmd())
    await _settle(w)
    w.client.revoked = True

    async def no_tunnel(*a, **k):
        await asyncio.Event().wait()

    import node_agent.worker as worker_mod

    orig = worker_mod.run_tunnel
    worker_mod.run_tunnel = no_tunnel

    async def never_poll(**kw):
        await asyncio.Event().wait()

    w.client.poll = never_poll
    try:
        code = await asyncio.wait_for(w.run(), 5)
    finally:
        worker_mod.run_tunnel = orig
    assert code == 2
    assert w.runtime.removed == [DEP]
    assert w.state.load_credentials() is None


def test_credentials_file_permissions(tmp_path):
    from node_agent.state import WorkerState

    st = WorkerState(tmp_path)
    st.save_credentials("n", "secret", "https://x")
    assert oct((tmp_path / "credentials.json").stat().st_mode & 0o777) == "0o600"
    assert json.loads((tmp_path / "credentials.json").read_text())["node_credential"] == "secret"


@pytest.mark.parametrize(
    "url,ok",
    [("https://cp.example", True), ("http://localhost:8000", True), ("http://cp.example", False), ("ftp://x", False)],
)
def test_control_plane_url_policy(url, ok):
    if ok:
        WorkerSettings(CONTROL_PLANE_URL=url)
    else:
        with pytest.raises(ValueError):
            WorkerSettings(CONTROL_PLANE_URL=url)


class FlakyPullRuntime(FakeRuntime):
    def __init__(self, failures, transient=True):
        super().__init__()
        self.failures = failures
        self.transient = transient
        self.pull_calls = 0

    async def prepare_model(self, handle, spec, progress):
        self.pull_calls += 1
        if self.pull_calls <= self.failures:
            raise WorkloadError("MODEL_PULL_FAILED", "registry returned 503", transient=self.transient)


@pytest.fixture
def fast_retries(make_worker):
    def _make(runtime):
        w = make_worker(runtime)
        w.settings.PULL_RETRY_BASE_SECONDS = 0.01
        return w

    return _make


async def test_transient_pull_failures_are_retried(fast_retries):
    rt = FlakyPullRuntime(failures=2)
    w = fast_retries(rt)
    await w.handle_command(deploy_cmd())
    await _settle(w)
    assert rt.pull_calls == 3
    assert w.client.reports[-1][1] == "READY"


async def test_pull_retries_are_bounded(fast_retries):
    rt = FlakyPullRuntime(failures=10)
    w = fast_retries(rt)
    await w.handle_command(deploy_cmd())
    await _settle(w)
    assert rt.pull_calls == 3
    assert w.client.reports[-1] == (DEP, "FAILED", "MODEL_PULL_FAILED")


async def test_permanent_pull_failure_is_not_retried(fast_retries):
    rt = FlakyPullRuntime(failures=10, transient=False)
    w = fast_retries(rt)
    await w.handle_command(deploy_cmd())
    await _settle(w)
    assert rt.pull_calls == 1


def test_transient_error_classification():
    from node_agent.runtime.ollama_api import is_transient

    assert is_transient("503: ") and is_transient("read: connection reset by peer") and is_transient("i/o timeout")
    assert not is_transient("pull model manifest: file does not exist")


async def test_restart_command_redeploys_without_reporting_stopped(make_worker):
    w = make_worker()
    await w.handle_command(deploy_cmd())
    await _settle(w)
    w.client.reports.clear()
    restart = {**deploy_cmd("r1"), "type": "RESTART"}
    await w.handle_command(restart)
    await _settle(w)
    assert w.runtime.removed == [DEP] and w.runtime.started == [DEP, DEP]
    states = [s for _, s, _ in w.client.reports]
    assert "STOPPED" not in states and states[-1] == "READY"


async def test_unexpected_runtime_bug_is_reported_not_stranded(make_worker):
    class Buggy(FakeRuntime):
        async def prepare_model(self, handle, spec, progress):
            raise TypeError("bug in runtime code")

    rt = Buggy()
    w = make_worker(rt)
    await w.handle_command(deploy_cmd())
    await _settle(w)
    assert w.client.reports[-1] == (DEP, "FAILED", "WORKER_ERROR")
    assert rt.removed == [DEP] and DEP not in w.workloads
