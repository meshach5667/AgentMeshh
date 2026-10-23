'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { ArrowUpRight, Search } from 'lucide-react';
import { Logo } from '@/components/brand/Logo';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { DashboardLink } from '@/components/auth/SessionLinks';
import { REPO_URL } from '@/lib/config';
import { DOC_PAGES, searchDocs } from '@/lib/docs';
import { cn } from '@/lib/utils';

function DocsSearch() {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const hits = searchDocs(query);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(target.tagName)) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const go = (href: string) => {
    setOpen(false);
    setQuery('');
    input.current?.blur();
    router.push(href);
  };

  return (
    <div className="relative w-full max-w-xs">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
      <input
        ref={input}
        type="search"
        value={query}
        placeholder="Search docs"
        aria-label="Search documentation"
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive((i) => Math.min(i + 1, hits.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((i) => Math.max(i - 1, 0));
          } else if (e.key === 'Enter' && hits[active]) {
            go(hits[active].href);
          } else if (e.key === 'Escape') {
            input.current?.blur();
          }
        }}
        className="h-8 w-full rounded-md border border-input bg-background pl-8 pr-8 text-[13px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-foreground/40"
      />
      <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-border px-1 font-mono text-[10px] text-muted-foreground sm:block">/</kbd>
      {open && query && (
        <div className="absolute left-0 right-0 top-10 z-50 overflow-hidden rounded-lg border border-border bg-popover shadow-lifted sm:right-auto sm:w-80">
          {hits.length ? (
            <ul role="listbox">
              {hits.map((h, i) => (
                <li key={h.href} role="option" aria-selected={i === active}>
                  <button
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => go(h.href)}
                    onMouseEnter={() => setActive(i)}
                    className={cn('block w-full px-3 py-2 text-left', i === active && 'bg-accent')}
                  >
                    <span className="block text-[13px] font-medium">{h.title}</span>
                    <span className="block text-[11px] text-muted-foreground">{h.page}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-3 py-3 text-[13px] text-muted-foreground">No results for &ldquo;{query}&rdquo;</p>
          )}
        </div>
      )}
    </div>
  );
}

function DocsNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Documentation" className="space-y-0.5">
      <Link
        href="/docs"
        onClick={onNavigate}
        className={cn('block rounded-md px-2.5 py-1.5 text-[13px] transition-colors', pathname === '/docs' ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')}
      >
        Overview
      </Link>
      {DOC_PAGES.map((p) => {
        const active = pathname === p.href;
        return (
          <div key={p.href}>
            <Link
              href={p.href}
              onClick={onNavigate}
              className={cn('block rounded-md px-2.5 py-1.5 text-[13px] transition-colors', active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')}
            >
              {p.title}
            </Link>
            {active && (
              <ul className="mb-2 ml-2.5 mt-1 space-y-0.5 border-l border-border pl-3">
                {p.sections.map((s) => (
                  <li key={s.id}>
                    <a href={`#${s.id}`} onClick={onNavigate} className="block py-0.5 text-[12.5px] text-muted-foreground transition-colors hover:text-foreground">
                      {s.title}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </nav>
  );
}

export function DocsShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [menu, setMenu] = useState(false);
  const current = DOC_PAGES.find((p) => p.href === pathname);
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6">
          <div className="flex shrink-0 items-center gap-2">
            <Logo />
            <span className="text-border">/</span>
            <Link href="/docs" className="text-[13px] font-medium">Docs</Link>
          </div>
          <div className="flex flex-1 justify-end md:justify-start md:pl-8">
            <DocsSearch />
          </div>
          <div className="hidden items-center gap-1 md:flex">
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-md px-2.5 text-[13px] text-muted-foreground hover:text-foreground">
              GitHub <ArrowUpRight className="size-3.5" />
            </a>
            <ThemeToggle />
            <DashboardLink className="ml-1 inline-flex h-8 items-center rounded-md bg-foreground px-3 text-[13px] font-medium text-background transition-opacity hover:opacity-85">
              Dashboard
            </DashboardLink>
          </div>
        </div>
        <div className="border-t border-border px-4 md:hidden">
          <button type="button" onClick={() => setMenu((m) => !m)} aria-expanded={menu} className="flex h-10 w-full items-center justify-between text-[13px]">
            <span className="font-medium">{current?.title ?? 'Overview'}</span>
            <span className="text-muted-foreground">{menu ? 'Close' : 'Menu'}</span>
          </button>
          {menu && (
            <div className="max-h-[70vh] overflow-y-auto pb-4">
              <DocsNav onNavigate={() => setMenu(false)} />
              <div className="mt-3 flex items-center gap-2 border-t border-border pt-3">
                <ThemeToggle />
                <a href={REPO_URL} className="text-[13px] text-muted-foreground">GitHub</a>
              </div>
            </div>
          )}
        </div>
      </header>
      <div className="mx-auto flex max-w-7xl gap-10 px-4 sm:px-6">
        <aside className="sticky top-14 hidden h-[calc(100vh-3.5rem)] w-56 shrink-0 overflow-y-auto py-8 md:block">
          <DocsNav />
        </aside>
        <main className="min-w-0 flex-1 py-10 md:py-12">{children}</main>
      </div>
    </div>
  );
}
