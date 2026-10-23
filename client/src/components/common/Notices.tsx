import Link from 'next/link';
import { AlertTriangle, Inbox, Info, ShieldAlert } from 'lucide-react';
import { cn } from '@/lib/utils';

export function Notice({
  tone = 'info',
  title,
  children,
  className,
}: {
  tone?: 'info' | 'warning' | 'danger';
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const Icon = tone === 'info' ? Info : tone === 'warning' ? AlertTriangle : ShieldAlert;
  return (
    <div
      role={tone === 'info' ? 'note' : 'alert'}
      className={cn(
        'flex gap-3 rounded-xl border p-4 text-sm',
        tone === 'info' && 'border-brand/25 bg-brand-soft/60',
        tone === 'warning' && 'border-amber-500/30 bg-amber-500/[0.06]',
        tone === 'danger' && 'border-rose-500/30 bg-rose-500/[0.06]',
        className,
      )}
    >
      <Icon
        className={cn(
          'mt-0.5 size-4 shrink-0',
          tone === 'info' && 'text-brand',
          tone === 'warning' && 'text-amber-500',
          tone === 'danger' && 'text-rose-500',
        )}
      />
      <div className="space-y-1">
        {title && <p className="font-medium">{title}</p>}
        <div className="text-muted-foreground">{children}</div>
      </div>
    </div>
  );
}

/** The trust model, stated the same way everywhere it appears (see docs/IMPLEMENTATION_PLAN.md). */
export function TrustNotice({ className }: { className?: string }) {
  return (
    <Notice tone="warning" title="Your requests run on a computer owned by an independent provider" className={className}>
      The provider can see the model, its memory, and every prompt and response this deployment handles. Container
      isolation protects the provider&apos;s machine; it does not hide your data from the provider. Do not send
      secrets, personal data, or anything confidential. Confidential computing is not available.
    </Notice>
  );
}

/** Marks a feature that exists in the product plan but is not implemented. */
export function PlannedNotice({ feature, children }: { feature: string; children?: React.ReactNode }) {
  return (
    <Notice tone="info" title={`${feature}: not available yet`}>
      {children ?? 'This is planned and not implemented. Nothing on this page simulates it.'}
    </Notice>
  );
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <Notice tone="danger" title="Could not load this page">
      <span>{message}</span>
      {retry && (
        <button type="button" onClick={retry} className="ml-2 underline">
          Try again
        </button>
      )}
    </Notice>
  );
}

export function EmptyState({ children, action }: { children: React.ReactNode; action?: { href: string; label: string } }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-border px-6 py-12 text-center text-sm text-muted-foreground">
      <span className="mb-3 flex size-10 items-center justify-center rounded-full bg-muted">
        <Inbox className="size-4" />
      </span>
      <p className="max-w-sm">{children}</p>
      {action && (
        <Link
          href={action.href}
          className="mt-4 inline-flex h-8 items-center rounded-lg bg-primary px-3 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
        >
          {action.label}
        </Link>
      )}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-4 border-b border-border/80 pb-7 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-[28px] font-semibold tracking-[-0.04em]">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
