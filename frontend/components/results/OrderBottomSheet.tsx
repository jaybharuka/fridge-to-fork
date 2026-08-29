'use client';

import { useEffect, useRef, useState, type TouchEvent } from 'react';
import type { ChecklistItem, TopUpSuggestion } from '@/lib/types';
import { getMissingIngredientDefaults } from '@/lib/quantity';
import { TopUpCard } from './TopUpCard';
import styles from './results.module.css';

interface OrderBottomSheetProps {
  open: boolean;
  itemsToOrder: ChecklistItem[];
  topUpSuggestions: TopUpSuggestion[];
  onClose: () => void;
  onConfirm: () => void;
}

// Ported from templates/index.html:2079-2098 (markup), 856-951 (CSS),
// renderOrderSheetItems (3929-3938), openOrderSheet/closeOrderSheet
// (3940-3966), swipe-to-dismiss (3976-3984). Always dark regardless of site
// theme — same reasoning as the dish hero.
//
// `mounted` stays true for the 400ms closing transition (matching the
// original's closeOrderSheet setTimeout) before the sheet actually unmounts,
// so the slide-down animation is visible instead of the panel vanishing
// instantly.
export function OrderBottomSheet({ open, itemsToOrder, topUpSuggestions, onClose, onConfirm }: OrderBottomSheetProps) {
  const [mounted, setMounted] = useState(open);
  const [visible, setVisible] = useState(false);
  const touchStartY = useRef(0);

  useEffect(() => {
    if (open) {
      setMounted(true);
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    }
    setVisible(false);
    const timer = setTimeout(() => setMounted(false), 400);
    return () => clearTimeout(timer);
  }, [open]);

  if (!mounted) return null;

  const topItems = topUpSuggestions.slice(0, 5);

  const handleTouchStart = (e: TouchEvent<HTMLDivElement>) => {
    touchStartY.current = e.touches[0].clientY;
  };
  const handleTouchEnd = (e: TouchEvent<HTMLDivElement>) => {
    if (e.changedTouches[0].clientY - touchStartY.current > 80) onClose();
  };

  return (
    <div className={styles.orderBottomSheet}>
      <div
        className={`${styles.orderSheetBackdrop} ${visible ? styles.visible : ''}`}
        onClick={onClose}
      />
      <div
        className={`${styles.orderSheetPanel} ${visible ? styles.visible : ''}`}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        <div className={styles.orderSheetHandle} />

        <div className={styles.orderSheetHeader}>
          <h3 className={styles.orderSheetTitle}>Your order</h3>
          <p className={styles.orderSheetSubtitle}>
            {itemsToOrder.length} item{itemsToOrder.length === 1 ? '' : 's'} to order
          </p>
        </div>

        <p className={styles.orderSheetSwiggy}>Powered by <strong>Swiggy</strong></p>

        <div className={styles.orderSheetItems}>
          {itemsToOrder.map((item, i) => {
            const { unit, qty } = getMissingIngredientDefaults(item.name);
            return (
              <div className={styles.orderSheetItem} key={i}>
                <span>{item.name}</span>
                <span className={styles.orderSheetItemQty}>{qty} {unit}</span>
              </div>
            );
          })}
        </div>

        {topItems.length > 0 && (
          <div className={styles.orderSheetTopUp}>
            <p className={styles.orderSheetTopUpLabel}>Add to your order?</p>
            <div className={styles.orderSheetTopUpCards}>
              {topItems.map((item, i) => (
                <TopUpCard key={i} item={item} />
              ))}
            </div>
          </div>
        )}

        <button type="button" className={styles.orderSheetConfirm} onClick={onConfirm}>
          Confirm order
        </button>
      </div>
    </div>
  );
}
