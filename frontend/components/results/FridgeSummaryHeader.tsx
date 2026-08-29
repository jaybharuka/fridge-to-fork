import type { ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import styles from './results.module.css';

interface FridgeSummaryHeaderProps {
  /** Controls the opacity crossfade described below — false while
   *  PhotoScanScreen is showing, true once its onRevealComplete fires. */
  visible: boolean;
  thumbUrl: string;
  ingredientCount: number;
  onOpenLightbox: () => void;
  /** Row click toggles the chips dropdown open/closed — mirrors
   *  toggleFridgeDropdown() on #fridgeSummaryRow. The dropdown's open
   *  state itself is owned by the parent (page.tsx), not this component,
   *  since FridgeChipsDropdown takes it as a controlled `open` prop. */
  onToggleDropdown: () => void;
  dropdownOpen: boolean;
  /** The <FridgeChipsDropdown> — rendered as a sibling of the clickable
   *  row (not a descendant of it) so its own clicks can never bubble into
   *  the row's onClick, matching the original DOM structure. */
  children: ReactNode;
}

// Ported from templates/index.html:2002-2024 (markup), 1165-1260 (CSS),
// the thumbnail click handler (lines 2963-2966).
//
// Do NOT implement the FLIP-clone morph from transitionToResults()
// (lines 2649-2733) — that technique clones a DOM node and animates its
// raw getBoundingClientRect() position, which exists purely to bridge two
// different fixed-position full-screen elements in vanilla DOM. In React
// the same visual result — "the photo hands off to the results thumbnail"
// — comes from a much simpler shared-element crossfade: this component
// already renders the thumbnail at its final position, just at opacity:0
// (via `visible=false`) for as long as PhotoScanScreen is showing on top
// of it. When PhotoScanScreen's onRevealComplete fires (Task 6), the
// parent fades PhotoScanScreen out and flips `visible` to true here, and
// the CSS transition on .fridgeSummaryHeader (opacity, ~450ms) does the
// rest — no clone, no manual rect math, same perceived handoff.
export function FridgeSummaryHeader({
  visible,
  thumbUrl,
  ingredientCount,
  onOpenLightbox,
  onToggleDropdown,
  dropdownOpen,
  children,
}: FridgeSummaryHeaderProps) {
  return (
    <div className={`${styles.fridgeSummaryHeader} ${visible ? styles.visible : ''}`}>
      <div className={styles.fridgeSummaryRow} onClick={onToggleDropdown}>
        <div
          className={styles.fridgeThumbTarget}
          onClick={e => {
            e.stopPropagation(); // don't also trigger the row's dropdown toggle
            onOpenLightbox();
          }}
        >
          <img className={styles.fridgeThumbImg} src={thumbUrl} alt="Your fridge" />
        </div>
        <div className={styles.fridgeSummaryText}>
          <p className={styles.fridgeSummaryLabel}>Your fridge</p>
          <p className={styles.fridgeSummaryCount}>
            {ingredientCount} item{ingredientCount === 1 ? '' : 's'} detected
          </p>
        </div>
        <div className={`${styles.fridgeDropdownChevron} ${dropdownOpen ? styles.open : ''}`}>
          <ChevronDown />
        </div>
      </div>
      {children}
    </div>
  );
}
