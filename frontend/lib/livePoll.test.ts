// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { startLivePoll, type LivePollOptions } from './livePoll.ts';

/** Manual timers: nothing really waits; `flush()` runs the pending timer and lets its async work finish. */
function harness<R>(over: Partial<LivePollOptions<R>> & { answers: Array<R | Error>; wait?: (r: R) => number | null }) {
  const answers = [...over.answers];
  const seen = { results: [] as R[], gaveUp: 0, waits: [] as number[], fetches: 0 };
  let pending: (() => void) | null = null;
  let cleared = 0;
  const stop = startLivePoll<R>({
    fetch: async () => {
      seen.fetches++;
      const next = answers.shift();
      if (next instanceof Error) throw next;
      return next as R;
    },
    onResult: r => seen.results.push(r),
    nextWaitSec: over.wait ?? (() => 30),
    onGiveUp: () => { seen.gaveUp++; },
    setTimer: (fn, ms) => { seen.waits.push(ms); pending = fn; return 1; },
    clearTimer: () => { cleared++; pending = null; },
    ...over,
  });
  const flush = async () => {
    const fn = pending;
    pending = null;
    fn?.();
    await new Promise(resolve => setImmediate(resolve));
  };
  const idle = () => new Promise(resolve => setImmediate(resolve));
  return { seen, stop, flush, idle, hasTimer: () => pending !== null, cleared: () => cleared };
}

describe('startLivePoll', () => {
  it('fetches at once, then again after the wait Swiggy asked for', async () => {
    const h = harness<string>({ answers: ['a', 'b'], wait: () => 20 });
    await h.idle();
    assert.deepEqual(h.seen.results, ['a']);
    assert.deepEqual(h.seen.waits, [20_000]);
    await h.flush();
    assert.deepEqual(h.seen.results, ['a', 'b']);
  });

  it('stops for good when the result is terminal (next wait null)', async () => {
    const h = harness<string>({ answers: ['live', 'done', 'never'], wait: r => (r === 'done' ? null : 10) });
    await h.idle();
    await h.flush();
    assert.equal(h.hasTimer(), false);
    assert.equal(h.seen.fetches, 2);
    assert.deepEqual(h.seen.results, ['live', 'done']);
  });

  it('retries after a failure at the default wait and resets the count on success', async () => {
    const net = new Error('net');
    const h = harness<string>({ answers: [net, net, net, net, 'ok', net, net, net, net, 'ok2'], maxFailures: 5 });
    for (let i = 0; i < 9; i++) { await h.idle(); await h.flush(); }
    await h.idle();
    assert.equal(h.seen.gaveUp, 0); // 4 failures, a success, 4 more: never 5 in a row
    assert.deepEqual(h.seen.results, ['ok', 'ok2']);
    assert.ok(h.seen.waits.every(ms => ms === 30_000));
  });

  it('gives up after the maximum consecutive failures and stops polling', async () => {
    const net = new Error('net');
    const h = harness<string>({ answers: [net, net, net], maxFailures: 3 });
    for (let i = 0; i < 4; i++) { await h.idle(); await h.flush(); }
    assert.equal(h.seen.gaveUp, 1);
    assert.equal(h.seen.fetches, 3);
    assert.equal(h.hasTimer(), false);
  });

  it('a cancelled poll does not report a result that arrives late, and clears its timer', async () => {
    let release: (v: string) => void = () => {};
    const seen: string[] = [];
    let timers = 0;
    const stop = startLivePoll<string>({
      fetch: () => new Promise<string>(resolve => { release = resolve; }),
      onResult: r => seen.push(r), nextWaitSec: () => 5, onGiveUp: () => {},
      setTimer: () => { timers++; return 1; }, clearTimer: () => {},
    });
    stop();
    release('late');
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(seen, []);
    assert.equal(timers, 0);
  });

  it('stop() clears a pending timer', async () => {
    const h = harness<string>({ answers: ['a', 'b'] });
    await h.idle();
    assert.equal(h.hasTimer(), true);
    h.stop();
    assert.equal(h.cleared(), 1);
    assert.equal(h.hasTimer(), false);
  });
});
