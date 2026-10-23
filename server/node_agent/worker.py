"""AgentMesh worker: shared by the Docker worker (MODE=docker) and the installable agent (MODE=agent).

Loops, all outbound:
  * heartbeat  - capabilities, allocation, workload health; receives reconciliation instructions
  * commands   - long-polls the persisted command queue (DEPLOY / STOP)
  * tunnel     - WebSocket carrying gateway inference requests to managed runtimes
  * health     - periodic local health checks of running workloads
"""

import asyncio
import contextlib
import logging
import re
from dataclasses import asdict
from datetime import datetime

import psutil

from . import schedule as availability_schedule
from .config import PROTOCOL_VERSION, WORKER_VERSION, WorkerSettings
from .hardware.discovery import default_allocation, hardware_report
from .metrics.collector import MetricsCollector
from .protocol import ControlPlaneClient, CredentialRevoked, ProtocolError, backoff
from .runtime.base import WorkloadError, WorkloadHandle, WorkloadRuntime, WorkloadSpec
from .state import WorkerState
from .tunnel import TunnelHandler, run_tunnel

logger = logging.getLogger(__name__)

TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}(/[a-z0-9][a-z0-9._-]{0,63})?(:[a-zA-Z0-9][a-zA-Z0-9._-]{0,63})?$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


KNOWN_RUNTIMES = ("ollama", "llamacpp", "vllm")
HF_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,191}$")


def _total_vram_mb(settings: WorkerSettings) -> int:
    if not settings.ALLOW_GPU:
        return 0
    return sum(g["vram_mb"] for g in hardware_report(settings.DATA_DIR)["gpus"])


def make_runtimes(settings: WorkerSettings) -> dict[str, WorkloadRuntime]:
    """Runtimes enabled in config. Each reports honestly whether it can run here (binary, GPU, Docker)."""
    hosts = tuple(h.strip() for h in settings.ALLOWED_MODEL_HOSTS.split(",") if h.strip())
    enabled = [r.strip() for r in settings.ENABLED_RUNTIMES.split(",") if r.strip() in KNOWN_RUNTIMES]
    vram = _total_vram_mb(settings)
    runtimes: dict[str, WorkloadRuntime] = {}
    if settings.RUNTIME_BACKEND == "docker":
        from .runtime.ollama_docker import OllamaDockerRuntime
        from .runtime.vllm import VLLMDockerRuntime

        common = dict(
            models_volume=settings.MODELS_VOLUME,
            network=settings.WORKLOAD_NETWORK,
            docker_host=settings.DOCKER_HOST,
            allow_gpu=settings.ALLOW_GPU,
            egress_network=settings.EGRESS_NETWORK,
        )
        if "ollama" in enabled:
            runtimes["ollama"] = OllamaDockerRuntime(image=settings.OLLAMA_IMAGE, **common)
        if "vllm" in enabled:
            runtimes["vllm"] = VLLMDockerRuntime(image=settings.VLLM_IMAGE, total_vram_mb=vram, **common)
        # llama.cpp is only offered by the installable agent for now.
        return runtimes
    from .runtime.llamacpp_process import LlamaCppProcessRuntime
    from .runtime.ollama_process import OllamaProcessRuntime
    from .runtime.vllm import VLLMProcessRuntime

    if "ollama" in enabled:
        runtimes["ollama"] = OllamaProcessRuntime(
            settings.data_path, settings.OLLAMA_BINARY, settings.PROCESS_CGROUP_LIMITS
        )
    if "llamacpp" in enabled:
        runtimes["llamacpp"] = LlamaCppProcessRuntime(
            settings.data_path, settings.LLAMA_SERVER_BINARY, settings.PROCESS_CGROUP_LIMITS, allowed_hosts=hosts
        )
    if "vllm" in enabled:
        runtimes["vllm"] = VLLMProcessRuntime(
            settings.data_path, settings.VLLM_BINARY, settings.PROCESS_CGROUP_LIMITS, total_vram_mb=vram
        )
    return runtimes


def make_runtime(settings: WorkerSettings) -> WorkloadRuntime:
    """Primary runtime (Ollama) - kept for callers that manage a single runtime."""
    runtimes = make_runtimes(settings)
    return runtimes.get("ollama") or next(iter(runtimes.values()))


