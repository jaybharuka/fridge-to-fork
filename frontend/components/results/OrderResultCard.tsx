import { Bike, ChefHat, CircleAlert, CircleCheckBig, Link2 } from 'lucide-react';
import type { ScanState } from '@/hooks/useScanStream';
import styles from './results.module.css';

interface OrderResultCardProps {
  result: ScanState['orderResult'];
  resultsAlreadyShown: boolean;
  onRetry: () => void;
}

// Port of handleEvent()'s cook_confirmed/step3/error/auth_required branches
// — templates/index.html:4637-4714 — and their CSS (.cook-card 981-985,
// .order-card/.order-row etc. 968-979, .error-card 987-1004, .auth-card/
// .auth-cta 953-966). React auto-escapes text content, so this needs no
// escapeHtml() equivalent.
export function OrderResultCard({ result, resultsAlreadyShown, onRetry }: OrderResultCardProps) {
  if (!result) return null;

  if (result.kind === 'cook_confirmed') {
    return (
      <div className={styles.cookCard}>
        <ChefHat />
        <div className={styles.cookCardTitle}>You&apos;re all set!</div>
        <div className={styles.cookCardSub}>All ingredients are ready in your kitchen.</div>
      </div>
    );
  }

  if (result.kind === 'order_placed') {
    return (
      <div className={styles.orderCard}>
        <div className={styles.orderIconWrap}><CircleCheckBig /></div>
        <div className={styles.orderTitle}>Order confirmed!</div>
        <div className={styles.orderId}>{result.orderId}</div>
        <div className={styles.orderDetails}>
          <div className={styles.orderRow}>
            <span className={styles.orderLabel}>Platform</span>
            <span className={styles.orderValue}>{result.platform}</span>
          </div>
          <div className={styles.orderRow}>
            <span className={styles.orderLabel}>Items</span>
            <span className={styles.orderValue}>{result.items.join(', ')}</span>
          </div>
          <div className={styles.orderRow}>
            <span className={styles.orderLabel}>ETA</span>
            <span className={`${styles.orderValue} ${styles.eta}`}>~{result.etaMinutes} min</span>
          </div>
        </div>
      </div>
    );
  }

  if (result.kind === 'cook_no_order') {
    return (
      <div className={styles.cookCard}>
        <ChefHat />
        <div className={styles.cookCardTitle}>Time to cook!</div>
        <div className={styles.cookCardSub}>All ingredients are in your fridge.</div>
      </div>
    );
  }

  if (result.kind === 'error') {
    if (resultsAlreadyShown) {
      return (
        <div className={styles.errorCard}>
          <CircleAlert />
          <span>{result.message}</span>
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

  // auth_required — a real <a href> (not a fetch/button) so it performs a
  // full page navigation for the OAuth redirect, exactly as the original.
  return (
    <div className={styles.authCard}>
      <div className={styles.authCardIcon}><Bike /></div>
      <div className={styles.authCardTitle}>Connect your Swiggy account</div>
      <div className={styles.authCardSub}>{result.message || 'Login to place this order instantly'}</div>
      <a className={styles.authCta} href="/auth/login"><Link2 /> Connect with Swiggy</a>
    </div>
  );
}
