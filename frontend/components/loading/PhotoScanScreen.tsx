'use client';
import { useEffect, useRef, useState } from 'react';
import { Check, CircleAlert } from 'lucide-react';
import type { DetectedIngredient } from '@/lib/types';
import styles from './loading.module.css';

// Ported from templates/index.html:2231 (PHOTO_SCAN_TIMEOUT_MS).
const PHOTO_SCAN_TIMEOUT_MS = 35000;

// Ported from templates/index.html:2415-2419 (PHOTO_SCAN_SUB_MESSAGES) —
// deliberately says nothing about the tech stack: users care what it's
// doing for them, not what's doing it.
const PHOTO_SCAN_SUB_MESSAGES = [
  'Reading shelf by shelf',
  'Checking every corner of your fridge',
  'Almost there, hang tight',
];
const SUB_MESSAGE_INTERVAL_MS = 3500;
const SUB_MESSAGE_FADE_MS = 300;
const REVEAL_STEP_MS = 180;
const REVEAL_SETTLE_MS = 800;

interface PhotoScanScreenProps {
  visible: boolean;
  /** Uploaded fridge photo object URLs; [0] shown large by default, the
   *  rest as a thumb strip (only rendered when there's more than one). */
  photoUrls: string[];
  /** null until the backend's step1 event arrives; the scan-line sweep
   *  stops the instant this first becomes non-null. */
  detectedIngredients: DetectedIngredient[] | null;
  /** Fires names.length * 180 + 800ms after ingredients arrive (matches
   *  showDetectionChips(), templates/index.html:2586-2624) — the signal
   *  page.tsx uses to trigger the transition-to-results morph (Task 7). */
  onRevealComplete: () => void;
  onRetry: () => void;
}

// Shown instead of the dark LoadingOverlay for photo scans — the user's own
// fridge photo with a scan-line sweep, then a staggered reveal of detected
// ingredients below it. Ported from templates/index.html:1912-1936
// (markup), 1325-1546 (CSS), 2445-2624 (behavior).
export function PhotoScanScreen({ visible, photoUrls, detectedIngredients, onRevealComplete, onRetry }: PhotoScanScreenProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [subIndex, setSubIndex] = useState(0);
  const [subFading, setSubFading] = useState(false);
  const [revealedCount, setRevealedCount] = useState(0);
  const [statusText, setStatusText] = useState('Scanning your fridge...');
  const [statusComplete, setStatusComplete] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const revealStartedRef = useRef(false);

  const names = (detectedIngredients ?? []).filter(i => i.name && i.name.trim() !== '');
  const scanStopped = detectedIngredients !== null;

  // Reset per-scan state whenever a scan (re)starts — initial mount, and
  // retryPhotoScan() resubmitting the same photos (lines 2549-2558), which
  // resets detectedIngredients back to null while the screen stays visible.
  useEffect(() => {
    if (!visible || scanStopped) return;
    setActiveIndex(0);
    setSubIndex(0);
    setSubFading(false);
    setRevealedCount(0);
    setStatusText('Scanning your fridge...');
    setStatusComplete(false);
    setTimedOut(false);
    revealStartedRef.current = false;
  }, [visible, scanStopped]);

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

  // 35s timeout notice — startPhotoScanTimeoutTimer/onPhotoScanTimeout
  // (lines 2523-2544), cleared the instant ingredients arrive
  // (clearPhotoScanTimeoutTimer, mirrored by the `scanStopped` guard).
  useEffect(() => {
    if (!visible || scanStopped) return;
    const t = setTimeout(() => setTimedOut(true), PHOTO_SCAN_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [visible, scanStopped]);

  // Staggered detected-items reveal — showDetectionChips()
  // (lines 2586-2624). Runs once per scan, the instant detectedIngredients
  // first transitions from null to populated.
  useEffect(() => {
    if (!visible || !scanStopped || revealStartedRef.current) return;
    revealStartedRef.current = true;
    setTimedOut(false);

    if (names.length === 0) {
      setStatusText('No ingredients found');
      const t = setTimeout(onRevealComplete, REVEAL_SETTLE_MS);
      return () => clearTimeout(t);
    }

    const timers: ReturnType<typeof setTimeout>[] = [];
    names.forEach((ingredient, i) => {
      timers.push(
        setTimeout(() => {
          setRevealedCount(i + 1);
          const isLast = i === names.length - 1;
          setStatusText(
            isLast
              ? `Found ${names.length} ingredient${names.length === 1 ? '' : 's'}`
              : i === 0
                ? 'Found something...'
                : `Found ${ingredient.name}...`
          );
          setStatusComplete(isLast);
        }, i * REVEAL_STEP_MS)
      );
    });
    timers.push(setTimeout(onRevealComplete, names.length * REVEAL_STEP_MS + REVEAL_SETTLE_MS));
    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, scanStopped]);

  if (!visible) return null;

  const revealed = names.slice(0, revealedCount);

  return (
    <div className={`${styles.photoScanScreen} ${styles.show}`}>
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

        <div className={`${styles.photoScanTimeoutState} ${timedOut ? styles.visible : styles.hidden}`}>
          <CircleAlert size={26} />
          <p className={styles.photoScanTimeoutHeading}>This is taking longer than usual</p>
          <p className={styles.photoScanTimeoutSub}>The vision service may be busy right now. You can keep waiting or try again.</p>
          <button type="button" className={styles.photoScanRetryBtn} onClick={onRetry}>
            Try again
          </button>
        </div>
      </div>
    </div>
  );
}
