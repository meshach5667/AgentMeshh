'use client';

import { useParams } from 'next/navigation';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ConfirmButton } from '@/components/common/ConfirmButton';
import { Pill, StatusBadge } from '@/components/common/StatusBadge';
import { ErrorState, Notice, PageHeader } from '@/components/common/Notices';
import { CapacityBars } from '@/components/nodes/CapacityBars';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useNode, useRevokeNode, useSetAccepting, useSetAcceptsCommunity } from '@/hooks/useNodes';
import { errorMessage } from '@/lib/errors';
import { ago, dateTime, runtimeLabel } from '@/lib/format';
import { nodeAvailability } from '@/lib/nodes';

export default function NodeDetailPage() {
  const id = useParams<{ id: string }>().id;
  const { data: node, isLoading, error, refetch } = useNode(id);
  const setAccepting = useSetAccepting();
  const setCommunity = useSetAcceptsCommunity();
  const revoke = useRevokeNode();

  if (isLoading) return <PageSkeleton />;
  if (error || !node) return <ErrorState message={errorMessage(error, 'Node not found')} retry={() => refetch()} />;

  const availability = nodeAvailability(node);
  const revoked = node.status === 'REVOKED';
  const metrics = node.last_metrics ?? {};
  const act = (p: Promise<unknown>, ok: string) => p.then(() => toast.success(ok)).catch((e) => toast.error(errorMessage(e)));

  return (
    <div className="space-y-6">
      <PageHeader
        title={node.name ?? 'Node'}
        description={`Node ${node.id}`}
        actions={
          !revoked && (
            <>
              {node.accepting_workloads ? (
                <Button
                  variant="outline"
                  disabled={setAccepting.isPending}
                  onClick={() => act(setAccepting.mutateAsync({ id: node.id, accepting: false }), 'Node paused')}
                >
                  Pause new work
                </Button>
              ) : (
                <Button
                  disabled={setAccepting.isPending}
                  onClick={() => act(setAccepting.mutateAsync({ id: node.id, accepting: true }), 'Node resumed')}
                >
                  Resume
                </Button>
              )}
              <ConfirmButton
                confirmLabel="Revoke: stops its deployments"
                onConfirm={() => act(revoke.mutateAsync(node.id), 'Node revoked')}
              >
                Revoke
              </ConfirmButton>
            </>
          )
        }
      />

      <Notice tone={availability.tone === 'green' ? 'info' : availability.tone === 'amber' ? 'warning' : 'danger'} title={availability.label}>
        {availability.detail}
      </Notice>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Worker</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
              <dt className="text-muted-foreground">Status</dt>
              <dd>
                <StatusBadge status={node.status} />
              </dd>
              <dt className="text-muted-foreground">Type</dt>
              <dd>{node.mode === 'agent' ? 'Installable agent' : node.mode === 'docker' ? 'Docker worker' : (node.mode ?? '—')}</dd>
              <dt className="text-muted-foreground">Version</dt>
              <dd className="font-mono text-xs">
                {node.worker_version ?? '—'} (protocol {node.protocol_version ?? '—'})
              </dd>
              <dt className="text-muted-foreground">Region</dt>
              <dd>{node.region ?? 'not set'}</dd>
              <dt className="text-muted-foreground">Last heartbeat</dt>
              <dd>{ago(node.last_heartbeat)}</dd>
              <dt className="text-muted-foreground">Enrolled</dt>
              <dd>{dateTime(node.created_at)}</dd>
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Capacity</CardTitle>
            <CardDescription>Reserved by deployments, out of the limits you set when installing the worker.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <CapacityBars node={node} />
            {Object.keys(metrics).length > 0 && (
              <p className="text-xs text-muted-foreground">
                Whole machine, last reported:
                {metrics.cpu_percent != null && ` CPU ${Math.round(metrics.cpu_percent)}%`}
                {metrics.ram_percent != null && ` · memory ${Math.round(metrics.ram_percent)}%`}
                {metrics.gpu_utilization != null && ` · GPU ${Math.round(metrics.gpu_utilization)}%`}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Runtimes</CardTitle>
          <CardDescription>Reported by the worker at each heartbeat.</CardDescription>
        </CardHeader>
        <CardContent>
          {(node.runtimes ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No runtimes reported.</p>
          ) : (
            <ul className="divide-y divide-border">
              {(node.runtimes ?? []).map((r) => (
                <li key={`${r.name}-${r.backend}`} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span>
                    <span className="font-medium">{runtimeLabel(r.name)}</span>{' '}
                    <span className="text-muted-foreground">
                      {r.version ? `v${r.version}` : ''} {r.backend ? `· ${r.backend}` : ''}
                    </span>
                    {r.detail && <span className="block text-xs text-muted-foreground">{r.detail}</span>}
                  </span>
                  <span className="flex gap-1">
                    {r.gpu && <Pill tone="blue">GPU</Pill>}
                    {r.limits_enforced === false && <Pill tone="amber">limits advisory</Pill>}
                    <Pill tone={r.available ? 'green' : 'gray'}>{r.available ? 'available' : 'unavailable'}</Pill>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {!revoked && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Community models <Pill tone={node.accepts_community_models ? 'amber' : 'gray'}>{node.accepts_community_models ? 'accepted' : 'off'}</Pill>
            </CardTitle>
            <CardDescription>
              Customers can import public GGUF models from Hugging Face for their own use. No operator reviews them.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              <li>They run only with llama.cpp, from a file pinned to a Hugging Face commit and checked against its SHA-256 before loading.</li>
              <li>Gated, private, and non-commercially licensed models are refused. Pickle and other code-carrying formats are never accepted.</li>
              <li>The model&apos;s output is not reviewed. Turning this on means your machine may serve models AgentMesh has not vetted.</li>
              <li>Turning it off stops new placements. Community deployments already running keep running until they stop or move.</li>
            </ul>
            {node.accepts_community_models ? (
              <Button
                variant="outline"
                disabled={setCommunity.isPending}
                onClick={() => act(setCommunity.mutateAsync({ id: node.id, accept: false }), 'Community models turned off')}
              >
                Stop accepting community models
              </Button>
            ) : (
              <ConfirmButton
                variant="outline"
                disabled={setCommunity.isPending}
                confirmLabel="Yes, accept unreviewed models"
                onConfirm={() => act(setCommunity.mutateAsync({ id: node.id, accept: true }), 'Community models accepted')}
              >
                Accept community models
              </ConfirmButton>
            )}
          </CardContent>
        </Card>
      )}

      <p className="text-xs text-muted-foreground">
        &quot;Pause new work&quot; stops AgentMesh from placing new deployments here; running ones keep serving. To stop
        running deployments too, run <code className="font-mono">agentmesh-worker drain</code> on the machine.
        &quot;Revoke&quot; disables the node&apos;s credential and stops its deployments immediately; AgentMesh moves them to
        other nodes when it can.
      </p>
    </div>
  );
}
