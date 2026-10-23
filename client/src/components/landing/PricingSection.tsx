'use client';

import Link from 'next/link';
import { usePricing } from '@/hooks/useBilling';
import { money } from '@/lib/format';

/** Live price list from GET /billing/pricing. */
export function PricingSection() {
  const { data } = usePricing();
  const r = data?.current;
  const rows = r
    ? [
        ['CPU core', money(r.cpu_core_hour, r.currency), 'per hour'],
        ['Memory', money(r.ram_gb_hour, r.currency), 'per GB-hour'],
        ['GPU memory', money(r.vram_gb_hour, r.currency), 'per GB-hour'],
        ['Input tokens', money(r.input_tokens_per_million, r.currency), 'per million'],
        ['Output tokens', money(r.output_tokens_per_million, r.currency), 'per million'],
      ]
    : [];
  return (
    <section id="pricing" className="py-28">
      <div className="mx-auto grid max-w-6xl gap-12 px-6 lg:grid-cols-2 lg:items-center">
        <div>
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">Pricing</p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight md:text-[2.75rem] md:leading-[1.1]">Pay for what serves.</h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Prepaid and transparent. You&apos;re charged for the resources reserved for your deployment only while it is
            ready, plus the tokens it processes. Downloads, startup and unhealthy time are free.
          </p>
          <p className="mt-4 text-sm text-muted-foreground">
            Providers receive {r ? `${Math.round((1 - Number(r.platform_fee_rate)) * 100)}%` : 'most'} of every charge.
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-2 shadow-soft">
          {r ? (
            <>
              <div className="divide-y divide-border">
                {rows.map(([label, price, unit]) => (
                  <div key={label} className="flex items-baseline justify-between px-5 py-4">
                    <span className="text-sm text-muted-foreground">{label}</span>
                    <span>
                      <span className="font-semibold tabular-nums">{price}</span>{' '}
                      <span className="text-xs text-muted-foreground">{unit}</span>
                    </span>
                  </div>
                ))}
              </div>
              <p className="px-5 pb-4 pt-2 text-xs text-muted-foreground">Live price list, version {r.version}.</p>
            </>
          ) : (
            <div className="px-6 py-10 text-center">
              <p className="font-medium">No prices published yet</p>
              <p className="mt-1 text-sm text-muted-foreground">
                The network operator hasn&apos;t set a price list, so usage is currently measured but not charged.
              </p>
            </div>
          )}
          <div className="p-3">
            <Link href="/register" className="flex h-10 items-center justify-center rounded-lg bg-primary text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90">
              Start deploying
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
