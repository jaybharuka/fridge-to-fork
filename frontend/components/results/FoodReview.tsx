'use client';

import { formatInr, type FoodReview as Review } from '@/lib/food';
import { ProductThumb } from './ProductThumb';
import { VegMark } from './FoodPicker';
import styles from './instamart.module.css';

const Thumb = ({ url }: { url: string | null }) => (
  <ProductThumb url={url} className={styles.thumb} fallbackClassName={styles.thumbFallback} />
);

const PAYMENT_HINT = { cod: 'Pay when it arrives', upi_qr: 'Opens a payment page to scan or tap', upi_intent: 'Opens a payment page in your UPI app' } as const;

interface ReviewProps {
  review: Review;
  paymentKey: string | null;
  disabled: boolean;
  onSelectPayment: (key: string) => void;
}

/** The real Food cart, exactly as Swiggy will bill it. Items are read-only: editing goes back a step. */
export function FoodReview({ review, paymentKey, disabled, onSelectPayment }: ReviewProps) {
  const where = [review.address.label, review.address.text].filter(Boolean).join(' — ');
  const restaurant = [review.restaurant.name, review.restaurant.area].filter(Boolean).join(' · ');
  return (
    <div>
      <p className={styles.address}>Delivering to <strong>{where || 'your saved address'}</strong></p>
      {restaurant && <p className={styles.address}>From <strong>{restaurant}</strong>{review.restaurant.deliverySubtitle ? ` · ${review.restaurant.deliverySubtitle}` : ''}</p>}
      {review.warning && <p className={styles.warn}>{review.warning}</p>}
      {review.blockers.map(b => <p key={b} className={styles.blocker}>{b}</p>)}

      <div>
        {review.items.map(item => (
          <div key={item.menuItemId} className={styles.cartItem}>
            <Thumb url={item.imageUrl} />
            <div className={styles.info}>
              <div className={styles.dishTitle}><VegMark isVeg={item.isVeg} /><p className={styles.name}>{item.name}</p></div>
              <p className={styles.meta}>Quantity {item.quantity}{!item.available ? ' · out of stock' : ''}</p>
              {[...item.variants, ...item.addons].length > 0 && <p className={styles.cartVariants}>{[...item.variants, ...item.addons].join(' · ')}</p>}
            </div>
            {item.lineTotal !== null && <span className={styles.lineTotal}>{formatInr(item.lineTotal)}</span>}
          </div>
        ))}
      </div>

      <div className={styles.bill}>
        {review.lineItems.map(li => (
          <div key={li.label} className={styles.billRow}>
            <span>{li.label}</span>
            <span>
              {li.strikeoff ? <span className={styles.strike}>{formatInr(li.strikeoff)}</span> : null}
              {li.value === null ? '' : li.value < 0 ? `−${formatInr(-li.value)}` : li.value === 0 && li.strikeoff ? 'Free' : formatInr(li.value)}
            </span>
          </div>
        ))}
        <div className={styles.billTotal}><span>To pay</span><span>{review.total !== null ? formatInr(review.total) : '—'}</span></div>
      </div>

      <p className={styles.sectionLabel}>Payment</p>
      {review.payment.options.length === 0 ? (
        <p className={styles.blocker}>No payment method is available for this cart.</p>
      ) : (
        <div className={styles.payOptions} role="radiogroup" aria-label="Payment method">
          {review.payment.options.map(o => (
            <label key={o.key} className={`${styles.payOption} ${o.key === paymentKey ? styles.on : ''}`}>
              <input type="radio" name="food-payment" checked={o.key === paymentKey} disabled={disabled} onChange={() => onSelectPayment(o.key)} />
              <span className={styles.payText}>
                <span className={styles.payLabel}>{o.label}</span>
                <span className={styles.meta}>{PAYMENT_HINT[o.type]}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
