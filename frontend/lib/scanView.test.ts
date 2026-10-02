// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { initialState, reducer } from '../hooks/scanReducer.ts';
import type { ScanEvent } from './types.ts';
import { showsOnlyErrorCard } from './scanView.ts';

describe('showsOnlyErrorCard', () => {
  it('a failure before any results were shown is the error card alone', () => {
    assert.equal(showsOnlyErrorCard('error', false), true);
  });
  it('a late error over results the user really saw keeps them (the inline strip case)', () => {
    assert.equal(showsOnlyErrorCard('error', true), false);
  });
  it('never hides content in any other phase', () => {
    for (const phase of ['idle', 'loading', 'photo-scanning', 'results'] as const) {
      assert.equal(showsOnlyErrorCard(phase, false), false, phase);
      assert.equal(showsOnlyErrorCard(phase, true), false, phase);
    }
  });
});

describe('a vision timeout followed by a plan (the 2026-10-02 incident, stream as it used to arrive)', () => {
  const events: ScanEvent[] = [
    { type: 'step1', raw_description: '', ingredients: [], timed_out: true },
    {
      type: 'step2', decision: 'cook', recommended_meal: 'Chicken Lollipop', reasoning: 'r', suggestions: [],
      recipe_ingredients: [{ name: 'salt', quantity: '1 tsp', is_staple: true }], cooking_steps: ['x'], matched_fridge_items: [],
    } as unknown as ScanEvent,
    { type: 'complete' } as ScanEvent,
  ];
  const end = events.reduce(reducer, { ...initialState, hasPhoto: true, phase: 'photo-scanning' as const });

  it('the reducer still holds the plan data and the error, which is why the view must not draw both', () => {
    assert.equal(end.phase, 'error');
    assert.equal(end.scanOutcome?.kind, 'error');
    assert.equal(end.checklist.length > 0, true);
  });
  it('and the view shows only the error card for it', () => {
    assert.equal(showsOnlyErrorCard(end.phase, end.phase === 'results'), true);
  });
});
