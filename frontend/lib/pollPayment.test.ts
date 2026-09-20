// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { pollPayment, type PollOptions } from './pollPayment.ts';

type Outcome = { status: string };

/** A fake clock: sleeping advances it, so deadlines are deterministic and nothing really waits. */
function harness(over: Partial<PollOptions<Outcome>> & { answers: Array<Outcome | Error> }) {
  let clock = 0;
  const seen = { finals: [] as boolean[], done: [] as Outcome[], gaveUp: 0, errors: [] as unknown[], sleeps: [] as number[] };
  const answers = [...over.answers];
  const options: PollOptions<Outcome> = {
    pollIntervalMs: 1000,
    maxPollMs: 5000,
    isCurrent: () => true,
    check: async final => {
      seen.finals.push(final);
      const next = answers.shift() ?? { status: 'pending_payment' };
      if (next instanceof Error) throw next;
      return next;
    },
    onDone: o => seen.done.push(o),
    onGiveUp: () => { seen.gaveUp++; },
    onError: e => { seen.errors.push(e); return e instanceof Error && e.message === 'auth'; },
    sleep: async ms => { seen.sleeps.push(ms); clock += ms; },
    now: () => clock,
    ...over,
  };
  return { run: () => pollPayment(options), seen };
}

const pending = { status: 'pending_payment' };

describe('pollPayment', () => {
  it('stops at the first outcome that is not pending and reports it', async () => {
    const h = harness({ answers: [pending, pending, { status: 'placed' }] });
    await h.run();
    assert.deepEqual(h.seen.done, [{ status: 'placed' }]);
    assert.equal(h.seen.finals.length, 3);
    assert.equal(h.seen.gaveUp, 0);
  });

  it('a failed payment is a terminal outcome too', async () => {
    const h = harness({ answers: [{ status: 'failed' }] });
    await h.run();
    assert.deepEqual(h.seen.done, [{ status: 'failed' }]);
  });

  it('waits the poll interval before every check, never faster', async () => {
    const h = harness({ pollIntervalMs: 2500, answers: [pending, { status: 'placed' }] });
    await h.run();
    assert.deepEqual(h.seen.sleeps, [2500, 2500]);
  });

  it('asks once more with final=true at the deadline, then gives up', async () => {
    const h = harness({ pollIntervalMs: 1000, maxPollMs: 3000, answers: [] }); // pending forever
    await h.run();
    assert.deepEqual(h.seen.finals, [false, false, true]);
    assert.equal(h.seen.gaveUp, 1);
    assert.equal(h.seen.done.length, 0);
  });

  it('a late payment found by the final check is reported, not given up on', async () => {
    const h = harness({ pollIntervalMs: 1000, maxPollMs: 2000, answers: [pending, { status: 'placed' }] });
    await h.run();
    assert.deepEqual(h.seen.finals, [false, true]);
    assert.deepEqual(h.seen.done, [{ status: 'placed' }]);
    assert.equal(h.seen.gaveUp, 0);
  });

  it('gives up after four consecutive network failures', async () => {
    const h = harness({ maxPollMs: 60_000, answers: [new Error('net'), new Error('net'), new Error('net'), new Error('net')] });
    await h.run();
    assert.equal(h.seen.finals.length, 4);
    assert.equal(h.seen.gaveUp, 1);
  });

  it('a success in between resets the failure count', async () => {
    const net = new Error('net');
    const h = harness({ maxPollMs: 60_000, answers: [net, net, net, pending, net, net, net, { status: 'placed' }] });
    await h.run();
    assert.deepEqual(h.seen.done, [{ status: 'placed' }]);
    assert.equal(h.seen.gaveUp, 0);
  });

  it('a lost session stops polling at once without giving up or reporting an outcome', async () => {
    const h = harness({ answers: [pending, new Error('auth'), { status: 'placed' }] });
    await h.run();
    assert.equal(h.seen.finals.length, 2);
    assert.equal(h.seen.done.length, 0);
    assert.equal(h.seen.gaveUp, 0);
  });

  it('a closed or restarted sheet stops it quietly, even mid-wait', async () => {
    let current = true;
    const h = harness({ answers: [pending, pending, pending], isCurrent: () => current, sleep: async () => { current = false; } });
    await h.run();
    assert.equal(h.seen.finals.length, 0);
    assert.equal(h.seen.done.length, 0);
    assert.equal(h.seen.gaveUp, 0);
  });
});
