'use client';

import Link from 'next/link';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { StatCard } from '@/components/common/StatCard';
import { EmptyState, ErrorState } from '@/components/common/Notices';
import { TableSkeleton } from '@/components/ui/Skeleton';
import { useUsageSummary } from '@/hooks/useUsage';
import { errorMessage } from '@/lib/errors';
import { count, shortId } from '@/lib/format';
import type { UsageSummary } from '@/types';

const DAY_OPTIONS = [7, 30, 90];

export function UsageSummaryView({
  days,
  onDaysChange,
  scope,
  deploymentHref,
  deploymentLabel,
}: {
  days: number;
  onDaysChange: (d: number) => void;
  scope?: UsageSummary['scope'];
  deploymentHref?: (id: string) => string;
  deploymentLabel?: (id: string) => string;
}) {
  const { data, isLoading, error, refetch } = useUsageSummary(days, scope);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">Period</span>
        {DAY_OPTIONS.map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => onDaysChange(d)}
            aria-pressed={d === days}
            className={`rounded-md border px-2.5 py-1 ${d === days ? 'border-foreground font-medium' : 'border-border text-muted-foreground'}`}
          >
            {d} days
          </button>
        ))}
      </div>

      {error ? (
        <ErrorState message={errorMessage(error)} retry={() => refetch()} />
      ) : isLoading || !data ? (
        <TableSkeleton rows={3} />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              title="Requests"
              value={count(data.totals.requests)}
              hint={`${count(data.totals.succeeded)} succeeded, ${count(data.totals.failed)} failed`}
            />
            <StatCard title="Input tokens" value={count(data.totals.input_tokens)} />
            <StatCard title="Output tokens" value={count(data.totals.output_tokens)} />
            <StatCard
              title="Requests without token counts"
              value={count(data.totals.requests_without_token_counts)}
              hint="The runtime did not report counts (for example, a failed or cancelled request). Never estimated."
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Per day</CardTitle>
              <CardDescription>
                Token counts are reported by the model runtime on the provider&apos;s node and are not independently
                verified.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {data.by_day.length === 0 ? (
                <EmptyState>No inference requests in the last {days} days.</EmptyState>
              ) : (
                <div className="h-64 w-full" data-testid="usage-chart">
                  <ResponsiveContainer>
                    <BarChart data={data.by_day}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                      <XAxis dataKey="date" fontSize={12} />
                      <YAxis fontSize={12} allowDecimals={false} />
                      <Tooltip />
                      <Legend />
                      <Bar dataKey="input_tokens" name="Input tokens" stackId="t" fill="#60a5fa" />
                      <Bar dataKey="output_tokens" name="Output tokens" stackId="t" fill="#2563eb" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </CardContent>
          </Card>

          {data.by_deployment.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>By deployment</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Deployment</TableHead>
                      <TableHead className="text-right">Requests</TableHead>
                      <TableHead className="text-right">Failed</TableHead>
                      <TableHead className="text-right">Input tokens</TableHead>
                      <TableHead className="text-right">Output tokens</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.by_deployment.map((row) => {
                      const label = deploymentLabel?.(row.deployment_id) ?? shortId(row.deployment_id);
                      return (
                        <TableRow key={row.deployment_id}>
                          <TableCell className="font-mono text-xs">
                            {deploymentHref ? (
                              <Link className="underline underline-offset-4" href={deploymentHref(row.deployment_id)}>
                                {label}
                              </Link>
                            ) : (
                              label
                            )}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{count(row.requests)}</TableCell>
                          <TableCell className="text-right tabular-nums">{count(row.failed)}</TableCell>
                          <TableCell className="text-right tabular-nums">{count(row.input_tokens)}</TableCell>
                          <TableCell className="text-right tabular-nums">{count(row.output_tokens)}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
