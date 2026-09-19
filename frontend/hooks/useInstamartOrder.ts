'use client';
import { useCallback, useReducer, useRef } from 'react';
import {
  InstamartApiError,
  instamartApplyCoupon,
  instamartCart,
  instamartCheckout,
  instamartPaymentStatus,
  newIdempotencyKey,
  topAvailable,
  type AppliedCoupon,
  type CartSelection,
  type CouponList,
  type InstamartAddress,
  type InstamartOutcome,
  type InstamartReview,
  type InstamartSearchResult,
  type PendingPayment,
} from '../lib/instamart';
import { productCache } from '../lib/instamartSearch';
import { keyOf } from '../lib/searchCache';

export type Stage = 'searching' | 'picking' | 'building' | 'reviewing' | 'placing' | 'done' | 'error';

/** spinId === null means the user skipped this ingredient. */
export interface Choice { spinId: string | null; quantity: number }

export interface InstamartState {
  stage: Stage;
  address: InstamartAddress | null;
  results: InstamartSearchResult[];
  /** Add-on ingredients the user tapped (searched on demand, removable). */
  extras: string[];
  choices: Record<string, Choice>;
  review: InstamartReview | null;
  adjustments: string[];
  coupons: CouponList;
  /** Set once Swiggy's cart actually shows the discount; there is no remove-coupon tool. */
  appliedCoupon: AppliedCoupon | null;
  /** Code currently being applied (disables the coupon buttons). */
  couponBusy: string | null;
  /** Key of the chosen PaymentOption; re-validated server-side at checkout. */
  paymentKey: string | null;
  idempotencyKey: string | null;
  outcome: InstamartOutcome | null;
  /** Shown as a banner on the current step. */
  notice: string | null;
  /** Fatal for the current stage (stage === 'error'). */
  error: string | null;
  authNeeded: boolean;
}

type Action =
  | { type: 'SEARCH_START'; extras: string[] }
  | { type: 'EXTRA_ADD'; ingredient: string }
  | { type: 'SEARCH_OK'; address: InstamartAddress | null; results: InstamartSearchResult[] }
  | { type: 'EXTRA_OK'; address: InstamartAddress; result: InstamartSearchResult }
  | { type: 'EXTRA_REMOVE'; ingredient: string }
  | { type: 'PICK'; ingredient: string; spinId: string | null }
  | { type: 'QTY'; ingredient: string; quantity: number }
  | { type: 'BUILD_START' }
  | { type: 'BUILD_OK'; review: InstamartReview; adjustments: string[]; coupons: CouponList; key: string }
  | { type: 'SELECT_PAYMENT'; key: string }
  | { type: 'COUPON_START'; code: string }
  | { type: 'COUPON_OK'; review: InstamartReview; coupons: CouponList; coupon: AppliedCoupon; key: string }
  | { type: 'COUPON_FAIL'; notice: string; unusableCode?: string }
  | { type: 'PLACE_START' }
  | { type: 'PLACE_OK'; outcome: InstamartOutcome }
  | { type: 'REVIEW_NOTICE'; notice: string }
  | { type: 'BACK'; notice?: string | null }
  | { type: 'FAIL'; message: string; authNeeded: boolean; stage: Stage }
  | { type: 'RESET' };

const NO_COUPONS: CouponList = { available: false, items: [] };

const initial: InstamartState = {
  stage: 'searching', address: null, results: [], extras: [], choices: {}, review: null, adjustments: [],
  coupons: NO_COUPONS, appliedCoupon: null, couponBusy: null, paymentKey: null,
  idempotencyKey: null, outcome: null, notice: null, error: null, authNeeded: false,
};

/** The top in-stock match is pre-picked (Swiggy's own ranking); the user reviews, swaps or skips. */
function defaultChoice(result: InstamartSearchResult): Choice {
  return { spinId: topAvailable(result)?.spinId ?? null, quantity: 1 };
}

/** Keep the user's payment choice if Swiggy still offers it, else prefer cash on delivery, else the first option. */
function pickPayment(review: InstamartReview, current: string | null): string | null {
  const options = review.payment.options;
  if (current && options.some(o => o.key === current)) return current;
  return (options.find(o => o.type === 'cod') ?? options[0])?.key ?? null;
}

