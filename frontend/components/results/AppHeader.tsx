'use client';
import { useState } from 'react';
import { Check, Moon, Package, Sun } from 'lucide-react';
import { openOrders } from '@/lib/ordersUi';
import { useAuth } from '@/hooks/useAuth';
import { useTheme } from '@/hooks/useTheme';
import styles from './results.module.css';

const SPIN_MS = 300;

// Ported from templates/index.html:1767-1776 (markup), 186-203 (CSS),
// 2120-2141, 2149-2158 (toggleTheme/applyTheme behavior). The icon swap is
// a conditional element instead of the old outerHTML replace + a fresh
// lucide.createIcons() call — React just re-renders it.
export function AppHeader() {
  const { theme, toggle } = useTheme();
  const { status } = useAuth();
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
          <img src="/logo-mark.png" alt="" className={styles.brandLogo} width={20} height={20} />
          <span>Fridge to Fork</span>
        </div>
        <div className={styles.headerActions}>
          {status === 'connected' && (
            <span className={styles.connectedChip} role="status" aria-label="Swiggy account connected" title="Swiggy account connected">
              <Check aria-hidden /> Connected
            </span>
          )}
          {status === 'connected' && (
            <button type="button" className={styles.themeToggle} onClick={() => openOrders()} aria-label="Your Instamart orders">
              <Package />
            </button>
          )}
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
