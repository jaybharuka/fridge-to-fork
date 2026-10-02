// Ties every in-flight scan/replan call to the "generation" that started it, so a call the user has since left (back
// button, or a newer scan) can neither keep streaming nor dispatch late events into the reducer. Pure (no React) so it is
// unit tested in plain Node: see scanGuard.test.ts.
//
// Before this, resetting mid-scan left the fetch running: its later step1/step2 events landed on the idle reducer and put
// the results screen back over the landing page.

export interface ScanGuard {
  /** Starts a new generation: aborts whatever was running and returns the new generation plus the signal to fetch with. */
  begin(): { gen: number; signal: AbortSignal };
  /** Abandons the current generation (aborting its request); everything started before this is now stale. */
  cancel(): void;
  /** The generation currently allowed to dispatch. Capture it before an await and compare after. */
  current(): number;
  isCurrent(gen: number): boolean;
}

export function createScanGuard(): ScanGuard {
  let gen = 0;
  let controller: AbortController | null = null;
  const abort = () => {
    controller?.abort();
    controller = null;
  };
  return {
    begin() {
      abort();
      gen += 1;
      controller = new AbortController();
      return { gen, signal: controller.signal };
    },
    cancel() {
      abort();
      gen += 1;
    },
    current: () => gen,
    isCurrent: g => g === gen,
  };
}
