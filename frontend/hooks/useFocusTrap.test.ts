// Run: npm test   (node --experimental-strip-types --test hooks/*.test.ts lib/*.test.ts)
//
// Unit coverage for the focus-trap's actual wrap DECISION — kept DOM-free
// and generic (nextTrapTarget<T>) specifically so it's testable here; this
// repo has no jsdom/DOM-testing infra (confirmed in the phase 2 pass), so
// the DOM-mechanics half (does .focus() actually move focus, does Tab
// actually fire this handler, does focus actually restore on close) was
// verified live instead, via Chrome automation against both Sheet.tsx and
// FridgeLightbox.tsx — not repeated here as a brittle DOM-less substitute.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { nextTrapTarget } from './useFocusTrap.ts';

const [a, b, c] = ['a', 'b', 'c'];

describe('nextTrapTarget — Tab (forward)', () => {
  it('wraps from the last item to the first', () => {
    assert.equal(nextTrapTarget([a, b, c], c, false), a);
  });

  it('does nothing (returns null) when focus is in the middle — default Tab behavior proceeds', () => {
    assert.equal(nextTrapTarget([a, b, c], b, false), null);
  });

  it('does nothing when focus is already on the first item (only Shift+Tab wraps there)', () => {
    assert.equal(nextTrapTarget([a, b, c], a, false), null);
  });

  it('jumps to the first item when focus is outside the trap entirely (e.g. the trap just opened)', () => {
    assert.equal(nextTrapTarget([a, b, c], null, false), a);
    assert.equal(nextTrapTarget([a, b, c], 'not-in-list', false), a);
  });
});

describe('nextTrapTarget — Shift+Tab (backward)', () => {
  it('wraps from the first item to the last', () => {
    assert.equal(nextTrapTarget([a, b, c], a, true), c);
  });

  it('does nothing when focus is in the middle', () => {
    assert.equal(nextTrapTarget([a, b, c], b, true), null);
  });

  it('does nothing when focus is already on the last item', () => {
    assert.equal(nextTrapTarget([a, b, c], c, true), null);
  });

  it('jumps to the last item when focus is outside the trap entirely', () => {
    assert.equal(nextTrapTarget([a, b, c], null, true), c);
  });
});

describe('nextTrapTarget — a single focusable element', () => {
  it('Tab on the only element wraps to itself', () => {
    assert.equal(nextTrapTarget([a], a, false), a);
  });

  it('Shift+Tab on the only element wraps to itself', () => {
    assert.equal(nextTrapTarget([a], a, true), a);
  });
});

describe('nextTrapTarget — empty list', () => {
  it('returns null (caller prevents default and leaves focus alone)', () => {
    assert.equal(nextTrapTarget([], null, false), null);
    assert.equal(nextTrapTarget([], null, true), null);
  });
});
