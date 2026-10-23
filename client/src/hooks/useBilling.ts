import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../lib/api';
import type { Bank, Charge, Payment, PaymentsConfig, Payout, PayoutAccount, Pricing, PricingRule, ReconciliationReport } from '../types';

export const usePricing = () =>
  useQuery({ queryKey: ['billing', 'pricing'], queryFn: async () => (await api.get<Pricing>('/billing/pricing')).data });

export const useCharges = (deploymentId?: string) =>
  useQuery({
    queryKey: ['billing', 'charges', deploymentId ?? 'all'],
    queryFn: async () =>
      (await api.get<Charge[]>('/billing/charges', { params: { deployment_id: deploymentId, limit: 200 } })).data,
    refetchInterval: 30000,
  });

export const usePaymentsConfig = () =>
  useQuery({ queryKey: ['payments', 'config'], queryFn: async () => (await api.get<PaymentsConfig>('/payments/config')).data });

export const useTopups = () =>
  useQuery({ queryKey: ['payments', 'topups'], queryFn: async () => (await api.get<Payment[]>('/payments/topups')).data });

function useInvalidateMoney() {
  const qc = useQueryClient();
  return () => {
    for (const key of [['wallet'], ['transactions'], ['payments'], ['earnings'], ['billing'], ['admin']]) qc.invalidateQueries({ queryKey: key });
  };
}

export const useCreateTopup = () =>
  useMutation({ mutationFn: async (amount: string) => (await api.post<Payment>('/payments/topups', { amount })).data });

export const useVerifyTopup = () => {
  const invalidate = useInvalidateMoney();
  return useMutation({
    mutationFn: async (reference: string) =>
      (await api.post<Payment>(`/payments/topups/${encodeURIComponent(reference)}/verify`)).data,
    onSuccess: invalidate,
  });
};

export const useBanks = (enabled: boolean) =>
  useQuery({
    queryKey: ['payments', 'banks'],
    queryFn: async () => (await api.get<Bank[]>('/payments/banks')).data,
    enabled,
    staleTime: 3600_000,
  });

export const usePayoutAccount = () =>
  useQuery({
    queryKey: ['payments', 'payout-account'],
    queryFn: async () => (await api.get<PayoutAccount | null>('/payments/payout-account')).data,
  });

export const useSetPayoutAccount = () => {
  const invalidate = useInvalidateMoney();
  return useMutation({
    mutationFn: async (body: { account_number: string; bank_code: string }) =>
      (await api.put<PayoutAccount>('/payments/payout-account', body)).data,
    onSuccess: invalidate,
  });
};

export const usePayouts = () =>
  useQuery({
    queryKey: ['payments', 'payouts'],
    queryFn: async () => (await api.get<Payout[]>('/payments/payouts')).data,
    refetchInterval: 15000,
  });

export const useRequestPayout = () => {
  const invalidate = useInvalidateMoney();
  return useMutation({
    mutationFn: async (amount: string) => (await api.post<Payout>('/payments/payouts', { amount })).data,
    onSuccess: invalidate,
  });
};

// --- operator ---

export const usePricingVersions = () =>
  useQuery({ queryKey: ['admin', 'pricing'], queryFn: async () => (await api.get<PricingRule[]>('/admin/pricing')).data });

export type PricingInput = Pick<
  PricingRule,
  'cpu_core_hour' | 'ram_gb_hour' | 'vram_gb_hour' | 'input_tokens_per_million' | 'output_tokens_per_million' | 'platform_fee_rate'
> & { notes?: string; effective_from?: string };

export const useCreatePricing = () => {
  const invalidate = useInvalidateMoney();
  return useMutation({
    mutationFn: async (body: PricingInput) => (await api.post<PricingRule>('/admin/pricing', body)).data,
    onSuccess: invalidate,
  });
};

export const useAdminPayouts = (status?: string) =>
  useQuery({
    queryKey: ['admin', 'payouts', status ?? ''],
    queryFn: async () => (await api.get<Payout[]>('/admin/payouts', { params: { status: status || undefined } })).data,
    refetchInterval: 15000,
  });

export const useDecidePayout = () => {
  const invalidate = useInvalidateMoney();
  return useMutation({
    mutationFn: async ({ id, approve, reason }: { id: string; approve: boolean; reason?: string }) =>
      approve
        ? (await api.post<Payout>(`/admin/payouts/${id}/approve`)).data
        : (await api.post<Payout>(`/admin/payouts/${id}/reject`, { reason: reason || null })).data,
    onSuccess: invalidate,
  });
};

export const useReconciliation = () =>
  useQuery({
    queryKey: ['admin', 'reconciliation'],
    queryFn: async () => (await api.get<ReconciliationReport>('/admin/reconciliation')).data,
  });

export const useRunReconciliation = () => {
  const invalidate = useInvalidateMoney();
  return useMutation({
    mutationFn: async () => (await api.post<Record<string, unknown>>('/admin/reconciliation/run')).data,
    onSuccess: invalidate,
  });
};
