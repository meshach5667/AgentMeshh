import Link from 'next/link';
import { ArrowRight } from 'lucide-react';

export function CTA() {
  return (
    <section className="py-28">
      <div className="mx-auto max-w-6xl px-6">
        <div className="relative overflow-hidden rounded-xl border border-border bg-foreground px-8 py-16 text-center text-background md:px-16">
          <h2 className="relative text-4xl font-semibold tracking-tight md:text-5xl">Ship your first model today.</h2>
          <p className="relative mx-auto mt-4 max-w-xl text-lg opacity-70">
            Start with a small model like SmolLM2 or Qwen2.5 and have an OpenAI-compatible endpoint in minutes.
          </p>
          <div className="relative mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link href="/register" className="inline-flex h-11 items-center gap-2 rounded-lg bg-background px-5 text-sm font-medium text-foreground transition-opacity hover:opacity-90">
              Get started <ArrowRight className="size-4" />
            </Link>
            <Link href="/register?role=provider" className="inline-flex h-11 items-center rounded-lg border border-background/20 px-5 text-sm font-medium transition-colors hover:bg-background/10">
              Become a provider
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
