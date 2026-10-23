'use client';

import { useState } from 'react';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ChargesTable } from '@/components/billing/ChargesTable';
import { StatCard } from '@/components/common/StatCard';
import { Pill, StatusBadge } from '@/components/common/StatusBadge';
import { EmptyState, ErrorState, Notice, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import {
  useBanks,
  useCharges,
  usePaymentsConfig,
  usePayoutAccount,
  usePayouts,
  useRequestPayout,
  useSetPayoutAccount,
} from '@/hooks/useBilling';
import { useEarnings } from '@/hooks/useEarnings';
import { errorMessage } from '@/lib/errors';
import { dateTime, money } from '@/lib/format';


export default function EarningsPage() {
  const earnings = useEarnings();
  const config = usePaymentsConfig();
  const charges = useCharges();
  const account = usePayoutAccount();
  const payouts = usePayouts();
  const enabled = !!config.data?.enabled;
  const banks = useBanks(enabled);
  const setAccount = useSetPayoutAccount();
  const requestPayout = useRequestPayout();
  const [bank, setBank] = useState('');
  const [accountNumber, setAccountNumber] = useState('');
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState('');

  if (earnings.isLoading) return <PageSkeleton />;
  if (earnings.error || !earnings.data) return <ErrorState message={errorMessage(earnings.error)} retry={() => earnings.refetch()} />;
  const e = earnings.data;
  const currency = config.data?.currency;
  const held = (payouts.data ?? []).filter((p) => ['REQUESTED', 'PENDING', 'OTP_REQUIRED'].includes(p.status));

  return (
    <div className="space-y-6">
      <PageHeader title="Earnings" description="Your share of what customers paid for deployments your nodes served." />
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard title="Available to withdraw" value={money(e.available_balance, currency)} />
        <StatCard title="Earned in total" value={money(e.total_earnings, currency)} hint="Settled provider credits" />
        <StatCard title="Payouts in progress" value={money(held.reduce((t, p) => t + Number(p.amount), 0), currency)} hint={`${held.length} payout(s)`} />
      </div>

      {!enabled ? (
        <Notice title="Payouts are not configured on this network">An operator must set up Paystack before payouts can be made.</Notice>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Payout account {config.data?.mode === 'test' && <Pill tone="amber">test mode</Pill>}
              </CardTitle>
              <CardDescription>Verified with your bank through Paystack. AgentMesh keeps only the last four digits.</CardDescription>
            </CardHeader>
            <CardContent>
              {account.data && !editing ? (
                <div className="space-y-2 text-sm">
                  <p data-testid="payout-account">
                    {account.data.account_name} · {account.data.bank_name ?? account.data.bank_code} · ••••{account.data.account_last4}
                  </p>
                  <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                    Change
                  </Button>
                </div>
              ) : (
                <form
                  className="space-y-3"
                  onSubmit={(ev) => {
                    ev.preventDefault();
                    setAccount.mutate(
                      { bank_code: bank, account_number: accountNumber },
                      {
                        onSuccess: () => {
                          toast.success('Payout account verified');
                          setEditing(false);
                          setAccountNumber('');
                        },
                        onError: (err) => toast.error(errorMessage(err)),
                      },
                    );
                  }}
                >
                  <div className="space-y-1">
                    <Label htmlFor="bank">Bank</Label>
                    <select id="bank" required value={bank} onChange={(ev) => setBank(ev.target.value)} className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm">
                      <option value="">{banks.isLoading ? 'Loading banks…' : 'Choose your bank'}</option>
                      {(banks.data ?? []).map((b) => (
                        <option key={b.code} value={b.code}>
                          {b.name}
                        </option>
                      ))}
                    </select>
                    {banks.error && <p className="text-xs text-rose-500">{errorMessage(banks.error)}</p>}
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="acct">Account number</Label>
                    <Input id="acct" inputMode="numeric" pattern="\d{6,20}" required value={accountNumber} onChange={(ev) => setAccountNumber(ev.target.value.trim())} />
                  </div>
                  <Button type="submit" disabled={setAccount.isPending}>
                    {setAccount.isPending ? 'Verifying…' : 'Verify and save'}
                  </Button>
                </form>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Request a payout</CardTitle>
              <CardDescription>
                The amount is held from your balance at once.{' '}
                {config.data?.payouts_require_approval ? 'An operator approves each payout before it is sent.' : 'It is sent right away.'} Minimum{' '}
                {money(config.data?.payout_min ?? 0, currency)}.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form
                className="flex items-end gap-2"
                onSubmit={(ev) => {
                  ev.preventDefault();
                  requestPayout.mutate(amount, {
                    onSuccess: () => {
                      toast.success('Payout requested');
                      setAmount('');
                    },
                    onError: (err) => toast.error(errorMessage(err)),
                  });
                }}
              >
                <Input aria-label="Payout amount" type="number" min={config.data?.payout_min} step="0.01" value={amount} onChange={(ev) => setAmount(ev.target.value)} required />
                <Button type="submit" disabled={!account.data || requestPayout.isPending || !amount}>
                  Request payout
                </Button>
              </form>
              {!account.data && <p className="mt-2 text-xs text-muted-foreground">Add a payout account first.</p>}
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Payouts</CardTitle>
        </CardHeader>
        <CardContent>
          {(payouts.data ?? []).length === 0 ? (
            <EmptyState>No payouts yet.</EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Requested</TableHead>
                  <TableHead>Reference</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(payouts.data ?? []).map((p) => (
                  <TableRow key={p.id} data-testid="payout-row">
                    <TableCell className="text-xs">{dateTime(p.created_at)}</TableCell>
                    <TableCell className="font-mono text-xs">{p.reference}</TableCell>
                    <TableCell>
                      <StatusBadge status={p.status} />
                      {p.failure_reason && <div className="text-xs text-muted-foreground">{p.failure_reason}</div>}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{money(p.amount, p.currency)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Earnings by charge</CardTitle>
          <CardDescription>Your share after the platform fee, for each billing window your nodes served.</CardDescription>
        </CardHeader>
        <CardContent>
          {charges.error ? (
            <ErrorState message={errorMessage(charges.error)} />
          ) : (
            <ChargesTable charges={charges.data ?? []} side="provider" empty="No earnings yet." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
