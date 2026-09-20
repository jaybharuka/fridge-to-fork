'use client';

import { ExternalLink, LoaderCircle } from 'lucide-react';
import styles from './instamart.module.css';

/** A started UPI payment. The parent hook is polling; this screen just gives the user Swiggy's scan-or-tap payment page. */
export function PaymentPending({ bridgeUrl, onClose }: { bridgeUrl: string; onClose: () => void }) {
  return (
    <div className={styles.centered}>
      <LoaderCircle className={`${styles.bigIcon} ${styles.warnIcon} ${styles.spin}`} />
      <h4 className={styles.outcomeTitle}>Complete your payment</h4>
      <p className={styles.outcomeBody}>Open Swiggy&apos;s payment page to scan the QR or tap to pay in your UPI app. We&apos;ll update this screen as soon as it goes through.</p>
      <a className={styles.primary} style={{ display: 'block', textDecoration: 'none' }} href={bridgeUrl} target="_blank" rel="noopener noreferrer">
        <ExternalLink style={{ width: 16, height: 16, verticalAlign: '-3px' }} /> Open payment page
      </a>
      <p className={styles.hint}>Waiting for your payment… If you&apos;ve already paid, you can close this — check the Swiggy app for the order.</p>
      <button type="button" className={styles.secondary} onClick={onClose}>Close</button>
    </div>
  );
}
