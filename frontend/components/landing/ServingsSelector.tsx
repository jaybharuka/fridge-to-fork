import styles from './landing.module.css';

interface ServingsSelectorProps {
  value: number;
  onChange: (n: number) => void;
}

const SERVINGS = [1, 2, 3, 4, 5, 6, 7, 8];

// Sits right above the main button, as a setting for it (landing redesign, 2026-10): between the dish box and the fridge card
// it read as a step of one form. Phase 2's slightly smaller pills stay, so the button is still the loudest thing on screen.
export function ServingsSelector({ value, onChange }: ServingsSelectorProps) {
  return (
    <div className={styles.servingsCard}>
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
    </div>
  );
}
