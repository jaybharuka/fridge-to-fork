'use client';

import { useState, type CSSProperties, type MouseEvent, type TouchEvent } from 'react';
import { ShoppingCart, Bike } from 'lucide-react';
import type { ChecklistItem } from '@/lib/types';
import { buildMissingSummaryText } from '@/hooks/useRecipeChecklist';
import styles from './results.module.css';

interface ChoiceCardProps {
  recommendedMeal: string;
  reasoning: string;
  itemsToOrder: ChecklistItem[];
  onOrderGroceries: () => void;
  onOrderDish: () => void;
  /** /api/order round trip in flight — disables both buttons. */
  orderPlacing: boolean;
}

// Ported from templates/index.html:3760-3770 (isInternalReasoning/
// firstSentence) — hides the reasoning subtitle for empty or
// internal-fallback-flavored text, otherwise shows only the first sentence.
function isInternalReasoning(text: string): boolean {
  if (!text) return true;
  const blocked = ['fallback', 'local fallback', 'enable the live model', 'temporary'];
  const lower = text.toLowerCase();
  return blocked.some(b => lower.includes(b));
}

function firstSentence(text: string): string {
  const idx = text.indexOf('.');
  return idx === -1 ? text : text.slice(0, idx + 1);
}

// Spotlight-follows-cursor effect (templates/index.html:2153-2169,
// updateChoiceSpotlight) — the original delegates from a single document
// mousemove/touchmove listener across both buttons since they're recreated
// via innerHTML on every render; a per-button React handler is simpler and
// behaviorally identical since the delegate already iterated per-button.
function useSpotlight() {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);

  const handleMove = (e: MouseEvent<HTMLButtonElement> | TouchEvent<HTMLButtonElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const point = 'touches' in e ? e.touches[0] : e;
    if (!point) return;
    setPos({ x: point.clientX - rect.left, y: point.clientY - rect.top });
  };
  const clear = () => setPos(null);

  return {
    className: pos ? styles.spotlightActive : '',
    style: pos ? ({ '--spot-x': `${pos.x}px`, '--spot-y': `${pos.y}px` } as CSSProperties) : undefined,
    onMouseMove: handleMove,
    onMouseLeave: clear,
    onTouchMove: handleMove,
    onTouchEnd: clear,
    onTouchCancel: clear,
  };
}

// Ported from templates/index.html:3772-3813 (renderChoiceCard) and CSS
// (lines 787-849, incl. the ::before spotlight-glow at 805-816). Instamart
// is the primary filled CTA, Swiggy a secondary outline button.
export function ChoiceCard({ recommendedMeal, reasoning, itemsToOrder, onOrderGroceries, onOrderDish, orderPlacing }: ChoiceCardProps) {
  const groceriesSpotlight = useSpotlight();
  const dishSpotlight = useSpotlight();
  // Which button started the order — the spinner swaps only that one's icon
  // (templates/index.html:3853-3855). Groceries goes via the preview sheet,
  // so this is set on click and only *reads* once orderPlacing flips true.
  const [clicked, setClicked] = useState<'groceries' | 'dish' | null>(null);

  const missingText = buildMissingSummaryText(itemsToOrder);
  const mealName = recommendedMeal || 'this dish';
  const showReasoning = !!reasoning && !isInternalReasoning(reasoning);

  return (
    <div className={`${styles.card} ${styles.contentFadeIn}`}>
      <div className={styles.choiceHeaderRow}>
        <span className={styles.choiceLabel}>How do you want to handle this?</span>
      </div>
      {showReasoning && <p className={styles.choiceSubtitle}>{firstSentence(reasoning)}</p>}
      <div className={styles.choiceButtons}>
        <button
          type="button"
          className={`${styles.choiceBtn} ${styles.choiceBtnPrimary} ${groceriesSpotlight.className} ${orderPlacing && clicked === 'groceries' ? styles.loading : ''}`}
          style={groceriesSpotlight.style}
          onMouseMove={groceriesSpotlight.onMouseMove}
          onMouseLeave={groceriesSpotlight.onMouseLeave}
          onTouchMove={groceriesSpotlight.onTouchMove}
          onTouchEnd={groceriesSpotlight.onTouchEnd}
          onTouchCancel={groceriesSpotlight.onTouchCancel}
          disabled={orderPlacing}
          onClick={() => { setClicked('groceries'); onOrderGroceries(); }}
        >
          <div className={styles.choiceIconCircle}>
            {orderPlacing && clicked === 'groceries' ? <div className={styles.spin} /> : <ShoppingCart />}
          </div>
          <div className={styles.choiceText}>
            <div className={styles.choiceBtnTitle}>Order missing items from Instamart</div>
            <div className={styles.choiceBtnSub}>{missingText}</div>
          </div>
        </button>
        <button
          type="button"
          className={`${styles.choiceBtn} ${styles.choiceBtnOutline} ${dishSpotlight.className} ${orderPlacing && clicked === 'dish' ? styles.loading : ''}`}
          style={dishSpotlight.style}
          onMouseMove={dishSpotlight.onMouseMove}
          onMouseLeave={dishSpotlight.onMouseLeave}
          onTouchMove={dishSpotlight.onTouchMove}
          onTouchEnd={dishSpotlight.onTouchEnd}
          onTouchCancel={dishSpotlight.onTouchCancel}
          disabled={orderPlacing}
          onClick={() => { setClicked('dish'); onOrderDish(); }}
        >
          <div className={styles.choiceIconCircle}>
            {orderPlacing && clicked === 'dish' ? <div className={styles.spin} /> : <Bike />}
          </div>
          <div className={styles.choiceText}>
            <div className={styles.choiceBtnTitle}>Order the dish from Swiggy</div>
            <div className={styles.choiceBtnSub}>Get {mealName} delivered</div>
          </div>
          <div className={styles.choiceMeta}>30 min</div>
        </button>
      </div>
      <p className={styles.choiceAttribution}>Powered by <strong>Swiggy</strong></p>
    </div>
  );
}
