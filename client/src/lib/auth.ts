import type { User } from '../types/user';

const TOKEN_KEY = 'token';
const USER_KEY = 'user';

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function removeToken(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

/** The signed-in user, cached so a reload or a slow API (Render cold start) does not sign the user out. */
export function getCachedUser(): User | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function setCachedUser(user: User): void {
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

/** True when the JWT's `exp` claim is in the past. A token that cannot be decoded is left for the API to judge. */
export function isTokenExpired(token: string, now = Date.now()): boolean {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const { exp } = JSON.parse(atob(payload)) as { exp?: number };
    return typeof exp === 'number' && exp * 1000 <= now;
  } catch {
    return false;
  }
}

/** A stored, unexpired token: what the UI treats as "signed in" before the API confirms it. */
export function hasSession(): boolean {
  const token = getToken();
  return !!token && !isTokenExpired(token);
}
