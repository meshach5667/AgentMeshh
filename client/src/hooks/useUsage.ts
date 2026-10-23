import { useQuery } from '@tanstack/react-query';
import api from '../lib/api';
import type { PublicStats, UsageSummary } from '../types';

export const useUsageSummary = (days = 30, scope?: UsageSummary['scope']) =>
  useQuery({
    queryKey: ['usage', 'summary', days, scope ?? 'default'],
    queryFn: async () => (await api.get<UsageSummary>('/usage/summary', { params: { days, scope } })).data,
    refetchInterval: 30000,
  });

export const usePublicStats = () =>
  useQuery({
    queryKey: ['stats', 'public'],
    queryFn: async () => (await api.get<PublicStats>('/stats/public')).data,
    refetchInterval: 30000,
    retry: 1,
  });
