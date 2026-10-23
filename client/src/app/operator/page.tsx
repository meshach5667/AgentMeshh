'use client';

import { Activity, Box, MessageSquare, Server } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatCard } from '@/components/common/StatCard';
import { StatusBadge } from '@/components/common/StatusBadge';
import { ErrorState, Notice, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useOperatorOverview } from '@/hooks/useAdmin';
import { errorMessage } from '@/lib/errors';
import { count, dateTime, money, runtimeLabel } from '@/lib/format';

const sum = (o: Record<string, number>, keys?: string[]) =>
  Object.entries(o).reduce((t, [k, v]) => (!keys || keys.includes(k) ? t + v : t), 0);

export default function OperatorOverview() {
  const { data, isLoading, error, refetch } = useOperatorOverview();
  if (isLoading) return <PageSkeleton />;
  if (error || !data) return <ErrorState message={errorMessage(error)} retry={() => refetch()} />;

  const online = sum(data.nodes_by_status, ['ONLINE', 'AVAILABLE', 'BUSY']);
  const u = data.usage_24h;

  return (
    <div className="space-y-6">
      <PageHeader title="Network overview" description={`Live from the database · ${dateTime(data.generated_at)}`} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Nodes online" value={`${online} / ${sum(data.nodes_by_status)}`} hint={`${data.nodes_paused} paused`} icon={Server} />
        <StatCard
          title="Deployments ready"
          value={data.deployments_by_status.READY ?? 0}
          hint={Object.entries(data.deployments_by_runtime).map(([r, n]) => `${runtimeLabel(r)} ${n}`).join(' · ') || undefined}
          icon={Activity}
        />
        <StatCard
          title="Requests (24 h)"
          value={count(u.requests)}
          hint={`${count(u.failed)} failed · ${count(u.output_tokens)} output tokens`}
          icon={MessageSquare}
        />
        <StatCard title="Deployable models" value={data.models.deployable} hint={`${data.models.approved} approved of ${data.models.total}`} icon={Box} />
      </div>

      {data.nodes_heartbeat_overdue > 0 && (
        <Notice tone="warning" title="Heartbeats overdue">
          {data.nodes_heartbeat_overdue} node(s) are marked online but have not reported within the heartbeat timeout. The
          health monitor will mark them offline and move their deployments; if this persists, check that the monitor is
          running (it needs the leader lock when several replicas run).
        </Notice>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <BreakdownCard title="Nodes by status" data={data.nodes_by_status} badges />
        <BreakdownCard title="Deployments by status" data={data.deployments_by_status} badges />
        <BreakdownCard title="Users by role" data={data.users_by_role} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Ledger totals</CardTitle>
        </CardHeader>
        <CardContent>
          {data.ledger.length === 0 ? (
            <p className="text-sm text-muted-foreground">No ledger entries.</p>
          ) : (
            <ul className="divide-y divide-border text-sm">
              {data.ledger.map((l) => (
                <li key={`${l.type}-${l.status}`} className="flex items-center justify-between py-2">
                  <span className="flex items-center gap-2">
                    {l.type} <StatusBadge status={l.status} />
                  </span>
                  <span className="tabular-nums">
                    {l.count} · {money(l.amount)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-muted-foreground">
            Deposits are Paystack top-ups, or unpaid test credits in development. See Reconciliation for consistency checks.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function BreakdownCard({ title, data, badges }: { title: string; data: Record<string, number>; badges?: boolean }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">None.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {entries.map(([k, n]) => (
              <li key={k} className="flex items-center justify-between">
                {badges ? <StatusBadge status={k} /> : <span className="capitalize">{k}</span>}
                <span className="tabular-nums">{n}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
