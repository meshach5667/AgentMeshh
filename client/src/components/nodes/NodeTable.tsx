import Link from 'next/link';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { StatusBadge } from '@/components/common/StatusBadge';
import { NodeAvailabilityBadge } from './NodeAvailabilityBadge';
import { ago, mb, runtimeLabel, shortId } from '@/lib/format';
import type { AdminNode, Node } from '@/types';

export function NodeTable({
  nodes,
  href,
  actions,
}: {
  nodes: (Node | AdminNode)[];
  href?: (n: Node) => string;
  actions?: (n: Node) => React.ReactNode;
}) {
  const showOwner = nodes.some((n) => 'owner_email' in n);
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Node</TableHead>
          {showOwner && <TableHead>Owner</TableHead>}
          <TableHead>Status</TableHead>
          <TableHead>Availability</TableHead>
          <TableHead>Runtimes</TableHead>
          <TableHead>Memory reserved</TableHead>
          <TableHead>Last heartbeat</TableHead>
          {actions && <TableHead className="text-right">Actions</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {nodes.map((n) => (
          <TableRow key={n.id} data-testid="node-row">
            <TableCell>
              {href ? (
                <Link href={href(n)} className="font-medium hover:underline">
                  {n.name ?? shortId(n.id)}
                </Link>
              ) : (
                <span className="font-medium">{n.name ?? shortId(n.id)}</span>
              )}
              <div className="text-xs text-muted-foreground">
                {n.mode === 'agent' ? 'Installable agent' : n.mode === 'docker' ? 'Docker worker' : (n.mode ?? '—')}
                {n.region ? ` · ${n.region}` : ''}
              </div>
            </TableCell>
            {showOwner && <TableCell className="text-xs">{(n as AdminNode).owner_email ?? '—'}</TableCell>}
            <TableCell>
              <StatusBadge status={n.status} />
            </TableCell>
            <TableCell>
              <NodeAvailabilityBadge node={n} />
            </TableCell>
            <TableCell className="text-xs">
              {(n.runtimes ?? []).filter((r) => r.available).map((r) => runtimeLabel(r.name)).join(', ') || '—'}
            </TableCell>
            <TableCell className="text-xs tabular-nums">
              {mb(n.reserved_ram_mb)} / {mb(n.allocated_ram_mb)}
            </TableCell>
            <TableCell className="text-xs">{ago(n.last_heartbeat)}</TableCell>
            {actions && <TableCell className="text-right">{actions(n)}</TableCell>}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
