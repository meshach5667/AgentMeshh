'use client';

import { usePublicStats } from '@/hooks/useUsage';
import { runtimeLabel } from '@/lib/format';

/** Live counts from the AgentMesh database. Nothing here is simulated. */
export function LiveStats() {
  const { data, isError } = usePublicStats();
  const items = [
    { label: 'Nodes online', value: data?.nodes_online },
    { label: 'GPU nodes online', value: data?.gpu_nodes_online },
    { label: 'Deployable models', value: data?.models_deployable },
    { label: 'Deployments serving', value: data?.deployments_ready },
  ];
  return (
    <section className="border-y border-border bg-muted/30" aria-label="Network right now">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-4">
          {items.map(({ label, value }) => (
            <div key={label} className="bg-background px-6 py-6">
              <div className="text-3xl font-semibold tracking-tight tabular-nums" data-testid={`stat-${label}`}>
                {value == null ? '—' : value.toLocaleString()}
              </div>
              <div className="mt-1 text-[13px] text-muted-foreground">{label}</div>
            </div>
          ))}
        </div>
        <p className="mt-4 flex items-center justify-center gap-2 text-xs text-muted-foreground">
          {!isError && data && (
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
            </span>
          )}
          {isError
            ? 'Live network figures are unavailable right now.'
            : data
              ? `Live from this AgentMesh network${data.runtimes_online.length ? ` · runtimes online: ${data.runtimes_online.map(runtimeLabel).join(', ')}` : ''}.`
              : 'Loading live network figures…'}
        </p>
      </div>
    </section>
  );
}
