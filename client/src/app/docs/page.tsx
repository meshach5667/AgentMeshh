import Link from 'next/link';
import { ArrowRight, BookOpen, Code2, Server, ShieldCheck, Users, Wrench } from 'lucide-react';
import { TrustNotice } from '@/components/common/Notices';
import { API_URL, DASHBOARD_URL, RELEASES_URL, REPO_URL } from '@/lib/config';
import { DOC_PAGES } from '@/lib/docs';

const ICONS = [BookOpen, Users, Server, Code2, Wrench, ShieldCheck];

const LINKS = [
  ['Dashboard', DASHBOARD_URL],
  ['Become a provider', `${DASHBOARD_URL}/register?role=provider`],
  ['API base URL', API_URL],
  ['Worker releases', RELEASES_URL],
  ['Source code', REPO_URL],
];

export default function DocsHome() {
  return (
    <div className="max-w-4xl">
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">Documentation</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-[-0.03em] md:text-[2.75rem] md:leading-[1.1]">AgentMesh docs</h1>
      <p className="mt-4 max-w-2xl text-lg text-muted-foreground">
        AgentMesh runs open-weight AI models on computers contributed by independent providers, behind an
        OpenAI-compatible API. These guides cover using it, hosting it, building on it, and running your own network.
      </p>

      <div className="mt-10 grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
        {DOC_PAGES.map((p, i) => {
          const Icon = ICONS[i];
          return (
            <Link key={p.href} href={p.href} className="group bg-background p-6 transition-colors hover:bg-muted/40">
              <Icon className="size-5" strokeWidth={1.6} />
              <p className="mt-5 flex items-center gap-1.5 text-[15px] font-semibold">
                {p.title}
                <ArrowRight className="size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{p.summary}</p>
            </Link>
          );
        })}
      </div>

      <div className="mt-12 grid gap-8 lg:grid-cols-2">
        <div>
          <h2 className="text-lg font-semibold">Quick start</h2>
          <ol className="mt-4 space-y-3 text-sm">
            {[
              ['Deploy a model', 'Sign up as a customer, pick a model, deploy, and call it with an API key.', '/docs/customers'],
              ['Host models', 'Sign up as a provider, create an enrollment token, and install the worker.', '/docs/providers'],
              ['Integrate', 'Use any OpenAI client against your deployment’s /v1 endpoint.', '/docs/api'],
            ].map(([title, body, href], i) => (
              <li key={href} className="flex gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-border font-mono text-xs">{i + 1}</span>
                <span>
                  <Link href={href} className="font-medium underline decoration-border underline-offset-4 hover:decoration-foreground">{title}</Link>
                  <span className="block text-muted-foreground">{body}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
        <div>
          <h2 className="text-lg font-semibold">Live links</h2>
          <dl className="mt-4 divide-y divide-border rounded-lg border border-border text-sm">
            {LINKS.map(([label, href]) => (
              <div key={label} className="flex flex-col gap-0.5 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="min-w-0 truncate font-mono text-xs">
                  <a href={href} target="_blank" rel="noreferrer" className="hover:underline">{href.replace('https://', '')}</a>
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      <TrustNotice className="mt-12" />
    </div>
  );
}
