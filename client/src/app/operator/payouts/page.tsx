'use client';

import { useState } from 'react';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ConfirmButton } from '@/components/common/ConfirmButton';
import { StatusBadge } from '@/components/common/StatusBadge';
import { EmptyState, ErrorState, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useAdminPayouts, useDecidePayout } from '@/hooks/useBilling';
import { errorMessage } from '@/lib/errors';
import { dateTime, money, shortId } from '@/lib/format';

const STATUSES = ['REQUESTED', '', 'PENDING', 'OTP_REQUIRED', 'SUCCEEDED', 'FAILED', 'REVERSED', 'REJECTED'];

export default function OperatorPayoutsPage() {
  const [status, setStatus] = useState('REQUESTED');
  const { data, isLoading, error, refetch } = useAdminPayouts(status);
  const decide = useDecidePayout();
  const act = (id: string, approve: boolean) => {
    const reason = approve ? undefined : window.prompt('Reason shown to the provider (optional)') ?? undefined;
    decide.mutate(
      { id, approve, reason },
      {
        onSuccess: (p) => toast.success(`Payout ${p.status.toLowerCase()}`),
        onError: (e) => toast.error(errorMessage(e)),
      },
    );
  };
  return (
    <div className="space-y-6">
      <PageHeader
        title="Payouts"
        description="Approving sends a Paystack transfer from the platform balance. Rejecting returns the held amount to the provider."
        actions={
          <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm">
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s || 'All'}
              </option>
            ))}
          </select>
        }
      />
      {isLoading ? (
        <PageSkeleton />
      ) : error ? (
        <ErrorState message={errorMessage(error)} retry={() => refetch()} />
      ) : (
        <Card>
          <CardContent className="pt-6">
            {(data ?? []).length === 0 ? (
              <EmptyState>No payouts.</EmptyState>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Requested</TableHead>
                    <TableHead>Provider</TableHead>
                    <TableHead>Reference</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data ?? []).map((p) => (
                    <TableRow key={p.id} data-testid="admin-payout-row">
                      <TableCell className="text-xs">{dateTime(p.created_at)}</TableCell>
                      <TableCell className="font-mono text-xs">{shortId(p.user_id)}</TableCell>
                      <TableCell className="font-mono text-xs">{p.reference}</TableCell>
                      <TableCell>
                        <StatusBadge status={p.status} />
                        {p.failure_reason && <div className="max-w-xs text-xs text-muted-foreground">{p.failure_reason}</div>}
                        {p.reconciled_at && <div className="text-xs text-muted-foreground">reconciled {dateTime(p.reconciled_at)}</div>}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">{money(p.amount, p.currency)}</TableCell>
                      <TableCell className="text-right">
                        {p.status === 'REQUESTED' && (
                          <span className="inline-flex gap-1">
                            <ConfirmButton size="sm" variant="default" confirmLabel="Send transfer" disabled={decide.isPending} onConfirm={() => act(p.id, true)}>
                              Approve
                            </ConfirmButton>
                            <Button size="sm" variant="ghost" disabled={decide.isPending} onClick={() => act(p.id, false)}>
                              Reject
                            </Button>
                          </span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
