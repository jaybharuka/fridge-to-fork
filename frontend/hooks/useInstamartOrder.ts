'use client';
import { useCallback, useReducer, useRef } from 'react';
import {
  InstamartApiError,
  instamartCart,
  instamartCheckout,
  instamartSearch,
  newIdempotencyKey,
  type CartSelection,
  type InstamartAddress,
  type InstamartOutcome,
  type InstamartReview,
  type InstamartSearchResult,
} from '../lib/instamart';

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
  | { type: 'BUILD_OK'; review: InstamartReview; adjustments: string[]; key: string }
  | { type: 'PLACE_START' }
  | { type: 'PLACE_OK'; outcome: InstamartOutcome }
  | { type: 'REVIEW_NOTICE'; notice: string }
  | { type: 'BACK'; notice?: string | null }
  | { type: 'FAIL'; message: string; authNeeded: boolean; stage: Stage }
  | { type: 'RESET' };

const initial: InstamartState = {
  stage: 'searching', address: null, results: [], extras: [], choices: {}, review: null, adjustments: [],
  idempotencyKey: null, outcome: null, notice: null, error: null, authNeeded: false,
};

/** The top in-stock match is pre-picked (Swiggy's own ranking); the user reviews, swaps or skips. */
function defaultChoice(result: InstamartSearchResult): Choice {
  const top = result.options.find(o => o.available);
  return { spinId: top?.spinId ?? null, quantity: 1 };
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
      return { ...state, stage: 'reviewing', review: action.review, adjustments: action.adjustments, idempotencyKey: action.key, notice: null };
    case 'PLACE_START':
      return { ...state, stage: 'placing', notice: null };
    case 'PLACE_OK':
      return { ...state, stage: 'done', outcome: action.outcome };
    case 'REVIEW_NOTICE':
      return { ...state, stage: 'reviewing', notice: action.notice };
    case 'BACK':
      return { ...state, stage: 'picking', review: null, idempotencyKey: null, notice: action.notice ?? null };
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
      const { address, results } = await instamartSearch(ingredients);
      if (run.current === id) dispatch({ type: 'SEARCH_OK', address, results });
    } catch (e) {
      const d = describe(e);
      if (run.current === id) dispatch({ type: 'FAIL', message: d.message, authNeeded: d.authNeeded, stage: 'error' });
    }
  }, []);

  const addExtra = useCallback(async (ingredient: string) => {
    const id = run.current;
    dispatch({ type: 'EXTRA_ADD', ingredient });
    try {
      const { address, results } = await instamartSearch([ingredient]);
      if (run.current === id && results[0]) dispatch({ type: 'EXTRA_OK', address, result: results[0] });
    } catch (e) {
      const d = describe(e);
      if (run.current === id) dispatch({ type: 'BACK', notice: d.message });
    }
  }, []);

  const removeExtra = useCallback((ingredient: string) => dispatch({ type: 'EXTRA_REMOVE', ingredient }), []);
  const pick = useCallback((ingredient: string, spinId: string | null) => dispatch({ type: 'PICK', ingredient, spinId }), []);
  const setQuantity = useCallback((ingredient: string, quantity: number) => dispatch({ type: 'QTY', ingredient, quantity }), []);
  const backToPicking = useCallback(() => dispatch({ type: 'BACK' }), []);
  const reset = useCallback(() => { run.current++; dispatch({ type: 'RESET' }); }, []);

  const buildCart = useCallback(async (addressId: string, selections: CartSelection[]) => {
    const id = run.current;
    dispatch({ type: 'BUILD_START' });
    try {
      const { review, adjustments } = await instamartCart(addressId, selections);
      if (run.current === id) dispatch({ type: 'BUILD_OK', review, adjustments, key: newIdempotencyKey() });
    } catch (e) {
      const d = describe(e);
      if (run.current !== id) return;
      if (d.authNeeded) dispatch({ type: 'FAIL', message: d.message, authNeeded: true, stage: 'error' });
      else dispatch({ type: 'BACK', notice: d.message });
    }
  }, []);

  const placeOrder = useCallback(async (addressId: string, expectedTotal: string, key: string) => {
    const id = run.current;
    dispatch({ type: 'PLACE_START' });
    try {
      const { order } = await instamartCheckout(addressId, expectedTotal, key);
      if (run.current === id) dispatch({ type: 'PLACE_OK', outcome: order });
    } catch (e) {
      if (run.current !== id) return;
      const d = describe(e);
      if (d.authNeeded) return dispatch({ type: 'FAIL', message: d.message, authNeeded: true, stage: 'error' });
      if (REVIEW_AGAIN.has(d.code)) return dispatch({ type: 'BACK', notice: `${d.message} Your choices are saved — review the cart again.` });
      if (d.code === 'checkout_in_progress') return dispatch({ type: 'REVIEW_NOTICE', notice: d.message });
      // No response at all (dropped connection): the order may or may not exist — never invite a blind retry.
      const ambiguous = d.code === 'network' || d.code === 'unexpected_response';
      dispatch({
        type: 'PLACE_OK',
        outcome: {
          status: ambiguous ? 'unknown' : 'failed',
          orderIds: [],
          message: ambiguous
            ? "We couldn't confirm whether the order went through. Check the Swiggy app before trying again."
            : d.message,
          verified: false,
          total: null,
        },
      });
    }
  }, []);

  return { state, search, addExtra, removeExtra, pick, setQuantity, backToPicking, buildCart, placeOrder, reset };
}
