'use client';

import { CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react';
import type { InstamartOutcome as Outcome, ReportContext } from '@/lib/instamart';
import { PaymentPending } from './PaymentPending';
import { ReportProblem } from './ReportProblem';
import styles from './instamart.module.css';

interface OutcomeProps {
  outcome: Outcome;
  /** True when the chosen payment was cash on delivery (nothing was paid online). */
  payOnDelivery: boolean;
  onClose: () => void;
  onBackToCart: () => void;
  /** Open live tracking for a placed order. */
  onTrack: (orderId: string) => void;
  /** Identifiers for a problem report: address, payment method, coupon. */
  reportContext: ReportContext;
}

export function InstamartOutcome({ outcome, payOnDelivery, onClose, onBackToCart, onTrack, reportContext }: OutcomeProps) {
  const ids = outcome.orderIds.join(', ');
  const report = (
    <ReportProblem
      input={{
        tool: 'checkout',
        errorMessage: outcome.message,
        flow: 'Reviewed the Instamart cart, chose a payment method and placed the order',
        context: { ...reportContext, ...(outcome.orderIds[0] ? { orderId: outcome.orderIds[0] } : {}) },
      }}
    />
  );

  if (outcome.status === 'pending_payment' && outcome.payment) return <PaymentPending bridgeUrl={outcome.payment.bridgeUrl} onClose={onClose} />;

  if (outcome.status === 'placed') {
    return (
      <div className={styles.centered}>
        <CircleCheck className={`${styles.bigIcon} ${styles.ok}`} />
        <h4 className={styles.outcomeTitle}>Order placed</h4>
        <p className={styles.outcomeBody}>
          {ids && <>Order {ids}. </>}
          {payOnDelivery && outcome.total ? <>Pay {outcome.total} on delivery. </> : !payOnDelivery ? <>Payment received. </> : null}
          Track it here or in the Swiggy app.
        </p>
        {!outcome.verified && <p className={styles.hint}>We couldn&apos;t double-check it with Swiggy — it&apos;s worth a glance in the app.</p>}
        {outcome.orderIds[0] && (
          <button type="button" className={styles.primary} onClick={() => onTrack(outcome.orderIds[0])}>Track order</button>
        )}
        <button type="button" className={styles.secondary} onClick={onClose}>Done</button>
      </div>
    );
  }
  if (outcome.status === 'failed') {
    return (
      <div className={styles.centered}>
        <CircleAlert className={`${styles.bigIcon} ${styles.bad}`} />
        <h4 className={styles.outcomeTitle}>Order not placed</h4>
        <p className={styles.outcomeBody}>{outcome.message}</p>
        <button type="button" className={styles.primary} onClick={onBackToCart}>Back to your cart</button>
        <button type="button" className={styles.secondary} onClick={onClose}>Close</button>
        {report}
      </div>
    );
  }
  // partial / unknown (and a pending payment with no usable page): never offer a retry — the order may exist.
  return (
    <div className={styles.centered}>
      <TriangleAlert className={`${styles.bigIcon} ${styles.warnIcon}`} />
      <h4 className={styles.outcomeTitle}>{outcome.status === 'partial' ? 'Only part of it went through' : 'Please check the Swiggy app'}</h4>
      <p className={styles.outcomeBody}>{outcome.message}</p>
      {ids && <p className={styles.outcomeBody}>Order {ids}.</p>}
      <p className={styles.hint}>Don&apos;t order again until you&apos;ve checked, so you aren&apos;t charged twice.</p>
      <button type="button" className={styles.primary} onClick={onClose}>Close</button>
      {report}
    </div>
  );
}
