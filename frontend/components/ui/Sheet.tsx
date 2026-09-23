'use client';

import { useEffect, useRef, useState, type ReactNode, type TouchEvent } from 'react';
import styles from './Sheet.module.css';

interface SheetProps {
  open: boolean;
  /** Called on backdrop click, swipe-down, or Escape. Always fires — a caller that must block closing mid-action
   *  (e.g. "don't close while placing an order") makes its own onClose a no-op for that case; the chrome itself
   *  has no opinion on when closing is allowed. */
  onClose: () => void;
  /** Accessible name for the dialog — required, since the visual title (if any) may not always be present/plain text. */
  ariaLabel: string;
  title?: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
}

const SWIPE_CLOSE_THRESHOLD_PX = 80;
const CLOSE_ANIMATION_MS = 400;

/** The one bottom-sheet chrome — extracted from the mount/visible/backdrop/panel/handle/swipe-to-close pattern the
 *  audit found independently reimplemented in InstamartOrderSheet, FoodOrderSheet, InstamartOrdersSheet and
 *  FoodOrdersSheet. Follows the light/dark toggle (confirmed decision, 2026-09): earlier sheets were hardcoded dark
 *  regardless of theme ("dish hero reasoning"); this one uses the same tokens as the rest of the page. Not yet
 *  adopted by any existing sheet — each is migrated in Phase 3/4, not rewritten wholesale here. */
export function Sheet({ open, onClose, ariaLabel, title, subtitle, children }: SheetProps) {
  const [mounted, setMounted] = useState(open);
  const [visible, setVisible] = useState(false);
  const touchStartY = useRef(0);

  useEffect(() => {
    if (open) {
      setMounted(true);
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    }
    setVisible(false);
    const timer = setTimeout(() => setMounted(false), CLOSE_ANIMATION_MS);
    return () => clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!mounted) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [mounted, onClose]);

  if (!mounted) return null;

  const handleTouchStart = (e: TouchEvent<HTMLDivElement>) => {
    touchStartY.current = e.touches[0].clientY;
  };
  const handleTouchEnd = (e: TouchEvent<HTMLDivElement>) => {
    if (e.changedTouches[0].clientY - touchStartY.current > SWIPE_CLOSE_THRESHOLD_PX) onClose();
  };

  return (
    <div className={styles.sheet}>
      <div className={`${styles.backdrop} ${visible ? styles.visible : ''}`} onClick={onClose} />
      <div
        className={`${styles.panel} ${visible ? styles.visible : ''}`}
        role="dialog"
        aria-label={ariaLabel}
        aria-modal="true"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        <div className={styles.handle} />
        {(title || subtitle) && (
          <div className={styles.header}>
            {title && <h3 className={styles.title}>{title}</h3>}
            {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
