'use client';

import { useCallback, useReducer, useRef } from 'react';
import { authHeaders, markDisconnected } from '../lib/auth';
import { BACKEND_URL } from '../lib/backend';
import { readSSEStream } from '../lib/sse';
import type { ChecklistItem, DetectedIngredient, MealSuggestion, ScanEvent, TopUpSuggestion } from '../lib/types';

export interface ScanState {
  phase: 'idle' | 'loading' | 'photo-scanning' | 'results' | 'error';
  hasPhoto: boolean;
  detectedIngredients: DetectedIngredient[];
  matchedFridgeItems: string[];
  suggestions: MealSuggestion[];
  recommendedMeal: string | null;
  reasoning: string;
  checklist: ChecklistItem[];
  cookingSteps: string[];
  topUpSuggestions: TopUpSuggestion[];
  awaitingChoice: boolean;
  recipeTabUnlocked: boolean;
  orderResult:
    | null
    | { kind: 'cook_confirmed' }
    | { kind: 'order_placed'; orderId: string; platform: string; items: string[]; etaMinutes: number }
    | { kind: 'cook_no_order' }
    | { kind: 'auth_required'; message?: string }
    | { kind: 'error'; message: string };
  scanError: string | null;
  timedOutVision: boolean;
  /** True for the whole /api/order round trip — ChoiceCard disables its
   *  buttons and spins the clicked one (templates/index.html:3849-3856). */
  orderPlacing: boolean;
  /** True once the 'step1' event has actually arrived, even if it detected
   *  zero ingredients. Distinguishes "not scanned yet" from "scanned, found
   *  nothing" — both leave `detectedIngredients` as `[]`, so consumers that
   *  need to react only once real (possibly empty) results are in must key
   *  on this, not `detectedIngredients.length`. */
  step1Received: boolean;
}

type Action =
  | ScanEvent
  | { type: 'SCAN_START'; hasPhoto: boolean }
  | { type: 'TOGGLE_ITEM'; index: number }
  | { type: 'ORDER_START' }
  | { type: 'ORDER_END' }
  | { type: 'RESET' }
  | {
      type: 'RESTORE';
      recommendedMeal: string;
      reasoning: string;
      checklist: ChecklistItem[];
      topUpSuggestions: TopUpSuggestion[];
    };

const initialState: ScanState = {
  phase: 'idle',
  hasPhoto: false,
  detectedIngredients: [],
  matchedFridgeItems: [],
  suggestions: [],
  recommendedMeal: null,
  reasoning: '',
  checklist: [],
  cookingSteps: [],
  topUpSuggestions: [],
  awaitingChoice: false,
  recipeTabUnlocked: false,
  orderResult: null,
  scanError: null,
  timedOutVision: false,
  orderPlacing: false,
  step1Received: false,
};

function reducer(state: ScanState, action: Action): ScanState {
  switch (action.type) {
    case 'SCAN_START':
      return {
        ...initialState,
        hasPhoto: action.hasPhoto,
        phase: action.hasPhoto ? 'photo-scanning' : 'loading',
      };

    case 'step1':
      return {
        ...state,
        detectedIngredients: action.ingredients,
        timedOutVision: !!action.timed_out,
        step1Received: true,
        // A photo scan stays in 'photo-scanning' — the PhotoScanScreen
        // component owns the reveal animation and its own transition to
        // 'results'. Recipe-only mode has no such screen, so go straight
        // to results.
        phase: state.hasPhoto ? state.phase : 'results',
      };

    case 'step2': {
      const checklist: ChecklistItem[] = action.recipe_ingredients.map(ing => {
        const foundInFridge = ing.found_in_fridge === true;
        const isStaple = ing.is_staple === true;
        return {
          name: ing.name,
          quantity: ing.quantity,
          estimated_price_inr: ing.estimated_price_inr || 0,
          foundInFridge,
          isStaple,
          checked: foundInFridge || isStaple,
        };
      });
      return {
        ...state,
        suggestions: action.suggestions,
        recommendedMeal: action.recommended_meal,
        reasoning: action.reasoning,
        cookingSteps: action.cooking_steps,
        matchedFridgeItems: action.matched_fridge_items,
        checklist,
      };
    }

    case 'awaiting_user_choice':
      return {
        ...state,
        reasoning: action.reasoning,
        recommendedMeal: action.recommended_meal || state.recommendedMeal,
        awaitingChoice: true,
        recipeTabUnlocked: true,
      };

    case 'top_up':
      if (!state.suggestions.length) return state;
      return { ...state, topUpSuggestions: action.suggestions };

    case 'complete':
      return { ...state, phase: 'results' };

    case 'cook_confirmed':
      return { ...state, orderResult: { kind: 'cook_confirmed' } };

    case 'step3': {
      if (action.placed) {
        return {
          ...state,
          orderResult: {
            kind: 'order_placed',
            orderId: action.order_id ?? '',
            platform: action.platform ?? '',
            items: action.items,
            etaMinutes: action.eta_minutes ?? 0,
          },
        };
      }
      if (action.decision === 'cook') {
        return { ...state, orderResult: { kind: 'cook_no_order' } };
      }
      return state;
    }

    case 'error':
      return {
        ...state,
        // The original's error branch calls hideLoadingOverlay() +
        // revealResultsSection() (templates/index.html:4693-4695), so an
        // error must leave 'loading'/'photo-scanning' or the overlay hangs
        // forever. Results that were already on screen stay 'results' —
        // OrderResultCard keys its inline-vs-full error card off that.
        phase: state.phase === 'results' ? 'results' : 'error',
        orderResult: { kind: 'error', message: action.message },
        scanError: action.message,
      };

    case 'auth_required':
      return { ...state, orderResult: { kind: 'auth_required', message: action.message } };

    // chooseAction() clears the order card before a retry
    // (templates/index.html:3858) so a stale error doesn't linger for the
    // whole second attempt.
    case 'ORDER_START':
      return { ...state, orderPlacing: true, orderResult: null, scanError: null };

    case 'ORDER_END':
      return { ...state, orderPlacing: false };

    case 'TOGGLE_ITEM':
      return {
        ...state,
        checklist: state.checklist.map((item, i) =>
          i === action.index ? { ...item, checked: !item.checked } : item
        ),
      };

    case 'RESET':
      return initialState;

    // Rehydrates just enough of the Order tab (checklist + top-up
    // suggestions) to reopen the order sheet after the full-page OAuth
    // redirect — see lib/pendingOrder.ts. Recipe tab content (cooking
    // steps, suggestions) intentionally isn't restored: it was never
    // persisted, since the user's goal here is finishing the order, not
    // rereading the recipe.
    case 'RESTORE':
      return {
        ...initialState,
        phase: 'results',
        hasPhoto: false,
        step1Received: true,
        recommendedMeal: action.recommendedMeal,
        reasoning: action.reasoning,
        checklist: action.checklist,
        topUpSuggestions: action.topUpSuggestions,
        awaitingChoice: true,
        recipeTabUnlocked: true,
      };

    // 'progress' and 'step2_partial' don't drive any state the UI reads
    // (matches old handleEvent()'s dead-tracked streamedIngredientNames).
    case 'progress':
    case 'step2_partial':
      return state;

    default:
      return state;
  }
}

