'use client';

import { Pill } from '@/components/common/StatusBadge';
import { useAiHealth } from '@/hooks/useAiDeployments';
import { AI_SERVICE_TEXT } from '@/lib/ai';

/** Availability of the AI agent. Shows no machine names, addresses, or credentials (the API returns none). */
export function AiHealthBadge() {
  const { data, isError } = useAiHealth();
  if (isError) return <Pill tone="gray">AI agent status unknown</Pill>;
  if (!data) return null;
  const tone = data.status === 'available' ? 'green' : data.status === 'degraded' ? 'amber' : 'red';
  return (
    <span className="inline-flex items-center gap-2" title={data.message} data-testid="ai-health">
      <Pill tone={tone}>{AI_SERVICE_TEXT[data.status]}</Pill>
      {data.queue_depth > 0 && <span className="text-xs text-muted-foreground">{data.queue_depth} queued</span>}
    </span>
  );
}
