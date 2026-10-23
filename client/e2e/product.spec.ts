import { expect, test, type Browser, type Page } from '@playwright/test';
import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { mkdtempSync, openSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const API = process.env.E2E_API || 'http://localhost:8000';
const SERVER_DIR = path.resolve(__dirname, '../../server');
const PYTHON = process.env.E2E_PYTHON || path.join(SERVER_DIR, 'venv/bin/python');
const MODEL = process.env.E2E_MODEL || 'SmolLM2 135M';
const OPERATOR = { email: process.env.E2E_OPERATOR_EMAIL ?? '', password: process.env.E2E_OPERATOR_PASSWORD ?? '' };
const PASSWORD = 'e2e-password-123';
const run = Date.now().toString(36);
// Base URL of tests/fixtures/fake_paystack_server.py; enables the billing and payment steps.
const FAKE_PAYSTACK = process.env.E2E_FAKE_PAYSTACK ?? '';

let worker: ChildProcess | undefined;
let workerLog = '';
let deploymentUrl = '';

test.describe.configure({ mode: 'serial' });

async function signUp(browser: Browser, role: 'customer' | 'provider'): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto(role === 'provider' ? '/register?role=provider' : '/register');
  await page.locator('input[type="email"]').fill(`e2e-${role}-${run}@example.com`);
  const pw = page.locator('input[type="password"]');
  await pw.nth(0).fill(PASSWORD);
  await pw.nth(1).fill(PASSWORD);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(new RegExp(`/${role}$`));
  return page;
}

async function signIn(browser: Browser, email: string, password: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto('/login');
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  return page;
}

const nav = (page: Page, label: string) => page.getByRole('complementary').getByRole('link', { name: label, exact: true }).click();

let provider: Page;
let customer: Page;
let ops: Page | undefined;

async function operator(browser: Browser): Promise<Page> {
  if (!ops) {
    ops = await signIn(browser, OPERATOR.email, OPERATOR.password);
    await expect(ops).toHaveURL(/\/operator$/);
  }
  return ops;
}

test.afterAll(async () => {
  if (worker && worker.exitCode === null) {
    worker.kill('SIGTERM');
    await new Promise((r) => worker!.once('exit', r));
  }
});

test('landing page shows live, not simulated, figures', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Live from this AgentMesh network')).toBeVisible();
  await expect(page.getByTestId('stat-Deployable models')).not.toHaveText('—');
  await expect(page.getByRole('heading', { name: 'What works today' })).toBeVisible();
  await expect(page.getByText(/99\.9%|TFLOP/)).toHaveCount(0);
});

test('operator publishes a price list', async ({ browser }) => {
  test.skip(!FAKE_PAYSTACK || !OPERATOR.email, 'billing steps need E2E_FAKE_PAYSTACK and operator credentials');
  const page = await operator(browser);
  await nav(page, 'Pricing');
  await expect(page.getByText('No prices yet')).toBeVisible();
  for (const [label, value] of [
    ['CPU core, per hour', '600'],
    ['Memory, per GB-hour', '300'],
    ['GPU memory, per GB-hour', '0'],
    ['Input tokens, per million', '2000'],
    ['Output tokens, per million', '4000'],
    ['Platform fee (0 to 0.5)', '0.1'],
  ]) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByLabel('Notes').fill('e2e prices');
  await page.getByRole('button', { name: 'Publish version' }).click();
  await expect(page.getByText('in force')).toBeVisible();
});

test('provider enrolls a real machine from the dashboard', async ({ browser }) => {
  provider = await signUp(browser, 'provider');
  await expect(provider.getByText('You have no nodes yet.')).toBeVisible();

  await nav(provider, 'Add a Machine');
  await provider.getByLabel('Name (optional)').fill(`e2e-node-${run}`);
  await provider.getByRole('button', { name: 'Create token' }).click();
  const token = (await provider.locator('code').filter({ hasText: /^am_enroll_/ }).first().textContent())!.trim();
  await expect(provider.locator('pre').first()).toContainText(`--token ${token}`);

  const dataDir = mkdtempSync(path.join(tmpdir(), 'agentmesh-e2e-ui-'));
  const env = {
    ...process.env,
    AGENTMESH_CONTROL_PLANE_URL: API,
    AGENTMESH_DATA_DIR: dataDir,
    AGENTMESH_MODE: 'agent',
    AGENTMESH_NODE_NAME: `e2e-node-${run}`,
    AGENTMESH_MAX_CPU_CORES: '2',
    AGENTMESH_MAX_RAM_MB: '3072',
    AGENTMESH_MAX_DISK_MB: '4096',
    AGENTMESH_HEARTBEAT_INTERVAL_SECONDS: '5',
  };
  const enroll = spawnSync(PYTHON, ['-m', 'node_agent', 'enroll', '--token', token], { cwd: SERVER_DIR, env, encoding: 'utf8' });
  expect(enroll.status, enroll.stderr).toBe(0);
  workerLog = path.join(dataDir, 'worker.log');
  const log = openSync(workerLog, 'a');
  worker = spawn(PYTHON, ['-m', 'node_agent', 'run'], { cwd: SERVER_DIR, env, stdio: ['ignore', log, log] });

  await nav(provider, 'My Nodes');
  const row = provider.getByTestId('node-row').filter({ hasText: `e2e-node-${run}` });
  await expect(row.getByText('Accepting work')).toBeVisible({ timeout: 60000 });
  await expect(row).toContainText('Ollama');
});

