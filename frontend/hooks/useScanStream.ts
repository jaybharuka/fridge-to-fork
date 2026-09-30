'use client';

import { useCallback, useReducer } from 'react';
import { authHeaders } from '../lib/auth';
import { BACKEND_URL } from '../lib/backend';
import { readSSEStream } from '../lib/sse';
import type { ChecklistItem, TopUpSuggestion } from '../lib/types';
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

  return { state, startScan, toggleChecklistItem, reset, restore };
}
