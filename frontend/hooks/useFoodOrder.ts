'use client';
import { useCallback, useReducer, useRef } from 'react';
import {
  FoodApiError,
  foodApplyCoupon,
  foodCart,
  foodCheckout,
  foodPaymentStatus,
  foodSearch,
  newIdempotencyKey,
  type AppliedCoupon,
  type CouponList,
  type FoodOutcome,
  type FoodPendingPayment,
  type FoodResult,
  type FoodReview,
  type InstamartAddress,
} from '../lib/food';
import { setSelectedAddressId } from '../lib/addressStore';
import { pollPayment as pollPaymentLoop } from '../lib/pollPayment';
import { initialPicks, setQuantity, setVariant, toggleAddon, toSelection, type Picks } from '../lib/foodSelection';

export type Stage = 'searching' | 'picking' | 'building' | 'reviewing' | 'placing' | 'done' | 'error';

export interface FoodState {
  stage: Stage;
  address: InstamartAddress | null;
  results: FoodResult[];
  /** The dish being customized (menuItemId) and what has been picked for it. */
  openId: string | null;
  picks: Picks | null;
  review: FoodReview | null;
  coupons: CouponList;
  /** Set once Swiggy's cart actually shows the discount; there is no remove-coupon tool. */
  appliedCoupon: AppliedCoupon | null;
  /** Code currently being applied (disables the coupon buttons). */
  couponBusy: string | null;
  /** Key of the chosen PaymentOption; re-validated server-side at checkout. */
  paymentKey: string | null;
  idempotencyKey: string | null;
  outcome: FoodOutcome | null;
  notice: string | null;
  /** The Swiggy tool behind `notice` / `error` when one refused, so a problem report can name it. */
  noticeTool: string | null;
  error: string | null;
  errorTool: string | null;
  authNeeded: boolean;
}

type Action =
  | { type: 'SEARCH_START' }
  | { type: 'SEARCH_OK'; address: InstamartAddress; results: FoodResult[] }
  | { type: 'OPEN'; result: FoodResult }
  | { type: 'CLOSE_ITEM' }
  | { type: 'VARIANT'; groupId: string; optionId: string }
  | { type: 'ADDON'; groupId: string; addonId: string; max: number | null }
  | { type: 'QTY'; quantity: number }
  | { type: 'BUILD_START' }
  | { type: 'BUILD_OK'; review: FoodReview; coupons: CouponList; key: string }
  | { type: 'COUPON_START'; code: string }
  | { type: 'COUPON_OK'; review: FoodReview; coupons: CouponList; coupon: AppliedCoupon; key: string }
  | { type: 'COUPON_FAIL'; notice: string; unusableCode?: string; tool?: string | null }
  | { type: 'SELECT_PAYMENT'; key: string }
  | { type: 'PLACE_START' }
  | { type: 'PLACE_OK'; outcome: FoodOutcome }
  | { type: 'REVIEW_NOTICE'; notice: string; tool?: string | null }
  | { type: 'BACK'; notice?: string | null; tool?: string | null }
  | { type: 'FAIL'; message: string; authNeeded: boolean; tool?: string | null }
  | { type: 'RESET' };

const NO_COUPONS: CouponList = { available: false, items: [] };

const initial: FoodState = {
  stage: 'searching', address: null, results: [], openId: null, picks: null, review: null, coupons: NO_COUPONS, appliedCoupon: null, couponBusy: null, paymentKey: null,
  idempotencyKey: null, outcome: null, notice: null, noticeTool: null, error: null, errorTool: null, authNeeded: false,
};

/** Keep the user's payment choice if Swiggy still offers it, else prefer cash on delivery, else the first option. */
function pickPayment(review: FoodReview, current: string | null): string | null {
  const options = review.payment.options;
  if (current && options.some(o => o.key === current)) return current;
  return (options.find(o => o.type === 'cod') ?? options[0])?.key ?? null;
}

