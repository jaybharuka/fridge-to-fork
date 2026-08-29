'use client';
import { useState } from 'react';
import { Moon, Sun, Utensils } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';
import styles from './results.module.css';

const SPIN_MS = 300;

// Ported from templates/index.html:1767-1776 (markup), 186-203 (CSS),
// 2120-2141, 2149-2158 (toggleTheme/applyTheme behavior). The icon swap is
// a conditional element instead of the old outerHTML replace + a fresh
// lucide.createIcons() call — React just re-renders it.
export function AppHeader() {
  const { theme, toggle } = useTheme();
  const [spinning, setSpinning] = useState(false);

  function handleClick() {
    setSpinning(true);
    setTimeout(() => setSpinning(false), SPIN_MS);
    toggle();
  }

  return (
    <header className={styles.appHeader}>
      <div className={styles.appHeaderInner}>
        <div className={styles.brand}>
          <Utensils />
          <span>Fridge to Fork</span>
        </div>
        <div className={styles.headerActions}>
          <button
            type="button"
            className={`${styles.themeToggle} ${spinning ? styles.spinning : ''}`}
            onClick={handleClick}
            aria-label="Toggle light and dark mode"
          >
            {theme === 'dark' ? <Moon /> : <Sun />}
          </button>
        </div>
      </div>
    </header>
  );
}
