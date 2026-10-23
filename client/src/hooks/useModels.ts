import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import api from '../lib/api';
import type { CommunityModelPreview, Model } from '../types';

export const useModels = () =>
  useQuery({
    queryKey: ['models'],
    queryFn: async () => (await api.get<Model[]>('/models')).data,
  });

/** A catalog model, or one of the caller's own imported community models (which the public route hides). */
export const useModel = (id: string | null) =>
  useQuery({
    queryKey: ['models', id],
    queryFn: async () => {
      try {
        return (await api.get<Model>(`/models/${id}`)).data;
      } catch (e) {
        if (!isAxiosError(e) || e.response?.status !== 404) throw e;
        return (await api.get<Model>(`/models/community/${id}`)).data;
      }
    },
    enabled: !!id,
    retry: false,
  });

/** Models the signed-in customer imported from Hugging Face. */
export const useCommunityModels = (enabled = true) =>
  useQuery({
    queryKey: ['models', 'community'],
    queryFn: async () => (await api.get<Model[]>('/models/community')).data,
    enabled,
  });

export const usePreviewCommunityModel = () =>
  useMutation({
    mutationFn: async ({ repo, revision }: { repo: string; revision?: string }) =>
      (await api.get<CommunityModelPreview>('/models/community/preview', { params: { repo, revision: revision || undefined } }))
        .data,
  });

export const useImportCommunityModel = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { repo: string; file: string; revision: string; accept_terms: boolean }) =>
      (await api.post<Model>('/models/community', body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['models', 'community'] }),
  });
};

export const useWithdrawCommunityModel = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/models/community/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['models', 'community'] }),
  });
};
