'use client';

import { LoaderCircle } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import styles from './Button.module.css';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost';
export type ButtonSize = 'md' | 'sm';

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner in place of the icon and disables the button — the click already in flight, not a new one. */
  loading?: boolean;
  /** Leading icon (a lucide-react element, sized by the button). Hidden while loading. */
  icon?: ReactNode;
  /** Buttons in this app are full-width by default (every existing CTA is); opt out for an inline one. */
  fullWidth?: boolean;
  type?: 'button' | 'submit';
}

/** The one button component — consolidates three independent implementations the audit found (instamart.module.css's
 *  .primary/.secondary, results.module.css's .ctaSecondaryBtn and its separate .choiceBtn family, landing.module.css's
 *  own .analyseBtn/.addPhotoBtn), each with its own radius/shadow/hover/disabled treatment. Screens adopt this one
 *  by one in later phases; existing buttons are untouched until then. */
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  fullWidth = true,
  type = 'button',
  disabled,
  className,
  children,
  ...rest
}: ButtonProps) {
  const classes = [
    styles.button,
    styles[variant],
    styles[size],
    fullWidth ? styles.fullWidth : '',
    loading ? styles.loading : '',
    className ?? '',
  ].filter(Boolean).join(' ');

  return (
    <button type={type} className={classes} disabled={disabled || loading} aria-busy={loading || undefined} {...rest}>
      {loading ? <LoaderCircle className={styles.spinner} aria-hidden="true" /> : icon}
      <span className={styles.label}>{children}</span>
    </button>
  );
}
