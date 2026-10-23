"""Ollama backend for the Docker worker: one container per deployment.

Container hardening: memory and CPU limits, PID limit, all capabilities dropped, no-new-privileges, read-only
root filesystem with a tmpfs /tmp, no host bind mounts (only the AgentMesh-owned model cache volume), and no
Docker socket. GPUs are attached only when the deployment needs one and the provider allowed GPU use.
The serving port is published on loopback only, or the container joins a private network shared with the
worker. Containers this worker did not create (by label) are never touched.

Network egress: when a workload network is configured (the worker runs in a container), that network is
created as ``internal`` (no route out). The container joins the egress network only while it downloads the
model and is disconnected before it serves any request. In loopback mode (worker on the host) Docker cannot
isolate egress this way, and the runtime reports ``egress_restricted=False``.

Containers do not protect the workload from the host administrator; see docs/IMPLEMENTATION_PLAN.md.
"""

import asyncio

from . import ollama_api
from .base import ProgressCallback, RuntimeCapabilities, WorkloadError, WorkloadHandle, WorkloadRuntime, WorkloadSpec

LABEL = "io.agentmesh.managed"
LABEL_DEPLOYMENT = "io.agentmesh.deployment"


class OllamaDockerRuntime(WorkloadRuntime):
    name = "ollama"
    backend = "docker"
    allowed_paths = ollama_api.ALLOWED_PATHS

    def __init__(
        self,
        image: str,
        models_volume: str = "agentmesh-models",
        network: str = "",
        docker_host: str = "",
        allow_gpu: bool = False,
        client=None,
        egress_network: str = "",
    ):
        self.image = image
        self.models_volume = models_volume
        self.network = network
        self.egress_network = egress_network if network else ""
        self.allow_gpu = allow_gpu
        self._docker_host = docker_host
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import docker

            self._client = docker.DockerClient(base_url=self._docker_host) if self._docker_host else docker.from_env()
        return self._client

    async def _call(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def capabilities(self) -> RuntimeCapabilities:
        try:
            await self._call(self.client.ping)
        except Exception as exc:  # noqa: BLE001
            return RuntimeCapabilities(
                "ollama", "", "docker", False, False, True, f"Docker unavailable: {type(exc).__name__}"
            )
        version = self.image.rsplit(":", 1)[-1] if ":" in self.image and "@" not in self.image else self.image
        detail = "container limits; egress " + ("restricted after download" if self.egress_restricted else "open")
        return RuntimeCapabilities("ollama", version[:50], "docker", True, self.allow_gpu, True, detail)

    @property
    def egress_restricted(self) -> bool:
        return bool(self.network and self.egress_network)

    async def _ensure_networks(self) -> None:
        import docker

        if not self.network:
            return
        try:
            net = await self._call(self.client.networks.get, self.network)
            if self.egress_network and not net.attrs.get("Internal"):
                raise WorkloadError(
                    "RUNTIME_START_FAILED",
                    f"Workload network '{self.network}' must be internal (no egress); recreate it with --internal",
                )
        except docker.errors.NotFound:
            await self._call(
                self.client.networks.create,
                self.network,
                driver="bridge",
                internal=bool(self.egress_network),
                labels={LABEL: "true"},
            )
        if self.egress_network:
            try:
                await self._call(self.client.networks.get, self.egress_network)
            except docker.errors.NotFound:
                await self._call(
                    self.client.networks.create, self.egress_network, driver="bridge", labels={LABEL: "true"}
                )

    async def _ensure_image(self) -> None:
        import docker

        try:
            await self._call(self.client.images.get, self.image)
        except docker.errors.ImageNotFound:
            try:
                await self._call(self.client.images.pull, self.image)
            except docker.errors.APIError as exc:
                raise WorkloadError(
                    "RUNTIME_IMAGE_UNAVAILABLE", f"Could not pull runtime image: {exc.explanation}"
                ) from None

    def _container_name(self, deployment_id: str) -> str:
        return f"agentmesh-wl-{deployment_id}"

    async def start(self, spec: WorkloadSpec) -> WorkloadHandle:
        import docker

        await self._ensure_image()
        await self._ensure_networks()
        name = self._container_name(spec.deployment_id)
        # A leftover container from an interrupted attempt is ours by name and label; replace it.
        await self._remove_by_name(name)
        port = self.internal_port
        kwargs = dict(
            name=name,
            detach=True,
            labels={LABEL: "true", LABEL_DEPLOYMENT: spec.deployment_id},
            mem_limit=f"{spec.ram_mb}m",
            memswap_limit=f"{spec.ram_mb}m",
            nano_cpus=int(spec.cpu_cores * 1e9),
            pids_limit=512,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            restart_policy={"Name": "no"},
            **self._container_config(spec),
        )
        if spec.gpu and self.allow_gpu:
            kwargs["device_requests"] = [docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])]
        if self.network:
            kwargs["network"] = self.network
        else:
            kwargs["ports"] = {f"{port}/tcp": ("127.0.0.1", None)}
        try:
            container = await self._call(self.client.containers.run, self.image, **kwargs)
        except docker.errors.APIError as exc:
            raise WorkloadError(
                "RUNTIME_START_FAILED", f"Could not start runtime container: {exc.explanation}"
            ) from None

        if self.egress_restricted:
            # Temporary internet access for the model download only (see prepare_model).
            egress = await self._call(self.client.networks.get, self.egress_network)
            await self._call(egress.connect, container)
        if self.network:
            base_url = f"http://{name}:{port}"
        else:
            await self._call(container.reload)
            binding = container.attrs["NetworkSettings"]["Ports"][f"{port}/tcp"][0]
            base_url = f"http://127.0.0.1:{binding['HostPort']}"
        handle = WorkloadHandle(
            spec.deployment_id, base_url, "docker", {"container_id": container.id, "name": name, "runtime": self.name}
        )

        async def alive():
            return await self.is_alive(handle)

        try:
            await self._wait_started(base_url, alive)
        except WorkloadError:
            await self.remove(handle)
            raise
        return handle

    # --- hooks for other containerised runtimes (see vllm.py) ---------------------------------------------

    internal_port = 11434

    def _container_config(self, spec: WorkloadSpec) -> dict:
        return {
            "environment": {
                "OLLAMA_HOST": "0.0.0.0:11434",
                "OLLAMA_KEEP_ALIVE": "-1",
                "OLLAMA_NUM_PARALLEL": "1",
                "OLLAMA_MAX_LOADED_MODELS": "1",
                "OLLAMA_NOHISTORY": "1",
            },
            "volumes": {self.models_volume: {"bind": "/root/.ollama", "mode": "rw"}},
            "read_only": True,
            "tmpfs": {"/tmp": "rw,noexec,nosuid,size=512m"},
        }

    async def _wait_started(self, base_url: str, alive) -> None:
        await ollama_api.wait_api(base_url, timeout=90, is_alive=alive)

    async def prepare_model(self, handle: WorkloadHandle, spec: WorkloadSpec, progress: ProgressCallback) -> None:
        try:
            await ollama_api.pull(handle.base_url, spec.model_tag, progress)
        finally:
            if self.egress_restricted:
                await self._cut_egress(handle)

    async def _cut_egress(self, handle: WorkloadHandle) -> None:
        import docker

        container = await self._get_owned(handle.ref.get("container_id") or handle.ref.get("name", ""))
        if container is None:
            return
        egress = await self._call(self.client.networks.get, self.egress_network)
        try:
            await self._call(egress.disconnect, container, force=True)
        except docker.errors.APIError as exc:
            # Never serve with internet access that was promised to be removed.
            raise WorkloadError("RUNTIME_START_FAILED", f"Could not remove egress access: {exc.explanation}") from None

    async def verify_ready(self, handle: WorkloadHandle, spec: WorkloadSpec) -> str | None:
        return await ollama_api.verify_ready(handle.base_url, spec.model_tag, spec.num_ctx)

    async def health(self, handle: WorkloadHandle, spec: WorkloadSpec) -> bool:
        return await self.is_alive(handle) and await ollama_api.health(handle.base_url, spec.model_tag)

    async def _get_owned(self, ref: str):
        import docker

        try:
            container = await self._call(self.client.containers.get, ref)
        except docker.errors.NotFound:
            return None
        if container.labels.get(LABEL) != "true":
            return None  # never touch containers AgentMesh did not create
        return container

    async def is_alive(self, handle: WorkloadHandle) -> bool:
        container = await self._get_owned(handle.ref.get("container_id") or handle.ref.get("name", ""))
        if container is None:
            return False
        await self._call(container.reload)
        return container.status == "running"

    async def _remove_by_name(self, name: str) -> None:
        container = await self._get_owned(name)
        if container is not None:
            await self._call(container.remove, force=True)

    async def remove(self, handle: WorkloadHandle) -> None:
        import docker

        container = await self._get_owned(handle.ref.get("container_id") or handle.ref.get("name", ""))
        if container is None:
            return
        try:
            await self._call(container.stop, timeout=10)
        except docker.errors.APIError:
            pass
        try:
            await self._call(container.remove, force=True)
        except docker.errors.NotFound:
            pass
