'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import styles from './faq.module.css';

interface FaqItem {
  q: string;
  a: string;
}

interface FaqAccordionProps {
  faqs: FaqItem[];
}

// Same expand/collapse pattern as RecipeStepsSection (results.module.css's
// recipeStepsToggle/recipeStepsChevron/recipeStepsList) — a controlled
// button + max-height transition + rotating ChevronDown, not the native
// <details> element, so the interaction matches the rest of the app.
// Multiple questions can be open at once (simplest state shape; nothing in
// the design calls for closing siblings on open).
export function FaqAccordion({ faqs }: FaqAccordionProps) {
  const [openIndexes, setOpenIndexes] = useState<Set<number>>(new Set());

  function toggle(i: number) {
    setOpenIndexes(prev => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  return (
    <div className={styles.list}>
      {faqs.map(({ q, a }, i) => {
        const open = openIndexes.has(i);
        return (
          <div key={q} className={styles.item}>
            <button
              type="button"
              className={styles.question}
              onClick={() => toggle(i)}
              aria-expanded={open}
            >
              <span>{q}</span>
              <ChevronDown className={`${styles.chevron} ${open ? styles.rotated : ''}`} />
            </button>
            <div className={`${styles.answerWrap} ${open ? '' : styles.collapsed}`}>
              <p className={styles.answer}>{a}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
