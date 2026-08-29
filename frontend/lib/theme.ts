export type Theme = 'light' | 'dark';

export function getStoredTheme(): Theme | null {
  if (typeof window === 'undefined') return null;
  const v = localStorage.getItem('theme');
  return v === 'dark' || v === 'light' ? v : null;
}

export function setStoredTheme(theme: Theme) {
  localStorage.setItem('theme', theme);
}

export function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-color-scheme: dark)').matches;
}
