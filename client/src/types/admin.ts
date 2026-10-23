import type { Deployment } from './deployment';
import type { Node } from './node';
import type { UsageTotals } from './usage';

export interface AdminNode extends Node {
  owner_email: string | null;
}

export interface AdminDeployment extends Deployment {
  customer_email: string | null;
}

export interface OperatorOverview {
  nodes_by_status: Record<string, number>;
  nodes_paused: number;
  nodes_heartbeat_overdue: number;
  deployments_by_status: Record<string, number>;
  deployments_by_runtime: Record<string, number>;
  models: { total: number; approved: number; deployable: number };
  users_by_role: Record<string, number>;
  usage_24h: UsageTotals;
  ledger: { type: string; status: string; count: number; amount: string }[];
  generated_at: string;
}

export interface AuditLog {
  id: string;
  user_id: string | null;
  action: string | null;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string | null;
}
