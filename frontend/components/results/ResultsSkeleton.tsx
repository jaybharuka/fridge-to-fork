'use client';

import styles from './results.module.css';

// Ported from templates/index.html:2344-2366 (renderChecklistSkeleton /
// renderChoiceSkeleton) — placeholders rendered from step1 until step2
// (checklist) and awaiting_user_choice (order buttons) land. In recipe mode
// step1 arrives immediately while step2 streams for several seconds, so
// without these the results page is blank for that whole window.

export function ChecklistSkeleton() {
  return (
    <div className={styles.card}>
      <div className={styles.skeletonBlock}>
        {[0, 1, 2, 3, 4].map(i => (
          <div key={i} className={styles.skelRow} />
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
