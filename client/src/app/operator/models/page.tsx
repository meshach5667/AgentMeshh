'use client';

import toast from 'react-hot-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Pill } from '@/components/common/StatusBadge';
import { EmptyState, ErrorState, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useAdminModels, useSetArtifactEnabled, useSetModelApproval } from '@/hooks/useAdmin';
import { errorMessage } from '@/lib/errors';
import { ago, bytes, mb, runtimeLabel } from '@/lib/format';

export default function OperatorModelsPage() {
  const { data, isLoading, error, refetch } = useAdminModels();
  const approve = useSetModelApproval();
  const toggle = useSetArtifactEnabled();
  const act = (p: Promise<unknown>, ok: string) => p.then(() => toast.success(ok)).catch((e) => toast.error(errorMessage(e)));

  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorState message={errorMessage(error)} retry={() => refetch()} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Model catalog"
        description="Approve models and enable the runtime artifacts customers may deploy. Adding artifacts is done through the API (POST /models/{id}/artifacts), which validates pinned sources."
      />
      {(data ?? []).length === 0 && <EmptyState>The catalog is empty.</EmptyState>}
      {(data ?? []).map((m) => (
        <Card key={m.id} data-testid="operator-model">
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2">
                {m.name} {m.is_approved ? <Pill tone="green">approved</Pill> : <Pill tone="amber">not approved</Pill>}
              </CardTitle>
              <CardDescription>{[m.publisher, m.parameter_size, m.license].filter(Boolean).join(' · ')}</CardDescription>
            </div>
            <Button
              size="sm"
              variant={m.is_approved ? 'outline' : 'default'}
              disabled={approve.isPending}
              onClick={() => act(approve.mutateAsync({ id: m.id, approved: !m.is_approved }), m.is_approved ? 'Approval withdrawn' : 'Model approved')}
            >
              {m.is_approved ? 'Withdraw approval' : 'Approve'}
            </Button>
          </CardHeader>
          <CardContent>
            {m.artifacts.length === 0 ? (
              <p className="text-sm text-muted-foreground">No artifacts: this model cannot be deployed.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Runtime</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Size</TableHead>
                    <TableHead>Reservation</TableHead>
                    <TableHead>Last ready</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {m.artifacts.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell>{runtimeLabel(a.runtime)}</TableCell>
                      <TableCell className="max-w-sm text-xs">
                        <span className="break-all font-mono">{a.reference}</span>
                        {a.revision && <div className="font-mono text-muted-foreground">@{a.revision.slice(0, 12)}</div>}
                        {a.file && <div className="break-all font-mono text-muted-foreground">{a.file}</div>}
                        {a.sha256 && <div className="font-mono text-muted-foreground">sha256 {a.sha256.slice(0, 12)}…</div>}
                      </TableCell>
                      <TableCell className="text-xs">{bytes(a.size_bytes)}</TableCell>
                      <TableCell className="text-xs">
                        {mb(a.min_ram_mb)} RAM{a.gpu_required ? `, ${mb(a.min_vram_mb)} GPU` : ''}
                        {a.requirements_estimated && <div className="text-muted-foreground">estimate</div>}
                      </TableCell>
                      <TableCell className="text-xs">{ago(a.last_ready_at)}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={toggle.isPending}
                          onClick={() =>
                            act(toggle.mutateAsync({ modelId: m.id, artifactId: a.id, enabled: !a.is_enabled }), a.is_enabled ? 'Artifact disabled' : 'Artifact enabled')
                          }
                        >
                          {a.is_enabled ? 'Disable' : 'Enable'}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
