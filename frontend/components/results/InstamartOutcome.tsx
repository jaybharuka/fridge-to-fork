'use client';

import { CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react';
import type { InstamartOutcome as Outcome } from '@/lib/instamart';
import styles from './instamart.module.css';

interface OutcomeProps {
  outcome: Outcome;
  onClose: () => void;
  onBackToCart: () => void;
}

export function InstamartOutcome({ outcome, onClose, onBackToCart }: OutcomeProps) {
  const ids = outcome.orderIds.join(', ');
  if (outcome.status === 'placed') {
    return (
      <div className={styles.centered}>
        <CircleCheck className={`${styles.bigIcon} ${styles.ok}`} />
        <h4 className={styles.outcomeTitle}>Order placed</h4>
        <p className={styles.outcomeBody}>
          {ids && <>Order {ids}. </>}
          {outcome.total && <>Pay {outcome.total} on delivery. </>}
          Track it in the Swiggy app.
        </p>
        {!outcome.verified && <p className={styles.hint}>We couldn&apos;t double-check it with Swiggy — it&apos;s worth a glance in the app.</p>}
        <button type="button" className={styles.primary} onClick={onClose}>Done</button>
      </div>
    );
  }
  if (outcome.status === 'failed') {
    return (
      <div className={styles.centered}>
        <CircleAlert className={`${styles.bigIcon} ${styles.bad}`} />
        <h4 className={styles.outcomeTitle}>Order not placed</h4>
        <p className={styles.outcomeBody}>{outcome.message} Nothing was charged.</p>
        <button type="button" className={styles.primary} onClick={onBackToCart}>Back to your cart</button>
        <button type="button" className={styles.secondary} onClick={onClose}>Close</button>
      </div>
    );
  }
  // partial / unknown: never offer a retry — the order may exist.
  return (
    <div className={styles.centered}>
      <TriangleAlert className={`${styles.bigIcon} ${styles.warnIcon}`} />
      <h4 className={styles.outcomeTitle}>{outcome.status === 'partial' ? 'Only part of it went through' : 'Please check the Swiggy app'}</h4>
      <p className={styles.outcomeBody}>{outcome.message}</p>
      {ids && <p className={styles.outcomeBody}>Order {ids}.</p>}
      <p className={styles.hint}>Don&apos;t order again until you&apos;ve checked, so you aren&apos;t charged twice.</p>
      <button type="button" className={styles.primary} onClick={onClose}>Close</button>
    </div>
  );
}
