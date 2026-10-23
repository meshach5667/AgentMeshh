import type { Deployment, DeploymentStatus, ModelArtifact, Runtime } from '@/types';

// Mirrors server/app/services/catalog_service.py.
export const RUNTIME_PREFERENCE: Runtime[] = ['ollama', 'llamacpp', 'vllm'];
export const DEFAULT_NUM_CTX = 2048;
export const MIN_NUM_CTX = 512;
export const MAX_NUM_CTX = 8192;

export interface Requirements {
  cpu_cores: number;
  ram_mb: number;
  disk_mb: number;
  vram_mb: number;
  gpu_required: boolean;
}

/** Same formula as the scheduler's reservation (estimate_requirements): +128 MB per extra 2048 tokens. */
export function estimateRequirements(a: ModelArtifact, numCtx: number, requireGpu: boolean): Requirements {
  const extra = Math.max(0, Math.ceil((numCtx - DEFAULT_NUM_CTX) / 2048)) * 128;
  const gpu = a.gpu_required || requireGpu;
  return {
    cpu_cores: Math.max(1, a.min_cpu_cores || 1),
    ram_mb: a.min_ram_mb + extra,
    disk_mb: a.min_disk_mb,
    vram_mb: gpu ? (a.min_vram_mb || 0) + extra : 0,
    gpu_required: gpu,
  };
}

/** Enabled artifacts in the order "automatic" runtime selection tries them. */
export function deployableArtifacts(artifacts: ModelArtifact[]): ModelArtifact[] {
  return artifacts
    .filter((a) => a.is_enabled && RUNTIME_PREFERENCE.includes(a.runtime))
    .sort((x, y) => RUNTIME_PREFERENCE.indexOf(x.runtime) - RUNTIME_PREFERENCE.indexOf(y.runtime));
}

export function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export const STATUS_HELP: Record<DeploymentStatus, string> = {
  REQUESTED: 'Waiting for a node with enough free capacity.',
  SCHEDULED: 'Capacity is reserved on a node; waiting for its worker to pick up the job.',
  PROVISIONING: 'The node is starting the runtime and downloading the model. Large models can take several minutes.',
  STARTING: 'The model is loading. A test generation must succeed before the deployment is marked ready.',
  READY: 'Serving requests. The test generation succeeded.',
  UNHEALTHY:
    'The node stopped reporting or its health check failed. Requests return 503. If it does not recover within a few minutes, AgentMesh moves the deployment to another node.',
  STOPPING: 'The node is stopping the runtime and removing the workload.',
  STOPPED: 'Stopped. Resources on the node were released.',
  FAILED: 'Failed. See the error below.',
  CANCELLED: 'Cancelled before it became ready.',
};

export interface ApiExample {
  id: string;
  label: string;
  code: string;
}

/** Copy-paste examples for calling a deployment. Uses an API key from the environment, never a real secret. */
export function apiExamples(dep: Pick<Deployment, 'openai_base_url' | 'endpoint' | 'runtime' | 'model_tag'>): ApiExample[] {
  const base = dep.openai_base_url;
  const model = dep.model_tag ?? 'model';
  if (!base) return [];
  const examples: ApiExample[] = [
    {
      id: 'curl',
      label: 'curl',
      code: [
        `curl ${base}/chat/completions \\`,
        `  -H "Authorization: Bearer $AGENTMESH_API_KEY" \\`,
        `  -H "Content-Type: application/json" \\`,
        `  -d '{"model": "${model}", "messages": [{"role": "user", "content": "Hello"}]}'`,
      ].join('\n'),
    },
    {
      id: 'python',
      label: 'Python (openai)',
      code: [
        'import os',
        'from openai import OpenAI',
        '',
        `client = OpenAI(base_url="${base}", api_key=os.environ["AGENTMESH_API_KEY"])`,
        'reply = client.chat.completions.create(',
        `    model="${model}",`,
        '    messages=[{"role": "user", "content": "Hello"}],',
        ')',
        'print(reply.choices[0].message.content)',
      ].join('\n'),
    },
    {
      id: 'stream',
      label: 'Streaming',
      code: [
        `curl -N ${base}/chat/completions \\`,
        `  -H "Authorization: Bearer $AGENTMESH_API_KEY" \\`,
        `  -H "Content-Type: application/json" \\`,
        `  -d '{"model": "${model}", "stream": true, "messages": [{"role": "user", "content": "Hello"}]}'`,
      ].join('\n'),
    },
  ];
  if (dep.runtime === 'ollama' && dep.endpoint) {
    examples.push({
      id: 'ollama',
      label: 'Ollama API',
      code: [
        `curl ${dep.endpoint}/api/chat \\`,
        `  -H "Authorization: Bearer $AGENTMESH_API_KEY" \\`,
        `  -d '{"model": "${model}", "stream": false, "messages": [{"role": "user", "content": "Hello"}]}'`,
      ].join('\n'),
    });
  }
  return examples;
}
