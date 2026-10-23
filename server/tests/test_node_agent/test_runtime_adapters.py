"""Runtime adapter unit tests. The Docker backend uses a fake Docker client here; it has not yet been run
against a real Docker daemon (see docs/IMPLEMENTATION_PLAN.md)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from node_agent.runtime.base import WorkloadError, WorkloadHandle, WorkloadSpec
from node_agent.runtime.ollama_docker import LABEL, OllamaDockerRuntime
from node_agent.runtime.ollama_process import OllamaProcessRuntime
from node_agent.worker import parse_deploy_payload

DEP = "11111111-2222-3333-4444-555555555555"
SPEC = WorkloadSpec(DEP, "qwen2.5:0.5b", 2048, 2, 1024, 768, 0, False)


class FakeContainer:
    def __init__(self, labels, status="running"):
        self.id = "c123"
        self.labels = labels
        self.status = status
        self.attrs = {"NetworkSettings": {"Ports": {"11434/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49999"}]}}}
        self.removed = False

    def reload(self):
        pass

    def stop(self, timeout=10):
        self.status = "exited"

    def remove(self, force=False):
        self.removed = True


class FakeDocker:
    def __init__(self, existing=None):
        import docker

        self.errors = docker.errors
        self.run_kwargs = None
        self.existing = existing or {}
        outer = self

        class Containers:
            def run(self, image, **kwargs):
                outer.run_kwargs = {"image": image, **kwargs}
                c = FakeContainer(kwargs["labels"])
                outer.existing[kwargs["name"]] = c
                outer.existing[c.id] = c
                return c

            def get(self, ref):
                if ref in outer.existing:
                    return outer.existing[ref]
                raise docker.errors.NotFound("nope")

        class Images:
            def get(self, ref):
                return object()

        self.containers = Containers()
        self.images = Images()

    def ping(self):
        return True


async def test_docker_runtime_applies_isolation_and_limits(monkeypatch):
    fake = FakeDocker()
    rt = OllamaDockerRuntime("ollama/ollama:test", client=fake)

    async def ok(*a, **k):
        return "0.0.0"

    monkeypatch.setattr("node_agent.runtime.ollama_api.wait_api", ok)
    handle = await rt.start(SPEC)

    kw = fake.run_kwargs
    assert kw["mem_limit"] == "1024m" and kw["memswap_limit"] == "1024m"
    assert kw["nano_cpus"] == 2_000_000_000
    assert kw["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in kw["security_opt"]
    assert kw["read_only"] is True
    assert kw["ports"] == {"11434/tcp": ("127.0.0.1", None)}  # loopback only
    assert "privileged" not in kw and "network_mode" not in kw
    assert "device_requests" not in kw  # no GPU unless requested and allowed
    # Only the AgentMesh model cache volume is mounted: no host paths, no Docker socket.
    assert list(kw["volumes"]) == ["agentmesh-models"]
    assert all("docker.sock" not in str(v) for v in kw["volumes"].values())
    assert kw["labels"][LABEL] == "true"
    assert handle.base_url == "http://127.0.0.1:49999"


async def test_docker_runtime_gpu_only_when_allowed(monkeypatch):
    async def ok(*a, **k):
        return "0"

    monkeypatch.setattr("node_agent.runtime.ollama_api.wait_api", ok)
    gpu_spec = WorkloadSpec(DEP, "qwen2.5:0.5b", 2048, 2, 1024, 768, 4096, True)
    fake = FakeDocker()
    await OllamaDockerRuntime("img", client=fake, allow_gpu=False).start(gpu_spec)
    assert "device_requests" not in fake.run_kwargs
    fake = FakeDocker()
    await OllamaDockerRuntime("img", client=fake, allow_gpu=True).start(gpu_spec)
    assert fake.run_kwargs["device_requests"]


async def test_docker_runtime_never_touches_unlabelled_containers():
    foreign = FakeContainer(labels={})
    fake = FakeDocker(existing={"provider-ollama": foreign})
    rt = OllamaDockerRuntime("img", client=fake)
    await rt.remove(WorkloadHandle(DEP, "", "docker", {"container_id": "provider-ollama"}))
    assert foreign.removed is False
    assert await rt.is_alive(WorkloadHandle(DEP, "", "docker", {"container_id": "provider-ollama"})) is False


def test_process_runtime_environment_is_isolated(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-leak")
    monkeypatch.setenv("OLLAMA_MODELS", "/home/someone/.ollama/models")
    rt = OllamaProcessRuntime(tmp_path, cgroup_limits=False)
    env = rt._env(43210, SPEC)
    assert env["OLLAMA_HOST"] == "127.0.0.1:43210"  # loopback, never 0.0.0.0 or the default 11434
    assert env["OLLAMA_MODELS"] == str(tmp_path / "models")  # never the provider's own model store
    assert "OPENAI_API_KEY" not in env
    assert env["CUDA_VISIBLE_DEVICES"] == "-1"


def _payload(**over):
    p = {
        "deployment_id": DEP,
        "runtime": "ollama",
        "model_tag": "qwen2.5:0.5b",
        "num_ctx": 2048,
        "resources": {"cpu_cores": 1, "ram_mb": 1024, "disk_mb": 768, "vram_mb": 0, "gpu": False},
    }
    p.update(over)
    return p


def test_deploy_payload_accepts_valid():
    spec = parse_deploy_payload(_payload())
    assert spec.model_tag == "qwen2.5:0.5b" and spec.ram_mb == 1024


@pytest.mark.parametrize(
    "bad",
    [
        {"model_tag": "qwen; rm -rf /"},
        {"model_tag": "https://evil.example/model"},
        {"model_tag": "../../etc/passwd"},
        {"runtime": "shell"},
        {"deployment_id": "not-a-uuid"},
        {"resources": {"cpu_cores": "x"}},
        {"num_ctx": 10},
    ],
)
def test_deploy_payload_rejects_unsafe_input(bad):
    with pytest.raises(WorkloadError):
        parse_deploy_payload(_payload(**bad))


def test_hardware_report_shape(tmp_path):
    from node_agent.hardware.discovery import default_allocation, hardware_report

    hw = hardware_report(str(tmp_path))
    assert hw["cpu_cores"] >= 1 and hw["ram_mb"] > 0
    settings = SimpleNamespace(MAX_CPU_CORES=None, MAX_RAM_MB=None, MAX_DISK_MB=None, ALLOW_GPU=False, MAX_VRAM_MB=None)
    alloc = default_allocation(hw, settings)
    # Never offers the whole machine by default.
    assert alloc["ram_mb"] <= hw["ram_mb"] // 2 + 1
    assert alloc["vram_mb"] == 0


class FakeNetwork:
    def __init__(self, name, internal):
        self.name = name
        self.attrs = {"Internal": internal}
        self.members: set[str] = set()
        self.log: list[tuple[str, str]] = []

    def connect(self, container):
        self.members.add(container.id)
        self.log.append(("connect", container.id))

    def disconnect(self, container, force=False):
        self.members.discard(container.id)
        self.log.append(("disconnect", container.id))


def _with_networks(fake, existing=None):
    import docker

    fake.nets = dict(existing or {})

    class Networks:
        def get(self, name):
            if name in fake.nets:
                return fake.nets[name]
            raise docker.errors.NotFound("no net")

        def create(self, name, driver="bridge", internal=False, labels=None):
            fake.nets[name] = FakeNetwork(name, internal)
            return fake.nets[name]

    fake.networks = Networks()
    return fake


async def test_docker_egress_is_cut_after_download(monkeypatch):
    calls = []

    async def ok(*a, **k):
        return "0"

    async def fake_pull(base_url, tag, progress, **kw):
        # During the download the container is on the egress network.
        calls.append(sorted(n for n, net in fake.nets.items() if "c123" in net.members))

    monkeypatch.setattr("node_agent.runtime.ollama_api.wait_api", ok)
    monkeypatch.setattr("node_agent.runtime.ollama_api.pull", fake_pull)
    fake = _with_networks(FakeDocker())
    rt = OllamaDockerRuntime("img", client=fake, network="agentmesh-workloads", egress_network="agentmesh-egress")
    handle = await rt.start(SPEC)
    assert fake.nets["agentmesh-workloads"].attrs["Internal"] is True  # created without a route out
    assert fake.run_kwargs["network"] == "agentmesh-workloads" and "ports" not in fake.run_kwargs
    await rt.prepare_model(handle, SPEC, None)
    assert calls == [["agentmesh-egress"]]
    assert "c123" not in fake.nets["agentmesh-egress"].members  # no internet once serving
    assert handle.base_url == "http://agentmesh-wl-11111111-2222-3333-4444-555555555555:11434"


async def test_docker_egress_cut_even_when_download_fails(monkeypatch):
    async def ok(*a, **k):
        return "0"

    async def failing_pull(*a, **k):
        raise WorkloadError("MODEL_PULL_FAILED", "nope")

    monkeypatch.setattr("node_agent.runtime.ollama_api.wait_api", ok)
    monkeypatch.setattr("node_agent.runtime.ollama_api.pull", failing_pull)
    fake = _with_networks(FakeDocker())
    rt = OllamaDockerRuntime("img", client=fake, network="wl", egress_network="eg")
    handle = await rt.start(SPEC)
    with pytest.raises(WorkloadError):
        await rt.prepare_model(handle, SPEC, None)
    assert fake.nets["eg"].log[-1] == ("disconnect", "c123")


async def test_docker_refuses_non_internal_workload_network(monkeypatch):
    fake = _with_networks(FakeDocker(), {"wl": FakeNetwork("wl", internal=False)})
    rt = OllamaDockerRuntime("img", client=fake, network="wl", egress_network="eg")
    with pytest.raises(WorkloadError, match="must be internal"):
        await rt.start(SPEC)


async def test_loopback_mode_reports_open_egress():
    rt = OllamaDockerRuntime("img", client=FakeDocker(), egress_network="eg")  # no workload network
    caps = await rt.capabilities()
    assert rt.egress_restricted is False and "egress open" in caps.detail


# --- Phase 5: llama.cpp and vLLM adapters ------------------------------------------------------------------

HF_SOURCE = {
    "type": "huggingface",
    "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
    "revision": "9" * 40,
    "file": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
    "sha256": "a" * 64,
    "size": 100,
}
VLLM_SOURCE = {"type": "huggingface", "repo": "Qwen/Qwen2.5-0.5B-Instruct", "revision": "7" * 40}
LLAMA_SPEC = WorkloadSpec(DEP, "Qwen/Qwen2.5-0.5B-Instruct-GGUF", 2048, 2, 900, 640, 0, False, "llamacpp", HF_SOURCE)
VLLM_SPEC = WorkloadSpec(DEP, "Qwen/Qwen2.5-0.5B-Instruct", 4096, 2, 4096, 2048, 6144, True, "vllm", VLLM_SOURCE)


def test_llamacpp_argv_is_loopback_cpu_and_pinned_to_served_name(tmp_path):
    from node_agent.runtime.llamacpp_process import LlamaCppProcessRuntime

    rt = LlamaCppProcessRuntime(tmp_path, binary="/opt/llama-server", cgroup_limits=False)
    argv = rt._argv(tmp_path / "x.gguf", 41234, LLAMA_SPEC)
    joined = " ".join(argv)
    assert "--host 127.0.0.1 --port 41234" in joined and "0.0.0.0" not in joined
    assert "-ngl 0" in joined and "-c 2048" in joined and "-t 2" in joined
    assert argv[argv.index("--alias") + 1] == "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
    assert "/v1/chat/completions" in rt.allowed_paths and "/api/chat" not in rt.allowed_paths


async def test_llamacpp_rejects_unpinned_source(tmp_path):
    from dataclasses import replace

    from node_agent.runtime.llamacpp_process import LlamaCppProcessRuntime

    rt = LlamaCppProcessRuntime(tmp_path, cgroup_limits=False)
    with pytest.raises(WorkloadError):
        await rt.start(replace(LLAMA_SPEC, source={**HF_SOURCE, "revision": "main"}))


async def test_vllm_docker_container(monkeypatch):
    from node_agent.runtime.vllm import VLLMDockerRuntime

    fake = _with_networks(FakeDocker())
    rt = VLLMDockerRuntime(
        "vllm/vllm-openai:test", client=fake, allow_gpu=True, total_vram_mb=24576, network="wl", egress_network="eg"
    )
    handle = await rt.start(VLLM_SPEC)
    kw = fake.run_kwargs
    cmd = kw["command"]
    assert cmd[cmd.index("--model") + 1] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert cmd[cmd.index("--revision") + 1] == "7" * 40
    assert cmd[cmd.index("--served-model-name") + 1] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert cmd[cmd.index("--gpu-memory-utilization") + 1] == "0.25"  # 6144 of 24576 MB reserved
    assert kw["device_requests"] and kw["environment"]["VLLM_NO_USAGE_STATS"] == "1"
    assert kw["cap_drop"] == ["ALL"] and "privileged" not in kw and "ipc_mode" not in kw
    assert handle.base_url.endswith(":8000")

    async def ready(*a, **k):
        return None

    monkeypatch.setattr("node_agent.runtime.vllm._wait_ready", ready)
    await rt.prepare_model(handle, VLLM_SPEC, ready)
    assert fake.nets["eg"].log[-1] == ("disconnect", "c123")  # no internet once loaded


async def test_vllm_refuses_without_gpu(tmp_path):
    from dataclasses import replace

    from node_agent.runtime.vllm import VLLMDockerRuntime, VLLMProcessRuntime

    with pytest.raises(WorkloadError, match="GPU"):
        await VLLMProcessRuntime(tmp_path, cgroup_limits=False).start(replace(VLLM_SPEC, gpu=False))
    with pytest.raises(WorkloadError, match="GPU"):
        await VLLMDockerRuntime("img", client=FakeDocker(), allow_gpu=False).start(VLLM_SPEC)
    caps = await VLLMProcessRuntime(tmp_path, binary="/bin/true", cgroup_limits=False, total_vram_mb=0).capabilities()
    assert caps.available is False and "GPU" in caps.detail


def test_deploy_payload_per_runtime():
    llama = _payload(runtime="llamacpp", model_tag="Qwen/Qwen2.5-0.5B-Instruct-GGUF", source=HF_SOURCE)
    assert parse_deploy_payload(llama).source["sha256"] == "a" * 64
    vllm = _payload(
        runtime="vllm",
        model_tag="Qwen/Qwen2.5-0.5B-Instruct",
        source=VLLM_SOURCE,
        resources={"cpu_cores": 2, "ram_mb": 4096, "disk_mb": 2048, "vram_mb": 4096, "gpu": True},
    )
    assert parse_deploy_payload(vllm).runtime == "vllm"
    for bad in (
        _payload(runtime="llamacpp", model_tag="x/y", source={**HF_SOURCE, "sha256": None}),
        _payload(runtime="llamacpp", model_tag="x/y", source={**HF_SOURCE, "type": "url"}),
        _payload(runtime="vllm", model_tag="x/y", source=VLLM_SOURCE),  # no GPU
        _payload(runtime="llamacpp", model_tag="x/../../y", source=HF_SOURCE),
    ):
        with pytest.raises(WorkloadError):
            parse_deploy_payload(bad)
