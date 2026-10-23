import { AxiosError, AxiosHeaders } from 'axios';
import { errorMessage, noCapacityDetail } from '../errors';
import { apiExamples, deployableArtifacts, estimateRequirements } from '../deployments';
import { mb, parseApiDate } from '../format';
import { nodeAvailability } from '../nodes';
import type { ModelArtifact, Node } from '@/types';

function axiosError(status: number, data: unknown): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError('failed', 'ERR', undefined, undefined, {
    status,
    statusText: '',
    headers,
    config: { headers },
    data,
  });
}

const artifact = (over: Partial<ModelArtifact> = {}): ModelArtifact => ({
  id: 'a',
  runtime: 'ollama',
  source_type: 'ollama',
  reference: 'qwen2.5:0.5b',
  revision: null,
  file: null,
  sha256: null,
  size_bytes: null,
  format: 'ollama',
  quantization: null,
  min_ram_mb: 1024,
  min_disk_mb: 768,
  min_vram_mb: 0,
  min_cpu_cores: 1,
  gpu_required: false,
  requirements_estimated: true,
  is_enabled: true,
  last_ready_at: null,
  ...over,
});

describe('errorMessage', () => {
  it('reads FastAPI string details, validation lists and gateway errors', () => {
    expect(errorMessage(axiosError(404, { detail: 'Deployment not found' }))).toBe('Deployment not found');
    expect(
      errorMessage(axiosError(422, { detail: [{ loc: ['body', 'config', 'num_ctx'], msg: 'too large' }] })),
    ).toBe('config.num_ctx: too large');
    expect(errorMessage(axiosError(409, { error: { code: 'deployment_not_ready', message: 'Not ready yet' } }))).toBe(
      'Not ready yet',
    );
  });

  it('explains placement failures with their reasons', () => {
    const err = axiosError(503, {
      detail: { code: 'no_eligible_node', message: 'No node fits', reasons: { insufficient_capacity: 2 } },
    });
    expect(noCapacityDetail(err)?.reasons).toEqual({ insufficient_capacity: 2 });
    expect(errorMessage(err)).toBe('No node fits: not enough free CPU, memory, disk or GPU memory (2)');
    expect(noCapacityDetail(axiosError(500, { detail: 'boom' }))).toBeNull();
  });

  it('reports an unreachable API distinctly', () => {
    expect(errorMessage(new AxiosError('Network Error'))).toMatch(/Cannot reach the AgentMesh API/);
  });
});

describe('deployment helpers', () => {
  it('estimates reservations with the scheduler formula', () => {
    expect(estimateRequirements(artifact(), 2048, false)).toEqual({ cpu_cores: 1, ram_mb: 1024, disk_mb: 768, vram_mb: 0, gpu_required: false });
    // +128 MB per started 2048 tokens beyond the default, also on VRAM when a GPU is used.
    expect(estimateRequirements(artifact(), 4096, false).ram_mb).toBe(1152);
    expect(estimateRequirements(artifact({ min_vram_mb: 4096, gpu_required: true }), 8192, false)).toMatchObject({ ram_mb: 1408, vram_mb: 4480 });
  });

  it('orders enabled artifacts by runtime preference and drops disabled ones', () => {
    const list = deployableArtifacts([
      artifact({ id: 'v', runtime: 'vllm' }),
      artifact({ id: 'l', runtime: 'llamacpp' }),
      artifact({ id: 'o', runtime: 'ollama', is_enabled: false }),
    ]);
    expect(list.map((a) => a.id)).toEqual(['l', 'v']);
  });

  it('builds examples from the deployment endpoints, with Ollama routes only for Ollama', () => {
    const base = 'http://api/api/v1/deployments/d1';
    const ollama = apiExamples({ openai_base_url: `${base}/v1`, endpoint: `${base}/ollama`, runtime: 'ollama', model_tag: 'qwen2.5:0.5b' });
    expect(ollama.map((e) => e.id)).toEqual(['curl', 'python', 'stream', 'ollama']);
    expect(ollama[0].code).toContain(`${base}/v1/chat/completions`);
    expect(ollama[0].code).toContain('$AGENTMESH_API_KEY');
    const llama = apiExamples({ openai_base_url: `${base}/v1`, endpoint: `${base}/v1`, runtime: 'llamacpp', model_tag: 'x' });
    expect(llama.map((e) => e.id)).not.toContain('ollama');
    expect(apiExamples({ openai_base_url: null, endpoint: null, runtime: null, model_tag: null })).toEqual([]);
  });
});

describe('formatting', () => {
  it('treats API timestamps without an offset as UTC', () => {
    expect(parseApiDate('2026-10-21T10:00:00')?.toISOString()).toBe('2026-10-21T10:00:00.000Z');
    expect(parseApiDate('2026-10-21T10:00:00+02:00')?.toISOString()).toBe('2026-10-21T08:00:00.000Z');
    expect(parseApiDate(null)).toBeNull();
  });
  it('formats megabytes', () => {
    expect(mb(512)).toBe('512 MB');
    expect(mb(2048)).toBe('2 GB');
    expect(mb(1536)).toBe('1.5 GB');
  });
});

describe('nodeAvailability', () => {
  const node = (over: Partial<Node> = {}): Node =>
    ({
      id: 'n',
      status: 'ONLINE',
      last_heartbeat: new Date().toISOString(),
      accepting_workloads: true,
      worker_available: true,
      worker_unavailable_reason: null,
      ...over,
    }) as Node;

  it('follows the scheduler checks in order', () => {
    expect(nodeAvailability(node()).label).toBe('Accepting work');
    expect(nodeAvailability(node({ accepting_workloads: false })).label).toBe('Paused');
    expect(nodeAvailability(node({ worker_available: false, worker_unavailable_reason: 'schedule' })).detail).toMatch(/schedule/);
    expect(nodeAvailability(node({ last_heartbeat: new Date(Date.now() - 300000).toISOString() })).label).toBe('Offline');
    expect(nodeAvailability(node({ status: 'REVOKED', accepting_workloads: false })).label).toBe('Revoked');
  });
});
