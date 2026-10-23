import { create } from 'zustand';
import type { User, UserRole } from '../types/user';
import api from '../lib/api';
import { errorMessage } from '../lib/errors';
import { setToken, removeToken, getToken, getCachedUser, setCachedUser, isTokenExpired } from '../lib/auth';

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, role: UserRole) => Promise<void>;
  logout: () => void;
  initialize: () => Promise<void>;
  clearError: () => void;
}

const signedOut = { user: null, token: null, isAuthenticated: false, isLoading: false };

// One /auth/me check at a time, however many guards mount while it is in flight.
let verifying: Promise<void> | null = null;

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,

  login: async (email: string, password: string) => {
    set({ isLoading: true, error: null });
    try {
      const { data } = await api.post('/auth/login', { email, password });
      setToken(data.access_token);
      setCachedUser(data.user);
      set({
        token: data.access_token,
        user: data.user,
        isAuthenticated: true,
        isLoading: false,
      });
    } catch (err) {
      const message = errorMessage(err, 'Login failed');
      set({ error: message, isLoading: false });
      throw new Error(message);
    }
  },

  register: async (email: string, password: string, role: UserRole) => {
    set({ isLoading: true, error: null });
    try {
      const { data } = await api.post('/auth/register', { email, password, role });
      setToken(data.access_token);
      setCachedUser(data.user);
      set({
        token: data.access_token,
        user: data.user,
        isAuthenticated: true,
        isLoading: false,
      });
    } catch (err) {
      const message = errorMessage(err, 'Registration failed');
      set({ error: message, isLoading: false });
      throw new Error(message);
    }
  },

  logout: () => {
    removeToken();
    set({ ...signedOut, error: null });
  },

  /** Restores the stored session at once from the cached user, then confirms it with /auth/me. Only a 401/403
   * signs the user out; a network error or 5xx (for example the API waking up) keeps the session. */
  initialize: async () => {
    const token = getToken();
    if (!token || isTokenExpired(token)) {
      removeToken();
      set(signedOut);
      return;
    }
    const cached = getCachedUser();
    if (cached) set({ token, user: cached, isAuthenticated: true, isLoading: false });
    else set({ token });

    if (verifying) return verifying;
    verifying = (async () => {
      try {
        const { data } = await api.get('/auth/me', { headers: { Authorization: `Bearer ${token}` } });
        if (getToken() !== token) return; // signed out or switched accounts meanwhile
        setCachedUser(data);
        set({ user: data, isAuthenticated: true, isLoading: false });
      } catch (err) {
        const status = (err as { response?: { status?: number } }).response?.status;
        if (status === 401 || status === 403) {
          removeToken();
          set(signedOut);
        } else if (!cached) {
          // No cached user to fall back on, so the dashboard cannot pick a role yet; keep the token for a retry.
          set({ isLoading: false, error: errorMessage(err, 'Could not reach the server') });
        }
      } finally {
        verifying = null;
      }
    })();
    return verifying;
  },

  clearError: () => set({ error: null }),
}));
