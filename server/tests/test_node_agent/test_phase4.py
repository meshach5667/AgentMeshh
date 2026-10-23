"""Phase 4: installable agent - schedules, local pause/drain, config, services, signed updates, packaging."""

import base64
import hashlib
import json
import plistlib
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_agent import schedule, service, updater
from node_agent.config import WORKER_VERSION, WorkerSettings, load_settings
from node_agent.protocol import ControlPlaneClient
from tests.test_node_agent.test_worker import DEP, FakeClient, FakeRuntime, _settle, deploy_cmd

# --- schedules ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "when,expected",
    [
        (datetime(2026, 10, 20, 12, 0), False),  # Tue noon
        (datetime(2026, 10, 20, 18, 0), True),  # Tue 18:00 start
        (datetime(2026, 10, 21, 7, 59), True),  # Wed early: Tuesday's overnight window
        (datetime(2026, 10, 21, 8, 0), False),
        (datetime(2026, 10, 24, 15, 0), True),  # Saturday
        (datetime(2026, 10, 27, 7, 0), True),  # Tue 07:00: inside Monday's overnight window
    ],
)
def test_schedule_windows(when, expected):
    windows = schedule.parse("mon-fri 18:00-08:00; weekends 00:00-24:00")
    assert schedule.is_available(windows, when) is expected


def test_schedule_wraps_week_and_reports_next_change():
    windows = schedule.parse("sun 22:00-02:00")
    assert schedule.is_available(windows, datetime(2026, 10, 26, 1, 0))  # Monday 01:00, from Sunday
    assert schedule.next_change(windows, datetime(2026, 10, 26, 1, 0)) == datetime(2026, 10, 26, 2, 0)
    assert schedule.next_change([], datetime(2026, 10, 26, 1, 0)) is None


@pytest.mark.parametrize("bad", ["mon 25:00-26:00", "someday 10:00-11:00", "mon 10:00-10:00", "mon-fri"])
def test_schedule_rejects_bad_specs(bad):
    with pytest.raises(schedule.ScheduleError):
        schedule.parse(bad)


def test_bad_schedule_fails_config_validation():
    with pytest.raises(ValueError):
        WorkerSettings(AVAILABILITY_SCHEDULE="whenever")


# --- local availability on the worker ------------------------------------------------------------------


@pytest.fixture
def worker(tmp_path):
    from node_agent.worker import Worker

    def _make(**settings):
        s = WorkerSettings(DATA_DIR=str(tmp_path), CONTROL_PLANE_URL="http://localhost:1", **settings)
        return Worker(s, runtime=FakeRuntime(), client=FakeClient())

    return _make


async def test_pause_reports_unavailable_but_keeps_workloads(worker):
    w = worker()
    await w.handle_command(deploy_cmd())
    await _settle(w)
    w.state.set_control(paused=True, draining=False)
    await w.heartbeat_once()
    assert w.client.last_heartbeat["available"] is False
    assert w.client.last_heartbeat["unavailable_reason"] == "paused"
    assert DEP in w.workloads  # running work continues


async def test_drain_stops_workloads_so_they_move(worker):
    w = worker()
    await w.handle_command(deploy_cmd())
    await _settle(w)
    w.state.set_control(paused=True, draining=True)
    await w.heartbeat_once()
    assert DEP not in w.workloads and w.runtime.removed == [DEP]
    assert w.client.reports[-1] == (DEP, "STOPPED", "NODE_UNAVAILABLE")


async def test_deploy_while_paused_is_handed_back(worker):
    w = worker()
    w.state.set_control(paused=True, draining=False)
    await w.handle_command(deploy_cmd())
    assert w.runtime.started == []
    assert w.client.reports[-1] == (DEP, "FAILED", "NODE_UNAVAILABLE")


async def test_outside_schedule_drain_mode(worker, monkeypatch):
    w = worker(AVAILABILITY_SCHEDULE="mon 00:00-00:01", OUTSIDE_SCHEDULE="drain")
    monkeypatch.setattr(schedule, "is_available", lambda windows, now: False)
    await w.handle_command(deploy_cmd())  # handed back because we are outside the schedule
    assert w.client.reports[-1] == (DEP, "FAILED", "NODE_UNAVAILABLE")
    available, reason, drain = w.availability()
    assert (available, reason, drain) == (False, "schedule", True)


