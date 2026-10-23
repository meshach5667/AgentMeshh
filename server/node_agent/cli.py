"""AgentMesh worker CLI (installed as `agentmesh-worker`; also `python -m node_agent`).

    agentmesh-worker enroll --token am_enroll_...   one-time, token from the provider dashboard
    agentmesh-worker run                            serve (the installed service runs this)
    agentmesh-worker status                         enrollment, availability, workloads
    agentmesh-worker doctor [--deep]                check this machine's setup and suggest fixes
    agentmesh-worker pause | drain | resume         stop new work / also move running work away / undo
    agentmesh-worker hardware                       what is reported and offered
    agentmesh-worker update [--check]               install a signed worker update (see docs/WORKER.md)
    agentmesh-worker uninstall [--purge-models]     stop workloads and delete credentials

Configuration: ~/.config/agentmesh/worker.env (written by the installer) and AGENTMESH_* variables.
"""

import argparse
import asyncio
import json
import logging
import shutil
import signal
import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .config import WORKER_VERSION, config_file, load_settings
from .hardware.discovery import default_allocation, hardware_report


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _run(settings) -> int:
    from .worker import Worker

    worker = Worker(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop_event.set)
        except NotImplementedError:  # Windows
            pass
    return await worker.run()


async def _uninstall(settings) -> None:
    from .runtime.base import WorkloadHandle
    from .state import WorkerState
    from .worker import make_runtime

    state = WorkerState(settings.data_path)
    runtime = make_runtime(settings)
    for dep_id, rec in list(state.workloads.items()):
        if rec.get("handle"):
            try:
                await runtime.remove(WorkloadHandle(**rec["handle"]))
            except Exception as exc:  # noqa: BLE001
                print(f"Could not remove workload {dep_id}: {exc}")
        state.drop_workload(dep_id)
    state.delete_credentials()


