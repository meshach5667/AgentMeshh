import Link from 'next/link';
import { ArrowLeft, ArrowRight, Link2 } from 'lucide-react';
import { CodeBlock } from '@/components/common/CodeBlock';
import { Notice } from '@/components/common/Notices';
import { DOC_PAGES } from '@/lib/docs';
import { cn } from '@/lib/utils';

export function DocPage({ href, children }: { href: string; children: React.ReactNode }) {
  const index = DOC_PAGES.findIndex((p) => p.href === href);
  const page = DOC_PAGES[index];
  const prev = DOC_PAGES[index - 1];
  const next = DOC_PAGES[index + 1];
  return (
    <article className="max-w-3xl">
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">Documentation</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-[-0.03em] md:text-4xl">{page.title}</h1>
      <p className="mt-3 text-lg text-muted-foreground">{page.summary}</p>
      <div className="mt-10 space-y-14">{children}</div>
      <nav className="mt-16 grid gap-3 border-t border-border pt-8 sm:grid-cols-2" aria-label="Pagination">
        {prev ? (
          <Link href={prev.href} className="rounded-lg border border-border p-4 transition-colors hover:bg-muted/50">
            <span className="flex items-center gap-1 text-xs text-muted-foreground"><ArrowLeft className="size-3" /> Previous</span>
            <span className="mt-1 block text-sm font-medium">{prev.title}</span>
          </Link>
        ) : (
          <Link href="/docs" className="rounded-lg border border-border p-4 transition-colors hover:bg-muted/50">
            <span className="flex items-center gap-1 text-xs text-muted-foreground"><ArrowLeft className="size-3" /> Previous</span>
            <span className="mt-1 block text-sm font-medium">Overview</span>
          </Link>
        )}
        {next && (
          <Link href={next.href} className="rounded-lg border border-border p-4 text-right transition-colors hover:bg-muted/50 sm:col-start-2">
            <span className="flex items-center justify-end gap-1 text-xs text-muted-foreground">Next <ArrowRight className="size-3" /></span>
            <span className="mt-1 block text-sm font-medium">{next.title}</span>
          </Link>
        )}
      </nav>
    </article>
  );
}

export function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 space-y-4">
      <h2 className="group flex items-center gap-2 text-xl font-semibold tracking-tight md:text-2xl">
        {title}
        <a href={`#${id}`} aria-label={`Link to ${title}`} className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
          <Link2 className="size-4" />
        </a>
      </h2>
      {children}
    </section>
  );
}

export function H3({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    <h3 id={id} className="scroll-mt-24 pt-2 text-base font-semibold">
      {children}
    </h3>
  );
}

export function P({ children, className }: { children: React.ReactNode; className?: string }) {
  return <p className={cn('leading-7 text-foreground/85', className)}>{children}</p>;
}

export function List({ items, ordered }: { items: React.ReactNode[]; ordered?: boolean }) {
  const Tag = ordered ? 'ol' : 'ul';
  return (
    <Tag className={cn('space-y-2 pl-5 leading-7 text-foreground/85', ordered ? 'list-decimal' : 'list-disc')}>
      {items.map((item, i) => (
        <li key={i} className="pl-1">{item}</li>
      ))}
    </Tag>
  );
}

export function C({ children }: { children: React.ReactNode }) {
  return <code className="rounded border border-border bg-muted/60 px-1 py-0.5 font-mono text-[0.85em]">{children}</code>;
}

export function A({ href, children }: { href: string; children: React.ReactNode }) {
  const cls = 'font-medium underline decoration-border underline-offset-4 transition-colors hover:decoration-foreground';
  return href.startsWith('/') || href.startsWith('#') ? (
    <Link href={href} className={cls}>{children}</Link>
  ) : (
    <a href={href} className={cls} target="_blank" rel="noreferrer">{children}</a>
  );
}

export function Code({ code, title }: { code: string; title?: string }) {
  return (
    <div>
      {title && <p className="mb-1.5 font-mono text-xs text-muted-foreground">{title}</p>}
      <CodeBlock code={code} />
    </div>
  );
}

export function Callout({ tone = 'info', title, children }: { tone?: 'info' | 'warning' | 'danger'; title?: string; children: React.ReactNode }) {
  return <Notice tone={tone} title={title}>{children}</Notice>;
}

export function Table({ head, rows }: { head: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted/50">
          <tr>
            {head.map((h) => (
              <th key={h} className="whitespace-nowrap px-3 py-2 text-xs font-medium text-muted-foreground">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-2 align-top leading-6">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StatusPill({ status }: { status: 'working' | 'test-mode' | 'unverified' | 'planned' }) {
  const label = { working: 'Working', 'test-mode': 'Test mode', unverified: 'Not verified', planned: 'Planned' }[status];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium',
        status === 'working' && 'border-brand/30 text-foreground',
        status === 'test-mode' && 'border-amber-500/40 text-amber-700 dark:text-amber-300',
        status === 'unverified' && 'border-amber-500/40 text-amber-700 dark:text-amber-300',
        status === 'planned' && 'border-border text-muted-foreground',
      )}
    >
      <span
        className={cn(
          'size-1.5 rounded-full',
          status === 'working' && 'bg-brand',
          (status === 'test-mode' || status === 'unverified') && 'bg-amber-500',
          status === 'planned' && 'bg-muted-foreground/50',
        )}
      />
      {label}
    </span>
  );
}
