import styles from './results.module.css';

interface ToastProps {
  message: string | null;
}

// Port of templates/index.html:2077 (markup) and CSS (lines 1670-1677).
export function Toast({ message }: ToastProps) {
  return (
    <div className={`${styles.toast} ${message ? styles.show : ''}`}>
      {message}
    </div>
  );
}
