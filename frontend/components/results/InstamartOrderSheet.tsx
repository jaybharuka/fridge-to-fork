'use client';

import { Link2, LoaderCircle } from 'lucide-react';
import { useEffect, useRef, useState, type TouchEvent } from 'react';
import type { ChecklistItem, TopUpSuggestion } from '@/lib/types';
import { selectionsFrom, useInstamartOrder, type Stage } from '@/hooks/useInstamartOrder';
import { useAuth } from '@/hooks/useAuth';
import { formatInr } from '@/lib/instamart';
import { InstamartOutcome } from './InstamartOutcome';
import { estimateSubtotal, InstamartPicker } from './InstamartPicker';
import { InstamartReview } from './InstamartReview';
import { TopUpCard } from './TopUpCard';
import resultsStyles from './results.module.css';
import styles from './instamart.module.css';

interface InstamartOrderSheetProps {
  open: boolean;
  itemsToOrder: ChecklistItem[];
  topUpSuggestions: TopUpSuggestion[];
  /** Add-ons to re-select when reopening after the OAuth round trip (lib/pendingOrder.ts). */
  initialSelectedTopUpNames?: string[];
  /** Checklist item the user tapped: its row is scrolled into view and highlighted once products load. */
  focusIngredient?: string | null;
  onClose: () => void;
  /** Fired just before "Connect with Swiggy" navigates away, so the caller can stash state to resume. */
  onConnectClick: (selectedTopUpNames: string[]) => void;
}

const SUBTITLES: Record<Stage, string> = {
  searching: 'Searching Instamart…',
  picking: 'Choose what to add to your cart',
  building: 'Building your cart…',
  reviewing: 'Review your cart before ordering',
  placing: 'Placing your order…',
  done: 'Order status',
  error: 'Something went wrong',
};

