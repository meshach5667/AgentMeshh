// Mirrors server/app/schemas/node.py (NodeOut).
export type NodeStatus =
  | 'REGISTERING'
  | 'ONLINE'
  | 'AVAILABLE'
  | 'BUSY'
  | 'DEGRADED'
  | 'OFFLINE'
  | 'SUSPENDED'
  | 'REVOKED';

export interface NodeRuntime {
  name: string;
  version?: string;
  backend?: string;
  available?: boolean;
  gpu?: boolean;
  limits_enforced?: boolean;
  detail?: string;
}

export interface Node {
  id: string;
  owner_id: string;
  name: string | null;
  status: NodeStatus;
  region: string | null;
  reputation_score: number | null;
  last_heartbeat: string | null;
  created_at: string;
  mode: 'docker' | 'agent' | string | null;
  worker_version: string | null;
  protocol_version: number | null;
  runtimes: NodeRuntime[] | null;
  /** Set by the provider or operator in AgentMesh ("pause"). */
  accepting_workloads: boolean;
  /** Provider opt-in to unreviewed models customers imported from Hugging Face. Off by default. */
  accepts_community_models: boolean;
  /** Reported by the worker itself (local pause, drain, or availability schedule). */
  worker_available: boolean;
  worker_unavailable_reason: string | null;
  allocated_cpu_cores: number;
  allocated_ram_mb: number;
  allocated_disk_mb: number;
  allocated_vram_mb: number;
  reserved_cpu_cores: number;
  reserved_ram_mb: number;
  reserved_disk_mb: number;
  reserved_vram_mb: number;
  last_metrics: Record<string, number> | null;
}

export interface EnrollmentToken {
  token: string;
  expires_at: string;
}
