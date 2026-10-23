'use client';

import Link from 'next/link';
import { Activity, MessageSquare, Server, Wallet } from 'lucide-react';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatCard } from '@/components/common/StatCard';
import { EmptyState, ErrorState, Notice, PageHeader } from '@/components/common/Notices';
import { NodeTable } from '@/components/nodes/NodeTable';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useEarnings } from '@/hooks/useEarnings';
import { useNodes } from '@/hooks/useNodes';
import { useUsageSummary } from '@/hooks/useUsage';
import { errorMessage } from '@/lib/errors';
import { count, money } from '@/lib/format';
import { nodeAvailability } from '@/lib/nodes';

export default function ProviderOverview() {
  const nodes = useNodes();
  const earnings = useEarnings();
  const usage = useUsageSummary(7);

  if (nodes.isLoading) return <PageSkeleton />;
  if (nodes.error) return <ErrorState message={errorMessage(nodes.error)} retry={() => nodes.refetch()} />;

  const list = (nodes.data ?? []).filter((n) => n.status !== 'REVOKED');
  const accepting = list.filter((n) => nodeAvailability(n).tone === 'green').length;
  const attention = list.filter((n) => nodeAvailability(n).tone === 'red');

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        description="Your machines on AgentMesh and the work they serve."
        actions={
          <Link href="/provider/nodes/register" className={buttonVariants()}>
            Add a machine
          </Link>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Nodes accepting work" value={`${accepting} / ${list.length}`} icon={Server} />
        <StatCard
          title="Deployments hosted now"
          value={earnings.data?.active_deployments ?? '—'}
          hint={earnings.data ? `${earnings.data.total_deployments} hosted in total` : undefined}
          icon={Activity}
        />
        <StatCard
          title="Requests served (7 days)"
          value={usage.data ? count(usage.data.totals.requests) : '—'}
          hint={usage.data ? `${count(usage.data.totals.output_tokens)} output tokens` : undefined}
          icon={MessageSquare}
        />
        <StatCard
          title="Earnings"
          value={earnings.data ? money(earnings.data.total_earnings) : '—'}
          hint="Settled provider credits"
          icon={Wallet}
        />
      </div>
      {attention.length > 0 && (
        <Notice tone="warning" title={`${attention.length} node${attention.length === 1 ? ' needs' : 's need'} attention`}>
          {attention.map((n) => `${n.name ?? n.id.slice(0, 8)}: ${nodeAvailability(n).detail}`).join(' ')}
        </Notice>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Nodes</CardTitle>
        </CardHeader>
        <CardContent>
          {list.length === 0 ? (
            <EmptyState action={{ href: '/provider/nodes/register', label: 'Enroll your first machine' }}>
              You have no nodes yet.
            </EmptyState>
          ) : (
            <NodeTable nodes={list} href={(n) => `/provider/nodes/${n.id}`} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
