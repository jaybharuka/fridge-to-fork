'use client';

import styles from './results.module.css';

// Ported from templates/index.html:2344-2366 (renderChecklistSkeleton /
// renderChoiceSkeleton) — placeholders rendered from step1 until step2
// (checklist) and awaiting_user_choice (order buttons) land. In recipe mode
// step1 arrives immediately while step2 streams for several seconds, so
// without these the results page is blank for that whole window.

// Shaped like the real checklist card (a stat line, then rows of checkbox + name + quantity + tag), so the real rows land where
// the placeholders were instead of replacing anonymous grey bars. Widths vary a little so it doesn't read as a table of clones.
const NAME_WIDTHS = ['52%', '38%', '60%', '44%', '56%', '34%'];
const QTY_WIDTHS = ['24%', '18%', '28%', '20%', '22%', '16%'];

export function ChecklistSkeleton() {
  return (
    <div className={styles.card} aria-hidden="true">
      <div className={styles.skelStat}>
        <div className={`${styles.skeletonBox} ${styles.skelStatLine}`} />
        <div className={`${styles.skeletonBox} ${styles.skelHookLine}`} />
      </div>
      <div className={styles.skeletonBlock}>
        {NAME_WIDTHS.map((w, i) => (
          <div key={i} className={styles.skelRichRow} style={{ animationDelay: `${i * 0.12}s` }}>
            <div className={`${styles.skeletonBox} ${styles.skelCheck}`} />
            <div className={styles.skelLines}>
              <div className={`${styles.skeletonBox} ${styles.skelName}`} style={{ width: w }} />
              <div className={`${styles.skeletonBox} ${styles.skelQty}`} style={{ width: QTY_WIDTHS[i] }} />
            </div>
            <div className={`${styles.skeletonBox} ${styles.skelTag}`} />
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChoiceSkeleton() {
  return (
    <div className={styles.card}>
      <div className={styles.skeletonButtons}>
        <div className={`${styles.skeletonBox} ${styles.skeletonBtn}`} />
        <div className={`${styles.skeletonBox} ${styles.skeletonBtn}`} />
      </div>
    </div>
  );
}
