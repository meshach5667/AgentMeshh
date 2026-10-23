import { create } from 'zustand';
import type { User, UserRole } from '../types/user';
import api from '../lib/api';
import { errorMessage } from '../lib/errors';
import { setToken, removeToken, getToken } from '../lib/auth';

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
    set({ user: null, token: null, isAuthenticated: false, isLoading: false, error: null });
  },

  initialize: async () => {
    const token = getToken();
    if (!token) {
      set({ isLoading: false });
      return;
    }
    try {
      set({ token });
      const { data } = await api.get('/auth/me', {
        headers: { Authorization: `Bearer ${token}` }
      });
      set({ user: data, isAuthenticated: true, isLoading: false });
    } catch {
      removeToken();
      set({ token: null, isLoading: false });
    }
  },

  clearError: () => set({ error: null }),
}));
