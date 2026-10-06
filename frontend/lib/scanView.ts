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
 *  step-1 durations: median 21s, p90 ~45s, none past 48s) and never reaches it; only the real step1 event (`done`) shows 100.
 *  A first-look event (pass 1 of a photo finished) is a real checkpoint: it lifts the bar to at least `firstLookBarFloor` and
 *  the bar keeps easing toward the same ceiling from there. The bar never moves backward and never passes the ceiling before `done`. */
export const SCAN_BAR_CEILING = 90;
export const SCAN_BAR_HALF_LIFE_MS = 14000;

/** Where the bar restarts easing from, and the elapsed time it was reached. */
export interface BarCheckpoint { from: number; atMs: number }

export function scanBarPercent(elapsedMs: number, done: boolean, checkpoint: BarCheckpoint | null = null): number {
  if (done) return 100;
  const elapsed = Math.max(0, elapsedMs);
  const estimate = SCAN_BAR_CEILING * (1 - Math.pow(0.5, elapsed / SCAN_BAR_HALF_LIFE_MS));
  if (!checkpoint) return estimate;
  const eased = checkpoint.from + (SCAN_BAR_CEILING - checkpoint.from) * (1 - Math.pow(0.5, Math.max(0, elapsed - checkpoint.atMs) / SCAN_BAR_HALF_LIFE_MS));
  return Math.min(SCAN_BAR_CEILING, Math.max(estimate, eased));
}

/** Pass 1 of photo k of n is done: of the 2n Gemini calls, 2k-1 are behind us, so about (2k-1)/(2n) of the way to the ceiling. */
export function firstLookBarFloor(photoIndex: number, photoCount: number): number {
  const n = Math.max(1, Math.floor(photoCount));
  const k = Math.min(n, Math.max(1, Math.floor(photoIndex)));
  return SCAN_BAR_CEILING * (2 * k - 1) / (2 * n);
}

/** The checkpoint a first-look event creates: from the higher of the floor and where the bar is right now (so it never steps back). */
export function nextBarCheckpoint(elapsedMs: number, current: BarCheckpoint | null, photoIndex: number, photoCount: number): BarCheckpoint {
  const now = scanBarPercent(elapsedMs, false, current);
  return { from: Math.min(SCAN_BAR_CEILING, Math.max(firstLookBarFloor(photoIndex, photoCount), now)), atMs: Math.max(0, elapsedMs) };
}

/** Whether the fridge-photo scan screen (with its bar) is up: from the tap until its reveal ends. An error before step1 never
 *  sets step1Received, so the screen, and the bar with it, gives way to the error card. */
export function showsPhotoScan(hasPhoto: boolean, revealed: boolean, phase: ScanState['phase'], step1Received: boolean): boolean {
  return hasPhoto && !revealed && (phase === 'photo-scanning' || step1Received);
}
