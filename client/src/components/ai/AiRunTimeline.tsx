import { StatusBadge, Pill } from '@/components/common/StatusBadge';
import { dateTime } from '@/lib/format';
import type { AiRunEvent } from '@/types';

const KIND_LABEL: Record<AiRunEvent['kind'], string> = {
  state: 'status',
  tool: 'tool',
  ai: 'AI',
  info: 'note',
  error: 'error',
};

export function AiRunTimeline({ events }: { events: AiRunEvent[] }) {
  if (events.length === 0) return <p className="text-sm text-muted-foreground">No events yet.</p>;
  return (
    <ol className="relative space-y-4 border-l border-border pl-5" data-testid="ai-run-events">
      {events.map((e, i) => (
        <li key={`${e.created_at}-${i}`} className="relative">
          <span className="absolute -left-[1.6rem] top-1.5 size-2.5 rounded-full border-2 border-background bg-muted-foreground" />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {e.to_status ? (
              <StatusBadge status={e.to_status} />
            ) : (
              <Pill tone={e.kind === 'error' ? 'red' : e.kind === 'ai' ? 'blue' : 'gray'}>{KIND_LABEL[e.kind]}</Pill>
            )}
            <span className="text-xs text-muted-foreground">{dateTime(e.created_at)}</span>
          </div>
          {e.message && <p className="mt-1 text-sm break-words text-muted-foreground">{e.message}</p>}
        </li>
      ))}
    </ol>
  );
}
