import type { Metadata } from 'next';
import { TrustNotice } from '@/components/common/Notices';
import { A, C, Callout, Code, DocPage, List, P, Section, Table } from '@/components/docs/DocsContent';
import { API_URL } from '@/lib/config';

export const metadata: Metadata = { title: 'Customer guide' };

export default function CustomerGuide() {
  return (
    <DocPage href="/docs/customers">
      <Callout tone="info">
        Everything here is done in the <A href="/customer">customer dashboard</A>. The same actions are available
        through the API; see the <A href="/docs/api">API reference</A>.
      </Callout>

      <Section id="models" title="Browse models">
        <P>
          Under <strong>Models</strong>, each card shows the runtimes that can serve the model (green means a node offering that runtime is
          online now), the smallest memory reservation, and when a deployment of it last passed its readiness test. Only models an
          operator has approved are listed. Being in the catalog does not guarantee a node with enough free capacity is online.
        </P>
        <Table
          head={['Runtime', 'Serves', 'Hardware', 'Notes']}
          rows={[
            [<C key="o">ollama</C>, 'Ollama registry tags', 'CPU or GPU', 'Widest node availability. Also exposes Ollama’s own API.'],
            [<C key="l">llamacpp</C>, 'One GGUF file from Hugging Face, pinned to a commit and checked by SHA-256', 'CPU', 'Smaller reservations for the same model.'],
            [<C key="v">vllm</C>, 'A full Hugging Face repository at a pinned commit', 'GPU required', 'Not yet verified on real GPU hardware.'],
          ]}
        />
        <P>Gated or private Hugging Face models are not supported: AgentMesh never sends access tokens to provider machines.</P>
      </Section>

      <Section id="huggingface" title="Import a model from Hugging Face">
        <P>
          Under <strong>Models</strong>, <strong>Your models from Hugging Face</strong> imports a public GGUF file for your own use. Enter a
          repository (<C>owner/name</C>) or a huggingface.co link, press <strong>Look up</strong>, choose a file, confirm you may use it under
          its license, and import. It then deploys like any other model.
        </P>
        <List
          items={[
            'Private to you: other customers cannot see or deploy it, and the AI deployment assistant does not use it.',
            'Pinned: AgentMesh records the commit you looked up and the file’s SHA-256 from Hugging Face. Providers verify the hash before loading, so later changes to the repository never reach your deployment. Import again to pick up a newer commit.',
            'Served by llama.cpp only, on nodes whose providers accept community models. Fewer nodes may have room for it.',
            'Memory and disk reservations are estimated from the file size.',
          ]}
        />
        <Table
          head={['Refused', 'Why']}
          rows={[
            ['Gated, private or disabled repositories', 'AgentMesh never sends Hugging Face tokens to provider machines.'],
            ['No declared license, or a non-commercial one (e.g. cc-by-nc-4.0)', 'Hosting on AgentMesh is paid, so it is commercial use.'],
            ['Formats other than single-file GGUF (safetensors repos, .bin/.pt pickles, split GGUFs, mmproj files)', 'Only a single GGUF file can be hash-pinned, and pickles can run code when loaded.'],
            ['Files over the size limit (16 GB by default)', 'Keeps downloads on provider machines reasonable.'],
          ]}
        />
        <P>
          You are responsible for using the model within its license. Operators can disable an imported model, or approve it into the public
          catalog. To remove one, stop its deployments, then press <strong>Remove</strong>.
        </P>
      </Section>

      <Section id="deploy" title="Deploy a model">
        <List
          ordered
          items={[
            'Open a model and choose a runtime, or Automatic (tries Ollama, then llama.cpp, then vLLM, and uses the first that fits on a node).',
            'Set the context window (512 to 8192 tokens) and, optionally, a region or a GPU requirement. The form shows what the scheduler will reserve and the hourly price.',
            'Read and confirm the trust notice, then press Deploy.',
          ]}
        />
        <P>
          If no node can take it, the form explains why for each runtime, for example &ldquo;runtime not installed on the node&rdquo; or
          &ldquo;not enough free CPU, memory, disk or GPU memory&rdquo;. Deploying needs enough wallet balance for one hour of the reservation
          (see <A href="#billing">billing</A>).
        </P>
      </Section>

      <Section id="lifecycle" title="Monitor a deployment">
        <P>The deployment page updates every 2 seconds while it starts, and shows each event, the verified model digest, and any error.</P>
        <Table
          head={['Status', 'Meaning']}
          rows={[
            [<C key="1">SCHEDULED</C>, 'Capacity reserved on a node.'],
            [<C key="2">PROVISIONING</C>, 'Runtime starting and model downloading.'],
            [<C key="3">STARTING</C>, 'Model loading; a test generation is run.'],
            [<C key="4">READY</C>, 'The test generation succeeded. The endpoint is live.'],
            [<C key="5">UNHEALTHY</C>, 'The node stopped reporting or the health check fails; requests get 503. If it does not recover within 3 minutes, the deployment moves to another node.'],
            [<><C>STOPPING</C> → <C>STOPPED</C> / <C>CANCELLED</C></>, 'Stopped after (or before) it was ready.'],
            [<C key="7">FAILED</C>, 'See the error code and message on the page.'],
          ]}
        />
        <P>
          When a node goes offline, is revoked, or runs out of memory or disk, the deployment moves to another eligible node automatically.
          Its id, endpoint and API keys stay the same. A deployment is tried on at most 3 nodes. Model problems, such as a model that cannot
          answer a test prompt, are not retried elsewhere. <strong>Restart</strong> reloads a serving deployment on its current node from the
          cached model.
        </P>
      </Section>

      <Section id="api-keys" title="API keys">
        <P>
          Create keys under <strong>API Keys</strong>. A key can be limited to one deployment and given an expiry date. The key (
          <C>am_sk_…</C>) is shown once; AgentMesh stores only a hash. Revoke a key at any time. Deleting a deployment revokes the keys
          scoped to it. API keys work for calling deployments only; account actions (deploying, billing) use your dashboard sign-in.
        </P>
      </Section>

      <Section id="call" title="Call your model">
        <P>
          A ready deployment has <strong>Try it</strong>, which sends one real request through the gateway (metered like any other), and
          copy-paste examples. Every deployment has an OpenAI-compatible base URL:
        </P>
        <Code
          title="curl"
          code={`curl ${API_URL}/deployments/<deployment-id>/v1/chat/completions \\
  -H "Authorization: Bearer $AGENTMESH_API_KEY" -H "Content-Type: application/json" \\
  -d '{"model": "qwen2.5:0.5b", "messages": [{"role": "user", "content": "Hello"}]}'`}
        />
        <Code
          title="Python (openai)"
          code={`import os
from openai import OpenAI

client = OpenAI(
    base_url="${API_URL}/deployments/<deployment-id>/v1",
    api_key=os.environ["AGENTMESH_API_KEY"],
)
reply = client.chat.completions.create(
    model="qwen2.5:0.5b",
    messages=[{"role": "user", "content": "Hello"}],
)
print(reply.choices[0].message.content)`}
        />
        <P>
          More, including streaming and Ollama&apos;s native API, is in the <A href="/docs/api#inference">API reference</A>.
        </P>
      </Section>

      <Section id="stop" title="Stop and delete">
        <P>
          <strong>Stop</strong> ends a deployment and releases its capacity. <strong>Delete</strong> also hides it and revokes keys scoped to
          it; usage records are kept. Charges stop when a deployment leaves READY.
        </P>
      </Section>

      <Section id="billing" title="Pricing, wallet and billing">
        <Callout tone="warning" title="Payments run in Paystack test mode">
          Top-ups use Paystack in test mode: pay with a{' '}
          <A href="https://paystack.com/docs/payments/test-payments/">Paystack test card</A>. No real money moves. The integration has been
          verified against a stand-in for Paystack&apos;s API, not yet against Paystack itself.
        </Callout>
        <List
          items={[
            <>Deployments are <strong>prepaid</strong>. Add funds under <strong>Wallet</strong>; you return to the wallet after checkout and the top-up is credited once Paystack confirms it.</>,
            'Prices are set by the network operator as a versioned price list: per CPU core-hour, per GB-hour of memory and of GPU memory, and per million input and output tokens. The landing page and deploy form show the current list.',
            'Every few minutes while a deployment is READY, you are charged for its reserved resources multiplied by READY time, plus its tokens. Downloads, startup and unhealthy time are free.',
            'Each deployment lists its charges, and the wallet lists them all.',
            <>When your balance runs out, your deployments are stopped with <C>INSUFFICIENT_FUNDS</C>. The balance can dip below zero by at most one billing interval.</>,
            'If no price list has been published yet, usage is measured but not charged.',
          ]}
        />
      </Section>

      <Section id="usage" title="Usage">
        <P>
          <strong>Usage</strong> shows requests, failures, and input and output tokens per day and per deployment. Token counts are reported by the
          model runtime on the provider&apos;s machine and are not independently verified. Requests whose runtime reported no counts are shown
          separately; AgentMesh never estimates token counts. Prompts and responses are not stored.
        </P>
      </Section>

      <Section id="privacy" title="Privacy">
        <TrustNotice />
        <P>
          The dashboard shows this notice before every deployment and asks you to confirm it. Read more in{' '}
          <A href="/docs/security#trust-model">Security &amp; limitations</A>.
        </P>
      </Section>
    </DocPage>
  );
}
