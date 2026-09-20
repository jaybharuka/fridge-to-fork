// Client-driven polling of a pending UPI payment (nothing is held open server-side), shared by the Instamart and Food
// flows. Pure and dependency-injected (sleep + clock) so the rules can be unit tested in plain Node — see
// pollPayment.test.ts.
//
// At the deadline it asks once more with final=true, so Swiggy can reconcile a late payment; repeated network failures
// end as "gave up" (which callers show as "unknown, check the Swiggy app", never as a failure that invites a retry).

export interface PollOptions<O extends { status: string }> {
  pollIntervalMs: number;
  maxPollMs: number;
  /** false once the sheet was closed or restarted: stop quietly. */
  isCurrent: () => boolean;
  check: (final: boolean) => Promise<O>;
  /** Any outcome that is not still 'pending_payment'. */
  onDone: (outcome: O) => void;
  /** Deadline passed, or the network failed repeatedly, without a terminal answer. */
  onGiveUp: () => void;
  /** Return true when the error means the Swiggy session is gone: polling stops (the caller shows "connect"). */
  onError: (error: unknown) => boolean;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

export const MAX_CONSECUTIVE_FAILURES = 4;

export async function pollPayment<O extends { status: string }>(o: PollOptions<O>): Promise<void> {
  const sleep = o.sleep ?? ((ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms)));
  const now = o.now ?? Date.now;
  const deadline = now() + o.maxPollMs;
  let failures = 0;
  while (o.isCurrent()) {
    await sleep(o.pollIntervalMs);
    if (!o.isCurrent()) return;
    const final = now() >= deadline;
    try {
      const outcome = await o.check(final);
      failures = 0;
      if (outcome.status !== 'pending_payment') return o.onDone(outcome);
    } catch (e) {
      if (o.onError(e)) return;
      if (++failures >= MAX_CONSECUTIVE_FAILURES) return o.onGiveUp();
    }
    if (final) return o.onGiveUp();
  }
}
