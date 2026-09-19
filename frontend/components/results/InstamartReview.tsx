'use client';

import { formatInr, type InstamartReview as Review } from '@/lib/instamart';
import { ProductThumb } from './ProductThumb';
import styles from './instamart.module.css';

const Thumb = ({ url }: { url: string | null }) => (
  <ProductThumb url={url} className={styles.thumb} fallbackClassName={styles.thumbFallback} />
);

interface ReviewProps {
  review: Review;
  adjustments: string[];
}

/** The real Instamart cart, exactly as Swiggy will bill it. Read-only: editing goes back a step. */
export function InstamartReview({ review, adjustments }: ReviewProps) {
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

      <div className={styles.bill}>
        {review.lineItems.map(li => (
          <div className={styles.billRow} key={li.label}><span>{li.label}</span><span>{li.value}</span></div>
        ))}
        <div className={styles.billTotal}><span>{review.totalLabel}</span><span>{review.total}</span></div>
      </div>
      <p className={styles.payment}>Payment: <strong>Cash on delivery</strong> — you pay when it arrives.</p>

      {review.warning && <p className={styles.warn} style={{ marginTop: 12 }}>{review.warning}</p>}
      {review.blockers.map(b => <p key={b} className={styles.blocker} style={{ marginTop: 12 }}>{b}</p>)}
    </div>
  );
}
