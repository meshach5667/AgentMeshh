import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../lib/api';
import type { Wallet } from '../types';

export const useWallet = () =>
  useQuery({
    queryKey: ['wallet'],
    queryFn: async () => (await api.get<Wallet>('/wallets')).data,
  });

/** Unpaid test credits. The server allows this only in dev/test environments (no payment provider yet). */
export const useAddTestCredits = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (amount: number) => (await api.post('/wallets/deposit', { amount })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['wallet'] });
      qc.invalidateQueries({ queryKey: ['transactions'] });
    },
  });
};
