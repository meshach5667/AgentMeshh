'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useStoredSession } from '@/hooks/useStoredSession';

/** On /login and /register: a user who is already signed in goes straight to their dashboard. */
export function RedirectIfSignedIn() {
  const home = useStoredSession();
  const router = useRouter();
  useEffect(() => {
    if (home) router.replace(home);
  }, [home, router]);
  return null;
}

/** Goes to the signed-in user's dashboard, or to `signedOutHref` when no session is stored. */
export function DashboardLink({ className, signedOutHref = '/login', children }: { className?: string; signedOutHref?: string; children: React.ReactNode }) {
  const home = useStoredSession();
  return <Link href={home ?? signedOutHref} className={className}>{children}</Link>;
}