test('provider can pause and resume the node', async () => {
  await provider.getByRole('link', { name: `e2e-node-${run}` }).click();
  await provider.getByRole('button', { name: 'Pause new work' }).click();
  await expect(provider.getByText('Paused in AgentMesh.')).toBeVisible();
  await provider.getByRole('button', { name: 'Resume' }).click();
  await expect(provider.getByText('New deployments can be placed here when they fit.')).toBeVisible();
  await expect(provider.getByText(/Ollama/).first()).toBeVisible();
});

test('customer deploys a model and it becomes ready on the real node', async ({ browser }) => {
  customer = await signUp(browser, 'customer');
  if (FAKE_PAYSTACK) {
    // Prepaid: top up through the Paystack flow. Paystack's hosted page is stubbed; the payment is confirmed by a
    // signed webhook from the fake Paystack server, then verified when the customer returns.
    await nav(customer, 'Wallet');
    await expect(customer.getByText('Paystack test mode: no real money')).toBeVisible();
    await customer.route('https://checkout.paystack.com/**', (route) => route.fulfill({ body: '<h1>Paystack checkout (stub)</h1>', contentType: 'text/html' }));
    await customer.getByLabel(/^Amount/).fill('2000');
    await customer.getByRole('button', { name: 'Pay with Paystack' }).click();
    await customer.waitForURL(/checkout\.paystack\.com\/fake-am-top-/);
    const reference = customer.url().split('fake-')[1];
    const paid = await (await customer.request.post(`${FAKE_PAYSTACK}/_test/pay/${reference}`)).json();
    expect(paid.webhook_status).toBe(200);
    await customer.goto(`/customer/wallet?reference=${reference}&trxref=${reference}`);
    await expect(customer.getByTestId('stat-Balance')).toHaveText(/2,000\.00/);
    await expect(customer).toHaveURL(/\/customer\/wallet$/);
  }
  await nav(customer, 'Models');
  await customer.getByLabel('Search models').fill(MODEL);
  const card = customer.getByTestId('model-card').filter({ hasText: MODEL });
  await card.getByRole('link', { name: 'Configure and deploy' }).click();

  await customer.getByRole('radio', { name: /^Ollama/ }).check();
  if (FAKE_PAYSTACK) await expect(customer.getByTestId('hourly-ollama')).toContainText('per hour while');
  const deploy = customer.getByRole('button', { name: 'Deploy' });
  await expect(deploy).toBeDisabled();
  await customer.getByRole('checkbox', { name: /I understand the provider can see/ }).check();
  await deploy.click();

  await expect(customer).toHaveURL(/\/customer\/deployments\/[0-9a-f-]{36}$/);
  deploymentUrl = customer.url();
  await expect(customer.getByTestId('deployment-events')).toContainText('SCHEDULED');
  await expect(customer.locator('[data-status="READY"]').first()).toBeVisible({ timeout: 15 * 60 * 1000 });
  await expect(customer.getByText('Verified digest')).toBeVisible();
  // Ollama reports the manifest digest as bare hex; llama.cpp as sha256:<hex>.
  await expect(customer.getByText(/^(sha256:)?[0-9a-f]{64}$/)).toBeVisible();
});

test('customer gets a real answer from the playground', async () => {
  await customer.getByLabel('Prompt').fill('What is the capital of France? Answer in one word.');
  await customer.getByRole('button', { name: 'Send' }).click();
  const answer = customer.getByTestId('playground-answer');
  await expect(answer).toBeVisible({ timeout: 120000 });
  await expect(answer).toContainText('reported by the runtime');
  expect(((await answer.locator('p').first().textContent()) ?? '').trim().length).toBeGreaterThan(0);
  await expect(customer.getByText('/v1/chat/completions').first()).toBeVisible({ timeout: 30000 });
});

test('customer creates a scoped API key and calls the deployment with it', async ({ request }) => {
  const deploymentId = deploymentUrl.split('/').at(-1)!;
  await nav(customer, 'API Keys');
  await customer.getByLabel('Name').fill('e2e-app');
  await customer.getByLabel('Deployment').selectOption(deploymentId);
  await customer.getByRole('button', { name: 'Create key' }).click();
  await expect(customer.getByText('Copy this key now. It will not be shown again.')).toBeVisible();
  const key = (await customer.locator('code').filter({ hasText: /^am_sk_/ }).first().textContent())!.trim();

  const resp = await request.post(`${API}/api/v1/deployments/${deploymentId}/v1/chat/completions`, {
    headers: { Authorization: `Bearer ${key}` },
    data: { model: 'ignored', messages: [{ role: 'user', content: 'Say hi' }], max_tokens: 8 },
    timeout: 120000,
  });
  expect(resp.status()).toBe(200);
  expect((await resp.json()).choices.length).toBeGreaterThan(0);

  await customer.getByRole('button', { name: 'I have saved it' }).click();
  await customer.reload();
  const row = customer.getByTestId('api-key-row').filter({ hasText: 'e2e-app' });
  await expect(row).toContainText(`Deployment ${deploymentId.slice(0, 8)}`);
  await expect(row).not.toContainText('never');

  await nav(customer, 'Usage');
  await expect(customer.getByTestId('usage-chart')).toBeVisible();
  // One playground request and one API-key request.
  await expect(customer.getByTestId('stat-Requests')).toHaveText('2');
});

