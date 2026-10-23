import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { StatusBadge } from '@/components/common/StatusBadge';
import { EmptyState } from '@/components/common/Notices';
import { dateTime, money, shortId } from '@/lib/format';
import type { Transaction } from '@/types';

const TYPE_LABEL: Record<string, string> = {
  DEPOSIT: 'Deposit',
  COMPUTE_CHARGE: 'Compute charge',
  PROVIDER_CREDIT: 'Provider credit',
  PLATFORM_FEE: 'Platform fee',
  REFUND: 'Refund',
  PAYOUT: 'Payout',
};

/** Ledger rows. `walletId` decides the sign: money into that wallet is positive. */
export function LedgerTable({ rows, walletId, empty }: { rows: Transaction[]; walletId?: string; empty: string }) {
  if (rows.length === 0) return <EmptyState>{empty}</EmptyState>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Date</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Description</TableHead>
          <TableHead>Deployment</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Amount</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((tx) => {
          const incoming = walletId ? tx.to_wallet === walletId : true;
          return (
            <TableRow key={tx.id}>
              <TableCell className="text-sm">{dateTime(tx.created_at)}</TableCell>
              <TableCell className="text-sm">{TYPE_LABEL[tx.type] ?? tx.type}</TableCell>
              <TableCell className="max-w-xs truncate text-sm text-muted-foreground">{tx.description ?? '—'}</TableCell>
              <TableCell className="font-mono text-xs">{tx.deployment_id ? shortId(tx.deployment_id) : '—'}</TableCell>
              <TableCell>
                <StatusBadge status={tx.status} />
              </TableCell>
              <TableCell className={`text-right font-mono text-sm ${incoming ? 'text-emerald-600 dark:text-emerald-400' : ''}`}>
                {walletId ? (incoming ? '+' : '−') : ''}
                {money(tx.amount)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
