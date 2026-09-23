import { Card } from '@/components/ui/Card';
import styles from './landing.module.css';

interface ServingsSelectorProps {
  value: number;
  onChange: (n: number) => void;
}

const SERVINGS = [1, 2, 3, 4, 5, 6, 7, 8];

// Phase 2 (2026-09): wrapped in a Card so this reads as one designed input group rather than loose circles floating
// in the page — the audit's finding was that it visually competed with the primary CTA right below it; grouping and
// slightly smaller pills quiet it down relative to that button, which should be the loudest thing on the screen.
export function ServingsSelector({ value, onChange }: ServingsSelectorProps) {
  return (
    <Card padding="sm" className={styles.servingsCard}>
      <label className={styles.inputLabel}>For how many people?</label>
      <div className={styles.servingsPills}>
        {SERVINGS.map((n) => (
          <button
            key={n}
            type="button"
            className={`${styles.servingsPill} ${n === value ? styles.active : ''}`}
            aria-pressed={n === value}
            onClick={() => onChange(n)}
          >
            {n}
          </button>
        ))}
      </div>
    </Card>
  );
}
