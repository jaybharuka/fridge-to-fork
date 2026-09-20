import { Bike, CircleAlert, Link2 } from 'lucide-react';
import type { ScanState } from '@/hooks/useScanStream';
import styles from './results.module.css';

interface ScanStatusCardProps {
  result: ScanState['scanOutcome'];
  resultsAlreadyShown: boolean;
  onRetry: () => void;
  /** Fired just before the auth card's "Connect with Swiggy" CTA navigates
   *  away, so the caller can stash current state to resume after the OAuth
   *  redirect (lib/pendingOrder.ts). */
  onConnectClick: () => void;
}

// /api/scan's exception handler can surface a bare HTTP status code
// ("Order service error: 502"); this normalizes that one raw-looking pattern
// before it reaches the inline error strip below, and every other message
// passes through unchanged.
function friendlyErrorMessage(message: string): string {
  if (/^Order service error: \d+$/.test(message)) {
    return "The order service is having trouble right now. Please try again in a moment.";
  }
  return message;
}

// What the scan stream can still leave on screen when it fails: an error
// (inline strip once results are showing, else a full "try again" card) or an
// expired Swiggy session. (Ordering has its own sheets; this card no longer
// shows orders.) React auto-escapes text content.
export function ScanStatusCard({ result, resultsAlreadyShown, onRetry, onConnectClick }: ScanStatusCardProps) {
  if (!result) return null;

  if (result.kind === 'error') {
    if (resultsAlreadyShown) {
      return (
        <div className={styles.errorCard}>
          <CircleAlert />
          <span>{friendlyErrorMessage(result.message)}</span>
        </div>
      );
    }
    return (
      <div className={`${styles.card} ${styles.scanStateCard}`}>
        <CircleAlert className={styles.scanStateIcon} />
        <div className={styles.scanStateHeading}>Something went wrong</div>
        <div className={styles.scanStateSub}>The scan didn&apos;t complete. Please try again.</div>
        <button type="button" className={styles.ctaSecondaryBtn} onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }

  // auth_required: a real <a href> (not a fetch/button) so it performs a full
  // page navigation for the OAuth redirect.
  return (
    <div className={styles.authCard}>
      <div className={styles.authCardIcon}><Bike /></div>
      <div className={styles.authCardTitle}>Connect your Swiggy account</div>
      <div className={styles.authCardSub}>{result.message || 'Login to place this order instantly'}</div>
      <a className={styles.authCta} href="/auth/login?next=/" onClick={onConnectClick}><Link2 /> Connect with Swiggy</a>
    </div>
  );
}
