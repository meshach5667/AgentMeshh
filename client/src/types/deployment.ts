import type { Runtime } from './model';

// Mirrors the control plane lifecycle (server/app/services/deployment_lifecycle.py).
export type DeploymentStatus =
  | 'REQUESTED'
  | 'SCHEDULED'
  | 'PROVISIONING'
  | 'STARTING'
  | 'READY'
  | 'UNHEALTHY'
  | 'STOPPING'
  | 'STOPPED'
  | 'FAILED'
  | 'CANCELLED';

export const TERMINAL_STATUSES: DeploymentStatus[] = ['STOPPED', 'FAILED', 'CANCELLED'];
export const IN_PROGRESS_STATUSES: DeploymentStatus[] = ['REQUESTED', 'SCHEDULED', 'PROVISIONING', 'STARTING', 'STOPPING'];

export interface DeploymentConfig {
  num_ctx?: number;
  region?: string | null;
  require_gpu?: boolean;
}

export interface Deployment {
  id: string;
  customer_id: string;
  model_id: string;
  node_id: string | null;
  status: DeploymentStatus;
  /** Runtime-native base URL (Ollama API for Ollama deployments, otherwise OpenAI-compatible). */
  endpoint: string | null;
  /** OpenAI-compatible base URL; works for every runtime. */
  openai_base_url: string | null;
  runtime: Runtime | null;
  artifact_id: string | null;
  model_tag: string | null;
  model_digest: string | null;
  config: DeploymentConfig | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  ready_at: string | null;
  ended_at: string | null;
  cleanup_status: string | null;
  schedule_attempts: number;
  restart_count: number;
}

export interface DeploymentEvent {
  from_status: string | null;
  to_status: string | null;
  actor: string;
  message: string | null;
  created_at: string;
}
