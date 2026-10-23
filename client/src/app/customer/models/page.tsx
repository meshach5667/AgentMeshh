'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { Search } from 'lucide-react';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Pill } from '@/components/common/StatusBadge';
import { EmptyState, ErrorState, PageHeader } from '@/components/common/Notices';
import { CommunityModels } from '@/components/models/CommunityModels';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useModels } from '@/hooks/useModels';
import { usePublicStats } from '@/hooks/useUsage';
import { deployableArtifacts } from '@/lib/deployments';
import { errorMessage } from '@/lib/errors';
import { ago, mb, runtimeLabel } from '@/lib/format';

export default function ModelCatalogPage() {
  const { data: models, isLoading, error, refetch } = useModels();
  const stats = usePublicStats();
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (models ?? []).filter((m) =>
      !q
        ? true
        : [m.name, m.family, m.publisher, m.parameter_size, ...m.artifacts.map((a) => a.reference)]
            .filter(Boolean)
            .some((v) => v!.toLowerCase().includes(q)),
    );
  }, [models, query]);

  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorState message={errorMessage(error)} retry={() => refetch()} />;

  const online = stats.data?.runtimes_online ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Model catalog"
        description="Open-weight models approved by AgentMesh operators. Each runtime serves a pinned copy of the model."
        actions={
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-2.5 top-2 size-4 text-muted-foreground" />
            <Input
              type="search"
              aria-label="Search models"
              placeholder="Search models"
              className="pl-8"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        }
      />
      {stats.data && (
        <p className="text-sm text-muted-foreground">
          {stats.data.nodes_online} node{stats.data.nodes_online === 1 ? '' : 's'} accepting work now
          {online && online.length > 0 ? `, offering ${online.map(runtimeLabel).join(', ')}` : ''}. Being listed here
          does not guarantee a node has room for a model.
        </p>
      )}
      {filtered.length === 0 ? (
        <EmptyState>{query ? 'No models match your search.' : 'No models are approved for deployment yet.'}</EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((m) => {
            const artifacts = deployableArtifacts(m.artifacts);
            const smallest = artifacts.reduce<number | null>((min, a) => (min == null || a.min_ram_mb < min ? a.min_ram_mb : min), null);
            const lastReady = artifacts.map((a) => a.last_ready_at).filter(Boolean).sort().at(-1);
            return (
              <Card key={m.id} className="flex flex-col" data-testid="model-card">
                <CardHeader>
                  <CardTitle>{m.name}</CardTitle>
                  <CardDescription>
                    {[m.publisher, m.parameter_size && `${m.parameter_size} parameters`, m.license].filter(Boolean).join(' · ')}
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex-1 space-y-3 text-sm">
                  <div className="flex flex-wrap gap-1">
                    {artifacts.map((a) => (
                      <Pill key={a.id} tone={online?.includes(a.runtime) ? 'green' : 'gray'}>
                        {runtimeLabel(a.runtime)}
                        {a.quantization ? ` ${a.quantization}` : ''}
                        {a.gpu_required ? ' · GPU' : ''}
                      </Pill>
                    ))}
                  </div>
                  <dl className="grid grid-cols-2 gap-y-1 text-muted-foreground">
                    <dt>Smallest reservation</dt>
                    <dd className="text-right text-foreground">{smallest ? `${mb(smallest)} RAM` : '—'}</dd>
                    <dt>Context length</dt>
                    <dd className="text-right text-foreground">{m.context_length?.toLocaleString() ?? '—'}</dd>
                    <dt>Last served on AgentMesh</dt>
                    <dd className="text-right text-foreground">{lastReady ? ago(lastReady) : 'not yet'}</dd>
                  </dl>
                </CardContent>
                <CardFooter>
                  {artifacts.length > 0 ? (
                    <Link href={`/customer/deployments/new?model=${m.id}`} className={buttonVariants({ className: 'w-full' })}>
                      Configure and deploy
                    </Link>
                  ) : (
                    <p className="text-sm text-muted-foreground">No runtime is enabled for this model.</p>
                  )}
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Green runtimes are offered by at least one online node right now. Resource figures are estimates.
      </p>
      <CommunityModels />
    </div>
  );
}
