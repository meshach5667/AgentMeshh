import type { Metadata } from 'next';
import { TrustNotice } from '@/components/common/Notices';
import { A, C, Callout, DocPage, List, P, Section, StatusPill, Table } from '@/components/docs/DocsContent';
import { REPO_URL } from '@/lib/config';

export const metadata: Metadata = { title: 'Security & limitations' };

export default function SecurityGuide() {
  return (
    <DocPage href="/docs/security">
      <Section id="trust-model" title="Trust model">
        <TrustNotice />
        <P>
          AgentMesh runs models on computers owned by independent providers. Container and process isolation protect the{' '}
          <em>provider&apos;s</em> machine from the workload; they do not protect the workload from the provider. A provider can read the model files,
          the process memory, and every prompt and response their node handles. Confidential computing (hardware-isolated nodes with attestation) is
          not implemented.
        </P>
        <P>Use community nodes only for data you would be comfortable sharing with a stranger.</P>
      </Section>

      <Section id="data" title="What data is stored">
        <Table
          head={['Data', 'Stored?']}
          rows={[
            ['Prompts and responses', 'No. They are not stored or logged by AgentMesh (they do pass through the provider’s machine).'],
            ['Per-request usage', 'Yes: endpoint, status, duration, response bytes, token counts and a request id.'],
            ['API keys and node credentials', 'Only as hashes. API keys are shown once.'],
            ['Passwords', 'Only as password hashes.'],
            ['Bank accounts (providers)', 'Only the last four digits; Paystack holds the rest.'],
            ['Paystack webhook payloads', 'No. They contain customer contact and card details.'],
            ['Provider hardware', 'CPU model and cores, RAM, free disk, OS, architecture, GPU model and VRAM. Public statistics show counts only.'],
          ]}
        />
        <P>Logs redact API keys, node credentials, bearer tokens and Paystack keys.</P>
      </Section>

      <Section id="worker-safety" title="Worker safety for providers">
        <List
          items={[
            'The worker only accepts “deploy an approved model with these limits” and “stop” from the control plane, and validates both. It never runs customer commands.',
            'Model weights come only from allowed hosts (Ollama registry, Hugging Face), pinned to exact versions and checked by digest; every redirect is checked.',
            'Workloads use their own ports, model directories and processes; your own Ollama install is never used or modified.',
            'On Linux, each workload runs in a systemd user scope with hard memory and CPU limits. On macOS limits are advisory.',
            'Signed self-updates accept only releases signed with the operator’s offline key, so a compromised control plane cannot push code.',
            <>The Docker worker needs the Docker socket, which is <strong>root-equivalent</strong> on the host. Prefer rootless Docker on a dedicated machine.</>,
          ]}
        />
      </Section>

      <Section id="controls" title="Platform controls">
        <List
          items={[
            'Login and registration are rate limited per client address and per email.',
            'Production startup refuses insecure settings: weak SECRET_KEY, wildcard CORS, non-https public URL, or an unapproved live Paystack key.',
            'Security headers on the API and dashboard (nosniff, frame denial, referrer policy; HSTS on the API in production).',
            'Paystack webhooks are checked with an HMAC-SHA512 signature in constant time, processed once, and credited only on matching amount and currency.',
            'All balance changes go through ledger entries with idempotency keys; reconciliation checks balances against the ledger.',
            'The dashboard redirects to checkout only on Paystack’s own domain.',
            'Billable output tokens are capped by the response bytes the gateway counted itself.',
          ]}
        />
      </Section>

      <Section id="risks" title="Known risks">
        <P>These are recorded in the project&apos;s security review and are not fixed yet:</P>
        <List
          items={[
            'Token counts come from the provider’s machine. The byte cap bounds output-token inflation but does not prevent it; input tokens are not bounded.',
            'A provider could keep a broken runtime “READY”: customers see failed requests, but resource time is still charged. Refunds need a ledger correction feature that does not exist yet.',
            'Session tokens are kept in the browser’s localStorage and there is no Content-Security-Policy yet, so an XSS bug could steal a session.',
            'No multi-factor authentication for anyone, including operators who approve payouts.',
            'Per-email login throttling lets someone who knows your address delay your sign-in by up to a minute.',
            'Customer balances can go below zero by up to one billing interval before deployments stop.',
            'The audit log is not tamper-evident, and secrets live in environment variables rather than a secret manager.',
          ]}
        />
      </Section>

      <Section id="not-verified" title="Not yet verified">
        <Table
          head={['Feature', 'Status', 'Detail']}
          rows={[
            ['Paystack payments and payouts', <StatusPill key="1" status="test-mode" />, 'Built against Paystack’s documented API and tested against a stand-in; not yet run against Paystack itself.'],
            ['Live (real-money) payments', <StatusPill key="2" status="planned" />, 'Disabled unless PAYSTACK_ALLOW_LIVE=true is set after a review.'],
            ['vLLM on GPUs', <StatusPill key="3" status="unverified" />, 'Unit-tested; not run on real GPU hardware. Default image tags are unverified.'],
            ['Docker worker', <StatusPill key="4" status="unverified" />, 'Unit-tested with a fake Docker client; not run against a real Docker daemon. No GPU detection in the container.'],
            ['Installable worker on macOS', <StatusPill key="5" status="unverified" />, 'launchd service files are generated and unit-tested but not run on a Mac.'],
            ['Prebuilt worker releases', <StatusPill key="6" status="planned" />, 'The release workflow and install flow are built and the install was tested on Linux against locally served assets; no release is published yet.'],
            ['Multi-replica billing with Redis', <StatusPill key="7" status="unverified" />, 'Concurrency safety rests on database compare-and-set; tested on SQLite only.'],
            ['Confidential computing', <StatusPill key="8" status="planned" />, 'Not implemented.'],
          ]}
        />
      </Section>

      <Section id="reporting" title="Reporting a vulnerability">
        <Callout tone="warning" title="Please do not open public issues for security problems">
          Report privately through GitHub&apos;s <A href={`${REPO_URL}/security/advisories/new`}>private vulnerability reporting</A>, with a description,
          steps to reproduce, and the impact. See <A href={`${REPO_URL}/blob/main/SECURITY.md`}>SECURITY.md</A>.
        </Callout>
        <P>
          Providers: if you suspect your node&apos;s credential was exposed, revoke the node in the dashboard; the worker stops its workloads and deletes
          its credentials when it learns it was revoked. Customers: revoke exposed API keys under <C>API Keys</C>.
        </P>
      </Section>
    </DocPage>
  );
}
