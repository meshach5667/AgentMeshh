// Decimal amounts are serialized as strings by the API.
export type TransactionType = 'DEPOSIT' | 'COMPUTE_CHARGE' | 'PROVIDER_CREDIT' | 'PLATFORM_FEE' | 'REFUND' | 'PAYOUT';
export type TransactionStatus = 'PENDING' | 'AUTHORIZED' | 'SETTLED' | 'REFUNDED' | 'FAILED';

export interface Wallet {
  id: string;
  user_id: string;
  balance: string;
  currency: string;
}

export interface Transaction {
  id: string;
  from_wallet: string | null;
  to_wallet: string | null;
  amount: string;
  type: TransactionType;
  status: TransactionStatus;
  deployment_id: string | null;
  reference: string | null;
  description: string | null;
  created_at: string;
}

export interface EarningsSummary {
  total_earnings: string;
  pending_earnings: string;
  available_balance: string;
  total_deployments: number;
  active_deployments: number;
}
