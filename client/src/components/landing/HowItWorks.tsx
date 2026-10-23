import Link from 'next/link';
import { ArrowRight } from 'lucide-react';

const TRACKS = [
  {
    eyebrow: 'For developers',
    title: 'From catalog to endpoint in minutes',
    href: '/register',
    cta: 'Deploy a model',
    steps: [
      ['Pick a model', 'Browse approved open-weight models with their runtimes, memory needs and hourly price.'],
      ['Deploy', 'AgentMesh reserves capacity on a node, downloads and verifies the model, and runs a test generation.'],
      ['Call it', 'Create a scoped API key and use any OpenAI client. Watch requests, tokens and charges live.'],
    ],
  },
  {
    eyebrow: 'For providers',
    title: 'Turn idle machines into income',
    href: '/register?role=provider',
    cta: 'Become a provider',
    steps: [
      ['Install the worker', 'A per-user agent or a Docker worker. Outbound connections only; no ports to open.'],
      ['Set your limits', 'Cap CPU, memory and disk, set availability hours, and pause or drain any time.'],
      ['Get paid', 'Earn your share of every charge for the deployments you serve, paid out to your bank via Paystack.'],
    ],
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="border-y border-border bg-muted/30 py-28">
      <div className="mx-auto max-w-6xl px-6">
        <div className="max-w-2xl">
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">How it works</p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight md:text-[2.75rem] md:leading-[1.1]">A two-sided compute network.</h2>
        </div>
        <div className="mt-14 grid gap-6 lg:grid-cols-2">
          {TRACKS.map((t) => (
            <div key={t.eyebrow} className="flex flex-col rounded-xl border border-border bg-card p-8">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{t.eyebrow}</p>
              <h3 className="mt-2 text-2xl font-semibold tracking-tight">{t.title}</h3>
              <ol className="mt-8 flex-1 space-y-6">
                {t.steps.map(([title, body], i) => (
                  <li key={title} className="flex gap-4">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-border bg-background font-mono text-xs text-muted-foreground">
                      {i + 1}
                    </span>
                    <div>
                      <p className="font-medium">{title}</p>
                      <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{body}</p>
                    </div>
                  </li>
                ))}
              </ol>
              <Link href={t.href} className="mt-8 inline-flex items-center gap-1.5 text-sm font-medium underline-offset-4 hover:underline">
                {t.cta} <ArrowRight className="size-4" />
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
