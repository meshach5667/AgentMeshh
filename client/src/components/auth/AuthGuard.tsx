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
  const { user, isAuthenticated, isLoading, initialize } = useAuth();
  const router = useRouter();
  const allowed = !roles || (!!user && roles.includes(user.role));

  useEffect(() => {
    initialize();
  }, [initialize]);

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) router.replace('/login');
    else if (!allowed) router.replace(homeFor(user?.role));
  }, [isAuthenticated, isLoading, allowed, user, router]);

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
