import Link from 'next/link';
import styles from './Footer.module.css';

// Small, unobtrusive text links — deliberately not a nav bar, matches the
// app's linear-scroll/no-nested-navigation design. Rendered once in
// app/layout.tsx (not page.tsx) so it appears under every page's content
// without touching the core scan/order flow.
export function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={styles.links}>
        <Link href="/about">About</Link>
        <span className={styles.dot}>·</span>
        <Link href="/faq">FAQ</Link>
        <span className={styles.dot}>·</span>
        <Link href="/contact">Contact</Link>
      </div>
    </footer>
  );
}
