'use client';

import { useState } from 'react';
import { BookOpen, ChevronDown } from 'lucide-react';
import styles from './results.module.css';

interface RecipeStepsSectionProps {
  steps: string[];
}

// Ported from templates/index.html:3355-3372 (buildRecipeStepsHtml),
// 3491-3497 (toggleRecipeSteps), 666-689 (CSS). `expanded` starts false,
// matching `recipeStepsExpanded` starting false (line 3205).
export function RecipeStepsSection({ steps }: RecipeStepsSectionProps) {
  const [expanded, setExpanded] = useState(false);

  if (!steps.length) return null;

  return (
    <div className={`${styles.recipeChecklistCard} ${styles.contentFadeIn}`}>
      <div className={styles.recipeStepsBlock}>
        {/* aria-expanded/aria-hidden (ui-ux-pro-max audit phase 4): a
            standard expand/collapse control with neither — a screen-reader
            user couldn't tell whether the steps were currently shown. The
            list stays in the DOM either way (collapsed via max-height, not
            display:none, for the slide transition), so aria-hidden is what
            actually keeps it out of the accessibility tree while closed. */}
        <button
          type="button"
          className={styles.recipeStepsToggle}
          onClick={() => setExpanded(e => !e)}
          aria-expanded={expanded}
        >
          <BookOpen /> How to make it
          <ChevronDown className={`${styles.recipeStepsChevron} ${expanded ? styles.rotated : ''}`} />
        </button>
        <ol className={`${styles.recipeStepsList} ${expanded ? '' : styles.collapsed}`} aria-hidden={!expanded}>
          {steps.map((step, i) => (
            <li key={i}>
              <span className={styles.recipeStepNum}>{i + 1}</span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
