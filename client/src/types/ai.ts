import type { Runtime } from './model';

// Mirrors server/app/services/ai/workflow.py.
export type AiRunStatus =
  | 'PLANNING'
  | 'SUBMITTING'
  | 'DEPLOYING'
  | 'VERIFYING'
  | 'READY'
  | 'RECOVERING'
  | 'STOPPING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export const AI_TERMINAL_STATUSES: AiRunStatus[] = ['COMPLETED', 'FAILED', 'CANCELLED'];

export type ModelSource = 'ollama' | 'huggingface';

export interface AutonomyLimits {
  max_spend: string;
  max_duration_hours: number;
  max_cpu_cores: number;
  max_ram_mb: number;
  max_vram_mb: number;
  max_recovery_attempts: number;
  allowed_runtimes: Runtime[];
  allowed_sources: ModelSource[];
}

export interface AiPlan {
  model_id: string;
  runtime: Runtime | null;
  num_ctx: number;
  require_gpu: boolean;
  region: string | null;
  duration_hours: number;
}

export interface AiRun {
  id: string;
  status: AiRunStatus;
  request: string;
  limits: AutonomyLimits;
  plan: AiPlan | null;
  model_name: string | null;
  deployment_id: string | null;
  deployment_ids: string[];
  deployment_status: string | null;
  runtime: Runtime | null;
  endpoint: string | null;
  openai_base_url: string | null;
  explanation: string | null;
  error_code: string | null;
  error_message: string | null;
  currency: string | null;
  estimated_hourly: string | null;
  estimated_total: string | null;
  actual_cost: string;
  recovery_attempts: number;
  agent_steps: number;
  tool_calls: number;
  waiting_for_ai: boolean;
  cancel_requested: boolean;
  stop_reason: string | null;
  deadline_at: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface AiRunEvent {
  kind: 'state' | 'tool' | 'ai' | 'info' | 'error';
  from_status: string | null;
  to_status: string | null;
  message: string | null;
  data: Record<string, unknown> | null;
  created_at: string;
}

export type AiServiceStatus = 'available' | 'degraded' | 'unavailable' | 'not_configured';

export interface AiHealth {
  status: AiServiceStatus;
  available: boolean;
  model: string;
  queue_depth: number;
  message: string;
}
