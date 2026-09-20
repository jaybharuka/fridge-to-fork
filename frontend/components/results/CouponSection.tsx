'use client';

import { formatInr, type AppliedCoupon, type CouponList } from '@/lib/instamart';
import styles from './instamart.module.css';

interface CouponSectionProps {
  coupons: CouponList;
  appliedCoupon: AppliedCoupon | null;
  /** Code being applied right now, if any. */
  couponBusy: string | null;
  disabled: boolean;
  /** Where "go back and rebuild" leads in this flow ("Edit items" / "Edit dish"). */
  editLabel: string;
  onApply: (code: string) => void;
}

/** Coupons Swiggy currently lists for this cart. There is no remove-coupon tool: changing the coupon means rebuilding the cart. */
export function CouponSection({ coupons, appliedCoupon, couponBusy, disabled, editLabel, onApply }: CouponSectionProps) {
  if (!coupons.available || coupons.items.length === 0) return null;
  return (
    <section aria-label="Coupons">
      <p className={styles.sectionLabel}>Coupons</p>
      {coupons.filter && <p className={styles.hint} style={{ textAlign: 'left', margin: '-4px 0 8px 0' }}>{coupons.filter}</p>}
      {appliedCoupon && (
        <p className={styles.couponApplied} role="status">
          {appliedCoupon.code} applied{appliedCoupon.savings ? ` — you save ${formatInr(appliedCoupon.savings)}` : ''}. To try a different coupon, go back with {editLabel} and rebuild the cart.
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
                onClick={() => onApply(c.code)}
              >
                {isApplied ? 'Applied' : couponBusy === c.code ? 'Applying…' : 'Apply'}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
