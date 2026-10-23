'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { usePricing } from '@/hooks/useBilling';
import { dateTime, money } from '@/lib/format';

export function PricingCard() {
  const { data } = usePricing();
  if (!data) return null;
  const r = data.current;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Prices</CardTitle>
        <CardDescription>
          {r
            ? `Version ${r.version}, in force since ${dateTime(r.effective_from)}. Charged while a deployment is READY, every ${Math.round(data.billing_interval_seconds / 60)} minutes.`
            : 'No prices are set: usage is measured but not charged.'}
        </CardDescription>
      </CardHeader>
      {r && (
        <CardContent>
          <dl className="grid grid-cols-2 gap-y-1 text-sm sm:grid-cols-[14rem_1fr]">
            <dt className="text-muted-foreground">CPU core, per hour</dt>
            <dd>{money(r.cpu_core_hour, r.currency)}</dd>
            <dt className="text-muted-foreground">Memory, per GB-hour</dt>
            <dd>{money(r.ram_gb_hour, r.currency)}</dd>
            <dt className="text-muted-foreground">GPU memory, per GB-hour</dt>
            <dd>{money(r.vram_gb_hour, r.currency)}</dd>
            <dt className="text-muted-foreground">Input tokens, per million</dt>
            <dd>{money(r.input_tokens_per_million, r.currency)}</dd>
            <dt className="text-muted-foreground">Output tokens, per million</dt>
            <dd>{money(r.output_tokens_per_million, r.currency)}</dd>
          </dl>
          <p className="mt-3 text-xs text-muted-foreground">
            Resource charges use the capacity reserved for the deployment, for the time it is READY (not while unhealthy).
            Token counts are reported by the model runtime on the provider&apos;s node. A deployment needs a balance
            covering {data.min_prepaid_hours} h of its reservation; when the balance runs out, deployments are stopped.
          </p>
          {data.upcoming.length > 0 && (
            <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
              Version {data.upcoming[0].version} takes effect {dateTime(data.upcoming[0].effective_from)}.
            </p>
          )}
        </CardContent>
      )}
    </Card>
  );
}
