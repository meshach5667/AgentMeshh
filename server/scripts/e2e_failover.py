"""Failover acceptance test with real workers: a node dies and its deployment moves to another node.

Needs a control plane started with short timeouts so the test finishes quickly, e.g.:

    HEARTBEAT_TIMEOUT_SECONDS=15 UNHEALTHY_GRACE_SECONDS=20 MONITOR_INTERVAL_SECONDS=3 \\
      uvicorn app.main:app --port 8000
    python scripts/e2e_failover.py --api http://127.0.0.1:8000 --model smollm2:135m

Both workers run on this machine in agent mode with separate data directories (and model caches).
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import psutil

SERVER_DIR = Path(__file__).resolve().parents[1]


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + detail if detail else ''}", flush=True)
    if not ok:
        raise SystemExit(f"Step failed: {name}")


def register(api: str, role: str) -> dict:
    email = f"failover-{role}-{uuid.uuid4().hex[:8]}@example.com"
    r = httpx.post(f"{api}/api/v1/auth/register", json={"email": email, "password": "e2e-password-123", "role": role})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def wait_for(fn, timeout: float, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    return None


class WorkerProc:
    def __init__(self, api: str, provider: dict, name: str, ollama_binary: str):
        self.dir = Path(tempfile.mkdtemp(prefix=f"agentmesh-failover-{name}-"))
        self.env = {
            **os.environ,
            "AGENTMESH_CONTROL_PLANE_URL": api,
            "AGENTMESH_DATA_DIR": str(self.dir),
            "AGENTMESH_MODE": "agent",
            "AGENTMESH_NODE_NAME": name,
            "AGENTMESH_MAX_CPU_CORES": "2",
            "AGENTMESH_MAX_RAM_MB": "3072",
            "AGENTMESH_MAX_DISK_MB": "4096",
            "AGENTMESH_HEARTBEAT_INTERVAL_SECONDS": "3",
        }
        if ollama_binary:
            self.env["AGENTMESH_OLLAMA_BINARY"] = ollama_binary
        token = httpx.post(f"{api}/api/v1/nodes/enrollment-tokens", json={"name": name}, headers=provider).json()[
            "token"
        ]
        subprocess.run(
            [sys.executable, "-m", "node_agent", "enroll", "--token", token],
            cwd=SERVER_DIR,
            env=self.env,
            check=True,
            capture_output=True,
        )
        self.node_id = json.loads((self.dir / "credentials.json").read_text())["node_id"]
        self.log = open(self.dir / "worker.log", "w")  # noqa: SIM115
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "node_agent", "run"],
            cwd=SERVER_DIR,
            env=self.env,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

    def runtime_pids(self) -> list[int]:
        data = json.loads((self.dir / "workloads.json").read_text()) if (self.dir / "workloads.json").exists() else {}
        return [w["handle"]["ref"]["pid"] for w in data.values() if w.get("handle")]

    def kill_hard(self) -> None:
        """Simulate the machine dying: worker and its runtimes vanish without a goodbye."""
        pids = self.runtime_pids()
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait()
        for pid in pids:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def stop(self) -> int | None:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                return self.proc.wait(30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return self.proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default="smollm2:135m")
    ap.add_argument("--ollama-binary", default="")
    ap.add_argument("--timeout", type=float, default=900)
    args = ap.parse_args()
    api = args.api.rstrip("/")
    binary = str(Path(args.ollama_binary).resolve()) if args.ollama_binary else ""

    provider, customer = register(api, "provider"), register(api, "customer")
    a = WorkerProc(api, provider, "node-a", binary)
    b = None
    try:
        check(
            "node A online",
            bool(
                wait_for(
                    lambda: httpx.get(f"{api}/api/v1/nodes/{a.node_id}", headers=provider).json()["status"] == "ONLINE",
                    30,
                )
            ),
        )
        model = next(m for m in httpx.get(f"{api}/api/v1/models").json() if m.get("model_tag") == args.model)
        dep = httpx.post(f"{api}/api/v1/deployments", json={"model_id": model["id"]}, headers=customer).json()
        check("deployment placed on node A", dep.get("node_id") == a.node_id, dep.get("status", str(dep)))

        def status():
            return httpx.get(f"{api}/api/v1/deployments/{dep['id']}", headers=customer).json()

        ready = wait_for(lambda: (lambda d: d if d["status"] == "READY" else None)(status()), args.timeout, 2)
        check("READY on node A", bool(ready))
        endpoint = ready["endpoint"]
        key = httpx.post(
            f"{api}/api/v1/api-keys", json={"name": "failover", "deployment_id": dep["id"]}, headers=customer
        ).json()["key"]
        auth = {"Authorization": f"Bearer {key}"}

        def ask() -> httpx.Response:
            return httpx.post(
                f"{endpoint}/api/generate",
                headers=auth,
                timeout=300,
                json={"prompt": "Say OK.", "stream": False, "options": {"num_predict": 8}},
            )

        first = ask()
        check("inference on node A", first.status_code == 200, repr(first.json().get("response", "")[:40]))

        # Second node joins only now, so the first placement was deterministic.
        b = WorkerProc(api, provider, "node-b", binary)
        check(
            "node B online",
            bool(
                wait_for(
                    lambda: httpx.get(f"{api}/api/v1/nodes/{b.node_id}", headers=provider).json()["status"] == "ONLINE",
                    30,
                )
            ),
        )

        t0 = time.monotonic()
        a.kill_hard()
        check("node A killed (worker and runtime)", a.proc.poll() is not None)
        down = ask()
        check(
            "gateway reports the outage cleanly",
            down.status_code in (503, 502),
            f"{down.status_code} {down.json().get('error', {}).get('code')}",
        )

        moved = wait_for(
            lambda: (lambda d: d if d["node_id"] == b.node_id and d["status"] == "READY" else None)(status()),
            args.timeout,
            2,
        )
        check(
            "deployment moved to node B and is READY again",
            bool(moved),
            f"{time.monotonic() - t0:.0f}s, placements={moved['schedule_attempts'] if moved else '?'}",
        )
        check("same deployment id and endpoint", moved["id"] == dep["id"] and moved["endpoint"] == endpoint)
        again = ask()
        check(
            "same API key works against node B", again.status_code == 200, repr(again.json().get("response", "")[:40])
        )
        events = httpx.get(f"{api}/api/v1/deployments/{dep['id']}/events", headers=customer).json()
        path = [e["to_status"] for e in events if e["to_status"]]
        check(
            "history shows the outage and the move",
            path[path.index("UNHEALTHY") :] == ["UNHEALTHY", "SCHEDULED", "PROVISIONING", "STARTING", "READY"],
            " -> ".join(path),
        )
        old = httpx.get(f"{api}/api/v1/nodes/{a.node_id}", headers=provider).json()
        check("node A offline with no capacity held", old["status"] == "OFFLINE" and old["reserved_ram_mb"] == 0)

        pid_before = b.runtime_pids()
        r = httpx.post(f"{api}/api/v1/deployments/{dep['id']}/restart", headers=customer)
        check("restart accepted", r.status_code == 200, r.text)
        restarted = wait_for(
            lambda: (lambda d: d if d["status"] == "READY" and d["restart_count"] == 1 else None)(status()), 300, 1
        )
        check(
            "READY after restart, new runtime process",
            bool(restarted) and b.runtime_pids() != pid_before,
            f"pid {pid_before} -> {b.runtime_pids()}",
        )
        check("inference after restart", ask().status_code == 200)

        httpx.delete(f"{api}/api/v1/deployments/{dep['id']}", headers=customer)
        released = wait_for(
            lambda: httpx.get(f"{api}/api/v1/nodes/{b.node_id}", headers=provider).json()["reserved_ram_mb"] == 0, 60
        )
        check("cleanup on node B after delete", bool(released) and not b.runtime_pids())
        leftovers = [p for p in pid_before + b.runtime_pids() if psutil.pid_exists(p)]
        check("no runtime processes left behind", not leftovers, str(leftovers))
    finally:
        a.stop()
        if b:
            check("node B shut down gracefully", b.stop() == 0)
    print("\nFailover test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
