import type { UserRole } from '@/types';

/** Dashboard home for each role. Authorization itself is enforced by the API, not by these routes. */
export function homeFor(role: UserRole | string | undefined): string {
  if (role === 'provider') return '/provider';
  if (role === 'operator' || role === 'admin') return '/operator';
  return '/customer';
}
