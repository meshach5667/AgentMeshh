'use client';

import { useState } from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { EmptyState, ErrorState, PageHeader } from '@/components/common/Notices';
import { NodeTable } from '@/components/nodes/NodeTable';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useNodes } from '@/hooks/useNodes';
import { errorMessage } from '@/lib/errors';

export default function ProviderNodesPage() {
  const { data, isLoading, error, refetch, isFetching } = useNodes();
  const [showRevoked, setShowRevoked] = useState(false);

  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorState message={errorMessage(error)} retry={() => refetch()} />;

  const all = data ?? [];
  const revoked = all.filter((n) => n.status === 'REVOKED').length;
  const rows = showRevoked ? all : all.filter((n) => n.status !== 'REVOKED');

  return (
    <div className="space-y-6">
      <PageHeader
        title="My nodes"
        description="Machines you have enrolled. Each runs the AgentMesh worker and reports every 15 seconds."
        actions={
          <>
            <Button variant="outline" size="icon" aria-label="Refresh" onClick={() => refetch()}>
              <RefreshCw className={isFetching ? 'animate-spin' : ''} />
            </Button>
            <Link href="/provider/nodes/register" className={buttonVariants()}>
              Add a machine
            </Link>
          </>
        }
      />
      {revoked > 0 && (
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={showRevoked} onChange={(e) => setShowRevoked(e.target.checked)} />
          Show revoked ({revoked})
        </label>
      )}
      <Card>
        <CardContent className="pt-6">
          {rows.length === 0 ? (
            <EmptyState action={{ href: '/provider/nodes/register', label: 'Enroll a machine' }}>No nodes to show.</EmptyState>
          ) : (
            <NodeTable nodes={rows} href={(n) => `/provider/nodes/${n.id}`} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
