'use client';

import { useCallback, useReducer, useState } from 'react';
import { authHeaders } from '../lib/auth';
import { BACKEND_URL } from '../lib/backend';
import { createScanGuard } from '../lib/scanGuard';
import { readSSEStream } from '../lib/sse';
import type { ChecklistItem, DetectedIngredient, MealSuggestion, TopUpSuggestion } from '../lib/types';
// State/reducer live in their own pure module (no React, no fetch-only
// imports) so hooks/useScanStream.test.ts can exercise the reducer directly
// under Node's test runner. See that file's header comment.
import { initialState, reducer } from './scanReducer';
export type { ScanState } from './scanReducer';
export { initialState, reducer };

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
  // One guard for the scan and the replans: reset() abandons all of them, so nothing late reaches the reducer.
  const [guard] = useState(createScanGuard);

  const startScan = useCallback(
    async (mode: 'photo' | 'recipe', opts: { files?: File[]; targetDish: string; servings: number }) => {
      const { files, targetDish, servings } = opts;
      const { gen, signal } = guard.begin();
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
        const res = await fetch(`${BACKEND_URL}/api/scan`, { method: 'POST', body: form, credentials: 'include', headers: await authHeaders(), signal });
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        await readSSEStream(res, ev => {
          if (guard.isCurrent(gen)) dispatch(ev);
        });
      } catch {
        // An aborted scan (back button, or superseded by a newer one) is not an error to show.
        if (guard.isCurrent(gen)) dispatch({ type: 'error', message: 'Something went wrong. Try again.' });
      }
    },
    [guard]
  );

  const toggleChecklistItem = useCallback((index: number) => {
    dispatch({ type: 'TOGGLE_ITEM', index });
  }, []);

  const reset = useCallback(() => {
    guard.cancel(); // stop the in-flight scan/replan first, so none of its late events can undo the reset
    dispatch({ type: 'RESET' });
  }, [guard]);

  const restore = useCallback(
    (payload: { recommendedMeal: string; reasoning: string; checklist: ChecklistItem[]; topUpSuggestions: TopUpSuggestion[] }) => {
      dispatch({ type: 'RESTORE', ...payload });
    },
    []
  );

  // Meal Suggestions card click: the checklist switch is instant and local
  // (dispatched synchronously below, before any network call — see
  // scanReducer's SELECT_MEAL case). Only top-up suggestions need a fresh
  // /api/replan call, since they're dish-specific and were never
  // pre-generated for every suggestion; that call is fire-and-forget from
  // the caller's point of view and fails silently (best-effort, matches
  // generate_top_up_suggestions' own behavior on the backend).
  const selectMeal = useCallback(
    async (suggestion: MealSuggestion, detectedIngredients: DetectedIngredient[], servings: number) => {
      dispatch({ type: 'SELECT_MEAL', suggestion });
      const gen = guard.current();
      try {
        const res = await fetch(`${BACKEND_URL}/api/replan`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            dish_name: suggestion.name,
            fridge_ingredients: detectedIngredients,
            servings,
            recipe_ingredients: suggestion.recipe_ingredients,
            cooking_steps: suggestion.cooking_steps,
          }),
        });
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        const body = await res.json();
        if (guard.isCurrent(gen)) dispatch({ type: 'top_up', suggestions: body.top_up_suggestions ?? [] });
      } catch {
        if (guard.isCurrent(gen)) dispatch({ type: 'REPLAN_TOP_UP_FAILED' });
      }
    },
    [guard]
  );

  // Free-text "or tell us what you'd like to make instead" — an arbitrary
  // dish with no pre-generated recipe, so this always calls plan_meals()
  // server-side (app.py's /api/replan, omitting recipe_ingredients).
  const replanCustomDish = useCallback(
    async (dishName: string, detectedIngredients: DetectedIngredient[], servings: number) => {
      dispatch({ type: 'REPLAN_START' });
      const gen = guard.current();
      try {
        const res = await fetch(`${BACKEND_URL}/api/replan`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dish_name: dishName, fridge_ingredients: detectedIngredients, servings }),
        });
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        const body = await res.json();
        const suggestion: MealSuggestion = {
          name: body.recommended_meal,
          description: '',
          cuisine: '',
          can_cook_now: true,
          missing_ingredients: body.missing_ingredients ?? [],
          prep_time_minutes: 0,
          recipe_ingredients: body.recipe_ingredients ?? [],
          cooking_steps: body.cooking_steps ?? [],
          total_order_price_inr: body.total_order_price_inr ?? 0,
          matched_fridge_items: body.matched_fridge_items ?? [],
        };
        if (guard.isCurrent(gen)) dispatch({ type: 'REPLAN_SUCCESS', suggestion, reasoning: body.reasoning ?? '', topUpSuggestions: body.top_up_suggestions ?? [] });
      } catch {
        if (guard.isCurrent(gen)) dispatch({ type: 'REPLAN_ERROR', message: "Couldn't plan that dish. Please try again." });
      }
    },
    [guard]
  );

  return { state, startScan, toggleChecklistItem, reset, restore, selectMeal, replanCustomDish };
}
