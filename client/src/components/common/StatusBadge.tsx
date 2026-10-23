import { cn } from '@/lib/utils';

const TONE: Record<string, string> = {
  green: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  blue: 'bg-brand-soft text-brand border-brand/25',
  amber: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/30',
  red: 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/30',
  gray: 'bg-muted text-muted-foreground border-border',
};

const STATUS_TONE: Record<string, keyof typeof TONE> = {
  // deployments
  READY: 'green',
  REQUESTED: 'blue',
  SCHEDULED: 'blue',
  PROVISIONING: 'blue',
  STARTING: 'blue',
  STOPPING: 'amber',
  UNHEALTHY: 'amber',
  FAILED: 'red',
  STOPPED: 'gray',
  CANCELLED: 'gray',
  // AI deployment runs
  PLANNING: 'blue',
  SUBMITTING: 'blue',
  DEPLOYING: 'blue',
  VERIFYING: 'blue',
  RECOVERING: 'amber',
  COMPLETED: 'gray',
  // nodes
  ONLINE: 'green',
  AVAILABLE: 'green',
  BUSY: 'blue',
  REGISTERING: 'blue',
  DEGRADED: 'amber',
  OFFLINE: 'red',
  SUSPENDED: 'red',
  REVOKED: 'red',
  // ledger
  SETTLED: 'green',
  PENDING: 'amber',
  AUTHORIZED: 'blue',
  REFUNDED: 'gray',
  // payments and payouts
  INITIALIZED: 'blue',
  SUCCEEDED: 'green',
  ABANDONED: 'gray',
  REVIEW: 'amber',
  OTP_REQUIRED: 'amber',
  REVERSED: 'red',
  REJECTED: 'red',
};

const PULSE = new Set(['REQUESTED', 'SCHEDULED', 'PROVISIONING', 'STARTING', 'STOPPING', 'PLANNING', 'SUBMITTING', 'DEPLOYING', 'VERIFYING', 'RECOVERING']);

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const tone = TONE[STATUS_TONE[status] ?? 'gray'];
  return (
    <span
      data-status={status}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11px] font-medium tracking-wide whitespace-nowrap',
        tone,
        className,
      )}
    >
      <span className={cn('size-1.5 rounded-full bg-current', PULSE.has(status) && 'animate-pulse')} />
      {status}
    </span>
  );
}

export function Pill({ children, tone = 'gray', className }: { children: React.ReactNode; tone?: keyof typeof TONE; className?: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium', TONE[tone], className)}>
      {children}
    </span>
  );
}
