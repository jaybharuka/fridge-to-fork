import styles from './results.module.css';

interface StickySummaryBarProps {
  visible: boolean;
  haveCount: number;
  total: number;
  dishName: string;
}

// Ported from templates/index.html:1949-1952 (markup), 1008-1035 (CSS),
// updateStickySummaryBar() (lines 3502-3516).
export function StickySummaryBar({ visible, haveCount, total, dishName }: StickySummaryBarProps) {
  const missingCount = total - haveCount;

  return (
    <div className={`${styles.stickySummaryBar} ${visible ? styles.visible : ''}`}>
      <span className={styles.stickySummaryText}>
        {haveCount} of {total} ingredient{total === 1 ? '' : 's'} · <strong>{missingCount} to order</strong>
      </span>
      <span className={styles.stickySummaryDish}>{dishName}</span>
    </div>
  );
}
