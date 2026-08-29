import { Wand2 } from 'lucide-react';
import styles from './landing.module.css';

interface GetRecipeButtonProps {
  state: 'ready' | 'loading';
  label: string;
  onClick: () => void;
}

// Ported from templates/index.html:1808-1811 (icon/spinner swap: 2751-2764)
export function GetRecipeButton({ state, label, onClick }: GetRecipeButtonProps) {
  return (
    <button
      type="button"
      className={`${styles.analyseBtn} ${state === 'ready' ? styles.ready : styles.loading}`}
      disabled={state === 'loading'}
      onClick={onClick}
    >
      <span>{state === 'loading' ? <div className={styles.spin} /> : <Wand2 size={16} />}</span>
      <span>{label}</span>
    </button>
  );
}
