'use client';

import { easedProgress, useElapsed } from './usePlanningProgress';
import styles from './planning.module.css';

interface PlanningProgressProps {
  /** A photo scan has already read the fridge by the time this shows, so its first step starts done. */
  hasPhoto: boolean;
}

const STEP_LABELS = {
  recipe: ['Understanding your request', 'Picking the best dish', 'Building your ingredient list', 'Finding add-ons to go with it'],
  photo: ['Fridge scanned', 'Picking the best dish', 'Building your ingredient list', 'Finding add-ons to go with it'],
};
// When each step becomes the active one. Tuned to the plan's usual 3-30s; the last step simply holds if it takes longer.
const STEP_AT_MS = [0, 3500, 9000, 16000];
const SLOW_AT_MS = 20000;
const VERY_SLOW_AT_MS = 45000;

/** Shown on the results page while the meal plan is still being written (no dish, no checklist yet): a hero-sized block that
 *  says what is happening, with an animated progress bar, plus live steps underneath. Presentation only: it is driven by a
 *  clock, not by the scan, and unmounts the moment the real dish arrives, so it cannot get out of step with it. */
export function PlanningProgress({ hasPhoto }: PlanningProgressProps) {
  const elapsed = useElapsed(true);
  const labels = hasPhoto ? STEP_LABELS.photo : STEP_LABELS.recipe;
  const clockStep = STEP_AT_MS.reduce((n, at, i) => (elapsed >= at ? i : n), 0);
  const active = hasPhoto ? Math.max(1, clockStep) : clockStep;
  const progress = easedProgress(elapsed);
  const slow = elapsed >= SLOW_AT_MS;
  const sub = elapsed >= VERY_SLOW_AT_MS
    ? "Still working on it. If this doesn't finish soon you can go back and try again."
    : slow
      ? 'Taking longer than usual, the recipe kitchen is busy. Still working on it.'
      : 'Putting your recipe together';

  return (
    <>
      <div className={styles.hero} role="status" aria-live="polite" aria-busy="true">
        <div className={styles.heroInner}>
          <div className={styles.ring} aria-hidden="true"><span /><span /></div>
          {/* keyed by the label so each step change re-mounts it and plays the fade-in */}
          <p key={labels[active]} className={styles.heroStatus}>{labels[active]}<span className={styles.dots} aria-hidden="true" /></p>
          <p key={sub} className={`${styles.heroSub} ${slow ? styles.heroSubSlow : ''}`}>{sub}</p>
        </div>
        <div className={styles.titleSkel} aria-hidden="true" />
        <div className={styles.metaSkel} aria-hidden="true" />
        <div className={styles.barTrack} aria-hidden="true">
          <div className={styles.barFill} style={{ width: `${progress}%` }} />
        </div>
      </div>

      <ol className={styles.steps} aria-label="Progress">
        {labels.map((label, i) => (
          <li
            key={label}
            className={`${styles.step} ${i < active ? styles.stepDone : ''} ${i === active ? styles.stepActive : ''}`}
            style={{ animationDelay: `${i * 70}ms` }}
          >
            <span className={styles.stepIcon} aria-hidden="true" />
            <span className={styles.stepLabel}>{label}</span>
            {i < active && <span className={styles.srOnly}>done</span>}
          </li>
        ))}
      </ol>
    </>
  );
}