function reducer(state: InstamartState, action: Action): InstamartState {
  switch (action.type) {
    case 'SEARCH_START':
      return { ...initial, extras: action.extras };
    case 'EXTRA_ADD':
      return state.extras.includes(action.ingredient) ? state : { ...state, extras: [...state.extras, action.ingredient] };
    case 'SEARCH_OK':
      return {
        ...state,
        stage: 'picking',
        address: action.address,
        results: action.results,
        choices: Object.fromEntries(action.results.map(r => [r.ingredient, defaultChoice(r)])),
      };
    case 'EXTRA_OK':
      if (state.results.some(r => r.ingredient === action.result.ingredient)) return state;
      return {
        ...state,
        address: state.address ?? action.address,
        results: [...state.results, action.result],
        choices: { ...state.choices, [action.result.ingredient]: defaultChoice(action.result) },
      };
    case 'EXTRA_REMOVE':
      return {
        ...state,
        extras: state.extras.filter(n => n !== action.ingredient),
        results: state.results.filter(r => r.ingredient !== action.ingredient),
        choices: Object.fromEntries(Object.entries(state.choices).filter(([name]) => name !== action.ingredient)),
      };
    case 'PICK':
      return { ...state, choices: { ...state.choices, [action.ingredient]: { spinId: action.spinId, quantity: state.choices[action.ingredient]?.quantity ?? 1 } } };
    case 'QTY':
      return { ...state, choices: { ...state.choices, [action.ingredient]: { ...state.choices[action.ingredient], quantity: action.quantity } } };
    case 'BUILD_START':
      return { ...state, stage: 'building', notice: null, error: null };
    case 'BUILD_OK':
      return {
        ...state,
        stage: 'reviewing',
        review: action.review,
        adjustments: action.adjustments,
        coupons: action.coupons,
        appliedCoupon: null, // a rebuilt cart starts without a coupon (clear_cart)
        couponBusy: null,
        paymentKey: pickPayment(action.review, state.paymentKey),
        idempotencyKey: action.key,
        notice: null,
      };
    case 'SELECT_PAYMENT':
      return { ...state, paymentKey: action.key };
    case 'COUPON_START':
      return { ...state, couponBusy: action.code, notice: null };
    case 'COUPON_OK':
      return {
        ...state,
        review: action.review,
        coupons: action.coupons,
        appliedCoupon: action.coupon,
        couponBusy: null,
        paymentKey: pickPayment(action.review, state.paymentKey),
        idempotencyKey: action.key, // the cart changed: never reuse a key from before the discount
        notice: null,
      };
    case 'COUPON_FAIL':
      return {
        ...state,
        couponBusy: null,
        notice: action.notice,
        coupons: action.unusableCode
          ? { ...state.coupons, items: state.coupons.items.map(c => (c.code === action.unusableCode ? { ...c, applicable: false, message: action.notice } : c)) }
          : state.coupons,
      };
    case 'PLACE_START':
      return { ...state, stage: 'placing', notice: null };
    case 'PLACE_OK':
      return { ...state, stage: 'done', outcome: action.outcome };
    case 'REVIEW_NOTICE':
      return { ...state, stage: 'reviewing', notice: action.notice };
    case 'BACK':
      return { ...state, stage: 'picking', review: null, idempotencyKey: null, appliedCoupon: null, couponBusy: null, notice: action.notice ?? null };
    case 'FAIL':
      return { ...state, stage: action.stage, error: action.message, authNeeded: action.authNeeded };
    case 'RESET':
      return { ...initial };
  }
}

/** Selections for the cart stage: every non-skipped ingredient's chosen SKU. */
export function selectionsFrom(state: InstamartState): CartSelection[] {
  return state.results.flatMap(r => {
    const choice = state.choices[r.ingredient];
    const option = r.options.find(o => o.spinId === choice?.spinId);
    return option && choice ? [{ spin_id: option.spinId, sku_id: option.skuId, quantity: choice.quantity }] : [];
  });
}

