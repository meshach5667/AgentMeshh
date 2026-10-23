import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../lib/api';
import type { ApiKey, CreatedApiKey } from '../types';

export const useApiKeys = () =>
  useQuery({
    queryKey: ['api-keys'],
    queryFn: async () => (await api.get<ApiKey[]>('/api-keys')).data,
  });

export const useCreateApiKey = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { name: string; deployment_id?: string; expires_at?: string }) =>
      (await api.post<CreatedApiKey>('/api-keys', payload)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  });
};

export const useRevokeApiKey = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => (await api.delete<ApiKey>(`/api-keys/${id}`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  });
};