def parse_deploy_payload(payload: dict) -> WorkloadSpec:
    """Validate a DEPLOY command. Anything unexpected is rejected rather than passed to the runtime."""
    from .runtime.model_store import validate_source

    dep_id = str(payload.get("deployment_id", ""))
    tag = str(payload.get("model_tag", ""))
    runtime = payload.get("runtime")
    res = payload.get("resources") or {}
    if not UUID_RE.fullmatch(dep_id):
        raise WorkloadError("INVALID_COMMAND", "Invalid deployment id")
    if runtime not in KNOWN_RUNTIMES:
        raise WorkloadError("UNSUPPORTED_RUNTIME", "Unsupported runtime")
    source = None
    if runtime == "ollama":
        if not TAG_RE.fullmatch(tag):
            raise WorkloadError("INVALID_MODEL", "Invalid model identifier")
    else:
        source = validate_source(payload.get("source"), needs_file=runtime == "llamacpp")
        if not HF_NAME_RE.fullmatch(tag) or ".." in tag:
            raise WorkloadError("INVALID_MODEL", "Invalid served model name")
    try:
        spec = WorkloadSpec(
            deployment_id=dep_id,
            model_tag=tag,
            num_ctx=int(payload.get("num_ctx", 2048)),
            cpu_cores=int(res["cpu_cores"]),
            ram_mb=int(res["ram_mb"]),
            disk_mb=int(res["disk_mb"]),
            vram_mb=int(res.get("vram_mb", 0)),
            gpu=bool(res.get("gpu", False)),
            runtime=runtime,
            source=source,
        )
    except (KeyError, TypeError, ValueError):
        raise WorkloadError("INVALID_COMMAND", "Invalid resource specification") from None
    if not (512 <= spec.num_ctx <= 131072 and 1 <= spec.cpu_cores <= 4096 and 64 <= spec.ram_mb and spec.disk_mb >= 0):
        raise WorkloadError("INVALID_COMMAND", "Resource values out of range")
    if runtime == "vllm" and not spec.gpu:
        raise WorkloadError("UNSUPPORTED_RUNTIME", "vLLM deployments require a GPU")
    return spec


