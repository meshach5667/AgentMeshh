'use client';

import { Card, CardContent } from '@/components/ui/card';
import { ErrorState, PageHeader } from '@/components/common/Notices';
import { TableSkeleton } from '@/components/ui/Skeleton';
import { LedgerTable } from '@/components/wallet/LedgerTable';
import { useLedger } from '@/hooks/useAdmin';
import { errorMessage } from '@/lib/errors';

export default function OperatorLedgerPage() {
  const { data, isLoading, error, refetch } = useLedger();
  return (
    <div className="space-y-6">
      <PageHeader title="Ledger" description="The 200 most recent ledger entries across all wallets." />
      <Card>
        <CardContent className="pt-6">
          {error ? <ErrorState message={errorMessage(error)} retry={() => refetch()} /> : isLoading ? <TableSkeleton /> : <LedgerTable rows={data ?? []} empty="The ledger is empty." />}
        </CardContent>
      </Card>
    </div>
  );
}
