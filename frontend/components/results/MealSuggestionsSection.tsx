import { useState } from 'react';
import { Star, Clock, Globe, Check, Loader2 } from 'lucide-react';
import type { MealSuggestion } from '@/lib/types';
import styles from './results.module.css';

interface MealSuggestionsSectionProps {
  suggestions: MealSuggestion[];
  recommendedMeal: string | null;
  /** Switches the active dish to one of `suggestions` — instant/local, see
   *  useScanStream.selectMeal. Omitted only makes the section read-only
   *  (unused today, but keeps this component usable purely for display). */
  onSelect?: (suggestion: MealSuggestion) => void;
  /** Plans a dish that isn't in `suggestions` at all — the free-text box
   *  below the cards. Always a real backend call (useScanStream.replanCustomDish). */
  onCustomDish?: (dishName: string) => void;
  /** True while onSelect's background top-up refresh or onCustomDish's
   *  planning call is in flight. */
  pending?: boolean;
  /** Set only by a failed custom-dish request (see scanReducer's REPLAN_ERROR). */
  error?: string | null;
}

// Ported from templates/index.html:2045-2048 (markup shell), 4569-4586
// (card build in the step2 handler), 762-786 (CSS) — now interactive:
// clicking a non-active card switches to it (feature added 2026-10-01, see
// useScanStream.selectMeal/replanCustomDish). The caller (page.tsx) decides
// whether to render this at all, matching
// `mealSuggestionsSection.classList.toggle('hidden', ev.suggestions.length <= 1)`.
export function MealSuggestionsSection({
  suggestions,
  recommendedMeal,
  onSelect,
  onCustomDish,
  pending,
  error,
}: MealSuggestionsSectionProps) {
  const [customDish, setCustomDish] = useState('');

  const submitCustomDish = () => {
    const trimmed = customDish.trim();
    if (!trimmed || pending) return;
    onCustomDish?.(trimmed);
    setCustomDish('');
  };

  return (
    <div className={styles.sectionReveal}>
      <div className={styles.sectionLabel}>
        <Star /> Meal Suggestions
      </div>
      <div className={styles.mealCards}>
        {suggestions.map((s, i) => {
          const isActive = s.name === recommendedMeal;
          const clickable = !!onSelect && !isActive;
          return (
            <div
              key={i}
              className={`${styles.mealCard} ${isActive ? styles.mealCardActive : ''} ${clickable ? styles.mealCardClickable : ''}`}
              role={clickable ? 'button' : undefined}
              tabIndex={clickable ? 0 : undefined}
              onClick={clickable ? () => onSelect!(s) : undefined}
              onKeyDown={clickable ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect!(s); } } : undefined}
            >
              {isActive && (
                <div className={styles.mealHeaderBar}>
                  <Check /> Selected
                </div>
              )}
              <div className={styles.mealBody}>
                <div className={styles.mealName}>{s.name}</div>
                <div className={styles.mealDesc}>{s.description}</div>
                <div className={styles.mealTagsRow}>
                  {s.prep_time_minutes > 0 && (
                    <span className={styles.mealTag}>
                      <Clock /> {s.prep_time_minutes}m
                    </span>
                  )}
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

      {onCustomDish && (
        <div className={styles.customDishRow}>
          <input
            type="text"
            className={styles.customDishInput}
            placeholder="Or tell us what you'd like to make instead"
            value={customDish}
            disabled={pending}
            onChange={e => setCustomDish(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submitCustomDish(); }}
          />
          <button
            type="button"
            className={styles.customDishBtn}
            disabled={pending || !customDish.trim()}
            onClick={submitCustomDish}
          >
            {pending ? <Loader2 className={styles.spin} /> : 'Go'}
          </button>
        </div>
      )}
      {error && <div className={styles.customDishError}>{error}</div>}
    </div>
  );
}
