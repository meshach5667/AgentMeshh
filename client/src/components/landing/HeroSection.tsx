import Link from 'next/link';
import { ArrowRight, ArrowUpRight, Check } from 'lucide-react';
import { CodeWindow } from './CodeWindow';

const PIPELINE = [
  ['Your app', 'Any OpenAI client'],
  ['AgentMesh gateway', 'Keys, metering, routing'],
  ['Provider nodes', 'Ollama · llama.cpp · vLLM'],
] as const;

const EVENTS = [
  ['Scheduled', 'Capacity reserved on a matching node'],
  ['Model verified', 'Weights pinned and checked by digest'],
  ['Ready', 'Test generation passed, endpoint live'],
] as const;

export function HeroSection() {
  return (
    <section className="relative isolate overflow-hidden border-b border-border pt-32 md:pt-40">
      <div className="bg-grid mask-fade-b pointer-events-none absolute inset-x-0 top-0 h-[520px] opacity-60" />
      <div className="relative mx-auto max-w-6xl px-6">
        <div className="mx-auto max-w-4xl text-center">
          <Link
            href="#status"
            className="inline-flex items-center gap-2 rounded-full border border-border bg-background py-1 pl-2.5 pr-3 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <span className="size-1.5 rounded-full bg-brand" />
            Open beta: community compute network
            <ArrowRight className="size-3" />
          </Link>
          <h1 className="mt-7 text-[2.6rem] font-semibold leading-[1.05] tracking-[-0.045em] sm:text-6xl md:text-[4rem]">
            Run open models on
            <br className="hidden sm:block" /> compute you don&apos;t manage.
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground">
            Deploy open-weight models onto a network of independent machines and call them through an
            OpenAI-compatible API. Placement, health checks, failover and billing are handled for you.
          </p>
          <div className="mt-9 flex flex-col justify-center gap-3 sm:flex-row">
            <Link
              href="/register"
              className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-foreground px-5 text-sm font-medium text-background transition-opacity hover:opacity-85"
            >
              Start deploying <ArrowRight className="size-4" />
            </Link>
            <Link
              href="/register?role=provider"
              className="inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-border bg-background px-5 text-sm font-medium transition-colors hover:bg-muted"
            >
              Contribute compute <ArrowUpRight className="size-4" />
            </Link>
          </div>
          <ul className="mt-7 flex flex-wrap justify-center gap-x-6 gap-y-2 text-[13px] text-muted-foreground">
            {['OpenAI-compatible', 'Automatic failover', 'Pay only while serving'].map((t) => (
              <li key={t} className="flex items-center gap-1.5">
                <Check className="size-3.5 text-brand" /> {t}
              </li>
            ))}
          </ul>
        </div>

        <div className="relative mt-16 md:mt-20">
          <div className="rounded-t-xl border border-b-0 border-border bg-muted/40 p-2 shadow-lifted sm:p-3">
            <div className="grid overflow-hidden rounded-lg border border-border bg-background lg:grid-cols-[1.35fr_1fr]">
              <div className="border-b border-border lg:border-b-0 lg:border-r">
                <CodeWindow />
              </div>
              <div className="flex flex-col">
                <div className="flex items-center justify-between border-b border-border px-5 py-3">
                  <p className="text-[13px] font-medium">qwen2.5-0.5b</p>
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-[11px] font-medium">
                    <span className="size-1.5 rounded-full bg-brand" /> Ready
                  </span>
                </div>
                <ol className="flex-1 space-y-4 px-5 py-5">
                  {EVENTS.map(([title, body]) => (
                    <li key={title} className="flex gap-3">
                      <span className="mt-1 flex size-4 shrink-0 items-center justify-center rounded-full border border-border">
                        <Check className="size-2.5 text-brand" />
                      </span>
                      <div>
                        <p className="text-[13px] font-medium">{title}</p>
                        <p className="text-[12px] text-muted-foreground">{body}</p>
                      </div>
                    </li>
                  ))}
                </ol>
                <div className="hidden grid-cols-3 border-t border-border sm:grid">
                  {PIPELINE.map(([title, body], i) => (
                    <div key={title} className={i ? 'border-l border-border px-3 py-3' : 'px-3 py-3'}>
                      <p className="text-[11px] font-medium">{title}</p>
                      <p className="mt-0.5 text-[10px] leading-snug text-muted-foreground">{body}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
