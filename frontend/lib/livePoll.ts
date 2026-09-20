// Polling of a live delivery status at the interval Swiggy asks for (never faster), shared by the Instamart and Food
// order screens. Pure and dependency-injected (timers) so the rules can be unit tested in plain Node — see
// livePoll.test.ts.
//
// It stops when the result says there is nothing more to poll (delivered/cancelled, or nothing pollable), when the
// caller cancels (sheet closed), or after repeated failures.

export interface LivePollOptions<R> {
  fetch: () => Promise<R>;
  onResult: (result: R) => void;
  /** Seconds until the next poll, or null to stop (a terminal state). Runs after every successful fetch. */
  nextWaitSec: (result: R) => number | null;
  /** Repeated failures: polling has stopped; the caller shows "updates paused". */
  onGiveUp: () => void;
  defaultWaitSec?: number;
  maxFailures?: number;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (handle: unknown) => void;
}

export const DEFAULT_WAIT_SEC = 30;
export const MAX_FAILURES = 5;

/** Starts polling immediately; returns a function that stops it. */
export function startLivePoll<R>(o: LivePollOptions<R>): () => void {
  const setTimer = o.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = o.clearTimer ?? (handle => clearTimeout(handle as ReturnType<typeof setTimeout>));
  const defaultWait = o.defaultWaitSec ?? DEFAULT_WAIT_SEC;
  const maxFailures = o.maxFailures ?? MAX_FAILURES;
  let alive = true;
  let timer: unknown;
  let failures = 0;

  const tick = async () => {
    let wait = defaultWait;
    try {
      const result = await o.fetch();
      if (!alive) return;
      failures = 0;
      o.onResult(result);
      const next = o.nextWaitSec(result);
      if (next === null) return;
      wait = next;
    } catch {
      if (!alive) return;
      if (++failures >= maxFailures) return o.onGiveUp();
    }
    timer = setTimer(() => { void tick(); }, wait * 1000);
  };
  void tick();
  return () => {
    alive = false;
    if (timer !== undefined) clearTimer(timer);
  };
}