// /api/scan and /api/order are long-running SSE streams (15-60s: cold
// start + two-pass Gemini vision + meal planning) — routing them through
// Vercel's next.config.js rewrite proxy risks hitting the Hobby plan's
// serverless function execution limit (as short as 10s), well before the
// real response finishes. Fetching the Render backend directly sidesteps
// that; CORS in app.py supports this cross-origin call, and auth rides an
// Authorization bearer (lib/auth.ts) because the session cookie is host-only
// on the Vercel origin and never reaches this one. Falls back to the same-origin proxy path when unset
// (local dev, where next.config.js's own BACKEND_URL default handles it).

export function useScanStream() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const orderInFlight = useRef(false);

  const startScan = useCallback(
    async (mode: 'photo' | 'recipe', opts: { files?: File[]; targetDish: string; servings: number }) => {
      const { files, targetDish, servings } = opts;
      dispatch({ type: 'SCAN_START', hasPhoto: mode === 'photo' && !!files?.length });
      const form = new FormData();
      if (mode === 'photo' && files?.length) {
        files.forEach((f, i) => form.append(`fridge_photo_${i}`, f));
      } else {
        form.append('mode', mode);
      }
      if (targetDish) form.append('target_dish', targetDish);
      form.append('servings', String(servings));
      try {
        const res = await fetch(`${BACKEND_URL}/api/scan`, { method: 'POST', body: form, credentials: 'include', headers: await authHeaders() });
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        await readSSEStream(res, ev => dispatch(ev));
      } catch {
        dispatch({ type: 'error', message: 'Something went wrong. Try again.' });
      }
    },
    []
  );

  const placeOrder = useCallback(
    async (action: 'cook' | 'order_dish', mealName: string) => {
      if (orderInFlight.current) return;
      orderInFlight.current = true;
      dispatch({ type: 'ORDER_START' });
      const form = new FormData();
      form.append('action', action);
      form.append('meal_name', mealName || '');
      try {
        const res = await fetch(`${BACKEND_URL}/api/order`, { method: 'POST', body: form, credentials: 'include', headers: await authHeaders() });
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        await readSSEStream(res, ev => {
          if (ev.type === 'auth_required') markDisconnected();
          dispatch(ev);
        });
      } catch {
        dispatch({ type: 'error', message: 'Something went wrong. Try again.' });
      } finally {
        orderInFlight.current = false;
        dispatch({ type: 'ORDER_END' });
      }
    },
    []
  );

  const toggleChecklistItem = useCallback((index: number) => {
    dispatch({ type: 'TOGGLE_ITEM', index });
  }, []);

  const reset = useCallback(() => {
    dispatch({ type: 'RESET' });
  }, []);

  const restore = useCallback(
    (payload: { recommendedMeal: string; reasoning: string; checklist: ChecklistItem[]; topUpSuggestions: TopUpSuggestion[] }) => {
      dispatch({ type: 'RESTORE', ...payload });
    },
    []
  );

  return { state, startScan, placeOrder, toggleChecklistItem, reset, restore };
}
