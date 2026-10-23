'use client';

import Link from 'next/link';
import { AccountCard } from '@/components/account/AccountCard';
import { PageHeader } from '@/components/common/Notices';

export default function CustomerSettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Settings" />
      <AccountCard />
      <p className="text-sm text-muted-foreground">
        Programmatic access uses{' '}
        <Link href="/customer/api-keys" className="underline underline-offset-4">
          API keys
        </Link>
        .
      </p>
    </div>
  );
}
