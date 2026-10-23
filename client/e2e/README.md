# End-to-end product test

`product.spec.ts` drives the dashboards in a real browser against a real control plane, a real installable-agent
worker and a real model (SmolLM2 135M through an isolated Ollama instance started by the worker; your own Ollama
service is not used). It downloads the model (about 270 MB) into a temporary worker data directory.

```bash
# 1. Control plane on a throwaway SQLite database
cd server
export DATABASE_URL=sqlite+aiosqlite:////tmp/agentmesh-e2e.db
venv/bin/python scripts/init_dev_db.py
AGENTMESH_OPERATOR_PASSWORD=e2e-operator-password venv/bin/python scripts/create_operator.py ops@example.com
venv/bin/uvicorn app.main:app --port 8000

# 2. Dashboard (production build)
cd client && npm run build && npm run start

# 3. The test (uses installed Google Chrome; omit PLAYWRIGHT_CHANNEL to use Playwright's Chromium)
cd client
E2E_OPERATOR_EMAIL=ops@example.com E2E_OPERATOR_PASSWORD=e2e-operator-password \
  PLAYWRIGHT_CHANNEL=chrome npx playwright test
```

Billing and payments: also start `tests/fixtures/fake_paystack_server.py` and point the API at it. The
operator then publishes prices, the customer tops up (Paystack's hosted page is stubbed in the browser, and
the payment is confirmed by a signed webhook), the deployment is charged, and the provider is paid out after
operator approval:

```bash
cd server
FAKE_PAYSTACK_SECRET=sk_test_fake0000000000000000000000 \
  FAKE_PAYSTACK_WEBHOOK=http://127.0.0.1:8000/api/v1/payments/paystack/webhook \
  venv/bin/uvicorn tests.fixtures.fake_paystack_server:app --port 8090
# start the API with these as well:
PAYSTACK_SECRET_KEY=sk_test_fake0000000000000000000000 PAYSTACK_BASE_URL=http://127.0.0.1:8090 \
  BILLING_INTERVAL_SECONDS=60 MONITOR_INTERVAL_SECONDS=5 PAYOUT_MIN_AMOUNT=1 venv/bin/uvicorn app.main:app --port 8000
# and run the test with E2E_FAKE_PAYSTACK=http://127.0.0.1:8090
```

Optional: `E2E_API` (default `http://localhost:8000`), `E2E_PYTHON` (default `../server/venv/bin/python`),
`E2E_MODEL` (catalog name, default `SmolLM2 135M`).
