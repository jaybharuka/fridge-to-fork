import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { AppHeader } from '@/components/results/AppHeader';
import styles from './StaticPage.module.css';

interface StaticPageProps {
  title: string;
  lead?: string;
  children: React.ReactNode;
}

// Shared shell for About/Contact/FAQ/404 — reuses AppHeader (stateless
// chrome, no scan dependency) so these pages match the app's design system
// without touching the scan/order flow.
export function StaticPage({ title, lead, children }: StaticPageProps) {
  return (
    <div>
      <AppHeader />
      <main id="main-content" className="wrap">
        <div className={styles.container}>
          <h1 className={styles.title}>{title}</h1>
          {lead && <p className={styles.lead}>{lead}</p>}
          <div className={styles.content}>{children}</div>
          <Link href="/" className={styles.backLink}>
            <ArrowLeft size={14} /> Back to Fridge to Fork
          </Link>
        </div>
      </main>
    </div>
  );
}
