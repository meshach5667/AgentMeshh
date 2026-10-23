"""End-to-end acceptance test: real worker, real Ollama, real inference through the AgentMesh gateway.

Requires a running control plane. The script creates a provider and a customer, enrolls and starts a worker
subprocess, deploys a model, runs streaming and non-streaming inference with an API key, checks metering and
tenant isolation, deletes the deployment, and verifies that capacity is released and the runtime is gone.

    # terminal 1
    DATABASE_URL=sqlite+aiosqlite:///./dev.db python scripts/init_dev_db.py
    DATABASE_URL=sqlite+aiosqlite:///./dev.db uvicorn app.main:app --port 8000
    # terminal 2
    python scripts/e2e_ollama.py --api http://127.0.0.1:8000 --mode agent --model smollm2:135m

Use --mode docker to exercise the Docker worker (needs a Docker daemon).
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

SERVER_DIR = Path(__file__).resolve().parents[1]


class _Done(Exception):  # noqa: N818
    pass


class Step:
    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + detail if detail else ''}", flush=True)
        if not ok:
            raise SystemExit(f"Step failed: {name}")


def register(api: str, role: str) -> dict:
    email = f"e2e-{role}-{uuid.uuid4().hex[:8]}@example.com"
    resp = httpx.post(
        f"{api}/api/v1/auth/register", json={"email": email, "password": "e2e-password-123", "role": role}
    )
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def wait_for(fn, timeout: float, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default="smollm2:135m")
    ap.add_argument("--mode", choices=["agent", "docker"], default="agent")
    ap.add_argument("--data-dir", default="")
    ap.add_argument("--ollama-binary", default="", help="Override the Ollama binary (agent mode)")
    ap.add_argument(
        "--runtime",
        choices=["ollama", "llamacpp", "vllm"],
        default=None,
        help="Deploy with this runtime (default: let AgentMesh choose)",
    )
    ap.add_argument("--llama-server", default="", help="llama-server binary for the llamacpp runtime")
    ap.add_argument(
        "--customer-api",
        default="",
        help="Send customer traffic to a different API replica than the worker (multi-replica check)",
    )
    ap.add_argument("--deploy-timeout", type=float, default=1200)
    ap.add_argument(
        "--expect-failure",
        default="",
        metavar="ERROR_CODE",
        help="Verify the failure path instead: the deployment must fail with this code and clean up",
    )
    args = ap.parse_args()
    api = args.api.rstrip("/")
    cust = (args.customer_api or args.api).rstrip("/")
    s = Step()

    data_dir = args.data_dir or tempfile.mkdtemp(prefix="agentmesh-e2e-worker-")
    env = {
        **os.environ,
        "AGENTMESH_CONTROL_PLANE_URL": api,
        "AGENTMESH_DATA_DIR": data_dir,
        "AGENTMESH_MODE": args.mode,
        "AGENTMESH_NODE_NAME": "e2e-node",
        "AGENTMESH_MAX_CPU_CORES": "2",
        "AGENTMESH_MAX_RAM_MB": "3072",
        "AGENTMESH_MAX_DISK_MB": "4096",
        "AGENTMESH_HEARTBEAT_INTERVAL_SECONDS": "5",
    }
    if args.llama_server:
        env["AGENTMESH_LLAMA_SERVER_BINARY"] = str(Path(args.llama_server).resolve())
    if args.ollama_binary:
        env["AGENTMESH_OLLAMA_BINARY"] = str(Path(args.ollama_binary).resolve())

    provider = register(api, "provider")
    customer = register(cust, "customer")
    s.check("provider and customer registered", True)

    token = httpx.post(f"{api}/api/v1/nodes/enrollment-tokens", json={"name": "e2e-node"}, headers=provider).json()[
        "token"
    ]
    enroll = subprocess.run(
        [sys.executable, "-m", "node_agent", "enroll", "--token", token],
        cwd=SERVER_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    s.check(
        "worker enrolled with one-time token",
        enroll.returncode == 0,
        enroll.stdout.strip().splitlines()[0] if enroll.returncode == 0 else enroll.stderr[-500:],
    )
    reuse = httpx.post(
        f"{api}/api/v1/worker/enroll",
        json={
            "token": token,
            "name": "x",
            "mode": "agent",
            "worker_version": "x",
            "protocol_version": 1,
            "hardware": {"os": "x", "arch": "x", "cpu_cores": 1, "ram_mb": 1, "disk_free_mb": 1},
            "allocation": {"cpu_cores": 1, "ram_mb": 1, "disk_mb": 1},
            "runtimes": [],
        },
    )
    s.check("enrollment token cannot be reused", reuse.status_code == 401)
    creds = json.loads((Path(data_dir) / "credentials.json").read_text())
    s.check(
        "credential stored with 0600 permissions",
        oct((Path(data_dir) / "credentials.json").stat().st_mode & 0o777) == "0o600",
    )

    log = open(Path(data_dir) / "worker.log", "w")  # noqa: SIM115
    worker = subprocess.Popen(
        [sys.executable, "-m", "node_agent", "run"], cwd=SERVER_DIR, env=env, stdout=log, stderr=subprocess.STDOUT
    )
    try:
        node = wait_for(
            lambda: next(
                (
                    n
                    for n in httpx.get(f"{api}/api/v1/nodes", headers=provider).json()
                    if n["id"] == creds["node_id"]
                    and n["status"] == "ONLINE"
                    and n["runtimes"]
                    and n["runtimes"][0]["available"]
                ),
                None,
            ),
            30,
        )
        s.check(
            "node online with capabilities",
            bool(node),
            f"alloc cpu={node['allocated_cpu_cores']} ram={node['allocated_ram_mb']}MB runtime="
            f"{node['runtimes'][0]['backend']} {node['runtimes'][0]['version']}"
            if node
            else "",
        )

        models = httpx.get(f"{cust}/api/v1/models").json()
        model = next((m for m in models if m.get("model_tag") == args.model), None)
        s.check(f"catalog offers {args.model}", model is not None)

        resp = httpx.post(
            f"{cust}/api/v1/deployments",
            json={"model_id": model["id"], "idempotency_key": uuid.uuid4().hex, "runtime": args.runtime},
            headers=customer,
        )
        s.check("deployment scheduled with reserved capacity", resp.status_code == 201, resp.text[:200])
        dep = resp.json()
        runtime = dep["runtime"]
        s.check("deployed with the expected runtime", args.runtime in (None, runtime), runtime)
        reserved = httpx.get(f"{api}/api/v1/nodes/{creds['node_id']}", headers=provider).json()
        s.check(
            "node capacity reserved",
            reserved["reserved_ram_mb"] == next(a["min_ram_mb"] for a in model["artifacts"] if a["runtime"] == runtime),
            f"reserved_ram_mb={reserved['reserved_ram_mb']}",
        )

        t0 = time.monotonic()

        def ready():
            d = httpx.get(f"{cust}/api/v1/deployments/{dep['id']}", headers=customer).json()
            if d["status"] == "FAILED":
                if args.expect_failure:
                    return d
                raise SystemExit(f"Deployment failed: {d['error_code']} {d['error_message']}")
            return d if d["status"] == "READY" else None

        if args.expect_failure:
            dep = wait_for(ready, args.deploy_timeout, 2)
            s.check(
                f"deployment failed with {args.expect_failure}",
                bool(dep) and dep["status"] == "FAILED" and dep["error_code"] == args.expect_failure,
                f"{dep['error_code']}: {(dep['error_message'] or '')[:120]}" if dep else "timed out",
            )
            events = httpx.get(f"{cust}/api/v1/deployments/{dep['id']}/events", headers=customer).json()
            path = [e["to_status"] for e in events if e["to_status"]]
            s.check("never reported READY", "READY" not in path, " -> ".join(path))
            n = wait_for(
                lambda: (lambda n: n if n["reserved_ram_mb"] == 0 else None)(
                    httpx.get(f"{api}/api/v1/nodes/{creds['node_id']}", headers=provider).json()
                ),
                30,
            )
            s.check("capacity released after failure", bool(n))
            s.check(
                "gateway refuses failed deployment",
                httpx.post(
                    f"{cust}/api/v1/deployments/{dep['id']}/ollama/api/chat", json={}, headers=customer
                ).status_code
                == 409,
            )
            workloads = json.loads((Path(data_dir) / "workloads.json").read_text())
            s.check("worker removed the failed runtime", dep["id"] not in workloads)
            return_code = 0
            raise _Done(return_code)

        dep = wait_for(ready, args.deploy_timeout, 2)
        events = httpx.get(
            f"{cust}/api/v1/deployments/{dep['id'] if dep else resp.json()['id']}/events", headers=customer
        ).json()
        s.check(
            "deployment READY after verified test generation",
            bool(dep),
            f"{time.monotonic() - t0:.0f}s, digest={dep['model_digest'] if dep else None}",
        )
        path = [e["to_status"] for e in events if e["to_status"]]
        s.check(
            "lifecycle followed the state machine",
            path == ["REQUESTED", "SCHEDULED", "PROVISIONING", "STARTING", "READY"],
            " -> ".join(path),
        )

        key = httpx.post(
            f"{cust}/api/v1/api-keys", json={"name": "e2e", "deployment_id": dep["id"]}, headers=customer
        ).json()
        auth = {"Authorization": f"Bearer {key['key']}"}
        endpoint = dep["endpoint"]
        oai = dep["openai_base_url"]
        probe_url = f"{endpoint}/api/chat" if runtime == "ollama" else f"{oai}/chat/completions"

        chunks, first, text, done = 0, None, "", False
        t1 = time.monotonic()
        if runtime == "ollama":
            stream_url = f"{endpoint}/api/chat"
            stream_body = {
                "model": "ignored",
                "messages": [{"role": "user", "content": "Name three primary colors."}],
                "options": {"num_predict": 40},
            }
        else:
            stream_url = f"{oai}/chat/completions"
            stream_body = {
                "model": "ignored",
                "messages": [{"role": "user", "content": "Name three primary colors."}],
                "max_tokens": 40,
                "stream": True,
            }
        with httpx.stream("POST", stream_url, headers=auth, timeout=300, json=stream_body) as r:
            status = r.status_code
            for line in r.iter_lines():
                if not line:
                    continue
                if runtime == "ollama":
                    obj = json.loads(line)
                    text += obj.get("message", {}).get("content", "")
                    done = done or bool(obj.get("done"))
                else:
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        done = True
                        continue
                    obj = json.loads(data)
                    for choice in obj.get("choices") or []:
                        text += (choice.get("delta") or {}).get("content") or ""
                chunks += 1
                first = first or time.monotonic() - t1
        s.check(
            "streaming chat through gateway",
            status == 200 and chunks > 2 and done and bool(text.strip()),
            f"{chunks} chunks, first chunk {(first or 0):.2f}s, reply={text.strip()[:60]!r}",
        )
        if runtime != "ollama":
            ollama_route = oai.rsplit("/", 1)[0] + "/ollama/api/chat"
            s.check(
                "Ollama-native route refused for this runtime",
                httpx.post(ollama_route, json={}, headers=auth).status_code == 404,
            )

        oa = httpx.post(
            f"{oai}/chat/completions",
            headers=auth,
            timeout=300,
            json={"model": "x", "messages": [{"role": "user", "content": "Say hi."}], "max_tokens": 16},
        )
        content = oa.json()["choices"][0]["message"]["content"] if oa.status_code == 200 else ""
        s.check(
            "OpenAI-compatible completion through gateway", oa.status_code == 200 and bool(content), repr(content[:60])
        )

        s.check("request without credentials rejected", httpx.post(probe_url, json={}).status_code == 401)
        other = register(cust, "customer")
        s.check(
            "other customer cannot reach deployment",
            httpx.post(probe_url, json={}, headers=other).status_code == 404,
        )

        usage = httpx.get(f"{cust}/api/v1/usage/{dep['id']}", headers=customer).json()
        ok_rows = [u for u in usage if u["kind"] == "inference" and u["outcome"] == "success"]
        s.check(
            "usage recorded per request",
            len(ok_rows) == 2,
            "; ".join(
                f"{u['endpoint']} in={u['input_tokens']} out={u['output_tokens']} "
                f"{u['duration_ms']}ms ({u['token_source']})"
                for u in ok_rows
            ),
        )

        handle = json.loads((Path(data_dir) / "workloads.json").read_text())[dep["id"]]["handle"]
        deleted = httpx.delete(f"{cust}/api/v1/deployments/{dep['id']}", headers=customer)
        s.check("delete accepted", deleted.status_code == 200, deleted.text)

        def released():
            n = httpx.get(f"{api}/api/v1/nodes/{creds['node_id']}", headers=provider).json()
            return n if n["reserved_ram_mb"] == 0 and n["reserved_cpu_cores"] == 0 else None

        n = wait_for(released, 60)
        s.check("capacity released after worker confirmed cleanup", bool(n))
        s.check(
            "deployment hidden after delete",
            httpx.get(f"{cust}/api/v1/deployments/{dep['id']}", headers=customer).status_code == 404,
        )
        s.check(
            "API key scoped to deleted deployment no longer works",
            httpx.post(probe_url, json={}, headers=auth).status_code == 401,
        )
        workloads = json.loads((Path(data_dir) / "workloads.json").read_text())
        gone = dep["id"] not in workloads
        if args.mode == "agent":
            port = handle["ref"]["port"]
            try:
                httpx.get(f"http://127.0.0.1:{port}/api/version", timeout=2)
                gone = False
            except httpx.HTTPError:
                pass
        s.check("runtime instance removed on the node", gone)
    except _Done:
        pass
    finally:
        worker.send_signal(signal.SIGTERM)
        try:
            code = worker.wait(30)
        except subprocess.TimeoutExpired:
            worker.kill()
            code = None
        log.close()
    s.check("worker shut down gracefully", code == 0, f"exit code {code}; log: {Path(data_dir) / 'worker.log'}")
    print(f"\nAll {len(s.results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
