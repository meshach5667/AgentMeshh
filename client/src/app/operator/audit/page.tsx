'use client';

import { useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { EmptyState, ErrorState, PageHeader } from '@/components/common/Notices';
import { TableSkeleton } from '@/components/ui/Skeleton';
import { useAuditLogs } from '@/hooks/useAdmin';
import { errorMessage } from '@/lib/errors';
import { dateTime, shortId } from '@/lib/format';

export default function AuditLogPage() {
  const [action, setAction] = useState('');
  const [resourceType, setResourceType] = useState('');
  const [resourceId, setResourceId] = useState('');
  const { data, isLoading, error, refetch } = useAuditLogs({
    action: action.trim(),
    resource_type: resourceType.trim(),
    resource_id: resourceId.trim(),
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Audit log" description="Security-relevant actions by customers, providers, operators and workers. Secrets are redacted." />
      <div className="grid gap-2 sm:grid-cols-3">
        <Input aria-label="Action" placeholder="Action, e.g. node.revoked" value={action} onChange={(e) => setAction(e.target.value)} />
        <Input aria-label="Resource type" placeholder="Resource type, e.g. deployment" value={resourceType} onChange={(e) => setResourceType(e.target.value)} />
        <Input aria-label="Resource id" placeholder="Resource id" value={resourceId} onChange={(e) => setResourceId(e.target.value)} />
      </div>
      <Card>
        <CardContent className="pt-6">
          {error ? (
            <ErrorState message={errorMessage(error)} retry={() => refetch()} />
          ) : isLoading ? (
            <TableSkeleton />
          ) : (data ?? []).length === 0 ? (
            <EmptyState>No matching entries.</EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data ?? []).map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="whitespace-nowrap text-xs">{dateTime(a.created_at)}</TableCell>
                    <TableCell className="font-mono text-xs">{a.action}</TableCell>
                    <TableCell className="text-xs">
                      {a.resource_type} <span className="font-mono">{shortId(a.resource_id)}</span>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{a.user_id ? shortId(a.user_id) : 'system'}</TableCell>
                    <TableCell className="max-w-md truncate font-mono text-xs text-muted-foreground" title={JSON.stringify(a.details)}>
                      {a.details ? JSON.stringify(a.details) : ''}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
