'use client';

import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import { useStoredSession } from '@/hooks/useStoredSession';

const primary = 'inline-flex h-9 items-center rounded-lg bg-foreground px-4 text-[13px] font-medium text-background transition-opacity hover:opacity-85';

export function HeaderAuthLinks() {
  const home = useStoredSession();
  if (home) {
    return (
      <Link href={home} className={`group gap-1.5 ${primary}`}>
        Dashboard <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
      </Link>
    );
  }
  return (
    <>
      <Link href="/login" className="group hidden h-9 items-center gap-1.5 px-2 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground sm:inline-flex">
        Sign in <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
      </Link>
      <Link href="/register" className={primary}>
        Get started
      </Link>
    </>
  );
}
