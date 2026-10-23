'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { LogoMark } from '@/components/brand/Logo';
import { useAuth } from '../../hooks/useAuth';
import { homeFor } from '@/lib/roles';
import type { UserRole } from '@/types';

/** Sends signed-out users to /login and users of another role to their own dashboard. This is navigation only;
 * the API authorizes every request. */
export function AuthGuard({ children, roles }: { children: React.ReactNode; roles?: UserRole[] }) {
  const { user, token, isAuthenticated, isLoading, error, initialize } = useAuth();
  const router = useRouter();
  const allowed = !roles || (!!user && roles.includes(user.role));

  useEffect(() => {
    initialize();
  }, [initialize]);

  // A token we could not verify yet (API unreachable) is not a sign-out: offer a retry instead of /login.
  const unverified = !isLoading && !isAuthenticated && !!token;

  useEffect(() => {
    if (isLoading || unverified) return;
    if (!isAuthenticated) router.replace('/login');
    else if (!allowed) router.replace(homeFor(user?.role));
  }, [isAuthenticated, isLoading, unverified, allowed, user, router]);

  if (unverified) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-6">
        <div className="flex max-w-sm flex-col items-center gap-4 text-center">
          <LogoMark className="size-10" />
          <p className="text-sm text-muted-foreground">{error ?? 'Could not reach the server'}. You are still signed in.</p>
          <button
            type="button"
            onClick={() => initialize()}
            className="inline-flex h-9 items-center rounded-lg bg-foreground px-4 text-[13px] font-medium text-background transition-opacity hover:opacity-85"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }
  if (isLoading || !isAuthenticated || !allowed) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <LogoMark className="size-10 animate-pulse" />
          <p className="animate-pulse text-sm text-muted-foreground">Loading…</p>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
