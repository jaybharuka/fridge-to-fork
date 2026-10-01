'use client';

import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import styles from './results.module.css';

interface FridgeLightboxProps {
  open: boolean;
  imageUrl: string;
  onClose: () => void;
}

// Ported from templates/index.html:2067-2072 (markup), 1206-1244 (CSS),
// openFridgeLightbox()/closeFridgeLightbox() (lines 2944-2957) and the
// backdrop-click-closes listener (lines 2960-2962).
//
// ui-ux-pro-max audit phase 3: this was the app's other hand-rolled modal
// surface (Sheet.tsx was the first) with none of a dialog's expected
// behavior — no role/aria-modal, no Escape-to-close, no focus trap/
// restoration. Gets all of it now, via the same shared hook Sheet.tsx uses.
export function FridgeLightbox({ open, imageUrl, onClose }: FridgeLightboxProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  useFocusTrap(open, containerRef);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  return (
    <div
      ref={containerRef}
      className={`${styles.fridgeLightbox} ${open ? styles.visible : ''}`}
      role="dialog"
      aria-label="Your fridge photo"
      aria-modal="true"
      aria-hidden={!open}
      tabIndex={-1}
      onClick={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <button type="button" className={styles.fridgeLightboxClose} onClick={onClose} aria-label="Close">
        <X />
      </button>
      <img className={styles.fridgeLightboxImg} src={imageUrl} alt="Your fridge" />
    </div>
  );
}
