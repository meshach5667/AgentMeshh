'use client';

import { useState } from 'react';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ConfirmButton } from '@/components/common/ConfirmButton';
import { EmptyState, ErrorState, PageHeader } from '@/components/common/Notices';
import { NodeTable } from '@/components/nodes/NodeTable';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useAdminNodes } from '@/hooks/useAdmin';
import { useRevokeNode, useSetAccepting } from '@/hooks/useNodes';
import { errorMessage } from '@/lib/errors';

const STATUSES = ['', 'ONLINE', 'OFFLINE', 'DEGRADED', 'REVOKED'];

export default function OperatorNodesPage() {
  const [status, setStatus] = useState('');
  const { data, isLoading, error, refetch } = useAdminNodes(status);
  const setAccepting = useSetAccepting();
  const revoke = useRevokeNode();
  const act = (p: Promise<unknown>, ok: string) => p.then(() => toast.success(ok)).catch((e) => toast.error(errorMessage(e)));

  return (
    <div className="space-y-6">
      <PageHeader
        title="All nodes"
        description="Every enrolled machine. Pausing stops new placements; revoking disables the credential and moves its deployments."
        actions={
          <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm">
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s || 'All statuses'}
              </option>
            ))}
          </select>
        }
      />
      {isLoading ? (
        <PageSkeleton />
      ) : error ? (
        <ErrorState message={errorMessage(error)} retry={() => refetch()} />
      ) : (
        <Card>
          <CardContent className="pt-6">
            {(data ?? []).length === 0 ? (
              <EmptyState>No nodes.</EmptyState>
            ) : (
              <NodeTable
                nodes={data ?? []}
                actions={(n) =>
                  n.status === 'REVOKED' ? null : (
                    <span className="inline-flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => act(setAccepting.mutateAsync({ id: n.id, accepting: !n.accepting_workloads }), n.accepting_workloads ? 'Paused' : 'Resumed')}>
                        {n.accepting_workloads ? 'Pause' : 'Resume'}
                      </Button>
                      <ConfirmButton size="sm" variant="ghost" confirmLabel="Revoke" onConfirm={() => act(revoke.mutateAsync(n.id), 'Node revoked')}>
                        Revoke
                      </ConfirmButton>
                    </span>
                  )
                }
              />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
