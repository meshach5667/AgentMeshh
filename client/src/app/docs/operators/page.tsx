import type { Metadata } from 'next';
import { A, C, Callout, Code, DocPage, List, P, Section, Table } from '@/components/docs/DocsContent';
import { API_URL, DASHBOARD_URL, REPO_URL } from '@/lib/config';

export const metadata: Metadata = { title: 'Operators & self-hosting' };

export default function OperatorGuide() {
  return (
    <DocPage href="/docs/operators">
      <Section id="hosted-vs-self" title="Hosted vs. your own instance">
        <Table
          head={['', 'Hosted AgentMesh', 'Your own instance']}
          rows={[
            ['Dashboard', <A key="d" href={DASHBOARD_URL}>{DASHBOARD_URL.replace('https://', '')}</A>, 'Wherever you deploy client/ (for example Vercel)'],
            ['API', <C key="a">{API_URL}</C>, <>Your host, e.g. <C>https://api.example.com/api/v1</C></>],
            ['Operators', 'Run by the AgentMesh maintainers', 'You'],
            ['Accounts, nodes, money', 'Shared hosted network', 'Completely separate; nothing is shared with the hosted network'],
          ]}
        />
        <P>
          The operator dashboard (<C>/operator</C>) works the same on both. The rest of this page is for people running their own instance from the{' '}
          <A href={REPO_URL}>source repository</A>.
        </P>
      </Section>

      <Section id="configuration" title="Configuration">
        <P>
          The API reads environment variables (or a <C>.env</C> file in the repository root). Anything other than{' '}
          <C>ENVIRONMENT=dev|development|test|testing</C> counts as production, and then the API refuses to start unless:
        </P>
        <List
          items={[
            <><C>SECRET_KEY</C> is random and at least 32 characters (<C>openssl rand -hex 32</C>);</>,
            <><C>CORS_ORIGINS</C> lists explicit origins (JSON array or comma-separated; no <C>*</C>);</>,
            <><C>PUBLIC_BASE_URL</C> uses <C>https://</C>;</>,
            <><C>PAYSTACK_SECRET_KEY</C>, if set, is a test key, unless <C>PAYSTACK_ALLOW_LIVE=true</C>.</>,
          ]}
        />
        <Table
          head={['Variable', 'Purpose']}
          rows={[
            [<C key="1">DATABASE_URL</C>, <>PostgreSQL. A plain <C>postgresql://</C> URL from your host is accepted and converted to the async driver; <C>sslmode=</C> becomes <C>ssl=</C>.</>],
            [<C key="2">SECRET_KEY</C>, 'Signs session tokens. Changing it signs everyone out.'],
            [<><C>PUBLIC_BASE_URL</C>, <C>FRONTEND_URL</C></>, 'Public https URLs of the API and the dashboard. Paystack returns customers to $FRONTEND_URL/customer/wallet.'],
            [<C key="4">CORS_ORIGINS</C>, 'Dashboard origins allowed to call the API.'],
            [<><C>COORDINATION_BACKEND=redis</C>, <C>REDIS_URL</C></>, 'Needed only for more than one API replica.'],
            [<C key="6">BILLING_CURRENCY</C>, 'One platform currency (default NGN). Choose it before taking payments.'],
            [<><C>PAYSTACK_SECRET_KEY</C>, <C>PAYSTACK_WEBHOOK_IPS</C></>, 'Payments; empty key disables them.'],
            [<C key="8">METRICS_TOKEN</C>, 'Bearer token for GET /metrics; empty disables it.'],
            [<C key="9">MIGRATE_ON_STARTUP</C>, 'Default true: the API applies database migrations when it starts (PostgreSQL only).'],
            [<C key="10">NEXT_PUBLIC_API_URL</C>, 'Dashboard build setting: your API’s /api/v1 URL. Baked in at build time.'],
          ]}
        />
        <P>
          <C>.env.example</C> lists the minimum set. Billing intervals, payment limits and rate limits have sensible defaults; see{' '}
          <C>server/app/core/config.py</C> and <C>docs/OPERATIONS.md</C> for every setting.
        </P>
      </Section>

      <Section id="deploy" title="Deploy">
        <P>Either run the whole stack with Docker Compose:</P>
        <Code
          code={`git clone ${REPO_URL}.git && cd AgentMeshh
export SECRET_KEY=$(openssl rand -hex 32)
export PUBLIC_BASE_URL=https://api.example.com FRONTEND_URL=https://app.example.com
docker compose up -d`}
        />
        <P>
          or deploy the parts separately: the API from <C>Dockerfile.server</C> (or <C>uvicorn app.main:app</C> in <C>server/</C>) on any host with
          PostgreSQL, and the dashboard from <C>client/</C> on Vercel with <C>NEXT_PUBLIC_API_URL</C> set. Put the API behind TLS, run uvicorn with{' '}
          <C>--proxy-headers</C>, and restrict <C>--forwarded-allow-ips</C> to your proxy. Change the default database credentials in{' '}
          <C>docker-compose.yml</C>.
        </P>
      </Section>

      <Section id="migrations" title="Database migrations">
        <P>
          With PostgreSQL, the API runs <C>alembic upgrade head</C> on startup, holding a database lock so several replicas cannot migrate at once.
          If a migration fails, the API does not start. To run them yourself instead, set <C>MIGRATE_ON_STARTUP=false</C> and run:
        </P>
        <Code code="cd server && alembic upgrade head" />
        <P>
          SQLite is for local development only: create it with <C>python scripts/init_dev_db.py</C>, since some migrations cannot run on SQLite.
        </P>
      </Section>

      <Section id="first-operator" title="First operator">
        <P>Operators cannot self-register. On a machine with the same <C>DATABASE_URL</C> as the API (for example your host&apos;s shell):</P>
        <Code
          code={`cd server
python scripts/create_operator.py ops@example.com              # prompts for a password (12+ characters)
python scripts/create_operator.py lead@example.com --role admin`}
        />
        <P>
          Running it for an existing account promotes that account. Each use is recorded in the audit log as <C>user.operator_provisioned</C>.
          Operator accounts have no multi-factor authentication yet; protect them carefully.
        </P>
      </Section>

      <Section id="catalog" title="Model catalog">
        <P>
          Under <strong>Model Catalog</strong>, approve models and enable or disable their artifacts (one per runtime). New catalog entries start
          unapproved. Adding an artifact, which needs a pinned source (an Ollama tag, or a Hugging Face commit and, for llama.cpp, a file SHA-256),
          is done with <C>POST /models/&#123;id&#125;/artifacts</C>; there is no dashboard form for it yet.
        </P>
      </Section>

      <Section id="pricing" title="Pricing">
        <P>
          Under <strong>Pricing</strong>, publish an immutable price version, effective now or later: CPU core-hour, memory GB-hour, GPU-memory
          GB-hour, input and output tokens per million, and the platform fee. Until a price list exists, usage is measured but not charged. You
          can set token prices to zero to charge for resources only.
        </P>
      </Section>

      <Section id="paystack" title="Payments (Paystack)">
        <Callout tone="warning" title="Test mode only">
          AgentMesh uses Paystack test mode unless a live key is explicitly allowed. It has been verified against a stand-in for Paystack&apos;s
          API but not against Paystack itself. Run the smoke script below before relying on it.
        </Callout>
        <List
          ordered
          items={[
            <>In the Paystack dashboard (test mode), copy the secret key into <C>PAYSTACK_SECRET_KEY</C> and set the webhook URL to <C>https://&lt;your-api&gt;/api/v1/payments/paystack/webhook</C>.</>,
            <>Check the integration against Paystack&apos;s real test API: <C>PAYSTACK_SECRET_KEY=sk_test_... python scripts/paystack_smoke.py</C> (add <C>--pay</C> to pay with a test card).</>,
            'Make a top-up from the dashboard and confirm that the webhook arrives: Reconciliation should show no open top-ups, and Ledger should show the deposit.',
            <>Payouts use Paystack Transfers: they need a funded balance and transfer OTP turned off, or they stop at <C>OTP_REQUIRED</C>.</>,
          ]}
        />
        <P>
          Top-ups are credited once, only after Paystack reports success with a matching amount and currency. Payouts are held at request time and
          need operator approval (<strong>Payouts</strong>). Reconciliation runs every 10 minutes when payments are enabled.
        </P>
      </Section>

      <Section id="monitoring" title="Monitoring">
        <Table
          head={['Endpoint', 'Use']}
          rows={[
            [<C key="1">GET /health</C>, 'Liveness.'],
            [<C key="2">GET /health/ready</C>, 'Database (and Redis) readiness; 503 if either fails. Use for load balancers.'],
            [<C key="3">GET /metrics</C>, <>Prometheus, with <C>Authorization: Bearer $METRICS_TOKEN</C>.</>],
            [<C key="4">GET /api/v1/admin/overview</C>, 'Operator dashboard figures, including nodes with overdue heartbeats.'],
            [<C key="5">GET /api/v1/admin/reconciliation</C>, 'Ledger invariants and open payment items.'],
          ]}
        />
        <P>
          Logs are JSON lines with a request id; API keys, node credentials, bearer tokens and Paystack keys are redacted. Alert on readiness
          failing, rising 5xx, payouts stuck <C>PENDING</C> or <C>OTP_REQUIRED</C>, reconciliation reporting <C>ok: false</C>, and{' '}
          <C>Background job … failed</C> in the logs.
        </P>
      </Section>

      <Section id="backups" title="Backups and recovery">
        <Code
          code={`cd server
DATABASE_URL=postgresql+asyncpg://… KEEP=14 ops/backup_db.sh /var/backups/agentmesh
DATABASE_URL=postgresql+asyncpg://…/agentmesh_restore ops/restore_db.sh /var/backups/agentmesh/agentmesh-<ts>.dump`}
        />
        <List
          items={[
            'Backups are compressed pg_dump files (mode 0600). Store copies off the host, encrypted, and test a restore monthly. The restore script refuses a non-empty database.',
            'After a restore: point DATABASE_URL at it, start the API (migrations run), then run reconciliation to re-check open top-ups and payouts with Paystack.',
            'API restarts lose nothing: workers reconnect and billing resumes from each deployment’s watermark without double charging.',
            'Never refund a pending payout by hand; the transfer may still complete. Ledger corrections and refunds need a code path that does not exist yet.',
            <>Full runbooks are in <A href={`${REPO_URL}/blob/main/docs/OPERATIONS.md`}>docs/OPERATIONS.md</A>.</>,
          ]}
        />
      </Section>

      <Section id="worker-releases" title="Publishing worker releases">
        <List
          ordered
          items={[
            <>Set <C>WORKER_VERSION</C> in <C>server/node_agent/config.py</C>, and <C>WORKER_VERSION</C> in <C>client/src/lib/config.ts</C> to match (a test checks this).</>,
            <>Commit, then tag and push: <C>git tag worker-v0.3.0 && git push origin worker-v0.3.0</C>.</>,
            <>The <C>Worker release</C> workflow checks the tag matches, builds the wheel, checks it installs, writes <C>SHA256SUMS</C>, and creates the GitHub release with the wheel, <C>install.sh</C>, <C>uninstall.sh</C> and <C>SHA256SUMS</C>.</>,
            'Redeploy the dashboard so Add a machine points at the new version.',
          ]}
        />
        <Callout tone="warning" title="The repository must be public">
          Providers download release assets anonymously, so the GitHub repository (or at least its releases) must be publicly readable.
        </Callout>
        <P>
          Signed self-updates are a separate, optional channel: sign a release manifest with <C>scripts/sign_worker_release.py</C> using an Ed25519 key
          kept offline, and point <C>WORKER_RELEASE_DIR</C> at the output. Never add that private key to GitHub Actions or the control plane.
        </P>
      </Section>
    </DocPage>
  );
}
