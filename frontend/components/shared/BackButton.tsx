'use client';
import { ChevronLeft } from 'lucide-react';
import styles from './BackButton.module.css';

interface BackButtonProps {
  onClick: () => void;
  label: string;
  /** The full-screen scan overlays are always dark, whatever the theme, so they need light-on-dark colours. */
  onDark?: boolean;
}

/** The one back control: a plain left chevron, same icon and size everywhere. Callers decide what "back" does. */
export function BackButton({ onClick, label, onDark = false }: BackButtonProps) {
  return (
    <button type="button" className={`${styles.back} ${onDark ? styles.onDark : ''}`} onClick={onClick} aria-label={label}>
      <ChevronLeft aria-hidden />
    </button>
  );
}
