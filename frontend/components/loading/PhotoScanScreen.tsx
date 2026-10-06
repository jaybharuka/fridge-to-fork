'use client';
import { useEffect, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import type { DetectedIngredient } from '@/lib/types';
import { nextBarCheckpoint, scanBarPercent, type BarCheckpoint } from '@/lib/scanView';
import { reconcileFinal, type Superseded } from '@/lib/firstLook';
import { mergeFirstLook } from '@/hooks/scanReducer';
import { BackButton } from '@/components/shared/BackButton';
import { useElapsed } from './usePlanningProgress';
import styles from './loading.module.css';

// Real-world latency on the deployed backend is a Render cold start (can
// be several seconds alone) plus a two-pass Gemini vision call, regularly
// landing in the 15-60s range — the original 35s threshold (ported from
// templates/index.html:2231) fired well inside normal scan time and read
// as a false alarm. Two thresholds now: a soft, reassuring notice once
// something genuinely unusual is happening. (There used to be a hard 90s
// notice too, but the backend now ends a scan at 60s with an error card.)
const SOFT_NOTICE_MS = 60000;

// Ported from templates/index.html:2415-2419 (PHOTO_SCAN_SUB_MESSAGES),
// extended to cover a full 60s before the soft notice without visibly
// looping — deliberately says nothing about the tech stack: users care
// what it's doing for them, not what's doing it.
const PHOTO_SCAN_SUB_MESSAGES = [
  'Reading shelf by shelf',
  'Checking every corner of your fridge',
  'Making sure nothing gets missed',
  'Almost done, double-checking the shelves',
  'Cross-referencing what is inside',
  'Just a few more seconds',
  'Almost there, hang tight',
];
const SUB_MESSAGE_INTERVAL_MS = 3500;
const SUB_MESSAGE_FADE_MS = 300;
const REVEAL_STEP_MS = 180;
const REVEAL_SETTLE_MS = 800;
// Matches `.photoScanScreen { transition: opacity .4s }` in loading.module.css.
const FADE_MS = 400;

interface PhotoScanScreenProps {
  visible: boolean;
  /** Uploaded fridge photo object URLs; [0] shown large by default, the
   *  rest as a thumb strip (only rendered when there's more than one). */
  photoUrls: string[];
  /** null until the backend's step1 event arrives; the scan-line sweep
   *  stops the instant this first becomes non-null. */
  detectedIngredients: DetectedIngredient[] | null;
  /** "First look": the pass-1 items found so far (cumulative), from step1_partial events, before the real step1. Additive:
   *  rows already shown are never removed. null when none has arrived (also what an older backend always gives). */
  firstLook: { ingredients: DetectedIngredient[]; photoIndex: number; photoCount: number } | null;
  /** From the final step1: shown rows the final merge replaced with a higher-confidence variant; swapped in place. */
  earlySuperseded: Superseded[];
  /** Fires names.length * 180 + 800ms after ingredients arrive (matches
   *  showDetectionChips(), templates/index.html:2586-2624) — the signal
   *  page.tsx uses to trigger the transition-to-results morph (Task 7). */
  onRevealComplete: () => void;
  onRetry: () => void;
  /** Leaves the scan: the caller aborts the request and resets to the landing screen. */
  onBack: () => void;
}

// Shown instead of the dark LoadingOverlay for photo scans — the user's own
// fridge photo with a scan-line sweep, then a staggered reveal of detected
// ingredients below it. Ported from templates/index.html:1912-1936
// (markup), 1325-1546 (CSS), 2445-2624 (behavior).
export function PhotoScanScreen({ visible, photoUrls, detectedIngredients, firstLook, earlySuperseded, onRevealComplete, onRetry, onBack }: PhotoScanScreenProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [subIndex, setSubIndex] = useState(0);
  const [subFading, setSubFading] = useState(false);
  const [revealedCount, setRevealedCount] = useState(0);
  // The rows on screen (first-look rows, then the final reconcile), and the timers revealing them one by one. Refs mirror
  // them so a later event can see what is already shown without re-running an effect on every tick.
  const [rows, setRows] = useState<DetectedIngredient[]>([]);
  const rowsRef = useRef<DetectedIngredient[]>([]);
  const revealedRef = useRef(0);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const [checkpoint, setCheckpoint] = useState<BarCheckpoint | null>(null);
  const checkpointRef = useRef<BarCheckpoint | null>(null);
  const elapsedRef = useRef(0);
  const [statusText, setStatusText] = useState('Scanning your fridge...');
  const [statusComplete, setStatusComplete] = useState(false);
  const [noticeLevel, setNoticeLevel] = useState<'none' | 'soft'>('none');
  // Same delayed-unmount pattern as LoadingOverlay: drop the .show class
  // first, let the .4s opacity transition play, unmount after. Without it
  // the handoff to the results thumbnail is a jump cut, not a crossfade.
  const [shouldRender, setShouldRender] = useState(visible);
  const [shown, setShown] = useState(false);
  const revealStartedRef = useRef(false);

  useEffect(() => {
    if (visible) {
      setShouldRender(true);
      return;
    }
    setShown(false);
    const t = setTimeout(() => setShouldRender(false), FADE_MS);
    return () => clearTimeout(t);
  }, [visible]);

  useEffect(() => {
    if (!visible) return;
    const frame = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(frame);
  }, [visible]);

  const names = (detectedIngredients ?? []).filter(i => i.name && i.name.trim() !== '');
  const scanStopped = detectedIngredients !== null;
  // Restarts on retry (scanStopped goes back to false). The bar is gone with the screen on an error, so it can't freeze.
  const elapsed = useElapsed(visible && !scanStopped);
  const barPercent = scanBarPercent(elapsed, scanStopped, checkpoint);

  const clearTimers = () => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  };
  const showRows = (next: DetectedIngredient[]) => {
    rowsRef.current = next;
    setRows(next);
  };
  /** Reveals rows[from..total) one every REVEAL_STEP_MS, after any earlier rows still waiting for their turn. Returns the ms until the last one. */
  const revealRows = (from: number, total: number, onEach?: (index: number) => void): number => {
    const waiting = Math.max(0, from - revealedRef.current);
    for (let i = from; i < total; i++) {
      timersRef.current.push(
        setTimeout(() => {
          revealedRef.current = Math.max(revealedRef.current, i + 1);
          setRevealedCount(revealedRef.current);
          onEach?.(i);
        }, (waiting + (i - from)) * REVEAL_STEP_MS)
      );
    }
    return (waiting + Math.max(0, total - from)) * REVEAL_STEP_MS;
  };

  // Declared before the first-look effect below, so that effect reads this render's elapsed time.
  useEffect(() => {
    elapsedRef.current = elapsed;
  }, [elapsed]);

  // Timers must not outlive the screen: a back press or an error ends the reveal, and onRevealComplete must not fire after it.
  useEffect(() => {
    if (!visible) clearTimers();
  }, [visible]);
  useEffect(() => clearTimers, []);

  // Reset per-scan state whenever a scan (re)starts — initial mount, and
  // retryPhotoScan() resubmitting the same photos (lines 2549-2558), which
  // resets detectedIngredients back to null while the screen stays visible.
  useEffect(() => {
    if (!visible || scanStopped) return;
    setActiveIndex(0);
    setSubIndex(0);
    setSubFading(false);
    setRevealedCount(0);
    revealedRef.current = 0;
    clearTimers();
    showRows([]);
    checkpointRef.current = null;
    setCheckpoint(null);
    setStatusText('Scanning your fridge...');
    setStatusComplete(false);
    setNoticeLevel('none');
    revealStartedRef.current = false;
  }, [visible, scanStopped]);

  // First look: pass 1 of a photo finished while pass 2 still runs. Add the new rows (never remove or reorder one), reveal only
  // those, and take the bar's real checkpoint. Does nothing once the real step1 has landed.
  useEffect(() => {
    if (!visible || scanStopped || !firstLook || firstLook.ingredients.length === 0) return;
    const before = rowsRef.current.length;
    const merged = mergeFirstLook(rowsRef.current, firstLook.ingredients);
    if (merged.length > before) {
      showRows(merged);
      revealRows(before, merged.length);
      setStatusText('Found so far, still looking...');
    }
    const next = nextBarCheckpoint(elapsedRef.current, checkpointRef.current, firstLook.photoIndex, firstLook.photoCount);
    checkpointRef.current = next;
    setCheckpoint(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firstLook, visible, scanStopped]);

  // Cycling sub-status message — startPhotoScanSubMessages()
  // (lines 2423-2438). Runs for as long as the screen is visible.
  useEffect(() => {
    if (!visible) return;
    const interval = setInterval(() => {
      setSubFading(true);
      setTimeout(() => {
        setSubIndex(i => (i + 1) % PHOTO_SCAN_SUB_MESSAGES.length);
        setSubFading(false);
      }, SUB_MESSAGE_FADE_MS);
    }, SUB_MESSAGE_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [visible]);

  // Soft/hard "still going" notices — adapted from
  // startPhotoScanTimeoutTimer/onPhotoScanTimeout (lines 2523-2544), split
  // into two thresholds (see SOFT_NOTICE_MS/HARD_NOTICE_MS above). Both
  // clear the instant ingredients arrive (mirrored by the `scanStopped`
  // guard) — a real `error` SSE event or network failure is a separate
  // path entirely (state.phase === 'error' in useScanStream), never routed
  // through this soft/hard notice UI.
  useEffect(() => {
    if (!visible || scanStopped) return;
    const soft = setTimeout(() => setNoticeLevel('soft'), SOFT_NOTICE_MS);
    return () => clearTimeout(soft);
  }, [visible, scanStopped]);

  // Staggered detected-items reveal — showDetectionChips()
  // (lines 2586-2624). Runs once per scan, the instant detectedIngredients
  // first transitions from null to populated. Rows a first look already put on screen stay (a few the final merge replaced are
  // swapped in place); only the items not shown yet are animated. With no first look it is the original reveal of every item.
  useEffect(() => {
    if (!visible || !scanStopped || revealStartedRef.current) return;
    revealStartedRef.current = true;
    setNoticeLevel('none');

    if (names.length === 0) {
      setStatusText('No ingredients found');
      const t = setTimeout(onRevealComplete, REVEAL_SETTLE_MS);
      return () => clearTimeout(t);
    }

    const { rows: finalRows, appendedFrom } = reconcileFinal(rowsRef.current, names, earlySuperseded);
    showRows(finalRows);
    const total = finalRows.length;
    const foundText = `Found ${names.length} ingredient${names.length === 1 ? '' : 's'}`;
    const msToLast = revealRows(appendedFrom, total, i => {
      const isLast = i === total - 1;
      setStatusText(isLast ? foundText : i === 0 ? 'Found something...' : `Found ${finalRows[i].name}...`);
      setStatusComplete(isLast);
    });
    if (appendedFrom >= total) {
      // Everything was already on screen from the first look: nothing left to animate, so say so now.
      setStatusText(foundText);
      setStatusComplete(true);
    }
    timersRef.current.push(setTimeout(onRevealComplete, msToLast + REVEAL_SETTLE_MS));
    return clearTimers;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, scanStopped]);

  if (!shouldRender) return null;

  const revealed = rows.slice(0, revealedCount);

  return (
    <div className={`${styles.photoScanScreen} ${shown ? styles.show : ''}`}>
      <BackButton onDark onClick={onBack} label="Cancel scan and go back" />
      <div className={styles.photoScanContent}>
        <div className={styles.photoScanContainer}>
          <img className={styles.fridgePhotoPreview} src={photoUrls[activeIndex] ?? photoUrls[0]} alt="Your fridge" />
          <div className={`${styles.photoScanLine} ${scanStopped ? styles.stopped : ''}`} />
        </div>

        {photoUrls.length > 1 && (
          <div className={`${styles.photoScanThumbStrip} ${styles.show}`}>
            {photoUrls.map((url, i) => (
              <img
                key={url}
                src={url}
                alt={`Fridge photo ${i + 1}`}
                className={`${styles.scanThumb} ${i === activeIndex ? styles.active : ''}`}
                onClick={() => setActiveIndex(i)}
              />
            ))}
          </div>
        )}

        <div className={styles.photoScanBar} role="progressbar" aria-label="Estimated scan progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(barPercent)}>
          <div className={styles.photoScanBarFill} style={{ width: `${barPercent}%` }} />
        </div>
        <p className={`${styles.photoScanStatus} ${statusComplete ? styles.complete : ''}`}>{statusText}</p>
        <p className={styles.photoScanSubStatus} style={{ opacity: subFading ? 0 : 1 }}>
          {PHOTO_SCAN_SUB_MESSAGES[subIndex]}
        </p>

        <div className={`${styles.detectedItemsList} ${revealed.length === 0 ? styles.detectedItemsListEmpty : ''}`}>
          {revealed.map((ingredient, i) => {
            const confidence = ingredient.confidence || 0;
            const tier = confidence >= 85 ? 'high' : confidence >= 70 ? 'medium' : null;
            return (
              <div
                key={`${ingredient.name}-${i}`}
                className={`${styles.detectedItemRow} ${tier ? styles[tier] : ''}`}
              >
                <div className={styles.detectedItemCheck}>
                  <Check />
                </div>
                <span className={styles.detectedItemName}>{ingredient.name}</span>
              </div>
            );
          })}
        </div>

        <div
          className={`${styles.photoScanTimeoutState} ${noticeLevel === 'none' ? styles.hidden : styles.visible} ${styles.soft}`}
        >
          <p className={styles.photoScanTimeoutHeading}>
            Still scanning, almost there
          </p>
          <p className={styles.photoScanTimeoutSub}>
            A thorough scan can take a little while. Feel free to keep waiting.
          </p>
          <button
            type="button"
            className={styles.photoScanRetryBtnSubtle}
            onClick={onRetry}
          >
            Try again
          </button>
        </div>
      </div>
    </div>
  );
}
