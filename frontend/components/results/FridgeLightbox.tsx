import { X } from 'lucide-react';
import styles from './results.module.css';

interface FridgeLightboxProps {
  open: boolean;
  imageUrl: string;
  onClose: () => void;
}

// Ported from templates/index.html:2067-2072 (markup), 1206-1244 (CSS),
// openFridgeLightbox()/closeFridgeLightbox() (lines 2944-2957) and the
// backdrop-click-closes listener (lines 2960-2962).
export function FridgeLightbox({ open, imageUrl, onClose }: FridgeLightboxProps) {
  return (
    <div
      className={`${styles.fridgeLightbox} ${open ? styles.visible : ''}`}
      onClick={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <button type="button" className={styles.fridgeLightboxClose} onClick={onClose} aria-label="Close">
        <X />
      </button>
      <img className={styles.fridgeLightboxImg} src={imageUrl} alt="Your fridge" />
    </div>
  );
}
