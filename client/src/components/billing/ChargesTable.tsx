import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { EmptyState } from '@/components/common/Notices';
import { count, dateTime, money, shortId } from '@/lib/format';
import type { Charge } from '@/types';

export function ChargesTable({ charges, side = 'customer', empty }: { charges: Charge[]; side?: 'customer' | 'provider'; empty: string }) {
  if (charges.length === 0) return <EmptyState>{empty}</EmptyState>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Period</TableHead>
          <TableHead>Deployment</TableHead>
          <TableHead className="text-right">READY time</TableHead>
          <TableHead className="text-right">Tokens in/out</TableHead>
          <TableHead className="text-right">{side === 'customer' ? 'Charged' : 'Your share'}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {charges.map((c) => (
          <TableRow key={c.id} data-testid="charge-row">
            <TableCell className="text-xs">{dateTime(c.period_start)}</TableCell>
            <TableCell className="font-mono text-xs">{shortId(c.deployment_id)}</TableCell>
            <TableCell className="text-right text-xs tabular-nums">{Math.round(c.ready_seconds / 60)} min</TableCell>
            <TableCell className="text-right text-xs tabular-nums">
              {count(c.input_tokens)} / {count(c.output_tokens)}
            </TableCell>
            <TableCell className="text-right font-mono text-xs" title={`resources ${c.resource_amount}, tokens ${c.token_amount}`}>
              {money(side === 'customer' ? c.amount : c.provider_amount, c.currency)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
