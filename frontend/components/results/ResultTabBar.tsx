import { BookOpen, ShoppingBag } from 'lucide-react';
import styles from './results.module.css';

type ResultTab = 'order' | 'recipe';

interface ResultTabBarProps {
  activeTab: ResultTab;
  onTabChange: (tab: ResultTab) => void;
  /** Clicking the Recipe tab while it's locked calls this instead of
   *  switching tabs — page.tsx wires it to the Toast component (Task 13). */
  onLockedClick: () => void;
  recipeUnlocked: boolean;
  /** Whether the "new content" dot should render at all. Starts true for
   *  every new scan and is permanently dropped for the rest of that scan
   *  the first time the unlocked Recipe tab is actually clicked — that
   *  per-scan reset lives in page.tsx's state, not here (mirrors
   *  resetResultTabs() recreating it per scan in the original). */
  recipeHasUnreadDot: boolean;
}

// Ported from templates/index.html:1957-1967 (markup), 1040-1083 (CSS),
// switchResultTab()/unlockRecipeTab() (lines 3531-3560).
export function ResultTabBar({ activeTab, onTabChange, onLockedClick, recipeUnlocked, recipeHasUnreadDot }: ResultTabBarProps) {
  function handleRecipeClick() {
    if (!recipeUnlocked) {
      onLockedClick();
      return;
    }
    onTabChange('recipe');
  }

  return (
    <div className={styles.resultTabBar}>
      <button
        type="button"
        className={`${styles.resultTab} ${activeTab === 'order' ? styles.active : ''}`}
        onClick={() => onTabChange('order')}
      >
        <ShoppingBag />
        <span>Order</span>
      </button>
      <button
        type="button"
        className={`${styles.resultTab} ${activeTab === 'recipe' ? styles.active : ''} ${!recipeUnlocked ? styles.locked : ''}`}
        onClick={handleRecipeClick}
        aria-disabled={!recipeUnlocked}
      >
        <BookOpen />
        <span>Recipe</span>
        {recipeHasUnreadDot && (
          <span className={recipeUnlocked ? styles.tabReadyDot : styles.tabLoadingDot} />
        )}
      </button>
    </div>
  );
}
