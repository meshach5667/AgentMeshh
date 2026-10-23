'use client';

import { AccountCard } from '@/components/account/AccountCard';
import Link from 'next/link';
import { PageHeader } from '@/components/common/Notices';

export default function ProviderSettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Settings" />
      <AccountCard />
      <p className="text-sm text-muted-foreground">
        Your payout bank account is managed on the{' '}
        <Link href="/provider/earnings" className="underline underline-offset-4">
          Earnings &amp; Payouts
        </Link>{' '}
        page. Node credentials are per machine: create an enrollment token under Add a Machine, and revoke a machine
        from its node page.
      </p>
    </div>
  );
}