function reducer(state: FoodState, action: Action): FoodState {
  switch (action.type) {
    case 'SEARCH_START':
      return { ...initial };
    case 'SEARCH_OK':
      return { ...state, stage: 'picking', address: action.address, results: action.results };
    case 'OPEN':
      return { ...state, openId: action.result.menuItemId, picks: initialPicks(action.result), notice: null, noticeTool: null };
    case 'CLOSE_ITEM':
      return { ...state, openId: null, picks: null };
    case 'VARIANT':
      return state.picks ? { ...state, picks: setVariant(state.picks, action.groupId, action.optionId) } : state;
    case 'ADDON':
      return state.picks ? { ...state, picks: toggleAddon(state.picks, action.groupId, action.addonId, action.max) } : state;
    case 'QTY':
      return state.picks ? { ...state, picks: setQuantity(state.picks, action.quantity) } : state;
    case 'BUILD_START':
      return { ...state, stage: 'building', notice: null, noticeTool: null, error: null, errorTool: null };
    case 'BUILD_OK':
      // a rebuilt cart starts without a coupon (the cart is flushed first)
      return { ...state, stage: 'reviewing', review: action.review, coupons: action.coupons, appliedCoupon: null, couponBusy: null, paymentKey: pickPayment(action.review, state.paymentKey), idempotencyKey: action.key, notice: null, noticeTool: null };
    case 'COUPON_START':
      return { ...state, couponBusy: action.code, notice: null, noticeTool: null };
    case 'COUPON_OK':
      // the cart changed: never reuse an idempotency key from before the discount
      return { ...state, review: action.review, coupons: action.coupons, appliedCoupon: action.coupon, couponBusy: null, paymentKey: pickPayment(action.review, state.paymentKey), idempotencyKey: action.key, notice: null, noticeTool: null };
    case 'COUPON_FAIL':
      return {
        ...state,
        couponBusy: null,
        notice: action.notice,
        noticeTool: action.tool ?? null,
        coupons: action.unusableCode
          ? { ...state.coupons, items: state.coupons.items.map(c => (c.code === action.unusableCode ? { ...c, applicable: false, message: action.notice } : c)) }
          : state.coupons,
      };
    case 'SELECT_PAYMENT':
      return { ...state, paymentKey: action.key };
    case 'PLACE_START':
      return { ...state, stage: 'placing', notice: null, noticeTool: null };
    case 'PLACE_OK':
      return { ...state, stage: 'done', outcome: action.outcome };
    case 'REVIEW_NOTICE':
      return { ...state, stage: 'reviewing', notice: action.notice, noticeTool: action.tool ?? null };
    case 'BACK':
      return { ...state, stage: 'picking', review: null, appliedCoupon: null, couponBusy: null, idempotencyKey: null, notice: action.notice ?? null, noticeTool: action.tool ?? null };
    case 'FAIL':
      return { ...state, stage: 'error', error: action.message, errorTool: action.tool ?? null, authNeeded: action.authNeeded };
    case 'RESET':
      return { ...initial };
  }
}

// Server-side reasons the reviewed cart is no longer safe to order: go back and rebuild it.
const REVIEW_AGAIN = new Set(['cart_changed', 'cart_blocked', 'cart_mismatch', 'out_of_stock', 'unserviceable', 'cart_expired']);
// A coupon Swiggy no longer lists / accepts: mark it unusable, keep the cart.
const COUPON_UNUSABLE = new Set(['coupon_not_found', 'coupon_not_applicable']);

const UNKNOWN_OUTCOME: FoodOutcome = {
  status: 'unknown',
  orderIds: [],
  message: "We couldn't confirm whether the order went through. Check the Swiggy app before trying again.",
  verified: false,
  total: null,
  detail: null,
  payment: null,
};

function describe(e: unknown): { message: string; authNeeded: boolean; code: string; tool: string | null } {
  if (e instanceof FoodApiError) return { message: e.message, authNeeded: e.code === 'auth_required', code: e.code, tool: e.tool };
  return { message: "Couldn't reach the server. Check your connection and try again.", authNeeded: false, code: 'network', tool: null };
}

