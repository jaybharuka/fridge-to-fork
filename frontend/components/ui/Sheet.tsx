'use client';

import { forwardRef, useEffect, useRef, useState, type ReactNode, type TouchEvent } from 'react';
import styles from './Sheet.module.css';

interface SheetProps {
  open: boolean;
  /** Called on backdrop click, swipe-down, or Escape. Always fires — a caller that must block closing mid-action
   *  (e.g. "don't close while placing an order") makes its own onClose a no-op for that case; the chrome itself
   *  has no opinion on when closing is allowed. */
  onClose: () => void;
  /** Fires once the close animation has actually finished and the sheet has unmounted — not on `onClose` itself,
   *  which can fire long before the sheet visually finishes closing. For a caller that resets its own flow state
   *  (cart, review, payment) only once the sheet is fully gone, so the reset is never visible mid-fade. */
  onClosed?: () => void;
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
 *  regardless of theme ("dish hero reasoning"); this one uses the same tokens as the rest of the page.
 *
 *  Forwards a ref to the panel element (Phase 3, 2026-09: added for InstamartOrderSheet's focusIngredient
 *  scroll-into-view, which needs to query within the sheet's own DOM) — additive, backward compatible with every
 *  existing caller that doesn't pass one. */
export const Sheet = forwardRef<HTMLDivElement, SheetProps>(function Sheet(
  { open, onClose, onClosed, ariaLabel, title, subtitle, children },
  ref
) {
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
    const timer = setTimeout(() => {
      setMounted(false);
      onClosed?.();
    }, CLOSE_ANIMATION_MS);
    return () => clearTimeout(timer);
    // onClosed deliberately not a dep: it's read at fire time via closure, not reactively — an unstable (inline)
    // onClosed from the caller must not restart this timer. Same intentional omission this codebase already uses
    // elsewhere for callback props (e.g. the search-start effects in *OrderSheet.tsx).
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        ref={ref}
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
});
