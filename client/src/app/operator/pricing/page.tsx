'use client';

import { useState } from 'react';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Pill } from '@/components/common/StatusBadge';
import { EmptyState, ErrorState, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useCreatePricing, usePricing, usePricingVersions, type PricingInput } from '@/hooks/useBilling';
import { errorMessage } from '@/lib/errors';
import { dateTime, money } from '@/lib/format';

const FIELDS: { key: keyof PricingInput; label: string }[] = [
  { key: 'cpu_core_hour', label: 'CPU core, per hour' },
  { key: 'ram_gb_hour', label: 'Memory, per GB-hour' },
  { key: 'vram_gb_hour', label: 'GPU memory, per GB-hour' },
  { key: 'input_tokens_per_million', label: 'Input tokens, per million' },
  { key: 'output_tokens_per_million', label: 'Output tokens, per million' },
  { key: 'platform_fee_rate', label: 'Platform fee (0 to 0.5)' },
];

export default function OperatorPricingPage() {
  const versions = usePricingVersions();
  const pricing = usePricing();
  const create = useCreatePricing();
  const current = pricing.data?.current;
  const [form, setForm] = useState<Record<string, string>>({});
  const [effective, setEffective] = useState('');
  const [notes, setNotes] = useState('');

  if (versions.isLoading) return <PageSkeleton />;
  if (versions.error) return <ErrorState message={errorMessage(versions.error)} retry={() => versions.refetch()} />;
  const currency = pricing.data?.currency;
  const value = (k: keyof PricingInput) => form[k] ?? (current ? String(current[k as keyof typeof current] ?? '') : k === 'platform_fee_rate' ? '0.1' : '0');

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pricing"
        description={`Prices are versioned and immutable. A new version applies from its start time; earlier usage keeps the price it was rated at. Currency: ${currency ?? ''}.`}
      />
      <Card>
        <CardHeader>
          <CardTitle>Publish a new version</CardTitle>
          <CardDescription>Pre-filled with the version in force. Customers see the change on their wallet page.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              const body = Object.fromEntries(FIELDS.map(({ key }) => [key, value(key)])) as PricingInput;
              if (effective) body.effective_from = new Date(effective).toISOString();
              if (notes.trim()) body.notes = notes.trim();
              create.mutate(body, {
                onSuccess: (r) => {
                  toast.success(`Version ${r.version} published`);
                  setForm({});
                  setNotes('');
                  setEffective('');
                },
                onError: (err) => toast.error(errorMessage(err)),
              });
            }}
          >
            <div className="grid gap-4 sm:grid-cols-3">
              {FIELDS.map(({ key, label }) => (
                <div key={key} className="space-y-1">
                  <Label htmlFor={key}>{label}</Label>
                  <Input id={key} type="number" min={0} step="any" required value={value(key)} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
                </div>
              ))}
              <div className="space-y-1">
                <Label htmlFor="effective">Takes effect (local time, optional)</Label>
                <Input id="effective" type="datetime-local" value={effective} onChange={(e) => setEffective(e.target.value)} />
              </div>
              <div className="space-y-1 sm:col-span-2">
                <Label htmlFor="notes">Notes</Label>
                <Input id="notes" maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Why prices changed" />
              </div>
            </div>
            <Button type="submit" disabled={create.isPending}>
              Publish version
            </Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Versions</CardTitle>
        </CardHeader>
        <CardContent>
          {(versions.data ?? []).length === 0 ? (
            <EmptyState>No prices yet: usage is measured but not charged.</EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Version</TableHead>
                  <TableHead>From</TableHead>
                  <TableHead className="text-right">CPU/h</TableHead>
                  <TableHead className="text-right">GB-h</TableHead>
                  <TableHead className="text-right">VRAM GB-h</TableHead>
                  <TableHead className="text-right">In/1M</TableHead>
                  <TableHead className="text-right">Out/1M</TableHead>
                  <TableHead className="text-right">Fee</TableHead>
                  <TableHead>Notes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(versions.data ?? []).map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>
                      {r.version} {current?.id === r.id && <Pill tone="green">in force</Pill>}
                    </TableCell>
                    <TableCell className="text-xs">{dateTime(r.effective_from)}</TableCell>
                    {[r.cpu_core_hour, r.ram_gb_hour, r.vram_gb_hour, r.input_tokens_per_million, r.output_tokens_per_million].map((v, i) => (
                      <TableCell key={i} className="text-right font-mono text-xs">
                        {money(v, r.currency)}
                      </TableCell>
                    ))}
                    <TableCell className="text-right text-xs">{(Number(r.platform_fee_rate) * 100).toFixed(1)}%</TableCell>
                    <TableCell className="max-w-xs truncate text-xs text-muted-foreground">{r.notes}</TableCell>
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
