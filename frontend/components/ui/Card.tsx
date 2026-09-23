'use client';

import type { HTMLAttributes } from 'react';
import styles from './Card.module.css';

type CardPadding = 'none' | 'sm' | 'md' | 'lg';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: CardPadding;
  /** Most cards in this app are bordered, flat surfaces (var(--bg-card) + var(--border)); a raised card uses
   *  elevation (--shadow-2) instead of a border, for content that should visually lift (e.g. a popover-like card). */
  elevated?: boolean;
}

/** The one card surface — a bordered var(--bg-card) box on the Phase 1 radius/spacing tokens. Not yet adopted by
 *  any existing screen (that's Phases 2-4); new/rebuilt screens use this instead of a bespoke `.card` class. */
export function Card({ padding = 'md', elevated = false, className, children, ...rest }: CardProps) {
  const classes = [styles.card, styles[`pad-${padding}`], elevated ? styles.elevated : '', className ?? ''].filter(Boolean).join(' ');
  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}
