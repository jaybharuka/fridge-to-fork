'use client';

import { formatInr, type AppliedCoupon, type CouponList, type InstamartReview as Review } from '@/lib/instamart';
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

      {coupons.available && coupons.items.length > 0 && (
        <section aria-label="Coupons">
          <p className={styles.sectionLabel}>Coupons</p>
          {appliedCoupon && (
            <p className={styles.couponApplied} role="status">
              {appliedCoupon.code} applied{appliedCoupon.savings ? ` — you save ${formatInr(appliedCoupon.savings)}` : ''}. To try a different coupon, go back with Edit items and rebuild the cart.
            </p>
          )}
          <ul className={styles.coupons}>
            {coupons.items.map(c => {
              const isApplied = appliedCoupon?.code.toLowerCase() === c.code.toLowerCase();
              return (
                <li key={c.code} className={`${styles.coupon} ${!c.applicable && !isApplied ? styles.couponOff : ''}`}>
                  <div className={styles.couponBody}>
                    <p className={styles.couponTitle}>{c.title} <span className={styles.couponCode}>{c.code}</span></p>
                    {c.description && <p className={styles.meta}>{c.description}</p>}
                    {!c.applicable && c.message && <p className={styles.couponWhy}>{c.message}</p>}
                    {c.terms.length > 0 && (
                      <details className={styles.terms}>
                        <summary>Terms</summary>
                        <ul>{c.terms.map(t => <li key={t}>{t}</li>)}</ul>
                      </details>
                    )}
                  </div>
                  <button
                    type="button"
                    className={styles.couponBtn}
                    disabled={disabled || !c.applicable || !!appliedCoupon || couponBusy !== null}
                    onClick={() => onApplyCoupon(c.code)}
                  >
                    {isApplied ? 'Applied' : couponBusy === c.code ? 'Applying…' : 'Apply'}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

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
