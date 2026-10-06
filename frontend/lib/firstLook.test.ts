// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
// The scan's "first look": pass-1 items shown while pass 2 still runs. The rules under test: the early list only grows, nothing
// shown is dropped when the final list lands, the final result is identical with or without early events, an older backend
// (no early events) and an unknown event type change nothing, and an aborted scan's events are dropped.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { initialState, mergeFirstLook, reducer, type ScanState } from '../hooks/scanReducer.ts';
import { reconcileFinal } from './firstLook.ts';
import { createScanGuard } from './scanGuard.ts';
import { firstLookBarFloor, nextBarCheckpoint, scanBarPercent, SCAN_BAR_CEILING } from './scanView.ts';
import type { DetectedIngredient, ScanEvent } from './types.ts';

const ing = (name: string, confidence = 80): DetectedIngredient => ({ name, quantity: '', confidence });
const names = (list: DetectedIngredient[]) => list.map(i => i.name);
const scanning: ScanState = { ...initialState, hasPhoto: true, phase: 'photo-scanning' };
const partial = (items: DetectedIngredient[], photo_index = 1, photo_count = 1): ScanEvent => ({ type: 'step1_partial', ingredients: items, photo_index, photo_count });
const step1 = (items: DetectedIngredient[], extra: Partial<Extract<ScanEvent, { type: 'step1' }>> = {}): ScanEvent => ({ type: 'step1', raw_description: '', ingredients: items, ...extra });

describe('mergeFirstLook (the early list only grows)', () => {
  it('appends what is new, in order, and ignores a name already shown (any case or spacing)', () => {
    assert.deepEqual(names(mergeFirstLook([ing('tomato')], [ing('Tomato '), ing('milk'), ing('egg')])), ['tomato', 'milk', 'egg']);
  });
  it('never removes or reorders a row, whatever the incoming list holds', () => {
    const shown = [ing('tomato'), ing('milk')];
    assert.deepEqual(names(mergeFirstLook(shown, [ing('egg')])), ['tomato', 'milk', 'egg']);
    assert.deepEqual(names(mergeFirstLook(shown, [])), ['tomato', 'milk']);
    assert.deepEqual(names(mergeFirstLook(shown, [ing('milk'), ing('tomato')])), ['tomato', 'milk']);
  });
  it('skips blank names and does not mutate its inputs', () => {
    const shown = [ing('tomato')];
    const out = mergeFirstLook(shown, [ing(''), ing('  ')]);
    assert.deepEqual(names(out), ['tomato']);
    assert.equal(shown.length, 1);
  });
});

describe('reconcileFinal (nothing shown is dropped when the final list lands)', () => {
  it('with nothing shown it is just the final list, all new: what an older backend gives', () => {
    const final = [ing('tomato', 90), ing('milk', 70)];
    const { rows, appendedFrom } = reconcileFinal([], final);
    assert.deepEqual(rows, final);
    assert.equal(appendedFrom, 0);
  });
  it('keeps the rows already on screen in place and appends only the new final items, in final order', () => {
    const shown = [ing('tomato', 90), ing('milk', 70)];
    const final = [ing('tomato', 90), ing('lemon', 85), ing('milk', 70), ing('egg', 60)];
    const { rows, appendedFrom } = reconcileFinal(shown, final);
    assert.deepEqual(names(rows), ['tomato', 'milk', 'lemon', 'egg']);
    assert.equal(appendedFrom, 2);
  });
  it('swaps a row the final merge replaced with its variant, in place, with the final confidence', () => {
    const shown = [ing('tomato', 90), ing('milk', 70)];
    const final = [ing('cherry tomato', 95), ing('milk', 70)];
    const { rows, appendedFrom } = reconcileFinal(shown, final, [{ from: 'tomato', to: 'cherry tomato' }]);
    assert.deepEqual(rows, [ing('cherry tomato', 95), ing('milk', 70)]);
    assert.equal(appendedFrom, 2);
  });
  it('does not show a swapped-in variant twice', () => {
    const final = [ing('cherry tomato', 95), ing('milk', 70)];
    const { rows } = reconcileFinal([ing('tomato', 90)], final, [{ from: 'tomato', to: 'cherry tomato' }]);
    assert.deepEqual(names(rows), ['cherry tomato', 'milk']);
  });
  it('keeps a shown row that is neither in the final list nor reported as replaced (it is never silently removed)', () => {
    const { rows } = reconcileFinal([ing('tomato'), ing('ghost')], [ing('tomato'), ing('milk')]);
    assert.deepEqual(names(rows), ['tomato', 'ghost', 'milk']);
  });
});

