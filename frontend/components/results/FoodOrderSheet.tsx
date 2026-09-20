'use client';

import { Link2, LoaderCircle } from 'lucide-react';
import { useEffect, useRef, useState, type TouchEvent } from 'react';
import { useFoodOrder, type Stage } from '@/hooks/useFoodOrder';
import { useAuth } from '@/hooks/useAuth';
import { useSelectedAddressId } from '@/lib/addressStore';
import { pickProblem } from '@/lib/foodSelection';
import { openOrders } from '@/lib/ordersUi';
import { formatInr } from '@/lib/food';
import type { ReportContext } from '@/lib/instamart';
import { AddressPicker } from './AddressPicker';
import { FoodOutcome } from './FoodOutcome';
import { FoodPicker } from './FoodPicker';
import { FoodReview } from './FoodReview';
import { ReportProblem } from './ReportProblem';
import resultsStyles from './results.module.css';
import styles from './instamart.module.css';

interface FoodOrderSheetProps {
  open: boolean;
  /** The recipe's dish, used as the search query. */
  dish: string;
  onClose: () => void;
}

const SUBTITLES: Record<Stage, string> = {
  searching: 'Finding it on Swiggy…',
  picking: 'Choose a dish to add to your cart',
  building: 'Building your cart…',
  reviewing: 'Review your order before placing it',
  placing: 'Placing your order…',
  done: 'Order status',
  error: 'Something went wrong',
};

