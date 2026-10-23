'use client';

import { useState } from 'react';
import { PageHeader } from '@/components/common/Notices';
import { UsageSummaryView } from '@/components/usage/UsageSummaryView';
import { useDeployments } from '@/hooks/useDeployments';
import { shortId } from '@/lib/format';

export default function CustomerUsagePage() {
  const [days, setDays] = useState(30);
  const deployments = useDeployments();
  const label = (id: string) => {
    const d = deployments.data?.find((x) => x.id === id);
    return d ? `${d.model_tag ?? 'deployment'} · ${shortId(id)}` : shortId(id);
  };
  return (
    <div className="space-y-6">
      <PageHeader
        title="Usage"
        description="Requests made to your deployments through the gateway. What you were charged is on the Wallet page."
      />
      <UsageSummaryView
        days={days}
        onDaysChange={setDays}
        deploymentHref={(id) => `/customer/deployments/${id}`}
        deploymentLabel={label}
      />
    </div>
  );
}
