'use client';

import Link from 'next/link';
import { Activity, Box, KeyRound, MessageSquare } from 'lucide-react';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatCard } from '@/components/common/StatCard';
import { StatusBadge } from '@/components/common/StatusBadge';
import { EmptyState, ErrorState, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useDeployments } from '@/hooks/useDeployments';
import { useApiKeys } from '@/hooks/useApiKeys';
import { useModels } from '@/hooks/useModels';
import { useUsageSummary } from '@/hooks/useUsage';
import { errorMessage } from '@/lib/errors';
import { ago, count, runtimeLabel } from '@/lib/format';
import { TERMINAL_STATUSES } from '@/types';

export default function CustomerOverview() {
  const deployments = useDeployments();
  const models = useModels();
  const keys = useApiKeys();
  const usage = useUsageSummary(7);

  if (deployments.isLoading) return <PageSkeleton />;
  if (deployments.error) return <ErrorState message={errorMessage(deployments.error)} retry={() => deployments.refetch()} />;

  const all = deployments.data ?? [];
  const live = all.filter((d) => !TERMINAL_STATUSES.includes(d.status));
  const ready = all.filter((d) => d.status === 'READY');
  const modelName = (id: string) => models.data?.find((m) => m.id === id)?.name;
  const activeKeys = (keys.data ?? []).filter((k) => !k.revoked_at).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        description="Your model deployments and their usage."
        actions={
          <Link href="/customer/models" className={buttonVariants()}>
            Deploy a model
          </Link>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Ready deployments" value={ready.length} hint={`${live.length} not stopped`} icon={Activity} />
        <StatCard title="Models in catalog" value={models.data?.length ?? '—'} icon={Box} />
        <StatCard title="Active API keys" value={keys.data ? activeKeys : '—'} icon={KeyRound} />
        <StatCard
          title="Requests (7 days)"
          value={usage.data ? count(usage.data.totals.requests) : '—'}
          hint={usage.data ? `${count(usage.data.totals.output_tokens)} output tokens` : undefined}
          icon={MessageSquare}
        />
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Current deployments</CardTitle>
          <Link href="/customer/deployments" className="text-sm underline underline-offset-4">
            View all
          </Link>
        </CardHeader>
        <CardContent>
          {live.length === 0 ? (
            <EmptyState action={{ href: '/customer/models', label: 'Browse models' }}>You have no running deployments.</EmptyState>
          ) : (
            <ul className="divide-y divide-border">
              {live.slice(0, 6).map((d) => (
                <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                  <Link href={`/customer/deployments/${d.id}`} className="font-medium hover:underline">
                    {modelName(d.model_id) ?? d.model_tag ?? d.id.slice(0, 8)}
                  </Link>
                  <span className="flex items-center gap-3 text-xs text-muted-foreground">
                    {runtimeLabel(d.runtime)} · created {ago(d.created_at)}
                    <StatusBadge status={d.status} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