// Server-side reasons the reviewed cart is no longer safe to order: go back and rebuild it.
const REVIEW_AGAIN = new Set(['cart_changed', 'cart_blocked', 'address_mismatch', 'min_order_not_met', 'unserviceable', 'out_of_stock', 'cart_expired']);
// A coupon Swiggy no longer lists / accepts: mark it unusable, keep the cart.
const COUPON_UNUSABLE = new Set(['coupon_not_found', 'coupon_not_applicable']);

const UNKNOWN_OUTCOME: InstamartOutcome = {
  status: 'unknown',
  orderIds: [],
  message: "We couldn't confirm whether the order went through. Check the Swiggy app before trying again.",
  verified: false,
  total: null,
  payment: null,
};

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

function describe(e: unknown): { message: string; authNeeded: boolean; code: string } {
  if (e instanceof InstamartApiError) return { message: e.message, authNeeded: e.code === 'auth_required', code: e.code };
  return { message: "Couldn't reach the server. Check your connection and try again.", authNeeded: false, code: 'network' };
}

export function useInstamartOrder() {
  const [state, dispatch] = useReducer(reducer, initial);
  // Bumped on every (re)start so a slow response from a closed/restarted sheet is dropped.
  const run = useRef(0);

  const search = useCallback(async (ingredients: string[], extras: string[] = []) => {
    const id = ++run.current;
    dispatch({ type: 'SEARCH_START', extras });
    if (ingredients.length === 0) {
      dispatch({ type: 'SEARCH_OK', address: null, results: [] });
      return;
    }
    try {
      // Served from the shared cache when the checklist already searched these.
      const { address, entries, error } = await productCache.ensure(ingredients);
      if (run.current !== id) return;
      if (!address) throw error ?? new Error('search failed');
      const results = [...new Map(ingredients.map(n => [keyOf(n), n])).values()].map(name => {
        const hit = entries.get(keyOf(name))?.result;
        return hit ? { ...hit, ingredient: name } : { ingredient: name, options: [], note: "Couldn't search this item" };
      });
      dispatch({ type: 'SEARCH_OK', address, results });
    } catch (e) {
      const d = describe(e);
      if (run.current === id) dispatch({ type: 'FAIL', message: d.message, authNeeded: d.authNeeded, stage: 'error' });
    }
  }, []);

  const addExtra = useCallback(async (ingredient: string) => {
    const id = run.current;
    dispatch({ type: 'EXTRA_ADD', ingredient });
    try {
      const { address, entries, error } = await productCache.ensure([ingredient]);
      if (run.current !== id) return;
      const hit = entries.get(keyOf(ingredient))?.result;
      if (!address || !hit) throw error ?? new Error('search failed');
      dispatch({ type: 'EXTRA_OK', address, result: { ...hit, ingredient } });
    } catch (e) {
      const d = describe(e);
      if (run.current === id) dispatch({ type: 'BACK', notice: d.message });
    }
  }, []);

  const removeExtra = useCallback((ingredient: string) => dispatch({ type: 'EXTRA_REMOVE', ingredient }), []);
  const pick = useCallback((ingredient: string, spinId: string | null) => dispatch({ type: 'PICK', ingredient, spinId }), []);
  const setQuantity = useCallback((ingredient: string, quantity: number) => dispatch({ type: 'QTY', ingredient, quantity }), []);
  const selectPayment = useCallback((key: string) => dispatch({ type: 'SELECT_PAYMENT', key }), []);
  const backToPicking = useCallback(() => dispatch({ type: 'BACK' }), []);
  const reset = useCallback(() => { run.current++; dispatch({ type: 'RESET' }); }, []);

  const buildCart = useCallback(async (addressId: string, selections: CartSelection[]) => {
    const id = run.current;
    dispatch({ type: 'BUILD_START' });
    try {
      const { review, adjustments, coupons } = await instamartCart(addressId, selections);
      if (run.current === id) dispatch({ type: 'BUILD_OK', review, adjustments, coupons, key: newIdempotencyKey() });
    } catch (e) {
      const d = describe(e);
      if (run.current !== id) return;
      if (d.authNeeded) dispatch({ type: 'FAIL', message: d.message, authNeeded: true, stage: 'error' });
      else dispatch({ type: 'BACK', notice: d.message });
    }
  }, []);

  const applyCoupon = useCallback(async (addressId: string, code: string) => {
    const id = run.current;
    dispatch({ type: 'COUPON_START', code });
    try {
      const { review, coupons, coupon } = await instamartApplyCoupon(addressId, code);
      if (run.current === id) dispatch({ type: 'COUPON_OK', review, coupons, coupon, key: newIdempotencyKey() });
    } catch (e) {
      const d = describe(e);
      if (run.current !== id) return;
      if (d.authNeeded) return dispatch({ type: 'FAIL', message: d.message, authNeeded: true, stage: 'error' });
      if (REVIEW_AGAIN.has(d.code)) return dispatch({ type: 'BACK', notice: `${d.message} Your choices are saved — review the cart again.` });
      dispatch({ type: 'COUPON_FAIL', notice: d.message, unusableCode: COUPON_UNUSABLE.has(d.code) ? code : undefined });
    }
  }, []);

  /** Client-driven UPI polling (nothing is held open server-side). At the deadline it asks once more
   *  with final=true so Swiggy can reconcile a late payment; repeated network failures end as "unknown". */
  const pollPayment = useCallback(async (payment: PendingPayment) => {
    const id = run.current;
    const deadline = Date.now() + payment.maxPollMs;
    let failures = 0;
    while (run.current === id) {
      await sleep(payment.pollIntervalMs);
      if (run.current !== id) return;
      const final = Date.now() >= deadline;
      try {
        const { order } = await instamartPaymentStatus(payment.orderId, payment.paasId, final);
        failures = 0;
        if (order.status !== 'pending_payment') return dispatch({ type: 'PLACE_OK', outcome: order });
      } catch (e) {
        const d = describe(e);
        if (d.authNeeded) return dispatch({ type: 'FAIL', message: d.message, authNeeded: true, stage: 'error' });
        if (++failures >= 4) return dispatch({ type: 'PLACE_OK', outcome: { ...UNKNOWN_OUTCOME, orderIds: [payment.orderId] } });
      }
      if (final) return dispatch({ type: 'PLACE_OK', outcome: { ...UNKNOWN_OUTCOME, orderIds: [payment.orderId] } });
    }
  }, []);

  const placeOrder = useCallback(async (addressId: string, expectedTotal: string, key: string, paymentKey: string) => {
    const id = run.current;
    dispatch({ type: 'PLACE_START' });
    try {
      const { order } = await instamartCheckout(addressId, expectedTotal, key, paymentKey);
      if (run.current !== id) return;
      dispatch({ type: 'PLACE_OK', outcome: order });
      if (order.status === 'pending_payment' && order.payment) void pollPayment(order.payment);
    } catch (e) {
      if (run.current !== id) return;
      const d = describe(e);
      if (d.authNeeded) return dispatch({ type: 'FAIL', message: d.message, authNeeded: true, stage: 'error' });
      if (d.code === 'payment_unavailable') return dispatch({ type: 'REVIEW_NOTICE', notice: d.message });
      if (REVIEW_AGAIN.has(d.code)) return dispatch({ type: 'BACK', notice: `${d.message} Your choices are saved — review the cart again.` });
      if (d.code === 'checkout_in_progress') return dispatch({ type: 'REVIEW_NOTICE', notice: d.message });
      // No response at all (dropped connection): the order may or may not exist — never invite a blind retry.
      const ambiguous = d.code === 'network' || d.code === 'unexpected_response';
      dispatch({ type: 'PLACE_OK', outcome: ambiguous ? UNKNOWN_OUTCOME : { ...UNKNOWN_OUTCOME, status: 'failed', message: d.message } });
    }
  }, [pollPayment]);

  return { state, search, addExtra, removeExtra, pick, setQuantity, selectPayment, backToPicking, buildCart, applyCoupon, placeOrder, reset };
}
