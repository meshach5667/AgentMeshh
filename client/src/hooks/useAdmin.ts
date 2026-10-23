import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../lib/api';
import type { AdminDeployment, AdminNode, AuditLog, Model, ModelArtifact, OperatorOverview, Transaction } from '../types';

export const useOperatorOverview = () =>
  useQuery({
    queryKey: ['admin', 'overview'],
    queryFn: async () => (await api.get<OperatorOverview>('/admin/overview')).data,
    refetchInterval: 15000,
  });

export const useAdminNodes = (status?: string) =>
  useQuery({
    queryKey: ['admin', 'nodes', status ?? ''],
    queryFn: async () => (await api.get<AdminNode[]>('/admin/nodes', { params: { status: status || undefined } })).data,
    refetchInterval: 15000,
  });

export const useAdminDeployments = (status?: string) =>
  useQuery({
    queryKey: ['admin', 'deployments', status ?? ''],
    queryFn: async () =>
      (await api.get<AdminDeployment[]>('/admin/deployments', { params: { status: status || undefined } })).data,
    refetchInterval: 15000,
  });

export const useAdminModels = () =>
  useQuery({
    queryKey: ['admin', 'models'],
    queryFn: async () => (await api.get<Model[]>('/admin/models')).data,
  });

export const useLedger = () =>
  useQuery({
    queryKey: ['admin', 'transactions'],
    queryFn: async () => (await api.get<Transaction[]>('/admin/transactions')).data,
  });

export const useAuditLogs = (filters: { action?: string; resource_type?: string; resource_id?: string }) =>
  useQuery({
    queryKey: ['admin', 'audit', filters],
    queryFn: async () =>
      (
        await api.get<AuditLog[]>('/admin/audit-logs', {
          params: Object.fromEntries(Object.entries(filters).filter(([, v]) => v)),
        })
      ).data,
  });

export const useSetModelApproval = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, approved }: { id: string; approved: boolean }) =>
      (await api.post<Model>(`/models/${id}/approval`, null, { params: { approved } })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin'] });
      qc.invalidateQueries({ queryKey: ['models'] });
    },
  });
};

export const useSetArtifactEnabled = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ modelId, artifactId, enabled }: { modelId: string; artifactId: string; enabled: boolean }) =>
      (await api.patch<ModelArtifact>(`/models/${modelId}/artifacts/${artifactId}`, { is_enabled: enabled })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin'] });
      qc.invalidateQueries({ queryKey: ['models'] });
    },
  });
};
