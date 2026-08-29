'use client';
import { useState, useCallback, useLayoutEffect } from 'react';
import { getStoredTheme, setStoredTheme, systemPrefersDark, Theme } from '@/lib/theme';

export function useTheme() {
  const [theme, setTheme] = useState<Theme>('dark');

  useLayoutEffect(() => {
    const stored = getStoredTheme();
    const initial: Theme = stored ?? (systemPrefersDark() ? 'dark' : 'light');
    setTheme(initial);
    document.documentElement.setAttribute('data-theme', initial);
  }, []);

  const toggle = useCallback(() => {
    setTheme(prev => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark';
      setStoredTheme(next);
      document.documentElement.setAttribute('data-theme', next);
      return next;
    });
  }, []);

  return { theme, toggle };
}
