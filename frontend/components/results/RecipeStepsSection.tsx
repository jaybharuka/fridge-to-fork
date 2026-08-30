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
        <button type="button" className={styles.recipeStepsToggle} onClick={() => setExpanded(e => !e)}>
          <BookOpen /> How to make it
          <ChevronDown className={`${styles.recipeStepsChevron} ${expanded ? styles.rotated : ''}`} />
        </button>
        <ol className={`${styles.recipeStepsList} ${expanded ? '' : styles.collapsed}`}>
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
