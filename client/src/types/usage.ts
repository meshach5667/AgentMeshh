// Mirrors server/app/services/reporting_service.py and schemas/usage.py.
export interface UsageTotals {
  requests: number;
  succeeded: number;
  failed: number;
  input_tokens: number;
  output_tokens: number;
  /** Requests where the runtime reported no token counts. Counts are never estimated. */
  requests_without_token_counts: number;
}

export interface UsageSummary {
  scope: 'customer' | 'provider' | 'network';
  days: number;
  since: string;
  totals: UsageTotals;
  by_day: (UsageTotals & { date: string })[];
  by_deployment: (UsageTotals & { deployment_id: string })[];
  token_source: string;
}

export interface UsageRecord {
  id: string;
  deployment_id: string | null;
  node_id: string | null;
  created_at: string;
  kind: string | null;
  request_id: string | null;
  endpoint: string | null;
  status_code: number | null;
  outcome: string | null;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  token_source: string | null;
}

export interface PublicStats {
  nodes_online: number;
  gpu_nodes_online: number;
  runtimes_online: string[];
  models_deployable: number;
  deployments_ready: number;
  features: {
    test_credits: boolean;
    payments: boolean;
    provider_payouts: boolean;
    confidential_computing: boolean;
  };
  generated_at: string;
}
