'use client';

import { formatInr, topAvailable, type InstamartSearchResult } from '@/lib/instamart';
import { ProductThumb } from './ProductThumb';
import styles from './instamart.module.css';

interface UsualItemsProps {
  items: InstamartSearchResult[];
  onAdd: (item: InstamartSearchResult) => void;
}

/** Products the user actually orders often (Swiggy's your_go_to_items) — real photo, price and SKU,
 *  so adding one needs no name search. */
export function UsualItems({ items, onAdd }: UsualItemsProps) {
  return (
    <section aria-label="Your usual items">
      <p className={styles.sectionLabel}>Your usual items</p>
      <div className={styles.usualRow}>
        {items.map(item => {
          const option = topAvailable(item);
          if (!option) return null;
          return (
            <div className={styles.usualCard} key={item.ingredient}>
              <ProductThumb url={option.imageUrl} className={styles.usualThumb} fallbackClassName={styles.usualThumbFallback} size="md" />
              <p className={styles.usualName}>{item.ingredient}</p>
              <p className={styles.meta}>{[option.size, formatInr(option.price)].filter(Boolean).join(' · ')}</p>
              <button type="button" className={styles.couponBtn} onClick={() => onAdd(item)} aria-label={`Add ${item.ingredient}`}>+ Add</button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
