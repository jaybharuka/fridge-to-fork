import styles from './landing.module.css';

interface ServingsSelectorProps {
  value: number;
  onChange: (n: number) => void;
}

const SERVINGS = [1, 2, 3, 4, 5, 6, 7, 8];

// Ported from templates/index.html:1793-1804
export function ServingsSelector({ value, onChange }: ServingsSelectorProps) {
  return (
    <div className={styles.servingsSection}>
      <label className={styles.inputLabel}>For how many people?</label>
      <div className={styles.servingsPills}>
        {SERVINGS.map((n) => (
          <button
            key={n}
            type="button"
            className={`${styles.servingsPill} ${n === value ? styles.active : ''}`}
            onClick={() => onChange(n)}
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}
