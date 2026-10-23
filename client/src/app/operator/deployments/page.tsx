'use client';

import { useState } from 'react';
import toast from 'react-hot-toast';
import { Card, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ConfirmButton } from '@/components/common/ConfirmButton';
import { StatusBadge } from '@/components/common/StatusBadge';
import { EmptyState, ErrorState, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useAdminDeployments } from '@/hooks/useAdmin';
import { useStopDeployment } from '@/hooks/useDeployments';
import { errorMessage } from '@/lib/errors';
import { ago, runtimeLabel, shortId } from '@/lib/format';
import { TERMINAL_STATUSES } from '@/types';

const STATUSES = ['', 'READY', 'SCHEDULED', 'PROVISIONING', 'STARTING', 'UNHEALTHY', 'STOPPING', 'FAILED', 'STOPPED', 'CANCELLED'];

export default function OperatorDeploymentsPage() {
  const [status, setStatus] = useState('');
  const { data, isLoading, error, refetch } = useAdminDeployments(status);
  const stop = useStopDeployment();

  return (
    <div className="space-y-6">
      <PageHeader
        title="All deployments"
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
              <EmptyState>No deployments.</EmptyState>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Deployment</TableHead>
                    <TableHead>Customer</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Node</TableHead>
                    <TableHead>Attempts</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data ?? []).map((d) => (
                    <TableRow key={d.id}>
                      <TableCell className="font-mono text-xs">{shortId(d.id)}</TableCell>
                      <TableCell className="text-xs">{d.customer_email ?? '—'}</TableCell>
                      <TableCell className="text-xs">
                        <span className="font-mono">{d.model_tag ?? '—'}</span>
                        <div className="text-muted-foreground">{runtimeLabel(d.runtime)}</div>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={d.status} />
                        {d.error_code && <div className="mt-1 text-xs text-rose-500" title={d.error_message ?? ''}>{d.error_code}</div>}
                      </TableCell>
                      <TableCell className="font-mono text-xs">{shortId(d.node_id)}</TableCell>
                      <TableCell className="text-xs tabular-nums">{d.schedule_attempts}</TableCell>
                      <TableCell className="text-xs">{ago(d.created_at)}</TableCell>
                      <TableCell className="text-right">
                        {!TERMINAL_STATUSES.includes(d.status) && d.status !== 'STOPPING' && (
                          <ConfirmButton
                            size="sm"
                            variant="ghost"
                            confirmLabel="Stop"
                            onConfirm={() =>
                              stop.mutateAsync(d.id).then(
                                () => toast.success('Stop requested'),
                                (e) => toast.error(errorMessage(e)),
                              )
                            }
                          >
                            Stop
                          </ConfirmButton>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