// Nothing is added to a cart or ordered until the user has seen real dishes from real restaurants (picker), then
// the real cart Swiggy will bill (review), and taps a separate "Place order". Always dark, like the Instamart sheet.
export function FoodOrderSheet({ open, dish, onClose }: FoodOrderSheetProps) {
  const auth = useAuth();
  const order = useFoodOrder();
  const { state } = order;
  const connected = auth.status === 'connected';

  const [mounted, setMounted] = useState(open);
  const [visible, setVisible] = useState(false);
  const [addressOpen, setAddressOpen] = useState(false);
  const selectedAddressId = useSelectedAddressId();
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

  // Start the search each time the sheet opens (or once the account is connected).
  useEffect(() => {
    if (!open || !connected) return;
    void order.search(dish, selectedAddressId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, connected]);

  // Drop all flow state once the closing animation has finished.
  useEffect(() => {
    if (!mounted) order.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted]);

  if (!mounted) return null;

  const placing = state.stage === 'placing';
  const close = () => { if (!placing) onClose(); }; // a request is in flight: the user must see its outcome
  const handleTouchStart = (e: TouchEvent<HTMLDivElement>) => { touchStartY.current = e.touches[0].clientY; };
  const handleTouchEnd = (e: TouchEvent<HTMLDivElement>) => { if (e.changedTouches[0].clientY - touchStartY.current > 80) close(); };

  const openResult = state.results.find(r => r.menuItemId === state.openId) ?? null;
  const problem = openResult && state.picks ? pickProblem(openResult, state.picks) : null;
  const selectedPayment = state.review?.payment.options.find(o => o.key === state.paymentKey) ?? null;
  // Identifiers a problem report should carry (no names, phone numbers or address text).
  const restaurantId = state.review?.restaurant.id ?? openResult?.restaurant.id ?? null;
  const addressId = state.review?.address.id ?? state.address?.id ?? null;
  const reportContext: ReportContext = {
    ...(addressId ? { addressId } : {}),
    ...(restaurantId ? { restaurantId } : {}),
    ...(openResult ? { menu_item_id: openResult.menuItemId } : {}),
    ...(selectedPayment ? { paymentMethod: selectedPayment.type === 'cod' ? 'Cash' : 'UPI' } : {}),
    ...(state.appliedCoupon ? { couponCode: state.appliedCoupon.code } : {}),
  };
  const noticeReport = state.notice && state.noticeTool && (
    <ReportProblem
      product="food"
      input={{ tool: state.noticeTool, errorMessage: state.notice, flow: state.review ? 'Reviewed the Food cart' : 'Chose a dish and built the Food cart', context: reportContext }}
    />
  );
  const needsConnect = auth.status === 'disconnected' || state.authNeeded;
  const busy = auth.status === 'loading' || state.stage === 'searching' || state.stage === 'building';

  return (
    <div className={resultsStyles.orderBottomSheet}>
      <div className={`${resultsStyles.orderSheetBackdrop} ${visible ? resultsStyles.visible : ''}`} onClick={close} />
      <div className={`${resultsStyles.orderSheetPanel} ${visible ? resultsStyles.visible : ''}`} onTouchStart={handleTouchStart} onTouchEnd={handleTouchEnd}>
        <div className={resultsStyles.orderSheetHandle} />

        <div className={resultsStyles.orderSheetHeader}>
          <h3 className={resultsStyles.orderSheetTitle}>Order {dish} from Swiggy</h3>
          <p className={resultsStyles.orderSheetSubtitle}>{needsConnect ? 'Connect Swiggy to continue' : SUBTITLES[state.stage]}</p>
        </div>
        <p className={resultsStyles.orderSheetSwiggy}>Powered by <strong>Swiggy</strong></p>

        {needsConnect ? (
          <div className={resultsStyles.orderSheetAuthNotice}>
            <p>Connect your Swiggy account to see real restaurants, dishes and prices near you.</p>
            <a className={resultsStyles.orderSheetAuthCta} href="/auth/login?next=/"><Link2 /> Connect with Swiggy</a>
          </div>
        ) : busy ? (
          <div className={styles.list} aria-busy="true" aria-label={SUBTITLES[state.stage]}>
            {[0, 1, 2].map(i => <div key={i} className={styles.skeleton} />)}
          </div>
        ) : state.stage === 'error' ? (
          <div className={styles.centered}>
            <p className={styles.outcomeBody}>{state.error}</p>
            <button type="button" className={styles.primary} onClick={() => order.search(dish, selectedAddressId)}>Try again</button>
            <button type="button" className={styles.secondary} onClick={close}>Close</button>
            <ReportProblem
              product="food"
              input={{ tool: state.errorTool ?? 'search_menu', errorMessage: state.error ?? 'Search failed', flow: 'Searched Swiggy Food for the dish', context: { ...((state.address?.id ?? selectedAddressId) ? { addressId: (state.address?.id ?? selectedAddressId) as string } : {}), query: dish } }}
            />
          </div>
        ) : state.stage === 'done' && state.outcome ? (
          <FoodOutcome outcome={state.outcome} payOnDelivery={selectedPayment?.type === 'cod'} onClose={onClose} onBackToCart={order.backToPicking} onTrack={id => { onClose(); openOrders(id, 'food', state.review?.address.id ?? null); }} reportTool={selectedPayment && selectedPayment.type !== 'cod' ? 'check_payment_status' : 'place_food_order'} reportContext={reportContext} />
        ) : state.stage === 'picking' && addressOpen ? (
          <AddressPicker
            currentId={state.address?.id ?? null}
            onBack={() => setAddressOpen(false)}
            onChoose={id => {
              setAddressOpen(false);
              // Availability, prices and delivery time depend on the address, so a different one restarts the search.
              if (id !== state.address?.id) void order.search(dish, id);
            }}
          />
        ) : state.stage === 'picking' ? (
          <>
            {state.notice && <p className={styles.notice}>{state.notice}</p>}
            {noticeReport}
            {state.address && (
              <p className={styles.address}>
                Delivering to <strong>{state.address.label}</strong> — {state.address.addressLine}{' '}
                <button type="button" className={styles.linkBtn} onClick={() => setAddressOpen(true)}>Change</button>
              </p>
            )}
            <FoodPicker
              results={state.results}
              openId={state.openId}
              picks={state.picks}
              onOpen={order.open}
              onClose={order.closeItem}
              onVariant={order.chooseVariant}
              onAddon={order.chooseAddon}
              onQuantity={order.setQty}
            />
            {openResult && state.picks && state.address && (
              <button
                type="button"
                className={styles.primary}
                disabled={problem !== null}
                onClick={() => order.buildCart(state.address!.id, openResult, state.picks!)}
              >
                {problem ? 'Finish your choices to continue' : `Review cart · ${state.picks.quantity} × ${openResult.name}`}
              </button>
            )}
            <p className={styles.hint}>Nothing is ordered yet — you&apos;ll review the real cart next.</p>
          </>
        ) : state.review ? (
          <>
            {state.notice && <p className={styles.notice}>{state.notice}</p>}
            {noticeReport}
            <FoodReview
              review={state.review}
              coupons={state.coupons}
              appliedCoupon={state.appliedCoupon}
              couponBusy={state.couponBusy}
              paymentKey={state.paymentKey}
              disabled={placing}
              onSelectPayment={order.selectPayment}
              onApplyCoupon={code => order.applyCoupon(state.review!.address.id, code)}
            />
            <button
              type="button"
              className={styles.primary}
              disabled={placing || state.couponBusy !== null || !selectedPayment || !state.review.canCheckout || state.review.total === null || !state.idempotencyKey}
              onClick={() => order.placeOrder(state.review!.address.id, state.review!.total!, state.idempotencyKey!, selectedPayment!.key)}
            >
              {placing ? (
                <><LoaderCircle className={styles.spin} style={{ width: 16, height: 16, verticalAlign: '-3px' }} /> Placing your order…</>
              ) : (
                selectedPayment?.type === 'cod'
                  ? `Place order · ${state.review.total !== null ? formatInr(state.review.total) : ''} · Pay on delivery`
                  : `Continue to payment · ${state.review.total !== null ? formatInr(state.review.total) : ''}`
              )}
            </button>
            <button type="button" className={styles.secondary} disabled={placing} onClick={order.backToPicking}>Edit dish</button>
            {placing && <p className={styles.hint}>Please keep this open until it finishes.</p>}
          </>
        ) : null}
      </div>
    </div>
  );
}
