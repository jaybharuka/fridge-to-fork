// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { askGate, cancelGate, confirmGate, type Gate } from './loadGate.ts';

function counter() {
  let calls = 0;
  return { load: () => { calls++; }, calls: () => calls };
}

describe('load-options confirmation gate', () => {
  it('asking alone makes no backend call', () => {
    const c = counter();
    const gate = askGate(null, 'm1');
    assert.equal(gate, 'm1');
    assert.equal(c.calls(), 0);
  });

  it('cancelling results in zero backend calls and closes the question', () => {
    const c = counter();
    let gate: Gate = askGate(null, 'm1');
    gate = cancelGate();
    assert.equal(gate, null);
    confirmGate(gate, 'm1', c.load); // a stray confirm after cancel must not flush the cart either
    assert.equal(c.calls(), 0);
  });

  it('confirming runs the load exactly once', () => {
    const c = counter();
    const gate = askGate(null, 'm1');
    const after = confirmGate(gate, 'm1', c.load);
    assert.equal(c.calls(), 1);
    assert.equal(after, null);
    confirmGate(after, 'm1', c.load); // a double tap on Continue
    assert.equal(c.calls(), 1);
  });

  it('confirming a dish that was never asked about does nothing', () => {
    const c = counter();
    confirmGate(null, 'm1', c.load);
    confirmGate(askGate(null, 'm2'), 'm1', c.load);
    assert.equal(c.calls(), 0);
  });

  it('asking about another dish replaces the first question', () => {
    const c = counter();
    const gate = askGate(askGate(null, 'm1'), 'm2');
    confirmGate(gate, 'm1', c.load);
    assert.equal(c.calls(), 0);
    confirmGate(gate, 'm2', c.load);
    assert.equal(c.calls(), 1);
  });
});
