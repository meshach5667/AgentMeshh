'use client';

import Link from 'next/link';
import { useState } from 'react';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { InlineValue } from '@/components/common/CodeBlock';
import { ConfirmButton } from '@/components/common/ConfirmButton';
import { Pill } from '@/components/common/StatusBadge';
import { EmptyState, ErrorState, Notice, PageHeader } from '@/components/common/Notices';
import { TableSkeleton } from '@/components/ui/Skeleton';
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '@/hooks/useApiKeys';
import { useDeployments } from '@/hooks/useDeployments';
import { errorMessage } from '@/lib/errors';
import { ago, dateTime, parseApiDate, shortId } from '@/lib/format';
import { TERMINAL_STATUSES, type ApiKey, type CreatedApiKey } from '@/types';

export default function ApiKeysPage() {
  const keys = useApiKeys();
  const deployments = useDeployments();
  const create = useCreateApiKey();
  const revoke = useRevokeApiKey();
  const [name, setName] = useState('');
  const [deploymentId, setDeploymentId] = useState('');
  const [expiresInDays, setExpiresInDays] = useState('');
  const [created, setCreated] = useState<CreatedApiKey | null>(null);

  const usable = (deployments.data ?? []).filter((d) => !TERMINAL_STATUSES.includes(d.status));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const days = Number(expiresInDays);
    create.mutate(
      {
        name: name.trim(),
        deployment_id: deploymentId || undefined,
        expires_at: days > 0 ? new Date(Date.now() + days * 86400000).toISOString() : undefined,
      },
      {
        onSuccess: (key) => {
          setCreated(key);
          setName('');
        },
      },
    );
  };

  const state = (k: ApiKey) => {
    if (k.revoked_at) return <Pill tone="red">Revoked</Pill>;
    const exp = parseApiDate(k.expires_at);
    if (exp && exp < new Date()) return <Pill tone="amber">Expired</Pill>;
    return <Pill tone="green">Active</Pill>;
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="API keys"
        description="Keys authenticate your applications to the inference gateway."
        actions={
          <Link href="/docs/api" className="inline-flex h-8 items-center rounded-lg border border-border px-3 text-[13px] font-medium transition-colors hover:bg-muted">
            API docs
          </Link>
        }
      />

      {created && (
        <Notice tone="warning" title="Copy this key now. It will not be shown again.">
          <div className="mt-2 space-y-2">
            <InlineValue value={created.key} />
            <p>
              Use it as <code className="font-mono">Authorization: Bearer &lt;key&gt;</code>. AgentMesh stores only a
              hash of it.
            </p>
            <Button size="sm" variant="outline" onClick={() => setCreated(null)}>
              I have saved it
            </Button>
          </div>
        </Notice>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Create a key</CardTitle>
          <CardDescription>Limit a key to one deployment where you can. Deleting that deployment revokes the key.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="grid gap-4 sm:grid-cols-[1fr_1fr_10rem_auto] sm:items-end">
            <div className="space-y-2">
              <Label htmlFor="key-name">Name</Label>
              <Input id="key-name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="my-app" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="key-scope">Deployment</Label>
              <select
                id="key-scope"
                value={deploymentId}
                onChange={(e) => setDeploymentId(e.target.value)}
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
              >
                <option value="">All my deployments</option>
                {usable.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.model_tag ?? 'deployment'} ({shortId(d.id)}, {d.status})
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="key-expiry">Expires in (days)</Label>
              <Input id="key-expiry" type="number" min={1} max={3650} value={expiresInDays} onChange={(e) => setExpiresInDays(e.target.value)} placeholder="Never" />
            </div>
            <Button type="submit" disabled={create.isPending || !name.trim()}>
              Create key
            </Button>
          </form>
          {create.error && <p className="mt-3 text-sm text-rose-500">{errorMessage(create.error)}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your keys</CardTitle>
        </CardHeader>
        <CardContent>
          {keys.error ? (
            <ErrorState message={errorMessage(keys.error)} retry={() => keys.refetch()} />
          ) : keys.isLoading ? (
            <TableSkeleton rows={2} />
          ) : (keys.data ?? []).length === 0 ? (
            <EmptyState>No API keys yet.</EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Key</TableHead>
                  <TableHead>Scope</TableHead>
                  <TableHead>Last used</TableHead>
                  <TableHead>Expires</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(keys.data ?? []).map((k) => (
                  <TableRow key={k.id} data-testid="api-key-row">
                    <TableCell className="font-medium">{k.name}</TableCell>
                    <TableCell className="font-mono text-xs">{k.prefix}…</TableCell>
                    <TableCell className="text-xs">{k.deployment_id ? `Deployment ${shortId(k.deployment_id)}` : 'All deployments'}</TableCell>
                    <TableCell className="text-xs">{ago(k.last_used_at)}</TableCell>
                    <TableCell className="text-xs">{dateTime(k.expires_at, 'Never')}</TableCell>
                    <TableCell>{state(k)}</TableCell>
                    <TableCell className="text-right">
                      {!k.revoked_at && (
                        <ConfirmButton
                          size="sm"
                          variant="ghost"
                          confirmLabel="Revoke"
                          onConfirm={() =>
                            revoke.mutateAsync(k.id).then(
                              () => toast.success('Key revoked'),
                              (e) => toast.error(errorMessage(e)),
                            )
                          }
                        >
                          Revoke
                        </ConfirmButton>
                      )}
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
