import { useQuery } from '@tanstack/react-query';
import { WORKER_VERSION } from '../lib/config';
import { workerTag } from '../lib/worker';

export type WorkerReleaseState = 'published' | 'unpublished' | 'unknown';

/** Asks GitHub whether the worker release this dashboard points at has been published. */
export const useWorkerRelease = (version = WORKER_VERSION) =>
  useQuery({
    queryKey: ['worker-release', version],
    queryFn: async (): Promise<WorkerReleaseState> => {
      const res = await fetch(`https://api.github.com/repos/meshach5667/AgentMeshh/releases/tags/${workerTag(version)}`, {
        headers: { Accept: 'application/vnd.github+json' },
      });
      if (res.ok) return 'published';
      if (res.status === 404) return 'unpublished';
      return 'unknown';
    },
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
