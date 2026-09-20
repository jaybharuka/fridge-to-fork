'use client';

import { CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react';
import { formatInr, type FoodOutcome as Outcome } from '@/lib/food';
import { PaymentPending } from './PaymentPending';
import styles from './instamart.module.css';

interface OutcomeProps {
  outcome: Outcome;
  /** True when the chosen payment was cash on delivery (nothing was paid online). */
  payOnDelivery: boolean;
  onClose: () => void;
  onBackToCart: () => void;
}

const total = (value: Outcome['total']): string | null => (typeof value === 'number' ? formatInr(value) : value ? String(value) : null);

export function FoodOutcome({ outcome, payOnDelivery, onClose, onBackToCart }: OutcomeProps) {
  const ids = outcome.orderIds.join(', ');

  // The parent hook is polling Swiggy; this screen just gives the user the payment page.
  if (outcome.status === 'pending_payment' && outcome.payment) return <PaymentPending bridgeUrl={outcome.payment.bridgeUrl} onClose={onClose} />;

  if (outcome.status === 'placed') {
    const amount = total(outcome.total);
    return (
      <div className={styles.centered}>
        <CircleCheck className={`${styles.bigIcon} ${styles.ok}`} />
        <h4 className={styles.outcomeTitle}>Order placed</h4>
        <p className={styles.outcomeBody}>
          {outcome.detail?.restaurant && <>From {outcome.detail.restaurant}. </>}
          {ids && <>Order {ids}. </>}
          {outcome.detail?.eta && <>Arriving in about {outcome.detail.eta}. </>}
          {payOnDelivery && amount ? <>Pay {amount} on delivery.</> : !payOnDelivery ? <>Payment received.</> : null}
        </p>
        {outcome.notice && <p className={styles.warn}>{outcome.notice}</p>}
        <p className={styles.hint}>You can follow it in the Swiggy app.</p>
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
        <p className={styles.outcomeBody}>{outcome.message}</p>
        <button type="button" className={styles.primary} onClick={onBackToCart}>Back to your dish</button>
        <button type="button" className={styles.secondary} onClick={onClose}>Close</button>
      </div>
    );
  }
  // unknown / partial / pending: never offer a retry — the order may exist.
  return (
    <div className={styles.centered}>
      <TriangleAlert className={`${styles.bigIcon} ${styles.warnIcon}`} />
      <h4 className={styles.outcomeTitle}>Please check the Swiggy app</h4>
      <p className={styles.outcomeBody}>{outcome.message}</p>
      {ids && <p className={styles.outcomeBody}>Order {ids}.</p>}
      <p className={styles.hint}>Don&apos;t order again until you&apos;ve checked, so you aren&apos;t charged twice.</p>
      <button type="button" className={styles.primary} onClick={onClose}>Close</button>
    </div>
  );
}
