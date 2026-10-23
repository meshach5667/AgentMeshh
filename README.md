# AgentMesh

AgentMesh lets developers deploy open-weight AI models on computers contributed by independent providers and
call them through an OpenAI-compatible API. Workloads run inside resource limits on the provider's machine; the
provider can see the data a workload handles
Billing is prepaid, with Paystack top-ups and provider payouts. These run in Paystack test mode and have not
yet been exercised against Paystack's live API.

## Documentation

The full documentation is in the dashboard at [agent-mesh-ten.vercel.app/docs](https://agent-mesh-ten.vercel.app/docs):

- [Getting started](https://agent-mesh-ten.vercel.app/docs/getting-started): roles, accounts, and what works today
- [Customer guide](https://agent-mesh-ten.vercel.app/docs/customers): deploy, call, and pay for models
- [Provider guide](https://agent-mesh-ten.vercel.app/docs/providers): install the worker and manage machines
- [API reference](https://agent-mesh-ten.vercel.app/docs/api): authentication, deployments, inference, errors
- [Operators & self-hosting](https://agent-mesh-ten.vercel.app/docs/operators) and [Security & limitations](https://agent-mesh-ten.vercel.app/docs/security)

The Markdown files in [docs/](docs/) hold the same material in more depth.

## Prerequisites

- Python 3.12+
- Node.js 20+
- Docker & Docker Compose
- PostgreSQL 16
- Redis 7

## Quick Start (Development)

1. Clone the repository
2. Copy environment variables:
   ```bash
   cp .env.example .env
   ```
3. Start infrastructure services:
   ```bash
   docker-compose up -d postgres redis
   ```
4. Setup Backend (Control Plane):
   ```bash
   cd server
   pip install -r requirements.txt
   alembic upgrade head
   uvicorn app.main:app --reload
   ```
5. Setup Frontend (Dashboard):
   ```bash
   cd client
   npm install
   npm run dev
   ```
6. Run a worker (in a new terminal). 
   ```bash
   cd server
   python -m node_agent enroll --token <token from POST /api/v1/nodes/enrollment-tokens>
   python -m node_agent run
   ```

For providers, `server/packaging/install.sh` installs the worker as a per-user background service (no root);

To call a deployed model,  For the customer, provider and
operator workflows (dashboard and API),
Running a network in production (configuration, Paystack, monitoring, backups, recovery):

Operators cannot self-register. Create the first operator account on the server:

```bash
cd server
python scripts/create_operator.py ops@example.com
```

### End-to-end check

```bash
cd server
DATABASE_URL=sqlite+aiosqlite:///./dev.db python scripts/init_dev_db.py
DATABASE_URL=sqlite+aiosqlite:///./dev.db uvicorn app.main:app --port 8000 &
python scripts/e2e_ollama.py --api http://127.0.0.1:8000 --model smollm2:135m
```

Failover across two local workers (start the API with `WORKER_HEARTBEAT_INTERVAL_SECONDS=3
HEARTBEAT_TIMEOUT_SECONDS=12 UNHEALTHY_GRACE_SECONDS=15` so it finishes quickly):

```bash
python scripts/e2e_failover.py --api http://127.0.0.1:8000 --model smollm2:135m
```

## Running tests

```bash
cd server
pytest                      # in-memory SQLite by default
TEST_DATABASE_URL=postgresql+asyncpg://agentmesh:agentmesh@localhost:5432/agentmesh_test pytest

cd client
npx tsc --noEmit && npx jest && npm run build
```

The browser end-to-end test (real control plane, real worker, real model, all three dashboards) is described in
[client/e2e/README.md](client/e2e/README.md).

## Project status

What works, what is missing, and the phased plan are tracked in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Deployment

- Live dashboard: [https://agent-mesh-ten.vercel.app](https://agent-mesh-ten.vercel.app).
- Live API: [https://agentmesh-riuz.onrender.com/api/v1](https://agentmesh-riuz.onrender.com/api/v1).
- Documentation: [https://agent-mesh-ten.vercel.app/docs](https://agent-mesh-ten.vercel.app/docs) (customer, provider, API, operator and security guides).
- Worker releases: [GitHub Releases](https://github.com/meshach5667/AgentMeshh/releases). Pushing a tag `worker-v<version>` that matches `WORKER_VERSION` runs `.github/workflows/worker-release.yml`, which publishes the wheel, `install.sh`, `uninstall.sh` and `SHA256SUMS`. Providers then install without cloning, from the dashboard's **Add a machine** page. No release has been published yet; see [docs/WORKER.md](docs/WORKER.md#publishing-a-release-maintainers).
- To deploy your own instance, use Vercel for `client/` and any container host for `Dockerfile.server`, or `docker-compose up -d` for the full stack. Set `NEXT_PUBLIC_API_URL` to that instance's API `/api/v1` URL.
  Set the variables in [.env.example](.env.example); a plain `postgresql://` `DATABASE_URL` is accepted.

Run `make help` for the development shortcuts.

## License

MIT License.
