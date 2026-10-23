import { capacityRows } from '@/lib/nodes';
import { mb } from '@/lib/format';
import type { Node } from '@/types';

/** Reserved (by AgentMesh deployments) versus allocated (the limit the provider set on the machine). */
export function CapacityBars({ node }: { node: Node }) {
  const rows = capacityRows(node);
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">The worker has not reported its limits yet.</p>;
  return (
    <div className="space-y-3">
      {rows.map((r) => {
        const pct = r.allocated > 0 ? Math.min(100, Math.round((r.reserved / r.allocated) * 100)) : 0;
        const fmt = (v: number) => (r.unit === 'mb' ? mb(v) : String(v));
        return (
          <div key={r.label} className="space-y-1">
            <div className="flex justify-between text-xs">
              <span>{r.label}</span>
              <span className="tabular-nums text-muted-foreground">
                {fmt(r.reserved)} of {fmt(r.allocated)} reserved
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={r.label} aria-valuenow={pct}>
              <div className={`h-full rounded-full ${pct >= 90 ? 'bg-amber-500' : 'bg-brand'}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
