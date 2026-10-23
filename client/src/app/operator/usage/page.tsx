'use client';

import { useState } from 'react';
import { PageHeader } from '@/components/common/Notices';
import { UsageSummaryView } from '@/components/usage/UsageSummaryView';

export default function OperatorUsagePage() {
  const [days, setDays] = useState(7);
  return (
    <div className="space-y-6">
      <PageHeader title="Network usage" description="All inference requests through the gateway." />
      <UsageSummaryView days={days} onDaysChange={setDays} scope="network" />
    </div>
  );
}