def _status(settings) -> dict:
    from . import schedule as availability_schedule
    from .state import WorkerState

    state = WorkerState(settings.data_path)
    creds = state.load_credentials()
    age = state.seconds_since_heartbeat()
    windows = availability_schedule.parse(settings.AVAILABILITY_SCHEDULE)
    now = datetime.now()
    nxt = availability_schedule.next_change(windows, now)
    return {
        "worker_version": WORKER_VERSION,
        "enrolled": bool(creds),
        "node_id": creds["node_id"] if creds else None,
        "control_plane": creds["control_plane_url"] if creds else settings.CONTROL_PLANE_URL,
        "config_file": str(config_file()) if config_file().is_file() else None,
        "connected": age is not None and age < 4 * settings.HEARTBEAT_INTERVAL_SECONDS,
        "last_heartbeat_seconds_ago": round(age) if age is not None else None,
        "local_control": state.control(),
        "schedule": settings.AVAILABILITY_SCHEDULE or "always",
        "in_schedule": availability_schedule.is_available(windows, now),
        "schedule_changes_at": nxt.isoformat(timespec="minutes") if nxt else None,
        "workloads": {k: v.get("state") for k, v in state.workloads.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentmesh-worker", description="AgentMesh worker")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--version", action="version", version=f"agentmesh-worker {WORKER_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)
    enroll_p = sub.add_parser("enroll", help="Enroll this machine using a one-time token")
    enroll_p.add_argument("--token", required=True)
    sub.add_parser("run", help="Run the worker")
    sub.add_parser("start", help="Enroll with AGENTMESH_ENROLLMENT_TOKEN if not enrolled yet, then run (containers)")
    status_p = sub.add_parser("status", help="Show enrollment, availability, and workloads")
    status_p.add_argument("--check", action="store_true", help="Exit non-zero unless a heartbeat succeeded recently")
    doctor_p = sub.add_parser("doctor", help="Check this machine's setup")
    doctor_p.add_argument("--deep", action="store_true", help="Also start a throwaway Ollama instance")
    sub.add_parser("pause", help="Stop accepting new workloads (running ones continue)")
    sub.add_parser("drain", help="Stop accepting work and move running workloads to other nodes")
    sub.add_parser("resume", help="Accept workloads again")
    sub.add_parser("hardware", help="Show detected hardware and the resources that would be offered")
    update_p = sub.add_parser("update", help="Install a signed worker update announced by the control plane")
    update_p.add_argument("--check", action="store_true", help="Only report whether an update is available")
    uninstall_p = sub.add_parser("uninstall", help="Stop workloads and remove credentials")
    uninstall_p.add_argument("--purge-models", action="store_true", help="Also delete the downloaded model cache")
    uninstall_p.add_argument("--service", metavar="NAME", help="Also remove the background service with this name")
    uninstall_p.add_argument("--remove-config", action="store_true", help="Also delete the config file")
    service_p = sub.add_parser("service", help="Manage the background service (systemd user unit / launchd agent)")
    service_p.add_argument("action", choices=["install", "uninstall", "status"])
    service_p.add_argument("--name", default="agentmesh-worker")
    service_p.add_argument("--linger", action="store_true", help="Linux: keep running when you are logged out")
    args = parser.parse_args(argv)
    _setup_logging(args.log_level)

    try:
        settings = load_settings()
    except (ValidationError, ValueError) as exc:
        if args.command == "doctor":
            from . import doctor

            checks = asyncio.run(doctor.run(None, settings_error=str(exc).splitlines()[-1]))
            print(doctor.render(checks))
            return 1
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return 2

    if args.command in ("run", "start", "enroll") and sys.platform == "win32":
        print("Windows is not supported yet. Use the Docker worker or Linux/macOS.", file=sys.stderr)
        return 2

    if args.command == "hardware":
        hw = hardware_report(settings.DATA_DIR)
        print(json.dumps({"hardware": hw, "offered_to_agentmesh": default_allocation(hw, settings)}, indent=2))
        return 0
    if args.command == "doctor":
        from . import doctor

        checks = asyncio.run(doctor.run(settings, deep=args.deep))
        print(doctor.render(checks))
        return 1 if any(c.status == doctor.FAIL for c in checks) else 0
    if args.command == "status":
        info = _status(settings)
        if args.check:
            healthy = info["enrolled"] and info["connected"]
            print("healthy" if healthy else f"unhealthy (last heartbeat: {info['last_heartbeat_seconds_ago']}s ago)")
            return 0 if healthy else 1
        print(json.dumps(info, indent=2))
        return 0
    if args.command in ("pause", "drain", "resume"):
        from .state import WorkerState

        state = WorkerState(settings.data_path)
        state.set_control(paused=args.command != "resume", draining=args.command == "drain")
        message = {
            "pause": "Paused: no new workloads. Running workloads continue.",
            "drain": "Draining: running workloads will be stopped and moved to other nodes.",
            "resume": "Resumed: accepting workloads (within the availability schedule).",
        }[args.command]
        print(f"{message} Takes effect within {settings.HEARTBEAT_INTERVAL_SECONDS} s if the worker is running.")
        return 0
    if args.command == "enroll":
        from .worker import enroll

        result = asyncio.run(enroll(settings, args.token))
        print(f"Enrolled node {result['node_id']}")
        print("Resources offered to AgentMesh:", json.dumps(result["allocation"]))
        for rt in result["runtimes"]:
            state = "available" if rt["available"] else f"unavailable ({rt['detail'] or 'not installed'})"
            print(
                f"Runtime {rt['name']} ({rt['backend']}): {state}, "
                f"limits {'enforced' if rt['limits_enforced'] else 'advisory'}"
            )
        return 0
    if args.command == "start":
        import os

        from .state import WorkerState
        from .worker import enroll

        if not WorkerState(settings.data_path).load_credentials():
            token = os.environ.get("AGENTMESH_ENROLLMENT_TOKEN", "")
            if not token:
                print("Not enrolled and AGENTMESH_ENROLLMENT_TOKEN is not set.")
                print("Create an enrollment token in the provider dashboard.")
                return 1
            result = asyncio.run(enroll(settings, token))
            print(f"Enrolled node {result['node_id']}; offered {json.dumps(result['allocation'])}")
        return asyncio.run(_run(settings))
    if args.command == "run":
        return asyncio.run(_run(settings))
    if args.command == "update":
        from . import updater

        return asyncio.run(updater.run(settings, check_only=args.check))
    if args.command == "service":
        from . import service

        if args.action == "status":
            print(service.status(args.name))
            return 0
        if args.action == "uninstall":
            print(service.uninstall(args.name))
            return 0
        executable = shutil.which("agentmesh-worker") or str(Path(sys.executable).with_name("agentmesh-worker"))
        if not Path(executable).exists():
            print("agentmesh-worker executable not found; install the package first (see install.sh)", file=sys.stderr)
            return 2
        cfg = config_file()
        if not cfg.is_file():
            print(f"Config file {cfg} not found; the installer writes it", file=sys.stderr)
            return 2
        print(service.install(args.name, executable, str(cfg), str(settings.data_path / "logs"), linger=args.linger))
        return 0
    if args.command == "uninstall":
        if args.service:
            from . import service

            print(service.uninstall(args.service))  # stop the service first so it cannot restart workloads
        asyncio.run(_uninstall(settings))
        if args.purge_models:
            shutil.rmtree(settings.data_path / "models", ignore_errors=True)
        if args.remove_config:
            config_file().unlink(missing_ok=True)
        print("Worker credentials removed and managed workloads stopped. Revoke the node in the dashboard too.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
