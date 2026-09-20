'use client';

import { formatInr, type AppliedCoupon, type CouponList, type InstamartReview as Review } from '@/lib/instamart';
import { CouponSection } from './CouponSection';
import { ProductThumb } from './ProductThumb';
import styles from './instamart.module.css';

const Thumb = ({ url }: { url: string | null }) => (
  <ProductThumb url={url} className={styles.thumb} fallbackClassName={styles.thumbFallback} />
);

const PAYMENT_HINT = {
  cod: 'Pay when it arrives',
  upi_qr: 'Opens a payment page to scan or tap',
  upi_intent: 'Opens a payment page in your UPI app',
} as const;

interface ReviewProps {
  review: Review;
  adjustments: string[];
  coupons: CouponList;
  appliedCoupon: AppliedCoupon | null;
  /** Code being applied right now, if any. */
  couponBusy: string | null;
  paymentKey: string | null;
  disabled: boolean;
  onSelectPayment: (key: string) => void;
  onApplyCoupon: (code: string) => void;
}

/** The real Instamart cart, exactly as Swiggy will bill it. Items are read-only: editing goes back a step. */
export function InstamartReview({ review, adjustments, coupons, appliedCoupon, couponBusy, paymentKey, disabled, onSelectPayment, onApplyCoupon }: ReviewProps) {
  const where = [review.address.label, review.address.text].filter(Boolean).join(' — ');
  return (
    <div>
      <p className={styles.address}>Delivering to <strong>{where || 'your saved address'}</strong></p>

      {adjustments.map(a => <p key={a} className={styles.adjust}>{a}</p>)}

      <div>
        {review.items.map(item => (
          <div className={styles.cartItem} key={item.spinId}>
            <Thumb url={item.imageUrl} />
            <div className={styles.info}>
              <p className={styles.name}>{item.name}</p>
              <p className={styles.meta}>
                {[item.variant, `${item.quantity} × ${formatInr(item.price)}`].filter(Boolean).join(' · ')}
                {!item.available && ' · out of stock'}
              </p>
            </div>
            {item.price !== null && <span className={styles.lineTotal}>{formatInr(item.price * item.quantity)}</span>}
          </div>
        ))}
      </div>

      <CouponSection coupons={coupons} appliedCoupon={appliedCoupon} couponBusy={couponBusy} disabled={disabled} editLabel="Edit items" onApply={onApplyCoupon} />

      <div className={styles.bill}>
        {review.lineItems.map(li => (
          <div className={styles.billRow} key={li.label}><span>{li.label}</span><span>{li.value}</span></div>
        ))}
        <div className={styles.billTotal}><span>{review.totalLabel}</span><span>{review.total}</span></div>
      </div>

      <p className={styles.sectionLabel}>Pay with</p>
      <div role="radiogroup" aria-label="Payment method" className={styles.payOptions}>
        {review.payment.options.map(o => (
          <label key={o.key} className={`${styles.payOption} ${o.key === paymentKey ? styles.on : ''}`}>
            <input
              type="radio"
              name="instamart-payment"
              checked={o.key === paymentKey}
              disabled={disabled}
              onChange={() => onSelectPayment(o.key)}
            />
            <span className={styles.payText}>
              <span className={styles.payLabel}>{o.label}</span>
              <span className={styles.meta}>{PAYMENT_HINT[o.type]}</span>
            </span>
          </label>
        ))}
      </div>

      {review.warning && <p className={styles.warn} style={{ marginTop: 12 }}>{review.warning}</p>}
      {review.blockers.map(b => <p key={b} className={styles.blocker} style={{ marginTop: 12 }}>{b}</p>)}
    </div>
  );
}
