import styles from './results.module.css';

interface ToastProps {
  message: string | null;
}

// Port of templates/index.html:2077 (markup) and CSS (lines 1670-1677).
// role="status" + aria-live="polite" (ui-ux-pro-max audit phase 3): with
// neither, a screen-reader user got no indication a toast appeared at all.
export function Toast({ message }: ToastProps) {
  return (
    <div className={`${styles.toast} ${message ? styles.show : ''}`} role="status" aria-live="polite">
      {message}
    </div>
  );
}
