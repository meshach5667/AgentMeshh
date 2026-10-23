import { useSyncExternalStore } from 'react';
import { getCachedUser, hasSession } from '../lib/auth';
import { homeFor } from '../lib/roles';

function subscribe(onChange: () => void) {
  window.addEventListener('storage', onChange);
  return () => window.removeEventListener('storage', onChange);
}

/** The signed-in user's dashboard path, read from storage without an API call; null when signed out and during
 * server rendering, so pages hydrate as signed out and switch once the browser has read the session. */
export function useStoredSession(): string | null {
  return useSyncExternalStore(
    subscribe,
    () => (hasSession() ? homeFor(getCachedUser()?.role) : null),
    () => null,
  );
}