class Worker:
    def __init__(
        self,
        settings: WorkerSettings,
        runtime: WorkloadRuntime | None = None,
        client: ControlPlaneClient | None = None,
        runtimes: dict[str, WorkloadRuntime] | None = None,
    ):
        self.settings = settings
        self.state = WorkerState(settings.data_path)
        if runtimes is None:
            runtimes = {runtime.name: runtime} if runtime is not None else make_runtimes(settings)
        self.runtimes: dict[str, WorkloadRuntime] = runtimes
        self.runtime = next(iter(runtimes.values()))  # primary runtime (kept for callers that expect one)
        creds = self.state.load_credentials()
        if client is None:
            if not creds:
                raise SystemExit("This machine is not enrolled. Run: python -m node_agent enroll --token <token>")
            client = ControlPlaneClient(settings.CONTROL_PLANE_URL, creds["node_id"], creds["node_credential"])
        self.client = client
        self.metrics = MetricsCollector()
        self.stop_event = asyncio.Event()
        self.revoked = False
        self.exit_code = 0
        # deployment_id -> {"spec": WorkloadSpec, "handle": WorkloadHandle|None, "state": str, "healthy": bool}
        self.workloads: dict[str, dict] = {}
        self.deploy_tasks: dict[str, asyncio.Task] = {}
        self.schedule = availability_schedule.parse(settings.AVAILABILITY_SCHEDULE)
        self._last_availability: tuple[bool, str | None] = (True, None)
        self.tunnel = TunnelHandler(
            self._resolve, settings.MAX_CONCURRENT_REQUESTS_PER_DEPLOYMENT, settings.REQUEST_TIMEOUT_SECONDS
        )

    # --- helpers -----------------------------------------------------------------------------------

    def _rt(self, spec: WorkloadSpec) -> WorkloadRuntime:
        runtime = self.runtimes.get(spec.runtime)
        if runtime is None:
            raise WorkloadError("RUNTIME_UNAVAILABLE", f"Runtime '{spec.runtime}' is not available on this node")
        return runtime

    def _resolve(self, deployment_id: str):
        w = self.workloads.get(deployment_id)
        if w and w["state"] == "running" and w["handle"] is not None:
            rt = self.runtimes.get(w["spec"].runtime)
            return w["handle"].base_url, w["spec"].model_tag, (rt.allowed_paths if rt else frozenset())
        return None

    def _persist(self, dep_id: str) -> None:
        w = self.workloads.get(dep_id)
        if w is None:
            self.state.drop_workload(dep_id)
            return
        self.state.put_workload(
            dep_id,
            {
                "spec": asdict(w["spec"]),
                "handle": asdict(w["handle"]) if w["handle"] else None,
                "state": w["state"],
            },
        )

    def availability(self, now: datetime | None = None) -> tuple[bool, str | None, bool]:
        """(available, reason, drain). Local CLI controls win over the schedule."""
        control = self.state.control()
        if control["draining"]:
            return False, "draining", True
        if control["paused"]:
            return False, "paused", False
        if not availability_schedule.is_available(self.schedule, now or datetime.now()):
            return False, "schedule", self.settings.OUTSIDE_SCHEDULE == "drain"
        return True, None, False

    async def drain(self, reason: str) -> None:
        """Stop every workload and tell the control plane why, so it moves them to other nodes."""
        for dep_id in list(self.workloads):
            logger.info("Draining workload %s (%s)", dep_id, reason)
            await self.stop_workload(
                dep_id, error_code="NODE_UNAVAILABLE", message=f"Provider made the node unavailable ({reason})"
            )

    async def capabilities_payload(self) -> dict:
        hw = hardware_report(self.settings.DATA_DIR)
        runtimes = []
        for rt in self.runtimes.values():
            caps = await rt.capabilities()
            runtimes.append(
                {"name": caps.name, "version": caps.version, "backend": caps.backend, "available": caps.available}
            )
        return {"hardware": hw, "allocation": default_allocation(hw, self.settings), "runtimes": runtimes}

    # --- lifecycle ---------------------------------------------------------------------------------

    async def adopt_existing(self) -> None:
        """After a restart, keep workloads that are still healthy and restart ones whose runtime died."""
        for dep_id, rec in list(self.state.workloads.items()):
            try:
                spec = WorkloadSpec(**rec["spec"])
            except (KeyError, TypeError):
                self.state.drop_workload(dep_id)
                continue
            if spec.runtime not in self.runtimes:
                logger.warning("Dropping workload %s: runtime %s is no longer enabled", dep_id, spec.runtime)
                self.state.drop_workload(dep_id)
                continue
            handle = WorkloadHandle(**rec["handle"]) if rec.get("handle") else None
            if (
                handle is not None
                and await self._rt(spec).is_alive(handle)
                and await self._rt(spec).health(handle, spec)
            ):
                self.workloads[dep_id] = {"spec": spec, "handle": handle, "state": "running", "healthy": True}
                logger.info("Re-adopted running workload %s", dep_id)
                continue
            if handle is not None:
                with contextlib.suppress(Exception):
                    await self._rt(spec).remove(handle)
            # Restart: the model is cached, so this is quick. The control plane will tell us to stop it if
            # the deployment was stopped while we were away.
            self.workloads[dep_id] = {"spec": spec, "handle": None, "state": "provisioning", "healthy": False}
            self.deploy_tasks[dep_id] = asyncio.create_task(self._deploy(spec, restart=True))

    async def _deploy(self, spec: WorkloadSpec, restart: bool = False) -> None:
        dep_id = spec.deployment_id
        w = self.workloads[dep_id]

        async def progress(msg: str) -> None:
            with contextlib.suppress(ProtocolError):
                await self.client.report(dep_id, "PROVISIONING", msg)

        try:
            free_disk = psutil.disk_usage(self.settings.DATA_DIR).free // (1024 * 1024)
            if free_disk < spec.disk_mb:
                raise WorkloadError("INSUFFICIENT_DISK", f"Only {free_disk} MB free; {spec.disk_mb} MB needed")
            available_ram = psutil.virtual_memory().available // (1024 * 1024)
            if available_ram < spec.ram_mb:
                raise WorkloadError(
                    "INSUFFICIENT_MEMORY", f"Only {available_ram} MB RAM available; {spec.ram_mb} MB needed"
                )
            await self.client.report(
                dep_id, "PROVISIONING", "Restarting runtime" if restart else "Starting isolated runtime"
            )
            w["handle"] = await self._rt(spec).start(spec)
            self._persist(dep_id)
            await self._pull_with_retries(w["handle"], spec, progress)
            await self.client.report(dep_id, "STARTING", "Loading model and running a test generation")
            w["state"] = "starting"
            digest = await self._rt(spec).verify_ready(w["handle"], spec)
            w["state"], w["healthy"] = "running", True
            self._persist(dep_id)
            await self.client.report(dep_id, "READY", "Model verified with a test generation", model_digest=digest)
            logger.info("Workload %s ready (%s)", dep_id, spec.model_tag)
        except asyncio.CancelledError:
            raise  # whoever cancelled (stop_workload / shutdown) owns cleanup
        except (WorkloadError, ProtocolError) as exc:
            code = getattr(exc, "code", "PROVISIONING_FAILED")
            message = getattr(exc, "message", str(exc))
            logger.warning("Workload %s failed: %s %s", dep_id, code, message)
            if w.get("handle"):
                with contextlib.suppress(Exception):
                    await self._rt(w["spec"]).remove(w["handle"])
            self.workloads.pop(dep_id, None)
            self._persist(dep_id)
            with contextlib.suppress(ProtocolError, CredentialRevoked):
                await self.client.report(dep_id, "FAILED", message, error_code=code)
        except Exception:  # noqa: BLE001
            # A bug must not strand the deployment in PROVISIONING until the stall timeout: clean up and report.
            logger.exception("Workload %s failed unexpectedly", dep_id)
            if w.get("handle"):
                with contextlib.suppress(Exception):
                    await self._rt(w["spec"]).remove(w["handle"])
            self.workloads.pop(dep_id, None)
            self._persist(dep_id)
            with contextlib.suppress(ProtocolError, CredentialRevoked):
                await self.client.report(dep_id, "FAILED", "Unexpected worker error", error_code="WORKER_ERROR")
        finally:
            self.deploy_tasks.pop(dep_id, None)

    async def _pull_with_retries(self, handle: WorkloadHandle, spec: WorkloadSpec, progress) -> None:
        attempts = max(1, self.settings.PULL_ATTEMPTS)
        for attempt in range(1, attempts + 1):
            try:
                await self._rt(spec).prepare_model(handle, spec, progress)
                return
            except WorkloadError as exc:
                if not exc.transient or attempt == attempts:
                    raise
                delay = self.settings.PULL_RETRY_BASE_SECONDS * 2 ** (attempt - 1)
                logger.warning(
                    "Download of %s failed (%s); retry %d/%d in %.0fs",
                    spec.model_tag,
                    exc.message,
                    attempt + 1,
                    attempts,
                    delay,
                )
                await progress(f"Download interrupted ({exc.message[:80]}); retrying in {delay:.0f}s")
                await asyncio.sleep(delay)

    async def stop_workload(
        self, dep_id: str, report: bool = True, error_code: str | None = None, message: str | None = None
    ) -> None:
        task = self.deploy_tasks.pop(dep_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        w = self.workloads.pop(dep_id, None)
        if w and w.get("handle"):
            with contextlib.suppress(Exception):
                await self._rt(w["spec"]).remove(w["handle"])
        self._persist(dep_id)
        if report:
            with contextlib.suppress(ProtocolError):
                await self.client.report(
                    dep_id, "STOPPED", message or "Workload stopped and cleaned up", error_code=error_code
                )

    async def handle_command(self, cmd: dict) -> None:
        cmd_id, ctype = str(cmd.get("id")), cmd.get("type")
        logger.info("command=%s type=%s deployment=%s", cmd_id, ctype, cmd.get("deployment_id"))
        if self.state.seen(cmd_id):
            await self.client.ack(cmd_id, "accepted")  # redelivery of a command we already handled
            return
        if ctype == "DEPLOY":
            try:
                spec = parse_deploy_payload(cmd.get("payload") or {})
            except WorkloadError as exc:
                self.state.mark_processed(cmd_id)
                await self.client.ack(cmd_id, "failed", f"{exc.code}: {exc.message}")
                return
            if spec.runtime not in self.runtimes:
                self.state.mark_processed(cmd_id)
                await self.client.ack(cmd_id, "accepted")
                await self.client.report(
                    spec.deployment_id,
                    "FAILED",
                    f"Runtime '{spec.runtime}' is not available here",
                    error_code="RUNTIME_UNAVAILABLE",
                )
                return
            available, reason, _ = self.availability()
            if not available:
                # Raced with a local pause/drain or the end of the schedule: hand it back for placement elsewhere.
                self.state.mark_processed(cmd_id)
                await self.client.ack(cmd_id, "accepted")
                await self.client.report(
                    spec.deployment_id, "FAILED", f"Node unavailable ({reason})", error_code="NODE_UNAVAILABLE"
                )
                return
            if spec.deployment_id not in self.workloads:
                self.workloads[spec.deployment_id] = {
                    "spec": spec,
                    "handle": None,
                    "state": "provisioning",
                    "healthy": False,
                }
                self._persist(spec.deployment_id)
                self.deploy_tasks[spec.deployment_id] = asyncio.create_task(self._deploy(spec))
            self.state.mark_processed(cmd_id)
            await self.client.ack(cmd_id, "accepted")
        elif ctype == "RESTART":
            try:
                spec = parse_deploy_payload(cmd.get("payload") or {})
            except WorkloadError as exc:
                self.state.mark_processed(cmd_id)
                await self.client.ack(cmd_id, "failed", f"{exc.code}: {exc.message}")
                return
            # Tear down the current runtime without reporting STOPPED, then deploy again (model is cached).
            await self.stop_workload(spec.deployment_id, report=False)
            self.workloads[spec.deployment_id] = {
                "spec": spec,
                "handle": None,
                "state": "provisioning",
                "healthy": False,
            }
            self._persist(spec.deployment_id)
            self.deploy_tasks[spec.deployment_id] = asyncio.create_task(self._deploy(spec, restart=True))
            self.state.mark_processed(cmd_id)
            await self.client.ack(cmd_id, "accepted")
        elif ctype == "STOP":
            dep_id = str((cmd.get("payload") or {}).get("deployment_id") or cmd.get("deployment_id"))
            await self.stop_workload(dep_id)
            self.state.mark_processed(cmd_id)
            await self.client.ack(cmd_id, "succeeded")
        else:
            self.state.mark_processed(cmd_id)
            await self.client.ack(cmd_id, "failed", "Unsupported command type")

    # --- loops -------------------------------------------------------------------------------------

    async def heartbeat_once(self) -> dict:
        available, reason, drain = self.availability()
        if (available, reason) != self._last_availability:
            logger.info("Availability: %s", "available" if available else f"unavailable ({reason})")
            self._last_availability = (available, reason)
        if drain and self.workloads:
            await self.drain(reason or "draining")
        payload = {
            "worker_version": WORKER_VERSION,
            **(await self.capabilities_payload()),
            "metrics": {k: float(v) for k, v in self.metrics.get_summary().items()},
            "deployments": [
                {"deployment_id": dep_id, "state": w["state"], "healthy": bool(w["healthy"])}
                for dep_id, w in self.workloads.items()
            ],
            "available": available,
            "unavailable_reason": reason,
        }
        resp = await self.client.heartbeat(payload)
        self.state.record_heartbeat()
        await self._maybe_auto_update(resp.get("latest_worker_version"))
        for dep_id in resp.get("stop_deployments", []):
            logger.info("Control plane asked to stop workload %s", dep_id)
            await self.stop_workload(str(dep_id))
        return resp

    async def _maybe_auto_update(self, latest: str | None) -> None:
        """Apply a signed update only when idle, then exit so the service manager restarts the new version."""
        if not (self.settings.AUTO_UPDATE and latest and not self.workloads and not self.deploy_tasks):
            return
        from . import updater

        try:
            if updater.parse_version(latest) <= updater.parse_version(WORKER_VERSION):
                return
            message = await updater.Updater(self.settings, self.client).apply()
        except (updater.UpdateError, Exception) as exc:  # noqa: BLE001
            logger.warning("Automatic update to %s skipped: %s", latest, exc)
            return
        logger.info("%s Exiting for restart.", message)
        self.exit_code = 75  # EX_TEMPFAIL: systemd Restart=on-failure / launchd KeepAlive restarts us
        self.stop_event.set()

    async def _heartbeat_loop(self) -> None:
        attempt = 0
        while not self.stop_event.is_set():
            try:
                resp = await self.heartbeat_once()
                attempt = 0
                interval = resp.get("heartbeat_interval_seconds", self.settings.HEARTBEAT_INTERVAL_SECONDS)
            except ProtocolError as exc:
                logger.warning("Heartbeat failed: %s", exc)
                interval = backoff(attempt, cap=self.settings.HEARTBEAT_INTERVAL_SECONDS)
                attempt += 1
            await self._sleep(interval)

    async def _command_loop(self) -> None:
        attempt = 0
        while not self.stop_event.is_set():
            try:
                for cmd in await self.client.poll(wait_seconds=20):
                    await self.handle_command(cmd)
                attempt = 0
            except ProtocolError as exc:
                logger.warning("Command poll failed: %s", exc)
                await self._sleep(backoff(attempt, cap=30))
                attempt += 1

    async def _health_loop(self) -> None:
        while not self.stop_event.is_set():
            await self._sleep(self.settings.HEALTH_CHECK_INTERVAL_SECONDS)
            for w in list(self.workloads.values()):
                if w["state"] == "running" and w["handle"] is not None:
                    w["healthy"] = await self._rt(w["spec"]).health(w["handle"], w["spec"])

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)

    async def run(self) -> int:
        """Run until stopped. Returns a process exit code."""
        for rt in self.runtimes.values():
            caps = await rt.capabilities()
            logger.info(
                "Runtime %s %s (%s): %s; limits %s%s",
                caps.name,
                caps.version or "?",
                caps.backend,
                "available" if caps.available else "unavailable",
                "enforced" if caps.limits_enforced else "advisory",
                f" - {caps.detail}" if caps.detail and not caps.available else "",
            )
        await self.adopt_existing()
        loops = [
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._command_loop()),
            asyncio.create_task(self._health_loop()),
            asyncio.create_task(
                run_tunnel(self.client.tunnel_url(), self.client.headers, self.tunnel, self.stop_event)
            ),
        ]
        stopper = asyncio.create_task(self.stop_event.wait())
        done, _ = await asyncio.wait([*loops, stopper], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception() if not task.cancelled() else None
            if isinstance(exc, CredentialRevoked):
                self.revoked = True
                logger.error("Node credential was revoked. Stopping all workloads.")
            elif exc is not None:
                logger.error("Worker loop crashed: %r", exc)
        self.stop_event.set()
        for task in [*loops, stopper]:
            task.cancel()
        await asyncio.gather(*loops, stopper, return_exceptions=True)
        if self.revoked:
            for dep_id in list(self.workloads):
                await self.stop_workload(dep_id, report=False)
            self.state.delete_credentials()
            return 2
        await self.shutdown()
        return self.exit_code

    async def shutdown(self) -> None:
        """Graceful exit. Docker workloads keep serving and are re-adopted on restart. Process workloads are
        children of the worker and are stopped; they restart from the cached model when the worker returns."""
        for task in list(self.deploy_tasks.values()):
            task.cancel()
        with contextlib.suppress(ProtocolError, CredentialRevoked):
            await self.client.disconnect()
        for w in list(self.workloads.values()):
            rt = self.runtimes.get(w["spec"].runtime)
            if rt is not None and rt.backend == "process" and w.get("handle"):
                with contextlib.suppress(Exception):
                    await rt.remove(w["handle"])
        await self.client.close()


async def enroll(
    settings: WorkerSettings,
    token: str,
    runtime: WorkloadRuntime | None = None,
    client: ControlPlaneClient | None = None,
) -> dict:
    from .identity import get_or_create_identity, get_public_key_pem

    state = WorkerState(settings.data_path)
    if state.load_credentials():
        raise SystemExit("Already enrolled. Run 'python -m node_agent uninstall' first to re-enroll.")
    runtimes = {runtime.name: runtime} if runtime is not None else make_runtimes(settings)
    client = client or ControlPlaneClient(settings.CONTROL_PLANE_URL)
    all_caps = [await rt.capabilities() for rt in runtimes.values()]
    caps = all_caps[0]
    hw = hardware_report(settings.DATA_DIR)
    _, pub = get_or_create_identity(settings.data_path)
    payload = {
        "token": token,
        "name": (settings.NODE_NAME or "agentmesh-node")[:100],
        "mode": settings.MODE,
        "worker_version": WORKER_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "hardware": hw,
        "allocation": default_allocation(hw, settings),
        "runtimes": [
            {"name": c.name, "version": c.version, "backend": c.backend, "available": c.available} for c in all_caps
        ],
        "public_key": get_public_key_pem(pub),
    }
    try:
        result = await client.enroll(payload)
    finally:
        await client.close()
    state.save_credentials(str(result["node_id"]), result["node_credential"], settings.CONTROL_PLANE_URL)
    return {
        "node_id": result["node_id"],
        "allocation": payload["allocation"],
        "runtime": asdict(caps),
        "runtimes": [asdict(c) for c in all_caps],
    }
