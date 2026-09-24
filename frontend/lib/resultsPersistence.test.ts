// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';
import { clearResultsSnapshot, consumeResultsSnapshot, saveResultsSnapshot, type ResultsSnapshot } from './resultsPersistence.ts';

// No DOM/browser globals under the plain Node test runner — a minimal
// in-memory stand-in for sessionStorage is enough to exercise the real
// save/consume/clear logic (including its try/catch fallbacks).
class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string): string | null { return this.store.has(key) ? this.store.get(key)! : null; }
  setItem(key: string, value: string): void { this.store.set(key, value); }
  removeItem(key: string): void { this.store.delete(key); }
}

const SNAPSHOT: ResultsSnapshot = {
  recommendedMeal: 'Paneer Tikka',
  reasoning: 'Uses what you already have.',
  checklist: [{ name: 'Paneer', quantity: '250 g', estimated_price_inr: 95, foundInFridge: false, isStaple: false, checked: false }],
  topUpSuggestions: [],
  targetDish: 'paneer',
  servings: 3,
  tab: 'recipe',
};

beforeEach(() => {
  (globalThis as { sessionStorage?: unknown }).sessionStorage = new MemoryStorage();
});

describe('saveResultsSnapshot / consumeResultsSnapshot', () => {
  it('round-trips exactly what was saved', () => {
    saveResultsSnapshot(SNAPSHOT);
    assert.deepEqual(consumeResultsSnapshot(), SNAPSHOT);
  });

  it('is one-shot — a second consume after the first sees nothing', () => {
    saveResultsSnapshot(SNAPSHOT);
    consumeResultsSnapshot();
    assert.equal(consumeResultsSnapshot(), null);
  });

  it('returns null when nothing was ever saved', () => {
    assert.equal(consumeResultsSnapshot(), null);
  });

  it('a later save overwrites an earlier, unconsumed one (only the freshest snapshot survives)', () => {
    saveResultsSnapshot(SNAPSHOT);
    const later: ResultsSnapshot = { ...SNAPSHOT, servings: 5 };
    saveResultsSnapshot(later);
    assert.deepEqual(consumeResultsSnapshot(), later);
  });

  it('clearResultsSnapshot removes an unconsumed snapshot (the "start over" case)', () => {
    saveResultsSnapshot(SNAPSHOT);
    clearResultsSnapshot();
    assert.equal(consumeResultsSnapshot(), null);
  });

  it('clearResultsSnapshot on an empty stash is a harmless no-op', () => {
    assert.doesNotThrow(() => clearResultsSnapshot());
  });

  it('save/consume/clear never throw even when sessionStorage is unavailable (private browsing, quota)', () => {
    const throwing = {
      getItem() { throw new Error('blocked'); },
      setItem() { throw new Error('blocked'); },
      removeItem() { throw new Error('blocked'); },
    };
    (globalThis as { sessionStorage?: unknown }).sessionStorage = throwing;
    assert.doesNotThrow(() => saveResultsSnapshot(SNAPSHOT));
    assert.doesNotThrow(() => clearResultsSnapshot());
    assert.equal(consumeResultsSnapshot(), null);
  });

  it('a corrupted stored value is treated as nothing to restore, not a crash', () => {
    const storage = new MemoryStorage();
    storage.setItem('f2f_results_snapshot', 'not valid json{');
    (globalThis as { sessionStorage?: unknown }).sessionStorage = storage;
    assert.equal(consumeResultsSnapshot(), null);
  });
});