describe('the progress bar checkpoint', () => {
  it('pass 1 of photo k of n puts the bar about (2k-1)/(2n) of the way to the ceiling', () => {
    assert.equal(firstLookBarFloor(1, 1), SCAN_BAR_CEILING * 0.5);
    assert.equal(firstLookBarFloor(1, 2), SCAN_BAR_CEILING * 0.25);
    assert.equal(firstLookBarFloor(2, 2), SCAN_BAR_CEILING * 0.75);
    assert.ok(firstLookBarFloor(3, 3) < SCAN_BAR_CEILING);
    assert.ok(firstLookBarFloor(9, 3) < SCAN_BAR_CEILING); // out-of-range input is clamped, never past the ceiling
    assert.ok(firstLookBarFloor(0, 0) > 0);
  });
  it('without a checkpoint it is exactly the old estimate', () => {
    for (const ms of [0, 3000, 10_000, 30_000]) assert.equal(scanBarPercent(ms, false), scanBarPercent(ms, false, null));
    assert.equal(scanBarPercent(10_000, true), 100);
  });
  it('a checkpoint lifts the bar to at least its floor and keeps easing toward the ceiling', () => {
    const cp = nextBarCheckpoint(10_000, null, 1, 1);
    assert.ok(scanBarPercent(10_000, false, cp) >= firstLookBarFloor(1, 1));
    assert.ok(scanBarPercent(10_000, false, cp) > scanBarPercent(10_000, false));
    assert.ok(scanBarPercent(30_000, false, cp) > scanBarPercent(10_000, false, cp));
  });
  it('never moves backward across several checkpoints and never reaches the ceiling before step1', () => {
    let cp = null as ReturnType<typeof nextBarCheckpoint> | null;
    let last = 0;
    for (let ms = 0; ms <= 120_000; ms += 500) {
      if (ms === 8_000) cp = nextBarCheckpoint(ms, cp, 1, 3);
      if (ms === 20_000) cp = nextBarCheckpoint(ms, cp, 2, 3);
      if (ms === 21_000) cp = nextBarCheckpoint(ms, cp, 3, 3);
      const now = scanBarPercent(ms, false, cp);
      assert.ok(now >= last - 1e-9, `moved backward at ${ms}ms: ${last} -> ${now}`);
      assert.ok(now <= SCAN_BAR_CEILING, `past the ceiling at ${ms}ms`);
      assert.ok(now < 100);
      last = now;
    }
  });
  it('a checkpoint that arrives when the bar is already ahead of its floor does not pull it back', () => {
    const before = scanBarPercent(60_000, false);
    const cp = nextBarCheckpoint(60_000, null, 1, 3);
    assert.ok(scanBarPercent(60_000, false, cp) >= before);
  });
});

describe('the reducer', () => {
  it('shows the first look while the photo scan runs, additively across events', () => {
    const one = reducer(scanning, partial([ing('tomato', 90)], 1, 2));
    assert.deepEqual(names(one.firstLook!.ingredients), ['tomato']);
    assert.equal(one.step1Received, false); // a first look is never the real step1
    const two = reducer(one, partial([ing('tomato', 90), ing('milk', 80)], 2, 2));
    assert.deepEqual(names(two.firstLook!.ingredients), ['tomato', 'milk']);
    assert.deepEqual([two.firstLook!.photoIndex, two.firstLook!.photoCount], [2, 2]);
  });
  it('ignores it in every other phase and once step1 has landed (a late or stale event changes nothing)', () => {
    for (const phase of ['idle', 'loading', 'results', 'error'] as const) {
      const state = { ...initialState, phase, hasPhoto: true };
      assert.equal(reducer(state, partial([ing('tomato')])), state, phase);
    }
    const landed = reducer(scanning, step1([ing('tomato')]));
    assert.equal(reducer(landed, partial([ing('late')])), landed);
  });
  it('ignores a malformed event', () => {
    assert.equal(reducer(scanning, { type: 'step1_partial', ingredients: undefined, photo_index: 1, photo_count: 1 } as unknown as ScanEvent), scanning);
  });
  it('SCAN_START and RESET clear it', () => {
    const shown = reducer(scanning, partial([ing('tomato')]));
    assert.equal(reducer(shown, { type: 'SCAN_START', hasPhoto: true }).firstLook, null);
    assert.equal(reducer(shown, { type: 'RESET' }).firstLook, null);
  });
  it('the final step1 is identical with or without early events, and carries the superseded pairs', () => {
    const final = step1([ing('cherry tomato', 95), ing('milk', 70)], { early_superseded: [{ from: 'tomato', to: 'cherry tomato' }] });
    const withEarly = [partial([ing('tomato', 90)]), final].reduce(reducer, scanning);
    const without = [final].reduce(reducer, scanning);
    assert.deepEqual(withEarly.detectedIngredients, without.detectedIngredients);
    assert.deepEqual(withEarly.earlySuperseded, [{ from: 'tomato', to: 'cherry tomato' }]);
    for (const k of ['phase', 'step1Received', 'timedOutVision', 'scanOutcome', 'hasPhoto'] as const) assert.deepEqual(withEarly[k], without[k], k);
  });
  it('an older backend (no early events, no early_superseded) behaves exactly as before', () => {
    const state = [step1([ing('tomato', 90)])].reduce(reducer, scanning);
    assert.equal(state.firstLook, null);
    assert.deepEqual(state.earlySuperseded, []);
    assert.deepEqual(state.detectedIngredients, [ing('tomato', 90)]);
    assert.equal(state.step1Received, true);
  });
  it('an unknown event type (a newer backend than this client) changes nothing', () => {
    const state = reducer(scanning, partial([ing('tomato')]));
    assert.equal(reducer(state, { type: 'step1_something_new', whatever: 1 } as unknown as ScanEvent), state);
  });
  it('a timed-out step1 still ends in the error outcome, first look or not', () => {
    const end = [partial([ing('tomato')]), step1([], { timed_out: true })].reduce(reducer, scanning);
    assert.equal(end.scanOutcome?.kind, 'error');
    assert.equal(end.step1Received, false);
  });
});

describe('an aborted scan (back button) drops its late events through the guard', () => {
  it('only the current generation reaches the reducer, as useScanStream does it', () => {
    const guard = createScanGuard();
    let state: ScanState = scanning;
    const { gen } = guard.begin();
    const deliver = (ev: ScanEvent) => { if (guard.isCurrent(gen)) state = reducer(state, ev); };
    deliver(partial([ing('tomato')]));
    assert.deepEqual(names(state.firstLook!.ingredients), ['tomato']);
    guard.cancel();
    state = reducer(state, { type: 'RESET' });
    deliver(partial([ing('late')]));
    deliver(step1([ing('late')]));
    assert.equal(state, initialState); // nothing late got through
  });
});