def test_cli_pause_resume_round_trip(tmp_path, monkeypatch, capsys):
    from node_agent.cli import main

    monkeypatch.setenv("AGENTMESH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENTMESH_CONFIG_FILE", str(tmp_path / "none.env"))
    assert main(["drain"]) == 0
    assert json.loads((tmp_path / "control.json").read_text())["draining"] is True
    assert main(["resume"]) == 0
    assert json.loads((tmp_path / "control.json").read_text()) | {"updated": 0} == {
        "paused": False,
        "draining": False,
        "updated": 0,
    }
    capsys.readouterr()
    assert main(["status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["local_control"] == {"paused": False, "draining": False} and status["enrolled"] is False


# --- config file ---------------------------------------------------------------------------------------


def test_config_file_and_env_precedence(tmp_path, monkeypatch):
    cfg = tmp_path / "worker.env"
    cfg.write_text(
        'AGENTMESH_MAX_RAM_MB=1234\nAGENTMESH_AVAILABILITY_SCHEDULE="daily 22:00-06:00"\n'
        "AGENTMESH_NODE_NAME=from-file\n"
    )
    monkeypatch.setenv("AGENTMESH_CONFIG_FILE", str(cfg))
    monkeypatch.setenv("AGENTMESH_NODE_NAME", "from-env")
    s = load_settings()
    assert s.MAX_RAM_MB == 1234 and s.AVAILABILITY_SCHEDULE == "daily 22:00-06:00"
    assert s.NODE_NAME == "from-env"  # environment beats the file


# --- background service files --------------------------------------------------------------------------


def test_systemd_unit(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    files = service.render_systemd("agentmesh-worker", "/home/u/venv/bin/agentmesh-worker", "/home/u/w.env")
    text = files.content.decode()
    assert files.path == tmp_path / "systemd/user/agentmesh-worker.service"
    assert "ExecStart=/home/u/venv/bin/agentmesh-worker run" in text
    assert "Environment=AGENTMESH_CONFIG_FILE=/home/u/w.env" in text
    assert "Restart=on-failure" in text and "NoNewPrivileges=yes" in text
    directives = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert not any(ln.startswith(("User=", "Group=")) for ln in directives)  # runs as the installing user


def test_launchd_plist_is_valid():
    files = service.render_launchd("agentmesh-worker", "/Users/u/venv/bin/agentmesh-worker", "/Users/u/w.env", "/tmp")
    plist = plistlib.loads(files.content)
    assert plist["Label"] == "io.agentmesh.agentmesh-worker"
    assert plist["ProgramArguments"] == ["/Users/u/venv/bin/agentmesh-worker", "run"]
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert files.path.name == "io.agentmesh.agentmesh-worker.plist"


@pytest.mark.parametrize("name", ["../evil", "a b", "x" * 65, ""])
def test_service_name_validation(name):
    with pytest.raises(ValueError):
        service.render_systemd(service._check_name(name), "x", "y")


# --- signed updates ------------------------------------------------------------------------------------


def _release(
    version: str,
    wheel_bytes: bytes = b"wheel-bytes",
    key: Ed25519PrivateKey | None = None,
    tamper: bool = False,
    sha: str | None = None,
):
    key = key or Ed25519PrivateKey.generate()
    wheel = f"agentmesh_worker-{version}-py3-none-any.whl"
    manifest = json.dumps(
        {
            "version": version,
            "wheel": wheel,
            "sha256": sha or hashlib.sha256(wheel_bytes).hexdigest(),
            "size": len(wheel_bytes),
        },
        sort_keys=True,
    ).encode()
    sig = base64.b64encode(key.sign(manifest)).decode()
    if tamper:
        manifest = manifest.replace(b'"version"', b'"version" ', 1)
    pub = base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json={"manifest": manifest.decode(), "signature": sig})
        if request.url.path.endswith(f"/releases/files/{wheel}"):
            return httpx.Response(200, content=wheel_bytes)
        return httpx.Response(404)

    return pub, httpx.MockTransport(handler)


def _bump(delta: int) -> str:
    major, minor, patch = updater.parse_version(WORKER_VERSION)
    return f"{major}.{minor}.{max(0, patch + delta)}"


def _updater(tmp_path, pub, transport, installed_version=None, install_rc=0):
    s = WorkerSettings(DATA_DIR=str(tmp_path), UPDATE_PUBLIC_KEY=pub)
    client = ControlPlaneClient("http://localhost:1", "n", "c", transport=transport)
    calls = []

    async def install(*args):
        calls.append(args)
        return install_rc

    async def probe():
        return installed_version

    return updater.Updater(s, client, install=install, probe=probe), calls


async def test_update_verified_and_installed(tmp_path):
    new = _bump(1)
    pub, transport = _release(new)
    up, calls = _updater(tmp_path, pub, transport, installed_version=new)
    assert "Update available" in await up.apply(check_only=True)
    assert calls == []
    assert f"-> {new}" in await up.apply()
    assert (tmp_path / "releases" / f"agentmesh_worker-{new}-py3-none-any.whl").read_bytes() == b"wheel-bytes"


async def test_tampered_manifest_rejected(tmp_path):
    pub, transport = _release(_bump(1), tamper=True)
    up, calls = _updater(tmp_path, pub, transport)
    with pytest.raises(updater.UpdateError, match="signature"):
        await up.apply()
    assert calls == []


async def test_manifest_signed_by_other_key_rejected(tmp_path):
    pub, _ = _release(_bump(1))
    _, transport = _release(_bump(1))  # signed by a different key
    up, _ = _updater(tmp_path, pub, transport)
    with pytest.raises(updater.UpdateError, match="signature"):
        await up.apply()


async def test_wheel_hash_mismatch_rejected(tmp_path):
    pub, transport = _release(_bump(1), sha="0" * 64)
    up, calls = _updater(tmp_path, pub, transport)
    with pytest.raises(updater.UpdateError, match="sha256"):
        await up.apply()
    assert calls == []


async def test_downgrade_and_same_version_refused(tmp_path):
    for version in (WORKER_VERSION, _bump(-1) if WORKER_VERSION.split(".")[2] != "0" else "0.0.1"):
        pub, transport = _release(version)
        up, calls = _updater(tmp_path, pub, transport)
        assert "Up to date" in await up.apply()
        assert calls == []


async def test_rollback_when_new_version_does_not_start(tmp_path):
    new = _bump(1)
    pub, transport = _release(new)
    up, calls = _updater(tmp_path, pub, transport, installed_version=None)
    previous = tmp_path / "releases" / f"agentmesh_worker-{WORKER_VERSION}-py3-none-any.whl"
    previous.parent.mkdir(parents=True)
    previous.write_bytes(b"old")
    with pytest.raises(updater.UpdateError, match="rolled back"):
        await up.apply()
    assert calls[-1][-1] == str(previous)


async def test_updates_disabled_without_pinned_key(tmp_path):
    _, transport = _release(_bump(1))
    up, _ = _updater(tmp_path, "", transport)
    with pytest.raises(updater.UpdateError, match="disabled"):
        await up.apply()


# --- packaging -----------------------------------------------------------------------------------------


def test_wheel_build_is_reproducible_and_complete(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("bw", Path(__file__).parents[2] / "scripts/build_worker_wheel.py")
    bw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bw)
    a = bw.build(tmp_path / "a")
    b = bw.build(tmp_path / "b")
    assert a.read_bytes() == b.read_bytes()
    names = zipfile.ZipFile(a).namelist()
    assert "node_agent/cli.py" in names and "node_agent/runtime/ollama_process.py" in names
    entry = zipfile.ZipFile(a).read(f"agentmesh_worker-{WORKER_VERSION}.dist-info/entry_points.txt").decode()
    assert "agentmesh-worker = node_agent.cli:main" in entry
    assert not any("tests" in n or "app/" in n for n in names)  # control-plane code never ships to providers


async def test_doctor_reports_unreachable_control_plane(tmp_path):
    from node_agent import doctor

    s = WorkerSettings(DATA_DIR=str(tmp_path), CONTROL_PLANE_URL="http://127.0.0.1:9")
    checks = await doctor.run(s)
    cp = next(c for c in checks if c.name == "Control plane reachable")
    assert cp.status == doctor.FAIL and cp.fix
    assert "[FAIL] Control plane reachable" in doctor.render(checks)


async def test_version_probe_ignores_current_directory(tmp_path, monkeypatch):
    """Regression: `python -m node_agent` from a directory holding another node_agent must not be probed."""
    shadow = tmp_path / "node_agent"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("")
    (shadow / "__main__.py").write_text("print('agentmesh-worker 0.0.0-shadow')")
    monkeypatch.chdir(tmp_path)
    version = await updater._installed_version()
    assert version != "0.0.0-shadow"
