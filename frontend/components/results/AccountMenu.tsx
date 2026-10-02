'use client';
import { useEffect, useRef, useState } from 'react';
import { Moon, Package, Sun, User, UtensilsCrossed } from 'lucide-react';
import { accountMenuModel } from '@/lib/accountMenu';
import { FOOD_ORDERING_ENABLED } from '@/lib/features';
import { openOrders } from '@/lib/ordersUi';
import { useTheme } from '@/hooks/useTheme';
import styles from './accountMenu.module.css';

interface AccountMenuProps {
  connected: boolean;
}

/** The header's one right-hand control: connection status, order history and the theme switch, behind a single button.
 *  A disclosure popover (not a modal): focus stays on the button, Tab walks into the panel, and Escape, a click outside
 *  or tabbing out closes it and, for Escape, puts focus back on the button. */
export function AccountMenu({ connected }: AccountMenuProps) {
  const [open, setOpen] = useState(false);
  const { theme, toggle } = useTheme();
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const model = accountMenuModel(connected, FOOD_ORDERING_ENABLED);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  function openList(kind: 'instamart' | 'food') {
    setOpen(false);
    openOrders(null, kind);
  }

  function chooseTheme(next: 'light' | 'dark') {
    if (next !== theme) toggle();
  }

  return (
    <div
      ref={rootRef}
      className={styles.root}
      onBlur={e => {
        // Tabbing out of the whole menu (button + panel) closes it.
        if (open && !e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <button
        ref={buttonRef}
        type="button"
        className={`${styles.trigger} ${open ? styles.triggerOpen : ''}`}
        aria-label={connected ? 'Account and settings, Swiggy connected' : 'Settings'}
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls="account-menu-panel"
        onClick={() => setOpen(o => !o)}
      >
        <User aria-hidden />
        {connected && <span className={styles.dot} aria-hidden="true" />}
      </button>

      {open && (
        <div id="account-menu-panel" className={styles.panel}>
          <div className={`${styles.status} ${model.connected ? styles.statusOn : ''}`} role="status">
            {model.statusLabel}
          </div>
          {model.showInstamartOrders && (
            <button type="button" className={styles.item} onClick={() => openList('instamart')}>
              <Package aria-hidden /> Instamart orders
            </button>
          )}
          {model.showFoodOrders && (
            <button type="button" className={styles.item} onClick={() => openList('food')}>
              <UtensilsCrossed aria-hidden /> Food orders
            </button>
          )}
          <hr className={styles.rule} />
          <div className={styles.segment} role="radiogroup" aria-label="Theme">
            <button type="button" role="radio" aria-checked={theme === 'light'} className={`${styles.seg} ${theme === 'light' ? styles.segOn : ''}`} onClick={() => chooseTheme('light')}>
              <Sun aria-hidden /> Light
            </button>
            <button type="button" role="radio" aria-checked={theme === 'dark'} className={`${styles.seg} ${theme === 'dark' ? styles.segOn : ''}`} onClick={() => chooseTheme('dark')}>
              <Moon aria-hidden /> Dark
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
