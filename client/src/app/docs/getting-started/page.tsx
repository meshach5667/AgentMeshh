import type { Metadata } from 'next';
import { A, C, Callout, DocPage, List, P, Section, StatusPill, Table } from '@/components/docs/DocsContent';
import { API_URL, DASHBOARD_URL, RELEASES_URL, REPO_URL } from '@/lib/config';

export const metadata: Metadata = { title: 'Getting started' };

export default function GettingStarted() {
  return (
    <DocPage href="/docs/getting-started">
      <Section id="what-it-is" title="What AgentMesh does">
        <P>
          AgentMesh lets you deploy open-weight AI models, such as Qwen2.5 or SmolLM2, onto computers contributed by
          independent providers, then call them through an OpenAI-compatible API. AgentMesh does the work in between:
        </P>
        <List
          items={[
            'Placement: it reserves CPU, memory, disk and GPU on a node that fits, and explains why when none does.',
            'Readiness: a deployment only becomes READY after a real test generation succeeds.',
            'Failover: when a node goes offline or fails, the deployment moves to another node with the same id, endpoint and keys.',
            'Keys and metering: scoped API keys, and per-request usage records that never store prompts or responses.',
            'Billing: prepaid wallets, charges for READY time and tokens, and payouts to providers.',
          ]}
        />
      </Section>

      <Section id="who-its-for" title="Who it is for">
        <Table
          head={['Role', 'What they do', 'Guide']}
          rows={[
            ['Customers', 'Deploy models and call them from their applications.', <A key="c" href="/docs/customers">Customer guide</A>],
            ['Providers', 'Run the worker on their machines and earn a share of what customers pay.', <A key="p" href="/docs/providers">Provider guide</A>],
            ['Developers', 'Integrate deployments with the API and OpenAI SDKs.', <A key="a" href="/docs/api">API reference</A>],
            ['Operators', 'Run the network: catalog, prices, payouts, monitoring. Or self-host a separate instance.', <A key="o" href="/docs/operators">Operator guide</A>],
          ]}
        />
      </Section>

      <Section id="accounts" title="Accounts and roles">
        <List
          ordered
          items={[
            <>
              Open <A href={`${DASHBOARD_URL}/register`}>the registration page</A> and choose <strong>Deploy models</strong> or{' '}
              <strong>Provide compute</strong>. Providers can go straight to{' '}
              <A href={`${DASHBOARD_URL}/register?role=provider`}>provider registration</A>.
            </>,
            'Use an email address and a password of at least 8 characters. You are signed in straight away and taken to your dashboard.',
            <>
              Sign in later at <A href={`${DASHBOARD_URL}/login`}>the login page</A>. Each account has one role; use separate accounts to
              be both a customer and a provider.
            </>,
          ]}
        />
        <P>
          <strong>Operators cannot self-register.</strong> Operator and admin accounts are created on the server with{' '}
          <C>scripts/create_operator.py</C> (see <A href="/docs/operators#first-operator">First operator</A>). Login and registration
          are rate limited per address and per email.
        </P>
      </Section>

      <Section id="status" title="What works today">
        <P>AgentMesh is early. This is the honest state of each area.</P>
        <Table
          head={['Area', 'Status', 'Notes']}
          rows={[
            ['Deploying approved models on Ollama or llama.cpp, OpenAI-compatible API with streaming', <StatusPill key="1" status="working" />, 'Verified end to end on real models.'],
            ['Automatic placement, readiness checks, moving deployments off failed nodes', <StatusPill key="2" status="working" />, ''],
            ['API keys, per-deployment scoping, per-request usage metering', <StatusPill key="3" status="working" />, 'Token counts come from the runtime on the provider’s machine and are not independently verified.'],
            ['Installable worker for Linux', <StatusPill key="4" status="working" />, 'Installer, service, pause/drain, signed updates and real inference verified on Linux.'],
            ['Installable worker on macOS', <StatusPill key="5" status="unverified" />, 'Service files are generated and unit-tested but not run on a Mac. Resource limits are advisory on macOS.'],
            ['Docker worker', <StatusPill key="6" status="unverified" />, 'Unit-tested with a fake Docker client; not yet run against a real Docker daemon.'],
            ['Prebuilt worker downloads (GitHub Releases)', <StatusPill key="7" status="planned" />, <>The release workflow exists; downloads work once the first <C>worker-v*</C> release is published on <A href={RELEASES_URL}>GitHub Releases</A>.</>],
            ['vLLM on GPU nodes', <StatusPill key="8" status="unverified" />, 'Built and unit-tested; not run on real GPU hardware.'],
            ['Prepaid billing, Paystack top-ups, provider payouts, reconciliation', <StatusPill key="9" status="test-mode" />, 'Paystack test mode only. Verified against a stand-in for Paystack’s API, not yet against Paystack itself.'],
            ['Live (real-money) payments', <StatusPill key="10" status="planned" />, <>Needs a live key, <C>PAYSTACK_ALLOW_LIVE=true</C>, and a review.</>],
            ['Confidential computing', <StatusPill key="11" status="planned" />, 'Not implemented. Providers can see the data their machines process.'],
          ]}
        />
        <Callout tone="warning" title="Trust model">
          Deployments run on computers owned by independent providers. A provider can inspect the model files, the process memory,
          and every prompt and response its node handles. Do not send confidential data to community nodes. See{' '}
          <A href="/docs/security">Security &amp; limitations</A>.
        </Callout>
      </Section>

      <Section id="links" title="Live links">
        <Table
          head={['What', 'URL']}
          rows={[
            ['Dashboard', <A key="d" href={DASHBOARD_URL}>{DASHBOARD_URL}</A>],
            ['Provider registration', <A key="r" href={`${DASHBOARD_URL}/register?role=provider`}>{`${DASHBOARD_URL}/register?role=provider`}</A>],
            ['API base URL', <C key="a">{API_URL}</C>],
            ['Interactive API reference (OpenAPI)', <A key="o" href={`${API_URL}/docs`}>{`${API_URL}/docs`}</A>],
            ['Worker releases', <A key="w" href={RELEASES_URL}>{RELEASES_URL}</A>],
            ['Source code', <A key="s" href={REPO_URL}>{REPO_URL}</A>],
          ]}
        />
      </Section>
    </DocPage>
  );
}
