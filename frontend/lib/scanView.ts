// Which screen a scan leaves on show. Pure (no React) so it is unit tested in plain Node: see scanView.test.ts.

import type { ScanState } from '../hooks/scanReducer';

/**
 * True when the scan failed before the user ever saw results: the screen must be the error card and nothing else.
 *
 * `Results` is mounted during the 'error' phase because the error card lives inside it. Without this, anything the stream
 * had already delivered (2026-10-02: a plan built on an empty fridge, "9 of 17 ingredients · 8 to order") rendered behind the
 * card, a plausible-looking order list with no fridge data behind it. When results WERE already on screen
 * (`resultsAlreadyShown`), a late error is shown as a strip above content the user has really seen, so that case is left alone.
 */
export function showsOnlyErrorCard(phase: ScanState['phase'], resultsAlreadyShown: boolean): boolean {
  return phase === 'error' && !resultsAlreadyShown;
}
