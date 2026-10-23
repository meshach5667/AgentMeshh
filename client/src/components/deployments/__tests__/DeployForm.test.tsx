import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AxiosError, AxiosHeaders } from 'axios';
import { DeployForm } from '../DeployForm';
import api from '@/lib/api';
import type { Model, ModelArtifact } from '@/types';

const push = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
jest.mock('@/lib/api', () => ({ __esModule: true, default: { post: jest.fn() } }));
const post = api.post as jest.Mock;

const artifact = (runtime: ModelArtifact['runtime'], over: Partial<ModelArtifact> = {}): ModelArtifact => ({
  id: runtime,
  runtime,
  source_type: runtime === 'ollama' ? 'ollama' : 'huggingface',
  reference: runtime === 'ollama' ? 'qwen2.5:0.5b' : 'Qwen/Qwen2.5-0.5B-Instruct-GGUF',
  revision: null,
  file: null,
  sha256: null,
  size_bytes: null,
  format: null,
  quantization: null,
  min_ram_mb: runtime === 'ollama' ? 1024 : 768,
  min_disk_mb: 768,
  min_vram_mb: 0,
  min_cpu_cores: 1,
  gpu_required: false,
  requirements_estimated: true,
  is_enabled: true,
  last_ready_at: null,
  ...over,
});

const model = { id: 'm1', name: 'Qwen', license: 'Apache-2.0', artifacts: [artifact('llamacpp'), artifact('ollama')] } as Model;

function renderForm(m: Model = model) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DeployForm model={m} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  post.mockReset();
  push.mockReset();
});

it('requires the trust acknowledgement before deploying', () => {
  renderForm();
  const deploy = screen.getByRole('button', { name: 'Deploy' });
  expect(deploy).toBeDisabled();
  expect(screen.getByText(/provider can see the model, its memory, and every prompt/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: /I understand the provider can see/ }));
  expect(deploy).toBeEnabled();
});

it('submits the chosen runtime and config with an idempotency key, then opens the deployment', async () => {
  post.mockResolvedValue({ data: { id: 'dep-1' } });
  renderForm();
  fireEvent.click(screen.getByRole('radio', { name: /^llama\.cpp/ }));
  fireEvent.change(screen.getByLabelText('Context window (tokens)'), { target: { value: '4096' } });
  // Only the chosen runtime is estimated: 768 MB + 128 MB for the larger context.
  expect(screen.getByText(/896 MB RAM/)).toBeInTheDocument();
  expect(screen.queryByText(/1 GB RAM/)).toBeNull();
  fireEvent.click(screen.getByRole('checkbox', { name: /I understand/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Deploy' }));
  await waitFor(() => expect(push).toHaveBeenCalledWith('/customer/deployments/dep-1'));
  const [url, body] = post.mock.calls[0];
  expect(url).toBe('/deployments');
  expect(body).toMatchObject({ model_id: 'm1', runtime: 'llamacpp', config: { num_ctx: 4096, require_gpu: false } });
  expect(body.idempotency_key).toEqual(expect.any(String));
});

it('lists automatic runtimes in preference order and omits runtime for automatic', async () => {
  post.mockResolvedValue({ data: { id: 'dep-2' } });
  renderForm();
  expect(screen.getByText(/Try Ollama, then llama\.cpp/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: /I understand/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Deploy' }));
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect(post.mock.calls[0][1].runtime).toBeUndefined();
});

it('explains a 503 per runtime', async () => {
  const headers = new AxiosHeaders();
  post.mockRejectedValue(
    new AxiosError('x', 'ERR', undefined, undefined, {
      status: 503,
      statusText: '',
      headers,
      config: { headers },
      data: {
        detail: {
          code: 'no_eligible_node',
          reasons: { insufficient_capacity: 1, unsupported_runtime: 1 },
          by_runtime: {
            ollama: { message: 'x', reasons: { insufficient_capacity: 1 } },
            llamacpp: { message: 'y', reasons: { unsupported_runtime: 1 } },
          },
        },
      },
    }),
  );
  renderForm();
  fireEvent.click(screen.getByRole('checkbox', { name: /I understand/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Deploy' }));
  expect(await screen.findByText('No node can run this deployment right now')).toBeInTheDocument();
  expect(screen.getByText(/1 node: not enough free CPU, memory, disk or GPU memory/)).toBeInTheDocument();
  expect(screen.getByText(/1 node: runtime not installed on the node/)).toBeInTheDocument();
  expect(push).not.toHaveBeenCalled();
});

it('refuses models without an enabled artifact', () => {
  renderForm({ ...model, artifacts: [artifact('ollama', { is_enabled: false })] });
  expect(screen.getByText(/no enabled runtime artifact/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Deploy' })).toBeNull();
});
