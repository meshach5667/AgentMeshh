import { useQuery } from '@tanstack/react-query';
import api from '../lib/api';
import type { Transaction } from '../types';

export const useTransactions = () =>
  useQuery({
    queryKey: ['transactions'],
    queryFn: async () => (await api.get<Transaction[]>('/transactions')).data,
  });
