import type { Metadata } from 'next';
import { A, C, Callout, Code, DocPage, H3, List, P, Section, Table } from '@/components/docs/DocsContent';
import { API_URL } from '@/lib/config';

export const metadata: Metadata = { title: 'API reference' };

const DEP = `${API_URL}/deployments/<deployment-id>`;

export default function ApiGuide() {
  return (
    <DocPage href="/docs/api">
      <Section id="base-url" title="Base URL">
        <Code code={API_URL} />
        <P>
          All paths below are relative to it. The full machine-readable schema is at <A href={`${API_URL}/docs`}>{`${API_URL}/docs`}</A>{' '}
          (OpenAPI). Requests and responses are JSON. Every response carries an <C>X-Request-ID</C> header; quote it when reporting a problem.
        </P>
      </Section>

      <Section id="auth" title="Authentication">
        <P>There are two kinds of credentials:</P>
        <Table
          head={['Credential', 'Get it from', 'Use it for']}
          rows={[
            ['Session token (JWT)', <><C key="a">POST /auth/register</C> or <C>POST /auth/login</C></>, 'Account actions: models, deployments, API keys, wallet, usage.'],
            [<>API key (<C key="b">am_sk_…</C>)</>, <><C key="c">POST /api-keys</C> or the dashboard</>, <>Calling deployments through the gateway (<C>/deployments/&#123;id&#125;/v1/…</C>, <C>/ollama/…</C>) only. The gateway also accepts a session token; that is how the dashboard&apos;s Try it works.</>],
          ]}
        />
        <Code
          title="Sign in and keep the token"
          code={`JWT=$(curl -s -X POST ${API_URL}/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"email": "you@example.com", "password": "your-password"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')`}
        />
        <P>
          Register with <C>POST /auth/register</C> and <C>{'{"email", "password", "role"}'}</C>, where <C>role</C> is <C>customer</C> or{' '}
          <C>provider</C> and the password has at least 8 characters. Both endpoints return <C>access_token</C> and the <C>user</C>. Send the token
          as <C>Authorization: Bearer $JWT</C>. <C>GET /auth/me</C> returns the signed-in user. Login and registration are rate limited (429 with{' '}
          <C>Retry-After</C>).
        </P>
      </Section>

      <Section id="models" title="Models">
        <Code code={`curl ${API_URL}/models`} />
        <P>
          Lists approved models. Each has <C>artifacts</C>: one per runtime that can serve it, pinned to an Ollama tag or a Hugging Face commit, with
          estimated <C>min_ram_mb</C>, <C>min_disk_mb</C>, <C>min_vram_mb</C> and <C>gpu_required</C>. <C>last_ready_at</C> shows when a deployment of
          it last passed its readiness test. <C>GET /models/&#123;id&#125;</C> returns one model.
        </P>
      </Section>

      <Section id="deployments" title="Deployments">
        <Code
          title="Create"
          code={`curl -X POST ${API_URL}/deployments \\
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \\
  -d '{"model_id": "<model-id>", "config": {"num_ctx": 4096}, "idempotency_key": "my-retry-key"}'`}
        />
        <List
          items={[
            <>Add <C>&quot;runtime&quot;: &quot;ollama&quot;</C> (or <C>llamacpp</C>, <C>vllm</C>) to choose one; otherwise they are tried in that order.</>,
            <><C>config</C> accepts only <C>num_ctx</C> (512–8192), <C>region</C> and <C>require_gpu</C>. Anything else is rejected.</>,
            <>Retrying with the same <C>idempotency_key</C> returns the same deployment.</>,
            <>No node available: <C>503</C> with <C>{'{"detail": {"code": "no_eligible_node", "reasons": {...}, "by_runtime": {...}}}'}</C>.</>,
            <>Not enough balance: <C>402</C> with <C>{'{"detail": {"code": "insufficient_balance", "required": ..., "balance": ...}}'}</C>.</>,
          ]}
        />
        <Table
          head={['Method and path', 'Purpose']}
          rows={[
            [<C key="1">GET /deployments</C>, 'Your deployments.'],
            [<C key="2">GET /deployments/&#123;id&#125;</C>, <>One deployment. Poll until <C>status</C> is <C>READY</C>; it then has <C>openai_base_url</C> and <C>endpoint</C>.</>],
            [<C key="3">GET /deployments/&#123;id&#125;/events</C>, 'Lifecycle events (progress, moves, errors).'],
            [<C key="4">POST /deployments/&#123;id&#125;/stop</C>, 'Stop it.'],
            [<C key="5">POST /deployments/&#123;id&#125;/restart</C>, 'Reload it on its current node from the cached model.'],
            [<C key="6">DELETE /deployments/&#123;id&#125;</C>, 'Stop, hide, and revoke its scoped keys. Usage records are kept.'],
          ]}
        />
        <P>
          Statuses: <C>SCHEDULED</C> → <C>PROVISIONING</C> → <C>STARTING</C> → <C>READY</C>, plus <C>UNHEALTHY</C>, <C>STOPPING</C>, <C>STOPPED</C>,{' '}
          <C>CANCELLED</C> and <C>FAILED</C> (with <C>error_code</C> and <C>error_message</C>). See the{' '}
          <A href="/docs/customers#lifecycle">customer guide</A> for what each means.
        </P>
      </Section>

      <Section id="api-keys" title="API keys">
        <Code
          code={`curl -X POST ${API_URL}/api-keys -H "Authorization: Bearer $JWT" \\
  -H "Content-Type: application/json" -d '{"name": "my-app", "deployment_id": "<deployment-id>"}'`}
        />
        <P>
          The <C>key</C> is returned once. Omit <C>deployment_id</C> to allow all your deployments. <C>GET /api-keys</C> lists keys (without
          secrets); <C>DELETE /api-keys/&#123;id&#125;</C> revokes one.
        </P>
      </Section>

      <Section id="inference" title="Inference">
        <P>
          Every deployment has <C>openai_base_url</C>, <C>…/deployments/&#123;id&#125;/v1</C>, which works for every runtime: <C>/chat/completions</C>,{' '}
          <C>/completions</C> and <C>/models</C>.
        </P>
        <Code
          code={`curl ${DEP}/v1/chat/completions \\
  -H "Authorization: Bearer $AGENTMESH_API_KEY" -H "Content-Type: application/json" \\
  -d '{"model": "any", "messages": [{"role": "user", "content": "Hello"}]}'`}
        />
        <H3>Ollama&apos;s native API</H3>
        <P>
          Ollama deployments also expose <C>endpoint</C>, <C>…/deployments/&#123;id&#125;/ollama</C>, with <C>/api/chat</C> and <C>/api/generate</C>.
          Calling it on a llama.cpp or vLLM deployment returns 404. Model-management routes (<C>api/pull</C>, <C>api/delete</C>, …) are never exposed.
        </P>
        <Code
          code={`curl ${DEP}/ollama/api/chat -H "Authorization: Bearer $AGENTMESH_API_KEY" \\
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'`}
        />
        <H3>Behaviour to know</H3>
        <List
          items={[
            <>The <C>model</C> field is always replaced with the deployment&apos;s model.</>,
            <>For Ollama, <C>keep_alive</C> is ignored and <C>options.num_ctx</C> is set to the deployment&apos;s context size.</>,
            'Prompts and responses pass through the provider’s machine and are not stored by AgentMesh.',
          ]}
        />
      </Section>

      <Section id="streaming" title="Streaming">
        <P>
          Set <C>&quot;stream&quot;: true</C> for server-sent events on <C>/v1</C>. AgentMesh adds <C>stream_options.include_usage</C> unless you set it, so the
          final chunk carries a <C>usage</C> object used for metering. The Ollama native API streams NDJSON.
        </P>
        <Code
          code={`curl -N ${DEP}/v1/chat/completions \\
  -H "Authorization: Bearer $AGENTMESH_API_KEY" -H "Content-Type: application/json" \\
  -d '{"model": "any", "stream": true, "messages": [{"role": "user", "content": "Write a haiku"}]}'`}
        />
      </Section>

      <Section id="sdks" title="SDK examples">
        <P>Any OpenAI-compatible client works. Point its base URL at your deployment.</P>
        <Code
          title="Python: pip install openai"
          code={`import os
from openai import OpenAI

client = OpenAI(
    base_url="${API_URL}/deployments/<deployment-id>/v1",
    api_key=os.environ["AGENTMESH_API_KEY"],
)

stream = client.chat.completions.create(
    model="any",
    messages=[{"role": "user", "content": "Explain DNS in one paragraph"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)`}
        />
        <Code
          title="JavaScript / TypeScript: npm install openai"
          code={`import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: '${API_URL}/deployments/<deployment-id>/v1',
  apiKey: process.env.AGENTMESH_API_KEY,
});

const reply = await client.chat.completions.create({
  model: 'any',
  messages: [{ role: 'user', content: 'Hello' }],
});
console.log(reply.choices[0].message.content);`}
        />
        <Callout tone="warning">
          Keep API keys on your server. Do not ship them in browser or mobile code.
        </Callout>
      </Section>

      <Section id="errors" title="Errors and limits">
        <P>
          Gateway errors use <C>{'{"error": {"code": "...", "message": "..."}}'}</C>. Account endpoints use FastAPI&apos;s <C>{'{"detail": ...}'}</C>.
        </P>
        <Table
          head={['Code', 'Meaning', 'What to do']}
          rows={[
            [<C key="1">unauthorized</C>, '401: missing, wrong, expired or revoked credentials.', 'Check the key.'],
            [<C key="2">deployment_not_found</C>, '404: no such deployment for you, or the key is scoped to a different deployment.', 'Check the id and the key’s scope.'],
            [<C key="3">deployment_not_ready</C>, '409: still starting, or moving to another node.', 'Retry with backoff.'],
            [<C key="4">deployment_unhealthy</C>, '503: health checks failing.', 'Retry with backoff; it moves after 3 minutes.'],
            [<C key="5">node_unavailable</C>, '503: the node went away.', 'Retry with backoff; failover is automatic.'],
            [<C key="6">rate_limited</C>, '429: over 60 requests per minute per key.', <>Honour <C key="r">Retry-After</C>.</>],
            [<C key="6b">too_many_concurrent_requests</C>, '429: the deployment already has 4 requests in flight.', 'Retry shortly, or deploy another replica of the model.'],
            [<C key="6c">timeout</C>, '504: the runtime did not start responding in time.', 'Retry; try a smaller prompt or model.'],
            [<C key="7">request_too_large</C>, '413: body over 1 MB.', 'Send less.'],
            [<C key="8">unsupported_endpoint</C>, '404: route not served by this runtime.', <>Use <C key="v">/v1</C>.</>],
          ]}
        />
        <P>Limits apply per control-plane process.</P>
      </Section>

      <Section id="usage" title="Usage and billing">
        <Table
          head={['Method and path', 'Returns']}
          rows={[
            [<C key="1">GET /usage/&#123;deployment_id&#125;</C>, <>One record per request: endpoint, status, duration, bytes, token counts. Newest 200 by default (<C>?limit=</C> up to 1000).</>],
            [<C key="2">GET /usage/summary?days=30</C>, 'Requests, successes, failures and tokens per day and per deployment (1–90 days).'],
            [<C key="3">GET /billing/pricing</C>, 'The price list in force.'],
            [<C key="4">GET /billing/charges?deployment_id=…</C>, 'What each billing window cost.'],
            [<C key="5">GET /wallets</C>, 'Your balance.'],
            [<C key="6">POST /payments/topups</C>, <>Start a Paystack checkout (test mode): <C>{'{"amount": 5000}'}</C>.</>],
            [<C key="7">GET /stats/public</C>, 'Network counts; no authentication.'],
          ]}
        />
        <P>
          Token counts are <C>runtime_reported</C>: they come from the provider&apos;s machine and are not independently verified. When the runtime does
          not report them they are <C>null</C>; they are never estimated.
        </P>
      </Section>
    </DocPage>
  );
}
