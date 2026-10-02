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

/** Fridge-scan bar. An elapsed-time ESTIMATE (Gemini reports no progress): eases toward 90% (half-life 14s, calibrated on real
 *  step-1 durations: median 21s, p90 ~45s, none past 48s) and never reaches it; only the real step1 event (`done`) shows 100. */
export const SCAN_BAR_CEILING = 90;
export const SCAN_BAR_HALF_LIFE_MS = 14000;
export function scanBarPercent(elapsedMs: number, done: boolean): number {
  if (done) return 100;
  return SCAN_BAR_CEILING * (1 - Math.pow(0.5, Math.max(0, elapsedMs) / SCAN_BAR_HALF_LIFE_MS));
}

/** Whether the fridge-photo scan screen (with its bar) is up: from the tap until its reveal ends. An error before step1 never
 *  sets step1Received, so the screen, and the bar with it, gives way to the error card. */
export function showsPhotoScan(hasPhoto: boolean, revealed: boolean, phase: ScanState['phase'], step1Received: boolean): boolean {
  return hasPhoto && !revealed && (phase === 'photo-scanning' || step1Received);
}