// Replaces the old single "Confirm order" sheet. Nothing is added to a cart or
// ordered until the user has seen real Instamart products (picker), then the
// real cart Swiggy will bill (review), and taps a separate "Place order".
// Always dark regardless of site theme — same reasoning as the dish hero.
export function InstamartOrderSheet({ open, itemsToOrder, topUpSuggestions, initialSelectedTopUpNames, focusIngredient, onClose, onConnectClick }: InstamartOrderSheetProps) {
  const auth = useAuth();
  const order = useInstamartOrder();
  const { state } = order;
  const connected = auth.status === 'connected';

  const [mounted, setMounted] = useState(open);
  const [visible, setVisible] = useState(false);
  const touchStartY = useRef(0);
  const panelRef = useRef<HTMLDivElement>(null);

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

  // Start (or restart after connecting) the search each time the sheet opens.
  useEffect(() => {
    if (!open || !connected) return;
    const missing = itemsToOrder.map(i => i.name);
    const restored = (initialSelectedTopUpNames ?? []).filter(n => !missing.includes(n));
    void order.search([...missing, ...restored], restored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, connected]);

  useEffect(() => {
    if (state.stage !== 'picking' || !focusIngredient) return;
    const rows = panelRef.current?.querySelectorAll<HTMLElement>('[data-ingredient]') ?? [];
    Array.from(rows).find(el => el.dataset.ingredient === focusIngredient)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [state.stage, focusIngredient]);

  // Drop all flow state once the closing animation has finished.
  useEffect(() => {
    if (!mounted) order.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted]);

  if (!mounted) return null;

  const placing = state.stage === 'placing';
  const selectedPayment = state.review?.payment.options.find(o => o.key === state.paymentKey) ?? null;
  const close = () => { if (!placing) onClose(); }; // a request is in flight: the user must see its outcome

  const selectedTopUps = new Set(state.extras);
  const toggleTopUp = (name: string) => {
    if (selectedTopUps.has(name)) order.removeExtra(name);
    else void order.addExtra(name);
  };

  const handleTouchStart = (e: TouchEvent<HTMLDivElement>) => { touchStartY.current = e.touches[0].clientY; };
  const handleTouchEnd = (e: TouchEvent<HTMLDivElement>) => { if (e.changedTouches[0].clientY - touchStartY.current > 80) close(); };

  const { count, amount } = estimateSubtotal(state.results, state.choices);
  const addOnsSearching = state.extras.some(n => !state.results.some(r => r.ingredient === n));
  const needsConnect = auth.status === 'disconnected' || state.authNeeded;

  return (
    <div className={resultsStyles.orderBottomSheet}>
      <div className={`${resultsStyles.orderSheetBackdrop} ${visible ? resultsStyles.visible : ''}`} onClick={close} />
      <div
        ref={panelRef}
        className={`${resultsStyles.orderSheetPanel} ${visible ? resultsStyles.visible : ''}`}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        <div className={resultsStyles.orderSheetHandle} />

        <div className={resultsStyles.orderSheetHeader}>
          <h3 className={resultsStyles.orderSheetTitle}>Your Instamart order</h3>
          <p className={resultsStyles.orderSheetSubtitle}>{needsConnect ? 'Connect Swiggy to continue' : SUBTITLES[state.stage]}</p>
        </div>
        <p className={resultsStyles.orderSheetSwiggy}>Powered by <strong>Swiggy</strong></p>

        {needsConnect ? (
          <div className={resultsStyles.orderSheetAuthNotice}>
            <p>Connect your Swiggy account to see real Instamart products and prices for what you&apos;re missing.</p>
            <a className={resultsStyles.orderSheetAuthCta} href="/auth/login?next=/" onClick={() => onConnectClick(Array.from(selectedTopUps))}>
              <Link2 /> Connect with Swiggy
            </a>
          </div>
        ) : auth.status === 'loading' || state.stage === 'searching' || state.stage === 'building' ? (
          <div className={styles.list} aria-busy="true" aria-label={SUBTITLES[state.stage]}>
            {[0, 1, 2].map(i => <div key={i} className={styles.skeleton} />)}
          </div>
        ) : state.stage === 'error' ? (
          <div className={styles.centered}>
            <p className={styles.outcomeBody}>{state.error}</p>
            <button type="button" className={styles.primary} onClick={() => order.search([...itemsToOrder.map(i => i.name), ...state.extras], state.extras)}>Try again</button>
            <button type="button" className={styles.secondary} onClick={close}>Close</button>
          </div>
        ) : state.stage === 'done' && state.outcome ? (
          <InstamartOutcome outcome={state.outcome} payOnDelivery={selectedPayment?.type === 'cod'} onClose={onClose} onBackToCart={order.backToPicking} />
        ) : state.stage === 'picking' ? (
          <>
            {state.notice && <p className={styles.notice}>{state.notice}</p>}
            {state.address && state.address.id && (
              <p className={styles.address}>Delivering to <strong>{state.address.label}</strong> — {state.address.addressLine}</p>
            )}
            <InstamartPicker
              results={state.results}
              choices={state.choices}
              extras={selectedTopUps}
              focusIngredient={focusIngredient}
              onPick={order.pick}
              onQuantity={order.setQuantity}
              onRemoveExtra={order.removeExtra}
            />
            {topUpSuggestions.length > 0 && (
              <>
                <p className={styles.sectionLabel}>Add to your order?</p>
                <div className={resultsStyles.orderSheetTopUpCards}>
                  {topUpSuggestions.slice(0, 5).map(item => (
                    <TopUpCard key={item.name} item={item} selected={selectedTopUps.has(item.name)} onToggle={() => toggleTopUp(item.name)} />
                  ))}
                </div>
              </>
            )}
            <button
              type="button"
              className={styles.primary}
              disabled={count === 0 || !state.address || addOnsSearching}
              onClick={() => state.address && order.buildCart(state.address.id, selectionsFrom(state))}
            >
              {addOnsSearching ? 'Searching add-ons…' : count === 0 ? 'Pick at least one item' : `Review cart · ${count} item${count === 1 ? '' : 's'} · about ${formatInr(amount)}`}
            </button>
            <p className={styles.hint}>Nothing is ordered yet — you&apos;ll review the real cart next.</p>
          </>
        ) : state.review ? (
          <>
            {state.notice && <p className={styles.notice}>{state.notice}</p>}
            <InstamartReview
              review={state.review}
              adjustments={state.adjustments}
              coupons={state.coupons}
              appliedCoupon={state.appliedCoupon}
              couponBusy={state.couponBusy}
              paymentKey={state.paymentKey}
              disabled={placing}
              onSelectPayment={order.selectPayment}
              onApplyCoupon={code => order.applyCoupon(state.review!.address.id!, code)}
            />
            <button
              type="button"
              className={styles.primary}
              disabled={placing || state.couponBusy !== null || !selectedPayment || !state.review.canCheckout || !state.review.address.id || !state.review.total || !state.idempotencyKey}
              onClick={() => order.placeOrder(state.review!.address.id!, state.review!.total!, state.idempotencyKey!, selectedPayment!.key)}
            >
              {placing ? (
                <><LoaderCircle className={styles.spin} style={{ width: 16, height: 16, verticalAlign: '-3px' }} /> Placing your order…</>
              ) : (
                selectedPayment?.type === 'cod' ? `Place order · ${state.review.total} · Pay on delivery` : `Continue to payment · ${state.review.total}`
              )}
            </button>
            <button type="button" className={styles.secondary} disabled={placing} onClick={order.backToPicking}>Edit items</button>
            {placing && <p className={styles.hint}>Please keep this open until it finishes.</p>}
          </>
        ) : null}
      </div>
    </div>
  );
}
