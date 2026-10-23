'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ChargesTable } from '@/components/billing/ChargesTable';
import { PricingCard } from '@/components/billing/PricingCard';
import { StatCard } from '@/components/common/StatCard';
import { Pill, StatusBadge } from '@/components/common/StatusBadge';
import { ErrorState, Notice, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useCharges, useCreateTopup, usePaymentsConfig, useTopups, useVerifyTopup } from '@/hooks/useBilling';
import { useAddTestCredits, useWallet } from '@/hooks/useWallet';
import { isPaystackCheckout, returnedReference, sumAmounts } from '@/lib/billing';
import { errorMessage } from '@/lib/errors';
import { dateTime, money } from '@/lib/format';

function Wallet() {
  const router = useRouter();
  const params = useSearchParams();
  const wallet = useWallet();
  const config = usePaymentsConfig();
  const topups = useTopups();
  const charges = useCharges();
  const createTopup = useCreateTopup();
  const verify = useVerifyTopup();
  const addCredits = useAddTestCredits();
  const [amount, setAmount] = useState('');
  const [testAmount, setTestAmount] = useState('1000');
  const verifiedRef = useRef<string | null>(null);

  // Returning from Paystack checkout: ask the server to confirm with Paystack, then clean the URL.
  const reference = returnedReference(params);
  useEffect(() => {
    if (!reference || verifiedRef.current === reference) return;
    verifiedRef.current = reference;
    verify.mutate(reference, {
      onSuccess: (p) => {
        if (p.status === 'SUCCEEDED') toast.success(`${money(p.amount, p.currency)} added to your wallet`);
        else if (p.status === 'INITIALIZED') toast('Payment not confirmed yet. It will be credited when Paystack confirms it.');
        else toast.error(`Payment ${p.status.toLowerCase()}${p.failure_reason ? `: ${p.failure_reason}` : ''}`);
        router.replace('/customer/wallet');
      },
      onError: (e) => toast.error(errorMessage(e)),
    });
  }, [reference, verify, router]);

  if (wallet.isLoading || config.isLoading) return <PageSkeleton />;
  if (wallet.error || !wallet.data) return <ErrorState message={errorMessage(wallet.error)} retry={() => wallet.refetch()} />;
  const cfg = config.data;
  const currency = wallet.data.currency;
  const spent = sumAmounts(charges.data ?? []);

  return (
    <div className="space-y-6">
      <PageHeader title="Wallet" description="Prepaid balance for your deployments." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard title="Balance" value={money(wallet.data.balance, currency)} hint={Number(wallet.data.balance) < 0 ? 'Top up to deploy again' : currency} />
        <StatCard title="Charged (recent)" value={money(spent, currency)} hint="Sum of the charges listed below" />
      </div>

      {cfg?.enabled ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Add funds {cfg.mode === 'test' && <Pill tone="amber">Paystack test mode: no real money</Pill>}
            </CardTitle>
            <CardDescription>
              You pay on Paystack&apos;s checkout page. Your balance is credited once Paystack confirms the payment.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex max-w-md items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                createTopup.mutate(amount, {
                  onSuccess: (p) => {
                    if (isPaystackCheckout(p.authorization_url)) window.location.assign(p.authorization_url);
                    else toast.error('Paystack did not return a valid checkout link');
                  },
                  onError: (err) => toast.error(errorMessage(err)),
                });
              }}
            >
              <div className="flex-1 space-y-1">
                <label htmlFor="topup" className="text-xs text-muted-foreground">
                  Amount ({cfg.currency}, {cfg.topup_min} to {cfg.topup_max})
                </label>
                <Input id="topup" type="number" min={cfg.topup_min} max={cfg.topup_max} step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required />
              </div>
              <Button type="submit" disabled={createTopup.isPending || !amount}>
                {createTopup.isPending ? 'Opening Paystack…' : 'Pay with Paystack'}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : (
        <Notice title="Card payments are not configured on this network">
          An operator must set a Paystack secret key before customers can add funds.
        </Notice>
      )}

      {cfg?.test_credits && (
        <Card>
          <CardHeader>
            <CardTitle>Add test credits</CardTitle>
            <CardDescription>Development environments only. Unpaid and without value.</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex max-w-sm items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                addCredits.mutate(Number(testAmount), {
                  onSuccess: () => toast.success('Test credits added'),
                  onError: (err) => toast.error(errorMessage(err)),
                });
              }}
            >
              <Input aria-label="Test credit amount" type="number" min={1} value={testAmount} onChange={(e) => setTestAmount(e.target.value)} />
              <Button type="submit" variant="outline" disabled={addCredits.isPending}>
                Add test credits
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      <PricingCard />

      {(topups.data ?? []).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Top-ups</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Reference</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(topups.data ?? []).map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="text-xs">{dateTime(p.created_at)}</TableCell>
                    <TableCell className="font-mono text-xs">{p.reference}</TableCell>
                    <TableCell>
                      <StatusBadge status={p.status} />
                      {p.failure_reason && <div className="text-xs text-muted-foreground">{p.failure_reason}</div>}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{money(p.amount, p.currency)}</TableCell>
                    <TableCell className="text-right">
                      {p.status === 'INITIALIZED' && (
                        <Button size="sm" variant="ghost" disabled={verify.isPending} onClick={() => verify.mutate(p.reference, { onError: (e) => toast.error(errorMessage(e)) })}>
                          Check status
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Recent charges</CardTitle>
        </CardHeader>
        <CardContent>
          <ChargesTable charges={charges.data ?? []} empty="No charges yet." />
        </CardContent>
      </Card>
    </div>
  );
}

export default function WalletPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Wallet />
    </Suspense>
  );
}
