import Link from 'next/link';
import { ArrowUpRight, Check } from 'lucide-react';
import { Logo } from '@/components/brand/Logo';
import { cn } from '@/lib/utils';

const POINTS = [
  'OpenAI-compatible endpoints for open-weight models',
  'Placement, health checks and failover handled for you',
  'Prepaid, itemised billing with provider payouts',
];

export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-background">
      <div className="grid min-h-screen lg:grid-cols-[1.04fr_0.96fr]">
        <section className="flex min-h-screen flex-col px-6 py-7 sm:px-10 lg:px-16 lg:py-9">
          <div className="flex items-center justify-between">
            <Logo />
            <Link href="/" className="text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
              Back to home
            </Link>
          </div>
          <div className="flex flex-1 items-center justify-center py-12 lg:py-16">
            <div className="w-full max-w-[420px]">{children}</div>
          </div>
          <div className="flex items-center justify-between gap-4 text-xs text-muted-foreground">
            <Link href="/#trust" className="transition-colors hover:text-foreground">
              How AgentMesh handles your data
            </Link>
            <span>© {new Date().getFullYear()} AgentMesh</span>
          </div>
        </section>

        <aside className="relative hidden min-h-screen flex-col justify-between border-l border-white/10 bg-[oklch(0.13_0_0)] px-12 py-10 text-white lg:flex xl:px-16">
          <p className="font-mono text-xs uppercase tracking-wider text-white/45">AgentMesh network</p>

          <div className="py-14">
            <h2 className="max-w-md text-4xl font-semibold leading-[1.1] tracking-[-0.035em] xl:text-[2.75rem]">
              Open models.
              <br />
              Shared compute.
              <br />
              <span className="text-white/45">One API.</span>
            </h2>
            <ul className="mt-8 space-y-3">
              {POINTS.map((point) => (
                <li key={point} className="flex items-center gap-3 text-sm text-white/65">
                  <Check className="size-4 shrink-0 text-white/80" />
                  {point}
                </li>
              ))}
            </ul>
            <div className="mt-12 max-w-md overflow-hidden rounded-lg border border-white/10 bg-white/[0.03]">
              <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
                <span className="font-mono text-[11px] text-white/50">POST /v1/chat/completions</span>
                <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-white/70">
                  <span className="size-1.5 rounded-full bg-emerald-400" /> 200
                </span>
              </div>
              <pre className="overflow-x-auto px-4 py-4 font-mono text-[12px] leading-6 text-white/70">
{`{
  "model": "qwen2.5:0.5b",
  "messages": [
    { "role": "user", "content": "Hello" }
  ]
}`}
              </pre>
            </div>
          </div>

          <div className="flex items-center justify-between border-t border-white/10 pt-5 text-xs text-white/45">
            <span>Compute from independent providers</span>
            <Link href="/#how-it-works" className="inline-flex items-center gap-1.5 transition-colors hover:text-white/80">
              How it works <ArrowUpRight className="size-3.5" />
            </Link>
          </div>
        </aside>
      </div>
    </main>
  );
}

export function Field({ label, children, aside }: { label: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <label className="block space-y-2">
      <span className="flex items-center justify-between text-[13px] font-medium text-foreground/85">
        {label}
        {aside}
      </span>
      {children}
    </label>
  );
}

export const inputClass = cn(
  'h-11 w-full rounded-lg border border-input bg-background px-3.5 text-sm outline-none transition-colors',
  'placeholder:text-muted-foreground/60 hover:border-foreground/25 focus:border-foreground/50 focus:ring-3 focus:ring-foreground/10',
);

export const submitClass =
  'inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-foreground px-5 text-sm font-medium text-background transition-opacity hover:opacity-85 disabled:opacity-50';
