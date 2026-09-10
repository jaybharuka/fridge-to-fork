'use client';

import { Link2 } from 'lucide-react';
import { useEffect, useRef, useState, type TouchEvent } from 'react';
import type { ChecklistItem, TopUpSuggestion } from '@/lib/types';
import type { ScanState } from '@/hooks/useScanStream';
import { getMissingIngredientDefaults } from '@/lib/quantity';
import { TopUpCard } from './TopUpCard';
import styles from './results.module.css';

interface OrderBottomSheetProps {
  open: boolean;
  itemsToOrder: ChecklistItem[];
  topUpSuggestions: TopUpSuggestion[];
  /** /api/order round trip in flight — disables Confirm and shows a spinner. */
  orderPlacing: boolean;
  /** Result of the last order attempt made from this sheet. auth_required
   *  and error results are shown inline (sheet stays open, selections
   *  survive); the caller closes the sheet on order_placed. */
  orderResult: ScanState['orderResult'];
  /** Pre-selects these top-ups on open instead of starting empty — used
   *  when the sheet is reopening after an OAuth round trip (lib/pendingOrder.ts). */
  initialSelectedTopUpNames?: string[];
  onClose: () => void;
  /** Selected top-up item names (optional add-ons), separate from
   *  itemsToOrder — merged into the order payload by the caller. */
  onConfirm: (selectedTopUpNames: string[]) => void;
  /** Fired just before the "Connect with Swiggy" CTA navigates away, so the
   *  caller can stash current selections to resume after the redirect. */
  onConnectClick: (selectedTopUpNames: string[]) => void;
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
export function OrderBottomSheet({ open, itemsToOrder, topUpSuggestions, orderPlacing, orderResult, initialSelectedTopUpNames, onClose, onConfirm, onConnectClick }: OrderBottomSheetProps) {
  const [mounted, setMounted] = useState(open);
  const [visible, setVisible] = useState(false);
  const [selectedTopUps, setSelectedTopUps] = useState<Set<string>>(new Set());
  const touchStartY = useRef(0);

  useEffect(() => {
    if (open) {
      setMounted(true);
      // Fresh selection on a normal open; restores the caller's picks when
      // reopening after the OAuth round trip.
      setSelectedTopUps(new Set(initialSelectedTopUpNames ?? []));
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    }
    setVisible(false);
    const timer = setTimeout(() => setMounted(false), 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const toggleTopUp = (name: string) => {
    setSelectedTopUps(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

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
            {itemsToOrder.length + selectedTopUps.size} item
            {itemsToOrder.length + selectedTopUps.size === 1 ? '' : 's'} to order
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
                <TopUpCard
                  key={i}
                  item={item}
                  selected={selectedTopUps.has(item.name)}
                  onToggle={() => toggleTopUp(item.name)}
                />
              ))}
            </div>
          </div>
        )}

        {orderResult?.kind === 'auth_required' && (
          <div className={styles.orderSheetAuthNotice}>
            <p>{orderResult.message || 'Connect your Swiggy account to place this order.'}</p>
            <a
              className={styles.orderSheetAuthCta}
              href="/auth/login?next=/"
              onClick={() => onConnectClick(Array.from(selectedTopUps))}
            >
              <Link2 /> Connect with Swiggy
            </a>
          </div>
        )}

        {orderResult?.kind === 'error' && (
          <p className={styles.orderSheetErrorNotice}>{orderResult.message}</p>
        )}

        <button
          type="button"
          className={styles.orderSheetConfirm}
          disabled={orderPlacing}
          onClick={() => onConfirm(Array.from(selectedTopUps))}
        >
          {orderPlacing ? 'Placing order…' : 'Confirm order'}
        </button>
      </div>
    </div>
  );
}