test('the running deployment is charged and the provider is paid out', async ({ browser }) => {
  test.skip(!FAKE_PAYSTACK || !OPERATOR.email, 'billing steps need E2E_FAKE_PAYSTACK and operator credentials');
  await customer.goto(deploymentUrl);
  // The billing job rates READY time every BILLING_INTERVAL_SECONDS (60 s in this run).
  await expect(customer.getByTestId('cost-so-far')).not.toHaveText(/^(—|NGN\s?0\.00)$/, { timeout: 4 * 60 * 1000 });
  await expect(customer.getByTestId('charge-row').first()).toBeVisible();

  await provider.goto('/provider/earnings');
  await expect(provider.getByTestId('stat-Earned in total')).not.toHaveText(/^NGN\s?0\.00$/);
  await provider.getByLabel('Bank').selectOption('001');
  await provider.getByLabel('Account number').fill('0123456789');
  await provider.getByRole('button', { name: 'Verify and save' }).click();
  await expect(provider.getByTestId('payout-account')).toContainText('••••6789');
  await provider.getByLabel('Payout amount').fill('1');
  await provider.getByRole('button', { name: 'Request payout' }).click();
  const row = provider.getByTestId('payout-row').first();
  await expect(row).toContainText('REQUESTED');
  const payoutRef = (await row.locator('td').nth(1).textContent())!.trim();

  const page = await operator(browser);
  await nav(page, 'Payouts');
  const pending = page.getByTestId('admin-payout-row').filter({ hasText: payoutRef });
  await pending.getByRole('button', { name: 'Approve' }).click();
  await pending.getByRole('button', { name: 'Send transfer' }).click();
  await page.getByLabel('Filter by status').selectOption('');
  await expect(page.getByTestId('admin-payout-row').filter({ hasText: payoutRef })).toContainText('PENDING');
  const done = await (await page.request.post(`${FAKE_PAYSTACK}/_test/transfer/${payoutRef}/success`)).json();
  expect(done.webhook_status).toBe(200);
  await provider.reload();
  await expect(provider.getByTestId('payout-row').filter({ hasText: payoutRef })).toContainText('SUCCEEDED');

  await nav(page, 'Reconciliation');
  await expect(page.getByText('Ledger consistent')).toBeVisible();
});

test('operator sees the whole network and the audit trail', async ({ browser }) => {
  test.skip(!OPERATOR.email, 'Set E2E_OPERATOR_EMAIL and E2E_OPERATOR_PASSWORD (see e2e/README.md)');
  const ops = await operator(browser);
  await nav(ops, 'Overview');
  await expect(ops.getByText('Network overview')).toBeVisible();
  await expect(ops.getByTestId('stat-Deployments ready')).toHaveText('1');
  await expect(ops.getByTestId('stat-Nodes online')).toHaveText('1 / 1');

  await nav(ops, 'All Deployments');
  await expect(ops.getByText(`e2e-customer-${run}@example.com`)).toBeVisible();
  await nav(ops, 'All Nodes');
  await expect(ops.getByText(`e2e-provider-${run}@example.com`)).toBeVisible();
  await nav(ops, 'Audit Log');
  await ops.getByLabel('Action').fill('node.paused');
  await expect(ops.locator('td', { hasText: 'node.paused' }).first()).toBeVisible();

  // A customer cannot open operator pages; the guard sends them home (and the API refuses anyway).
  await customer.goto('/operator');
  await expect(customer).toHaveURL(/\/customer$/);
});

test('customer deletes the deployment and the node releases its capacity', async () => {
  await customer.goto(deploymentUrl);
  await customer.getByRole('button', { name: 'Delete' }).click();
  await customer.getByRole('button', { name: 'Delete and revoke its keys' }).click();
  await expect(customer).toHaveURL(/\/customer\/deployments$/);

  await provider.goto('/provider/nodes');
  const row = provider.getByTestId('node-row').filter({ hasText: `e2e-node-${run}` });
  await expect(row).toContainText('0 MB / 3 GB', { timeout: 120000 });
  // The worker received the stop for this deployment (it removes the runtime before acknowledging).
  await expect(() => expect(readFileSync(workerLog, 'utf8')).toMatch(new RegExp(`type=STOP deployment=${deploymentUrl.split('/').at(-1)}`))).toPass({ timeout: 60000 });
});
