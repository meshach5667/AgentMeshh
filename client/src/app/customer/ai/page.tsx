'use client';

import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { AiDeployForm } from '@/components/ai/AiDeployForm';
import { AiHealthBadge } from '@/components/ai/AiHealthBadge';
import { StatusBadge } from '@/components/common/StatusBadge';
import { Notice, PageHeader } from '@/components/common/Notices';
import { useAiHealth, useAiRuns } from '@/hooks/useAiDeployments';
import { errorMessage } from '@/lib/errors';
import { ago, money } from '@/lib/format';

export default function AiDeploymentsPage() {
  const runs = useAiRuns();
  const health = useAiHealth();

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI Deploy"
        description="Describe a model deployment in plain language. An AI agent plans it; AgentMesh enforces your limits, verifies the result, and stops it when a limit is reached."
        actions={<AiHealthBadge />}
      />

      {health.data && !health.data.available && (
        <Notice tone="warning" title={health.data.status === 'not_configured' ? 'Not available' : 'The AI agent is not available right now'}>
          {health.data.message} Deployments that are already running are not affected.
        </Notice>
      )}

      <Card>
        <CardHeader>
          <CardTitle>New autonomous deployment</CardTitle>
          <CardDescription>
            The agent runs on AgentMesh&apos;s own inference machine (model {health.data?.model ?? '…'}). It can only choose
            from the approved catalog and propose actions; it never decides prices, availability, or permissions.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AiDeployForm />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your AI deployments</CardTitle>
        </CardHeader>
        <CardContent>
          {runs.error ? (
            <p className="text-sm text-rose-500">{errorMessage(runs.error)}</p>
          ) : (runs.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">None yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Request</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead className="text-right">Cost so far</TableHead>
                  <TableHead>Started</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(runs.data ?? []).map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="max-w-xs truncate">
                      <Link href={`/customer/ai/${r.id}`} className="underline-offset-4 hover:underline">
                        {r.request}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={r.status} />
                      {r.waiting_for_ai && <span className="ml-2 text-xs text-muted-foreground">waiting for AI</span>}
                    </TableCell>
                    <TableCell className="text-sm">{r.model_name ?? '—'}</TableCell>
                    <TableCell className="text-right text-sm">{money(r.actual_cost, r.currency ?? undefined)}</TableCell>
                    <TableCell className="text-xs">{ago(r.created_at)}</TableCell>
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
