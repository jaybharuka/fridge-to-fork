'use client';

import { Link2, LoaderCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import styles from './ConnectGate.module.css';

interface ConnectGateProps {
  /** Still finding out whether a Swiggy session exists (first paint / cold server). */
  checking: boolean;
  /** Fired just before navigating to Swiggy, so the caller can stash in-progress work to resume. */
  onConnectClick: () => void;
}

// Swiggy is required to use the app: real Instamart prices and ordering both
// need it. Everything behind this (dish input, Get Recipe, fridge scan) isn't
// rendered at all until a session exists, so nothing can be used around it.
export function ConnectGate({ checking, onConnectClick }: ConnectGateProps) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!checking) return;
    // The free-tier backend can take a while to wake up; say so instead of looking frozen.
    const timer = setTimeout(() => setSlow(true), 5000);
    return () => clearTimeout(timer);
  }, [checking]);

  return (
    <section className={styles.gate} aria-labelledby="connect-gate-title">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/logo-mark.png" alt="" className={styles.logo} width={56} height={56} />
      {checking ? (
        <>
          <h1 id="connect-gate-title" className={styles.title}>Fridge to Fork</h1>
          <p className={styles.body} role="status">
            <LoaderCircle className={styles.spin} aria-hidden /> Checking your Swiggy connection…
          </p>
          {slow && <p className={styles.hint}>This can take a moment while the server wakes up.</p>}
        </>
      ) : (
        <>
          <h1 id="connect-gate-title" className={styles.title}>Connect Swiggy to get started</h1>
          <p className={styles.body}>
            Connect your Swiggy account to see real Instamart prices and order what&apos;s missing.
          </p>
          <a className={styles.cta} href="/auth/login?next=/" onClick={onConnectClick}>
            <Link2 aria-hidden /> Connect with Swiggy
          </a>
          <p className={styles.hint}>You&apos;ll sign in on Swiggy. Nothing is ordered until you confirm it.</p>
        </>
      )}
    </section>
  );
}
