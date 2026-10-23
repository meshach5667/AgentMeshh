'use client';

import { Card, CardContent } from '@/components/ui/card';
import { ErrorState, PageHeader } from '@/components/common/Notices';
import { TableSkeleton } from '@/components/ui/Skeleton';
import { LedgerTable } from '@/components/wallet/LedgerTable';
import { useTransactions } from '@/hooks/useTransactions';
import { useWallet } from '@/hooks/useWallet';
import { errorMessage } from '@/lib/errors';

export default function CustomerTransactionsPage() {
  const tx = useTransactions();
  const wallet = useWallet();
  return (
    <div className="space-y-6">
      <PageHeader title="Transactions" description="Every ledger entry involving your wallet." />
      <Card>
        <CardContent className="pt-6">
          {tx.error ? (
            <ErrorState message={errorMessage(tx.error)} retry={() => tx.refetch()} />
          ) : tx.isLoading ? (
            <TableSkeleton />
          ) : (
            <LedgerTable rows={tx.data ?? []} walletId={wallet.data?.id} empty="No transactions yet." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
