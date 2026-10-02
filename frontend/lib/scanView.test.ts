// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { initialState, reducer } from '../hooks/scanReducer.ts';
import type { ScanEvent } from './types.ts';
import { scanBarPercent, SCAN_BAR_CEILING, showsOnlyErrorCard, showsPhotoScan } from './scanView.ts';

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

describe('scanBarPercent', () => {
  it('starts at 0, climbs, and never reaches the ceiling or 100 before the real event', () => {
    assert.equal(scanBarPercent(0, false), 0);
    let last = 0;
    for (const ms of [1000, 5000, 14000, 21000, 45000, 60000, 600000]) {
      const p = scanBarPercent(ms, false);
      assert.ok(p > last && p < SCAN_BAR_CEILING, `${ms}ms -> ${p}`);
      last = p;
    }
  });
  it('is calibrated (45% at 14s, mid-climb at the 21s median, 80%+ at 45s) and shows 100 only when done', () => {
    assert.ok(Math.abs(scanBarPercent(14000, false) - 45) < 0.01);
    assert.ok(scanBarPercent(21000, false) > 55 && scanBarPercent(21000, false) < 65);
    assert.ok(scanBarPercent(45000, false) > 80);
    assert.equal(scanBarPercent(1000, true), 100);
    assert.equal(scanBarPercent(-5, false), 0);
  });
});

describe('showsPhotoScan (the screen that owns the bar)', () => {
  it('is up while scanning and through the reveal after step1', () => {
    assert.equal(showsPhotoScan(true, false, 'photo-scanning', false), true);
    assert.equal(showsPhotoScan(true, false, 'planning', true), true);
  });
  it('is gone on a failure before step1, so the bar unmounts instead of freezing', () => {
    assert.equal(showsPhotoScan(true, false, 'error', false), false);
  });
  it('is gone once the reveal finished, and for non-photo scans', () => {
    assert.equal(showsPhotoScan(true, true, 'planning', true), false);
    assert.equal(showsPhotoScan(false, false, 'photo-scanning', false), false);
  });
});
