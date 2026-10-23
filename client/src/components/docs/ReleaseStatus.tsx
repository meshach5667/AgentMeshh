'use client';

import { Notice } from '@/components/common/Notices';
import { useWorkerRelease } from '@/hooks/useWorkerRelease';
import { RELEASES_URL, WORKER_VERSION } from '@/lib/config';
import { workerReleaseUrl } from '@/lib/worker';

export function ReleaseStatus() {
  const { data, isPending } = useWorkerRelease();
  if (isPending) return <Notice title={`Checking for the worker ${WORKER_VERSION} release…`}>Looking it up on GitHub.</Notice>;
  if (data === 'published') {
    return (
      <Notice title={`Worker ${WORKER_VERSION} is published`}>
        Assets are on the{' '}
        <a href={workerReleaseUrl()} className="underline underline-offset-4" target="_blank" rel="noreferrer">
          worker {WORKER_VERSION} release page
        </a>
        .
      </Notice>
    );
  }
  return (
    <Notice tone="warning" title={data === 'unpublished' ? `Worker ${WORKER_VERSION} has not been published yet` : 'Could not check the release'}>
      {data === 'unpublished' ? 'The download URLs below will work once the release appears on ' : 'Check '}
      <a href={RELEASES_URL} className="underline underline-offset-4" target="_blank" rel="noreferrer">
        GitHub Releases
      </a>
      {data === 'unpublished' ? '. Until then, install from source.' : ' before using the download commands.'}
    </Notice>
  );
}
