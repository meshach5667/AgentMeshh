'use client';

import React, { createContext, useCallback, useContext, useSyncExternalStore } from 'react';

type Theme = 'dark' | 'light';

interface ThemeContextType {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

// The <html> class (set before paint by the inline script in app/layout.tsx) is the source of truth.
const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};
const read = (): Theme => (document.documentElement.classList.contains('light') ? 'light' : 'dark');

function apply(theme: Theme) {
  const root = document.documentElement;
  root.classList.remove('dark', 'light');
  root.classList.add(theme);
  try {
    localStorage.setItem('theme', theme);
  } catch {
    // storage may be unavailable (private mode); the class still applies for this visit
  }
  listeners.forEach((l) => l());
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useSyncExternalStore(subscribe, read, () => 'dark' as Theme);
  const setTheme = useCallback((t: Theme) => apply(t), []);
  const toggleTheme = useCallback(() => apply(read() === 'dark' ? 'light' : 'dark'), []);
  return <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => {
  const ctx = useContext(ThemeContext);
  if (!ctx) return { theme: 'dark' as Theme, toggleTheme: () => {}, setTheme: () => {} };
  return ctx;
};
