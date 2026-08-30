import { Star, Clock, Globe } from 'lucide-react';
import type { MealSuggestion } from '@/lib/types';
import styles from './results.module.css';

interface MealSuggestionsSectionProps {
  suggestions: MealSuggestion[];
  recommendedMeal: string | null;
}

// Ported from templates/index.html:2045-2048 (markup shell), 4569-4586
// (card build in the step2 handler), 762-786 (CSS). Purely presentational —
// the caller (page.tsx, Task 14) decides whether to render this at all,
// matching `mealSuggestionsSection.classList.toggle('hidden', ev.suggestions.length <= 1)`.
export function MealSuggestionsSection({ suggestions, recommendedMeal }: MealSuggestionsSectionProps) {
  return (
    <div className={styles.sectionReveal}>
      <div className={styles.sectionLabel}>
        <Star /> Meal Suggestions
      </div>
      <div className={styles.mealCards}>
        {suggestions.map((s, i) => {
          const isRec = s.name === recommendedMeal;
          return (
            <div key={i} className={styles.mealCard}>
              {isRec && (
                <div className={styles.mealHeaderBar}>
                  <Star /> Recommended
                </div>
              )}
              <div className={styles.mealBody}>
                <div className={styles.mealName}>{s.name}</div>
                <div className={styles.mealDesc}>{s.description}</div>
                <div className={styles.mealTagsRow}>
                  <span className={styles.mealTag}>
                    <Clock /> {s.prep_time_minutes}m
                  </span>
                  {s.cuisine && (
                    <span className={styles.mealTag}>
                      <Globe /> {s.cuisine}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