export function useFoodOrder() {
  const [state, dispatch] = useReducer(reducer, initial);
  // Bumped on every (re)start so a slow response from a closed/restarted sheet is dropped.
  const run = useRef(0);

  const search = useCallback(async (dish: string, addressId: string | null = null) => {
    const id = ++run.current;
    dispatch({ type: 'SEARCH_START' });
    // Two passes at most: if the remembered address was deleted elsewhere, forget it and use the default.
    let target = addressId;
    for (let pass = 0; pass < 2; pass++) {
      try {
        const { address, results } = await foodSearch(dish, target);
        if (run.current === id) dispatch({ type: 'SEARCH_OK', address, results });
        return;
      } catch (e) {
        const d = describe(e);
        if (run.current !== id) return;
        if (d.code === 'address_not_found' && target && pass === 0) {
          setSelectedAddressId(null);
          target = null;
          continue;
        }
        return dispatch({ type: 'FAIL', message: d.message, authNeeded: d.authNeeded, tool: d.tool });
      }
    }
  }, []);

  const open = useCallback((result: FoodResult) => dispatch({ type: 'OPEN', result }), []);
  const closeItem = useCallback(() => dispatch({ type: 'CLOSE_ITEM' }), []);
  const chooseVariant = useCallback((groupId: string, optionId: string) => dispatch({ type: 'VARIANT', groupId, optionId }), []);
  const chooseAddon = useCallback((groupId: string, addonId: string, max: number | null) => dispatch({ type: 'ADDON', groupId, addonId, max }), []);
  const setQty = useCallback((quantity: number) => dispatch({ type: 'QTY', quantity }), []);
  const selectPayment = useCallback((key: string) => dispatch({ type: 'SELECT_PAYMENT', key }), []);
  const backToPicking = useCallback(() => dispatch({ type: 'BACK' }), []);
  const reset = useCallback(() => { run.current++; dispatch({ type: 'RESET' }); }, []);

  const buildCart = useCallback(async (addressId: string, result: FoodResult, picks: Picks) => {
    const id = run.current;
    dispatch({ type: 'BUILD_START' });
    try {
      const { review, coupons } = await foodCart(addressId, toSelection(result, picks));
      if (run.current === id) dispatch({ type: 'BUILD_OK', review, coupons, key: newIdempotencyKey() });
    } catch (e) {
      const d = describe(e);
      if (run.current !== id) return;
      if (d.authNeeded) dispatch({ type: 'FAIL', message: d.message, authNeeded: true });
      else dispatch({ type: 'BACK', notice: d.message, tool: d.tool });
    }
  }, []);

  const applyCoupon = useCallback(async (addressId: string, code: string) => {
    const id = run.current;
    dispatch({ type: 'COUPON_START', code });
    try {
      const { review, coupons, coupon } = await foodApplyCoupon(addressId, code);
      if (run.current === id) dispatch({ type: 'COUPON_OK', review, coupons, coupon, key: newIdempotencyKey() });
    } catch (e) {
      const d = describe(e);
      if (run.current !== id) return;
      if (d.authNeeded) return dispatch({ type: 'FAIL', message: d.message, authNeeded: true });
      if (REVIEW_AGAIN.has(d.code)) return dispatch({ type: 'BACK', notice: `${d.message} Your choices are saved — review the cart again.`, tool: d.tool });
      dispatch({ type: 'COUPON_FAIL', notice: d.message, unusableCode: COUPON_UNUSABLE.has(d.code) ? code : undefined, tool: COUPON_UNUSABLE.has(d.code) ? null : d.tool });
    }
  }, []);

  /** Client-driven UPI polling (shared with Instamart): nothing is held open server-side. */
  const pollPayment = useCallback((payment: FoodPendingPayment) => {
    const id = run.current;
    return pollPaymentLoop<FoodOutcome>({
      pollIntervalMs: payment.pollIntervalMs,
      maxPollMs: payment.maxPollMs,
      isCurrent: () => run.current === id,
      check: async final => (await foodPaymentStatus(payment, final)).order,
      onDone: outcome => dispatch({ type: 'PLACE_OK', outcome }),
      onGiveUp: () => dispatch({ type: 'PLACE_OK', outcome: { ...UNKNOWN_OUTCOME, orderIds: [payment.orderId] } }),
      onError: e => {
        const d = describe(e);
        if (d.authNeeded) dispatch({ type: 'FAIL', message: d.message, authNeeded: true });
        return d.authNeeded;
      },
    });
  }, []);

  const placeOrder = useCallback(async (addressId: string, expectedTotal: number, key: string, paymentKey: string) => {
    const id = run.current;
    dispatch({ type: 'PLACE_START' });
    try {
      const { order } = await foodCheckout(addressId, expectedTotal, key, paymentKey);
      if (run.current !== id) return;
      dispatch({ type: 'PLACE_OK', outcome: order });
      if (order.status === 'pending_payment' && order.payment) void pollPayment(order.payment);
    } catch (e) {
      if (run.current !== id) return;
      const d = describe(e);
      if (d.authNeeded) return dispatch({ type: 'FAIL', message: d.message, authNeeded: true });
      if (d.code === 'payment_unavailable' || d.code === 'checkout_in_progress') return dispatch({ type: 'REVIEW_NOTICE', notice: d.message });
      if (REVIEW_AGAIN.has(d.code)) return dispatch({ type: 'BACK', notice: `${d.message} Your choices are saved — review the cart again.`, tool: d.tool });
      // No response at all (dropped connection): the order may or may not exist — never invite a blind retry.
      const ambiguous = d.code === 'network' || d.code === 'unexpected_response';
      dispatch({ type: 'PLACE_OK', outcome: ambiguous ? UNKNOWN_OUTCOME : { ...UNKNOWN_OUTCOME, status: 'failed', message: d.message } });
    }
  }, [pollPayment]);

  return { state, search, open, closeItem, chooseVariant, chooseAddon, setQty, selectPayment, backToPicking, buildCart, applyCoupon, placeOrder, reset };
}
