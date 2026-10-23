import { useQuery } from '@tanstack/react-query';
import api from '../lib/api';
import type { EarningsSummary, Transaction } from '../types';

export const useEarnings = () =>
  useQuery({
    queryKey: ['earnings'],
    queryFn: async () => (await api.get<EarningsSummary>('/earnings')).data,
  });

/** Provider credits (settled and pending) to the caller's wallet. */
export const useEarningsHistory = () =>
  useQuery({
    queryKey: ['earnings', 'history'],
    queryFn: async () => (await api.get<Transaction[]>('/earnings/history')).data,
  });
