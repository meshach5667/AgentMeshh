'use client';

import { useState } from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ConfirmButton } from '@/components/common/ConfirmButton';
import { StatusBadge } from '@/components/common/StatusBadge';
import { EmptyState, ErrorState, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useDeleteDeployment, useDeployments, useStopDeployment } from '@/hooks/useDeployments';
import { useCommunityModels, useModels } from '@/hooks/useModels';
import { errorMessage } from '@/lib/errors';
import { ago, runtimeLabel, shortId } from '@/lib/format';
import { TERMINAL_STATUSES } from '@/types';

export default function DeploymentsPage() {
  const { data, isLoading, error, refetch, isFetching } = useDeployments();
  const models = useModels();
  const community = useCommunityModels();
  const stop = useStopDeployment();
  const remove = useDeleteDeployment();
  const [showEnded, setShowEnded] = useState(false);

  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorState message={errorMessage(error)} retry={() => refetch()} />;

  const all = data ?? [];
  const rows = showEnded ? all : all.filter((d) => !TERMINAL_STATUSES.includes(d.status));
  const modelName = (id: string) => [...(models.data ?? []), ...(community.data ?? [])].find((m) => m.id === id)?.name;
  const act = (p: Promise<unknown>, ok: string) => p.then(() => toast.success(ok)).catch((e) => toast.error(errorMessage(e)));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Deployments"
        description="Each deployment is one model running on one provider node, with its own endpoint."
        actions={
          <>
            <Button variant="outline" size="icon" aria-label="Refresh" onClick={() => refetch()}>
              <RefreshCw className={isFetching ? 'animate-spin' : ''} />
            </Button>
            <Link href="/customer/models" className={buttonVariants()}>
              New deployment
            </Link>
          </>
        }
      />
      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input type="checkbox" checked={showEnded} onChange={(e) => setShowEnded(e.target.checked)} />
        Show stopped, failed and cancelled ({all.length - all.filter((d) => !TERMINAL_STATUSES.includes(d.status)).length})
      </label>
      <Card>
        <CardContent className="pt-6">
          {rows.length === 0 ? (
            <EmptyState action={{ href: '/customer/models', label: 'Deploy a model' }}>No deployments to show.</EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead>Runtime</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Node</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((d) => {
                  const ended = TERMINAL_STATUSES.includes(d.status);
                  return (
                    <TableRow key={d.id} data-testid="deployment-row">
                      <TableCell>
                        <Link href={`/customer/deployments/${d.id}`} className="font-medium hover:underline">
                          {modelName(d.model_id) ?? d.model_tag ?? shortId(d.id)}
                        </Link>
                        <div className="font-mono text-xs text-muted-foreground">{shortId(d.id)}</div>
                      </TableCell>
                      <TableCell>{runtimeLabel(d.runtime)}</TableCell>
                      <TableCell>
                        <StatusBadge status={d.status} />
                        {d.error_code && <div className="mt-1 text-xs text-rose-500">{d.error_code}</div>}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{shortId(d.node_id)}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{ago(d.created_at)}</TableCell>
                      <TableCell className="text-right">
                        {ended ? (
                          <ConfirmButton size="sm" variant="ghost" confirmLabel="Delete" onConfirm={() => act(remove.mutateAsync(d.id), 'Deployment deleted')}>
                            Delete
                          </ConfirmButton>
                        ) : (
                          d.status !== 'STOPPING' && (
                            <ConfirmButton size="sm" variant="ghost" confirmLabel="Stop" onConfirm={() => act(stop.mutateAsync(d.id), 'Stop requested')}>
                              Stop
                            </ConfirmButton>
                          )
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
