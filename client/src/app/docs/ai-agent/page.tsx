import type { Metadata } from 'next';
import { C, Callout, Code, DocPage, List, P, Section, Table } from '@/components/docs/DocsContent';
import { API_URL } from '@/lib/config';

export const metadata: Metadata = { title: 'AI deployment agent' };

const CONTROL_PLANE = API_URL.replace(/\/api\/v1\/?$/, '');

export default function AiAgentGuide() {
  return (
    <DocPage href="/docs/ai-agent">
      <Section id="how-it-works" title="How it works">
        <P>
          Customers describe a deployment in plain language (<C>/customer/ai</C>) and authorize limits. A Gemma 4 model, served by
          Ollama on an internal inference machine, turns the request into a structured plan and diagnoses failures. Everything with
          consequences runs in the control plane&apos;s own code: catalog checks, limits, prices, wallet balance, node selection,
          capacity reservation, submission, verification, and stopping.
        </P>
        <Table
          head={['Component', 'Runs on', 'Responsible for']}
          rows={[
            ['Control plane', 'The API (e.g. Render)', 'Auth, scheduling, reservations, billing, workflow state, audit, limit enforcement'],
            ['Inference machine', 'An internal computer, e.g. an HP 15 laptop', 'Ollama + Gemma 4 + the adapter (python -m ai_adapter)'],
            ['Compute nodes', 'Provider machines', 'Customer model deployments, through the existing worker'],
          ]}
        />
        <P>
          The adapter connects <strong>outbound</strong> over HTTPS, reports health, and leases queued model calls from the control
          plane. The inference machine needs no public address and no open port, and Ollama stays bound to <C>127.0.0.1</C>. The
          inference machine is never a provider node: it is not enrolled as a worker and never runs customer workloads.
        </P>
        <Callout tone="info" title="What the model decides, and what it does not">
          The model chooses among catalog models and recovery actions and writes explanations. It never decides authorization, GPU
          availability, prices, budget compliance, or whether a deployment works. It cannot call submission, rollback, recovery or
          health-check tools itself; it can only propose them, and the application validates every proposal.
        </Callout>
      </Section>

      <Section id="hardware" title="Check the hardware">
        <P>Nothing is assumed about the machine. On the inference machine, run:</P>
        <Code
          code={[
            'lscpu | grep -E "Model name|^CPU\\(s\\)|Flags" | cut -c1-120   # CPU and AVX2/AVX-512 support',
            'free -h                                                     # total and available memory',
            'df -h /usr/share/ollama 2>/dev/null || df -h ~                # disk for models',
            'lspci | grep -iE "vga|3d"                                     # GPUs (an Intel iGPU is not used by default)',
            'cd server && python -m ai_adapter doctor                      # all of the above, plus Ollama and a recommendation',
          ].join('\n')}
        />
        <P>
          <C>doctor</C> changes nothing. It reports CPU flags, memory, free disk where Ollama stores models, whether an NVIDIA or
          ROCm GPU device exists (installed tools alone do not count), whether Ollama answers, and whether the configured model is
          pulled.
        </P>
        <P>Reference machine (measured 2026-10-21):</P>
        <Table
          head={['Item', 'HP Laptop 15-dy1xxx']}
          rows={[
            ['CPU', 'Intel Core i5-1035G1, 4 cores / 8 threads, AVX2 and AVX-512'],
            ['Memory', '15 GB total; often only 1-2 GB available with a browser and editor open'],
            ['GPU', 'Intel Iris Plus (integrated). No NVIDIA/AMD device: CPU inference'],
            ['Disk', '~390 GB free'],
            ['Ollama', '0.40.6, system service on 127.0.0.1:11434'],
          ]}
        />
      </Section>

      <Section id="model" title="Choose a Gemma 4 variant">
        <P>
          Download sizes below come from the Ollama registry manifests (checked 2026-10-21). Memory figures are estimates (weights
          plus about 1.5 GB for a 4,096-token context and the runtime).
        </P>
        <Table
          head={['Tag', 'Download', 'Memory needed (est.)', 'Use']}
          rows={[
            [<C key="a">gemma4:e2b-it-qat</C>, '4.3 GB', '~6 GB', 'Default. CPU-only laptops with 12-16 GB RAM'],
            [<C key="b">gemma4:e4b-it-qat</C>, '6.1 GB', '~8 GB', 'Machines with 16 GB+ to spare or a GPU; about half the speed on CPU'],
          ]}
        />
        <P>
          Larger variants (12b, 26b, 31b) are not supported by the adapter on laptops. Set the same tag in <C>OLLAMA_MODEL</C> on the
          control plane and the adapter: the control plane rejects answers from any other model, and the adapter refuses jobs for
          another model, so there is never a silent fallback.
        </P>
      </Section>

      <Section id="install" title="Install Ollama and the model">
        <List
          ordered
          items={[
            <>Install Ollama (Linux): <C>curl -fsSL https://ollama.com/install.sh | sh</C>. This creates the <C>ollama</C> systemd service.</>,
            <>
              Optional but recommended: apply <C>server/packaging/ollama-agentmesh.conf</C> as a drop-in. It pins Ollama to loopback,
              keeps one model loaded with one request at a time, and caps it at 6 of 8 threads and 8 GB of RAM.
            </>,
            <>Set up the adapter environment (a Python 3.11+ venv in <C>server/</C> with <C>pip install -r requirements-worker.txt</C>).</>,
            <>
              Pull the model through the adapter, which checks disk space and RAM first: <C>python -m ai_adapter pull</C> shows what it
              would do; <C>python -m ai_adapter pull --yes</C> downloads.
            </>,
            <>
              Test real inference: <C>python -m ai_adapter check</C> runs one small structured (JSON-schema) generation and prints the
              latency. It fails if the installed Ollama cannot run the model.
            </>,
          ]}
        />
        <Code
          title="Install the drop-in"
          code={[
            'sudo mkdir -p /etc/systemd/system/ollama.service.d',
            'sudo cp server/packaging/ollama-agentmesh.conf /etc/systemd/system/ollama.service.d/agentmesh.conf',
            'sudo systemctl daemon-reload && sudo systemctl restart ollama',
          ].join('\n')}
        />
      </Section>

      <Section id="connect" title="Connect it to AgentMesh">
        <List
          ordered
          items={[
            <>Generate a token: <C>openssl rand -hex 32</C>.</>,
            <>
              Control plane (e.g. Render environment): set <C>AI_INFERENCE_TOKEN</C> to it and <C>OLLAMA_MODEL</C> to the tag. Without
              a token the adapter endpoints are disabled and customers see “not configured”.
            </>,
            <>
              Inference machine: copy <C>server/ai_adapter/ai-adapter.env.example</C> to <C>~/.config/agentmesh/ai-adapter.env</C>,
              fill in the token, and <C>chmod 600</C> it.
            </>,
          ]}
        />
        <Table
          head={['Adapter variable', 'Default', 'Meaning']}
          rows={[
            [<C key="1">AGENTMESH_CONTROL_PLANE_URL</C>, CONTROL_PLANE, 'https required (except localhost)'],
            [<C key="2">AI_INFERENCE_TOKEN</C>, '—', 'Shared secret; must match the control plane'],
            [<C key="3">AI_INFERENCE_NODE_ID</C>, 'hp15', 'Name of this machine in health reports'],
            [<C key="4">OLLAMA_BASE_URL</C>, 'http://127.0.0.1:11434', 'Loopback only unless ALLOW_REMOTE_OLLAMA=true'],
            [<C key="5">OLLAMA_MODEL</C>, 'gemma4:e2b-it-qat', 'Must equal the control plane setting'],
            [<C key="6">AI_REQUEST_TIMEOUT</C>, '180', 'Seconds per model call'],
            [<C key="7">AI_MAX_CONCURRENT_REQUESTS</C>, '1', 'Model calls at once on this machine (max 4)'],
            [<><C>AI_NUM_CTX</C>, <C>AI_MAX_TOKENS</C></>, '4096, 512', 'Context and output caps (the adapter clamps requests to them)'],
            [<C key="9">AI_MIN_AVAILABLE_MEMORY_MB</C>, '1024', 'Stop taking work below this much free memory'],
            [<C key="10">AI_MAX_LOAD_PER_CPU</C>, '1.5', 'Stop taking work above this load average per CPU'],
          ]}
        />
        <P>
          Control-plane limits (<C>server/app/core/config.py</C>): <C>AI_QUEUE_MAX_LENGTH</C> (20), <C>AI_QUEUE_TTL_SECONDS</C>{' '}
          (3600), <C>AI_MAX_ATTEMPTS</C> (2), <C>AI_RATE_LIMIT_PER_MINUTE</C> (3 per user), <C>AI_MAX_AGENT_STEPS</C> (6),{' '}
          <C>AI_MAX_TOOL_CALLS</C> (8), <C>AI_MAX_DEPLOYMENT_HOURS</C> (168), <C>AI_MAX_RECOVERY_ATTEMPTS</C> (3).
        </P>
      </Section>

      <Section id="systemd" title="Run it at startup">
        <Code
          code={[
            'mkdir -p ~/.config/systemd/user',
            'cp server/packaging/agentmesh-ai-adapter.service ~/.config/systemd/user/',
            '# edit WorkingDirectory/ExecStart if the repository is not at ~/AgentMesh',
            'systemctl --user daemon-reload',
            'systemctl --user enable --now agentmesh-ai-adapter',
            'loginctl enable-linger "$USER"   # keep running while logged out',
            'journalctl --user -u agentmesh-ai-adapter -f',
          ].join('\n')}
        />
      </Section>

      <Section id="monitoring" title="Monitor CPU and memory">
        <List
          items={[
            <>Every heartbeat reports CPU %, load per CPU, and available memory; operators see them in <C>GET /api/v1/ai/health</C>. Customers only see available / busy / offline and the queue length.</>,
            <>On the machine: <C>ollama ps</C> (loaded model and its memory), <C>systemctl status ollama</C>, <C>top</C> or <C>htop</C>.</>,
            <>When memory or CPU is short, the adapter stops leasing work and reports why; requests wait in the queue. It never restarts Ollama.</>,
            <>Before the model is loaded, the adapter requires room for the weights plus 1.5 GB; once loaded (kept for 30 minutes), only the configured reserve.</>,
          ]}
        />
      </Section>

      <Section id="offline" title="Restarts and disconnections">
        <P>The inference machine is a personal computer; it will be off or offline sometimes. When it is:</P>
        <List
          items={[
            <>After <C>AI_NODE_TIMEOUT_SECONDS</C> (45 s) without a heartbeat the AI service shows as offline. Nothing is sent to it.</>,
            'The control plane, database, billing, and every running customer deployment keep working. Deployment state lives in the database, not in the model conversation.',
            'New AI requests are accepted and queued (up to AI_QUEUE_MAX_LENGTH). A request not answered within AI_QUEUE_TTL_SECONDS fails with “No AI decision was made”; nothing is deployed.',
            'Deterministic steps continue: verification, duration and spend limits, stopping and cancellation all work without the model.',
            'When the machine reconnects, the adapter heartbeats, leases the queued requests, and runs continue where they stopped. A model call that was in progress is re-queued once its lease expires (bounded by AI_MAX_ATTEMPTS).',
          ]}
        />
      </Section>

      <Section id="limits" title="Autonomy limits">
        <P>Customers set these per request; they are enforced in code, never by the prompt:</P>
        <List
          items={[
            'Maximum spend: the plan’s estimate must fit, the wallet must cover it, and the deployment is stopped when rated charges plus unrated READY time reach it.',
            'Maximum duration: the deployment is stopped when it is reached.',
            'Maximum CPU cores, memory, and GPU memory (0 = no GPU).',
            'Maximum automatic recovery attempts (platform ceiling 3).',
            'Allowed runtimes (Ollama, llama.cpp, vLLM) and model sources (Ollama registry, Hugging Face).',
            'Agent steps and tool calls per run (platform settings).',
          ]}
        />
        <Callout tone="warning" title="Budget is checked, not held">
          The ledger has no holds, so “reserve budget” means: the wallet must cover the estimate when the deployment is created, node
          capacity is reserved atomically in the same transaction as the existing prepaid check, and spending is enforced by stopping
          the deployment. Another deployment could still use the same balance in the meantime.
        </Callout>
      </Section>

      <Section id="testing" title="Tests">
        <Code
          code={[
            'cd server',
            'pytest tests/test_ai_agent.py tests/test_ai_adapter.py     # scripted model answers, no Ollama needed',
            '',
            '# Optional: real structured generation against a local Ollama that already has the model',
            'AGENTMESH_TEST_OLLAMA_URL=http://127.0.0.1:11434 \\',
            'AGENTMESH_TEST_OLLAMA_MODEL=gemma4:e2b-it-qat \\',
            '  pytest tests/test_ai_adapter.py -k real_ollama',
          ].join('\n')}
        />
        <P>
          The tests never pull models, never create paid deployments (no price is configured unless a test sets one), and never use
          GPUs. The real-Ollama test is skipped unless both variables are set and the model is already present.
        </P>
      </Section>

      <Section id="not-verified" title="Not yet verified">
        <List
          items={[
            'Gemma 4 has not been pulled or run on the reference HP 15, so its latency, memory use, and the quality of its JSON plans there are unmeasured. Run python -m ai_adapter check after pulling.',
            'Ollama 0.40.6 support for the gemma4 tags is assumed from the registry listing; check confirms it.',
            'The memory figures for each variant are estimates.',
            'The end-to-end flow was tested with scripted model answers and a simulated worker tunnel, not with a real provider node running a model.',
          ]}
        />
      </Section>
    </DocPage>
  );
}
