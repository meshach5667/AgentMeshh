import { Pill } from '@/components/common/StatusBadge';
import { nodeAvailability } from '@/lib/nodes';
import type { Node } from '@/types';

export function NodeAvailabilityBadge({ node }: { node: Node }) {
  const a = nodeAvailability(node);
  return (
    <span title={a.detail}>
      <Pill tone={a.tone}>{a.label}</Pill>
    </span>
  );
}
