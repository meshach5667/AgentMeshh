import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../lib/api';
import { AI_TERMINAL_STATUSES, type AiHealth, type AiRun, type AiRunEvent, type AutonomyLimits } from '../types';

const active = (r?: AiRun) => !!r && !AI_TERMINAL_STATUSES.includes(r.status);

export const useAiHealth = () =>
  useQuery({
    queryKey: ['ai', 'health'],
    queryFn: async () => (await api.get<AiHealth>('/ai/health')).data,
    refetchInterval: 15000,
  });

export const useAiRuns = () =>
  useQuery({
    queryKey: ['ai', 'runs'],
    queryFn: async () => (await api.get<AiRun[]>('/ai/deployments')).data,
    refetchInterval: (q) => (q.state.data?.some(active) ? 4000 : 20000),
  });

export const useAiRun = (id: string) =>
  useQuery({
    queryKey: ['ai', 'runs', id],
    queryFn: async () => (await api.get<AiRun>(`/ai/deployments/${id}`)).data,
    enabled: !!id,
    refetchInterval: (q) => (active(q.state.data) ? 3000 : 15000),
  });

export const useAiRunEvents = (id: string, live: boolean) =>
  useQuery({
    queryKey: ['ai', 'runs', id, 'events'],
    queryFn: async () => (await api.get<AiRunEvent[]>(`/ai/deployments/${id}/events`)).data,
    enabled: !!id,
    refetchInterval: live ? 3000 : 15000,
  });

export interface CreateAiRunInput {
  request: string;
  limits: AutonomyLimits;
  idempotency_key: string;
}

export const useCreateAiRun = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CreateAiRunInput) => (await api.post<AiRun>('/ai/deployments', payload)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ai', 'runs'] }),
  });
};

export const useCancelAiRun = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => (await api.post<AiRun>(`/ai/deployments/${id}/cancel`)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ai', 'runs'] });
      qc.invalidateQueries({ queryKey: ['deployments'] });
    },
  });
};
