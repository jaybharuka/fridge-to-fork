import styles from './landing.module.css';

// Ported from templates/index.html:1781-1784
export function Hero() {
  return (
    <div className={styles.hero}>
      <h1 className={styles.heroTitle}>
        Cook anything.
        <br />
        Order what&apos;s missing.
      </h1>
      <p className={styles.heroSub}>Type a dish. Scan your fridge. Get exactly what you need delivered.</p>
    </div>
  );
}
