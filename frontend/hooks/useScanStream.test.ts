// Run: npm test   (node --experimental-strip-types --test hooks/*.test.ts lib/*.test.ts)
//
// Regression test for the 2026-09-30 live incident: a real, visibly full
// fridge photo rendered "Nothing detected in your fridge — 0 items
// detected" after app.py's 60s vision timeout tripped (Gemini instability —
// see [STEP1 TIMEOUT] in the backend logs). The backend already sent
// timed_out: true on the step1 SSE event; the bug was that nothing in the
// frontend ever read it. These tests simulate that exact event shape
// (mocking "identify_ingredients took longer than the timeout" doesn't
// require a slow async call here — the reducer's whole job is reacting to
// the SSE payload app.py sends once its own timeout already fired, so the
// fix and its test both live at that boundary) and pin the fixed behavior.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { initialState, reducer } from './scanReducer.ts';
import type { ScanEvent } from '../lib/types.ts';

const scanningState = { ...initialState, hasPhoto: true, phase: 'photo-scanning' as const };

describe('useScanStream reducer — step1 timeout handling', () => {
  it('a timed-out step1 sets the same error outcome a genuine error event uses, not a valid empty result', () => {
    const timedOutEvent: ScanEvent = { type: 'step1', raw_description: '', ingredients: [], timed_out: true };
    const result = reducer(scanningState, timedOutEvent);

    assert.deepEqual(result.scanOutcome, { kind: 'error', message: "The scan didn't complete. Please try again." });
    assert.equal(result.timedOutVision, true);
    // The bug: these being set to "valid empty result" values is exactly
    // what let PhotoScanScreen/FridgeSummaryHeader/FridgeChipsDropdown
    // render "0 items detected" / "Nothing detected in your fridge" as if
    // it were a trustworthy scan outcome. Must stay unset.
    assert.equal(result.step1Received, false);
    assert.deepEqual(result.detectedIngredients, []);
  });

  it('matches the phase transition a genuine error event produces', () => {
    const timedOutEvent: ScanEvent = { type: 'step1', raw_description: '', ingredients: [], timed_out: true };
    const errorEvent: ScanEvent = { type: 'error', message: 'anything' };

    const viaTimeout = reducer(scanningState, timedOutEvent);
    const viaError = reducer(scanningState, errorEvent);

    assert.equal(viaTimeout.phase, viaError.phase);
    assert.equal(viaTimeout.phase, 'error');
  });

  it('a real, non-timed-out step1 with zero ingredients is unaffected — a genuinely empty fridge must still show as one', () => {
    const genuinelyEmpty: ScanEvent = { type: 'step1', raw_description: 'No ingredients detected.', ingredients: [] };
    const result = reducer(scanningState, genuinelyEmpty);

    assert.equal(result.step1Received, true);
    assert.deepEqual(result.detectedIngredients, []);
    assert.equal(result.scanOutcome, null);
    assert.equal(result.timedOutVision, false);
  });

  it('a real step1 with real ingredients still works normally', () => {
    const found: ScanEvent = {
      type: 'step1',
      raw_description: '2 ingredients detected.',
      ingredients: [
        { name: 'butter', quantity: '1', confidence: 90 },
        { name: 'cheese', quantity: '1', confidence: 85 },
      ],
    };
    const result = reducer(scanningState, found);

    assert.equal(result.step1Received, true);
    assert.equal(result.detectedIngredients.length, 2);
    assert.equal(result.scanOutcome, null);
  });

  it('does not clobber an already-shown results phase (mirrors the error-case comment: results on screen must stay on screen)', () => {
    const resultsState = { ...initialState, phase: 'results' as const };
    const timedOutEvent: ScanEvent = { type: 'step1', raw_description: '', ingredients: [], timed_out: true };
    const result = reducer(resultsState, timedOutEvent);

    assert.equal(result.phase, 'results');
    assert.deepEqual(result.scanOutcome, { kind: 'error', message: "The scan didn't complete. Please try again." });
  });
});

describe('useScanStream reducer — a step2/complete sequence arriving after a step1 timeout', () => {
  // Regression test for the 2026-10-01 live incident (third that night on
  // this flow): app.py deliberately keeps streaming after a step1 timeout
  // — step2 meal-planning runs on the empty fridge, and the request still
  // ends with a 'complete' event 30-90s later. That's confirmed real via
  // Render logs, not a hypothetical, and must NOT be "fixed" by changing
  // backend behavior. The bug was scanReducer's 'complete' case
  // unconditionally flipping phase to 'results', silently overwriting the
  // error state 'step1' had just set and downgrading ScanStatusCard to an
  // easy-to-miss inline strip on a page that otherwise looks like a normal
  // (if fridge-empty) result.
  const runTimedOutSequence = () => {
    let state = scanningState;
    state = reducer(state, { type: 'step1', raw_description: '', ingredients: [], timed_out: true });
    // app.py still runs step2 on the empty fridge and sends it through as
    // usual — this must not resurrect a "results" look.
    state = reducer(state, {
      type: 'step2',
      decision: 'order_groceries',
      recommended_meal: 'Butter Chicken',
      reasoning: 'Fallback plan since no fridge items were confirmed.',
      suggestions: [],
      recipe_ingredients: [],
      cooking_steps: [],
      matched_fridge_items: [],
    });
    state = reducer(state, {
      type: 'awaiting_user_choice',
      reasoning: 'Fallback plan since no fridge items were confirmed.',
      recommended_meal: 'Butter Chicken',
      missing_ingredients: [],
      total_order_price_inr: 0,
    });
    return reducer(state, { type: 'complete' });
  };

  it('stays in the error state instead of surfacing a misleading results phase', () => {
    const result = runTimedOutSequence();

    assert.equal(result.phase, 'error');
    assert.deepEqual(result.scanOutcome, { kind: 'error', message: "The scan didn't complete. Please try again." });
  });

  it('a genuine complete (no prior timeout) still reaches results normally', () => {
    let state = reducer(scanningState, {
      type: 'step1',
      raw_description: '2 ingredients detected.',
      ingredients: [{ name: 'butter', quantity: '1', confidence: 90 }],
    });
    state = reducer(state, { type: 'complete' });

    assert.equal(state.phase, 'results');
    assert.equal(state.scanOutcome, null);
  });
});
