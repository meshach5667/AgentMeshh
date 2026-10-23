import type { AiRunStatus, AiServiceStatus, AutonomyLimits } from '@/types';

// Platform ceilings, mirroring server settings AI_MAX_DEPLOYMENT_HOURS and AI_MAX_RECOVERY_ATTEMPTS.
export const MAX_DURATION_HOURS = 168;
export const MAX_RECOVERY_ATTEMPTS = 3;
export const MIN_REQUEST_CHARS = 5;
export const MAX_REQUEST_CHARS = 2000;

export const DEFAULT_LIMITS: AutonomyLimits = {
  max_spend: '1000',
  max_duration_hours: 2,
  max_cpu_cores: 4,
  max_ram_mb: 8192,
  max_vram_mb: 0,
  max_recovery_attempts: 1,
  allowed_runtimes: ['ollama', 'llamacpp', 'vllm'],
  allowed_sources: ['ollama', 'huggingface'],
};

/** Problems with a request before it is sent; the server enforces the same rules. */
export function validateAiRequest(text: string, limits: AutonomyLimits): string[] {
  const problems: string[] = [];
  const t = text.trim();
  if (t.length < MIN_REQUEST_CHARS) problems.push('Describe what you want to deploy.');
  if (t.length > MAX_REQUEST_CHARS) problems.push(`Keep the description under ${MAX_REQUEST_CHARS} characters.`);
  const spend = Number(limits.max_spend);
  if (!Number.isFinite(spend) || spend <= 0) problems.push('Maximum spend must be more than zero.');
  if (!(limits.max_duration_hours > 0) || limits.max_duration_hours > MAX_DURATION_HOURS)
    problems.push(`Maximum duration must be between 0 and ${MAX_DURATION_HOURS} hours.`);
  if (!Number.isInteger(limits.max_cpu_cores) || limits.max_cpu_cores < 1) problems.push('Allow at least 1 CPU core.');
  if (!Number.isInteger(limits.max_ram_mb) || limits.max_ram_mb < 512) problems.push('Allow at least 512 MB of memory.');
  if (!Number.isInteger(limits.max_vram_mb) || limits.max_vram_mb < 0) problems.push('GPU memory cannot be negative.');
  if (
    !Number.isInteger(limits.max_recovery_attempts) ||
    limits.max_recovery_attempts < 0 ||
    limits.max_recovery_attempts > MAX_RECOVERY_ATTEMPTS
  )
    problems.push(`Recovery attempts must be between 0 and ${MAX_RECOVERY_ATTEMPTS}.`);
  if (limits.allowed_runtimes.length === 0) problems.push('Allow at least one runtime.');
  if (limits.allowed_sources.length === 0) problems.push('Allow at least one model source.');
  return problems;
}

export const AI_STATUS_HELP: Record<AiRunStatus, string> = {
  PLANNING: 'The AI agent is choosing a model and a deployment plan from the approved catalog.',
  SUBMITTING: 'AgentMesh accepted the plan and is reserving capacity on a provider node.',
  DEPLOYING: 'A provider node is downloading and starting the model.',
  VERIFYING: 'The model reports ready. AgentMesh is sending it a real test request before publishing the endpoint.',
  READY: 'Verified with a real test request. The endpoint is live and is stopped automatically at your limits.',
  RECOVERING: 'The deployment failed. The AI agent is diagnosing it and may retry within your recovery limit.',
  STOPPING: 'Stopping the deployment and releasing its resources.',
  COMPLETED: 'Finished. The deployment was stopped (limit reached or stopped elsewhere).',
  FAILED: 'Failed. See the reason below. Nothing keeps running.',
  CANCELLED: 'Cancelled. Nothing keeps running.',
};

export const AI_SERVICE_TEXT: Record<AiServiceStatus, string> = {
  available: 'AI agent online',
  degraded: 'AI agent busy',
  unavailable: 'AI agent offline',
  not_configured: 'AI agent not configured',
};

export const STOP_REASON_TEXT: Record<string, string> = {
  cancelled: 'You cancelled it',
  max_duration: 'Reached the maximum duration',
  max_spend: 'Reached the maximum spend',
  verification_failed: 'Failed verification',
};
