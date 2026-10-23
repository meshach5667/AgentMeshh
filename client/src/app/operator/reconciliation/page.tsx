'use client';

import toast from 'react-hot-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatCard } from '@/components/common/StatCard';
import { CodeBlock } from '@/components/common/CodeBlock';
import { ErrorState, Notice, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useReconciliation, useRunReconciliation } from '@/hooks/useBilling';
import { errorMessage } from '@/lib/errors';
import { dateTime } from '@/lib/format';

const KIND_HELP: Record<string, string> = {
  wallet_balance: 'A wallet balance differs from its ledger entries. Investigate before any payout from this wallet.',
  charge_split: 'A charge’s ledger postings do not add up (debit ≠ provider credit + fee).',
  payment_not_credited_once: 'A successful top-up was not credited exactly once.',
  deposit_without_success: 'A deposit exists for a top-up that is not marked successful.',
  payment_needs_review: 'Paystack reported a different amount or currency than requested; not credited.',
  payout_hold: 'A payout’s held funds do not match its state.',
};

export default function ReconciliationPage() {
  const { data, isLoading, error, refetch, isFetching } = useReconciliation();
  const run = useRunReconciliation();
  if (isLoading) return <PageSkeleton />;
  if (error || !data) return <ErrorState message={errorMessage(error)} retry={() => refetch()} />;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Reconciliation"
        description={`Ledger invariants, checked ${dateTime(data.generated_at)}. Read-only: nothing is corrected automatically.`}
        actions={
          <>
            <Button variant="outline" onClick={() => refetch()} disabled={isFetching}>
              Recheck ledger
            </Button>
            <Button
              disabled={run.isPending}
              onClick={() =>
                run.mutate(undefined, {
                  onSuccess: (r) => toast.success(`Checked with Paystack: ${JSON.stringify(r).slice(0, 120)}`),
                  onError: (e) => toast.error(errorMessage(e)),
                })
              }
            >
              Check open items with Paystack
            </Button>
          </>
        }
      />
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard title="Top-ups awaiting payment" value={data.open.payments_initialized} />
        <StatCard title="Payouts awaiting approval" value={data.open.payouts_awaiting_approval} />
        <StatCard title="Payouts in flight" value={data.open.payouts_in_flight} />
      </div>
      {data.ok ? (
        <Notice title="Ledger consistent">
          {data.checked.wallets} wallets and {data.checked.charges} charges checked; no discrepancies.
        </Notice>
      ) : (
        <Card className="border-rose-500/40">
          <CardHeader>
            <CardTitle>{data.issues.length} discrepancies</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.issues.map((issue, i) => (
              <div key={i} className="space-y-1" data-testid="reconciliation-issue">
                <p className="text-sm font-medium">{KIND_HELP[issue.kind] ?? issue.kind}</p>
                <CodeBlock code={JSON.stringify(issue, null, 2)} />
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      {run.data && <CodeBlock code={JSON.stringify(run.data, null, 2)} />}
    </div>
  );
}
