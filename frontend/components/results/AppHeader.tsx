'use client';
import { useAuth } from '@/hooks/useAuth';
import { BackButton } from '@/components/shared/BackButton';
import { AccountMenu } from './AccountMenu';
import styles from './results.module.css';

interface AppHeaderProps {
  /** Clicking the logo/wordmark resets to the landing screen. Optional so AppHeader still renders fine wherever a reset
   *  genuinely doesn't apply. */
  onLogoClick?: () => void;
  /** Shown as a left chevron when given: the explicit "start over" control once a scan is under way. */
  onBack?: () => void;
}

// Three zones on a fixed grid: back chevron (left, only once a scan has started), the brand lockup centred, and one
// account menu (right) that holds the connection status, order history and the theme switch. The wordmark stays visible
// at every phone width; the side slots are the same width so the lockup is truly centred.
export function AppHeader({ onLogoClick, onBack }: AppHeaderProps) {
  const { status } = useAuth();

  const brandContent = (
    <>
      <img src="/logo-mark.png" alt="" className={styles.brandLogo} width={26} height={26} />
      <span className={styles.brandText}>Fridge to Fork</span>
    </>
  );

  return (
    <header className={styles.appHeader}>
      <div className={styles.appHeaderInner}>
        <div className={styles.headerSide}>
          {onBack && <BackButton onClick={onBack} label="Back to home, start over" />}
        </div>
        {onLogoClick ? (
          <button type="button" className={styles.brand} aria-label="Fridge to Fork — back to home" onClick={onLogoClick}>
            {brandContent}
          </button>
        ) : (
          <div className={styles.brand} aria-label="Fridge to Fork">
            {brandContent}
          </div>
        )}
        <div className={`${styles.headerSide} ${styles.headerSideEnd}`}>
          <AccountMenu connected={status === 'connected'} />
        </div>
      </div>
    </header>
  );
}
