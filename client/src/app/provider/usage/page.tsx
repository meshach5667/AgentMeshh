'use client';

import { useState } from 'react';
import { PageHeader } from '@/components/common/Notices';
import { UsageSummaryView } from '@/components/usage/UsageSummaryView';

export default function ProviderUsagePage() {
  const [days, setDays] = useState(30);
  return (
    <div className="space-y-6">
      <PageHeader
        title="Served usage"
        description="Inference requests answered by your nodes, from the gateway's metering. Content is never recorded."
      />
      <UsageSummaryView days={days} onDaysChange={setDays} />
    </div>
  );
}
