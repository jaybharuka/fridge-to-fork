// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { createScanGuard } from './scanGuard.ts';

describe('createScanGuard', () => {
  it('begin() hands out a live signal and the current generation', () => {
    const g = createScanGuard();
    const { gen, signal } = g.begin();
    assert.equal(signal.aborted, false);
    assert.equal(g.isCurrent(gen), true);
  });

  it('cancel() aborts the request and makes that generation stale (the back-button case)', () => {
    const g = createScanGuard();
    const { gen, signal } = g.begin();
    g.cancel();
    assert.equal(signal.aborted, true);
    assert.equal(g.isCurrent(gen), false);
  });

  it('a new begin() aborts the previous scan and only the new one is current', () => {
    const g = createScanGuard();
    const first = g.begin();
    const second = g.begin();
    assert.equal(first.signal.aborted, true);
    assert.equal(second.signal.aborted, false);
    assert.equal(g.isCurrent(first.gen), false);
    assert.equal(g.isCurrent(second.gen), true);
  });

  it('a replan captured before a reset is stale after it (late REPLAN_* events must be dropped)', () => {
    const g = createScanGuard();
    g.begin();
    const replanGen = g.current();
    g.cancel();
    assert.equal(g.isCurrent(replanGen), false);
  });

  it('cancel() with nothing running is harmless, and a later begin() works', () => {
    const g = createScanGuard();
    g.cancel();
    const { gen, signal } = g.begin();
    assert.equal(signal.aborted, false);
    assert.equal(g.isCurrent(gen), true);
  });
});
