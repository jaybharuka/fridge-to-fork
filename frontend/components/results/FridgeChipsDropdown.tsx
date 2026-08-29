'use client';
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, PlusCircle, Refrigerator, X } from 'lucide-react';
import type { DetectedIngredient } from '@/lib/types';
import styles from './results.module.css';

interface FridgeChipsDropdownProps {
  ingredients: DetectedIngredient[];
  matchedFridgeItems: string[];
  open: boolean;
  onClose: () => void;
}

// confClass() — templates/index.html:2808-2810
function confClass(pct: number): 'high' | 'mid' | 'low' {
  return pct >= 80 ? 'high' : pct >= 50 ? 'mid' : 'low';
}

function Chip({ ingredient, other }: { ingredient: DetectedIngredient; other: boolean }) {
  return (
    <div className={`${styles.chip} ${styles[confClass(ingredient.confidence)]} ${other ? styles.other : ''}`}>
      <div className={styles.chipDot} />
      {ingredient.name}
    </div>
  );
}

// Ported from templates/index.html:2015-2023 (markup), 1262-1305 &
// 416-466 (CSS), and the matched/other split + toggle logic from
// buildFridgeChip()/rerenderFridgeChips()/toggleOtherFridgeItems()
// (lines 2808-2896). Empty state ported from lines 4490-4497.
export function FridgeChipsDropdown({ ingredients, matchedFridgeItems, open, onClose }: FridgeChipsDropdownProps) {
  const [expanded, setExpanded] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Click-outside-to-close — outsideFridgeClick() (lines 2933-2939),
  // attached only while open. The listener is registered a tick late
  // (mirroring the original's setTimeout(0)) so the very click that opens
  // the dropdown doesn't immediately close it again.
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    const id = setTimeout(() => document.addEventListener('click', handleClick), 0);
    return () => {
      clearTimeout(id);
      document.removeEventListener('click', handleClick);
    };
  }, [open, onClose]);

  // rerenderFridgeChips()'s split: only splits when matchedFridgeItems is
  // populated AND doing so actually separates something; otherwise every
  // chip renders flat (same fallback the original leaves in place).
  const matchedLower = matchedFridgeItems.map(n => n.toLowerCase().trim());
  let primary = ingredients;
  let secondary: DetectedIngredient[] = [];
  if (matchedFridgeItems.length > 0) {
    primary = ingredients.filter(i => matchedLower.includes(i.name.toLowerCase().trim()));
    secondary = ingredients.filter(i => !matchedLower.includes(i.name.toLowerCase().trim()));
    if (secondary.length > 0 && primary.length < 4) {
      const needed = 5 - primary.length;
      primary = [...primary, ...secondary.slice(0, needed)];
      secondary = secondary.slice(needed);
    }
  }

  return (
    <div ref={dropdownRef} className={`${styles.fridgeChipsDropdown} ${open ? styles.visible : ''}`}>
      <div className={styles.fridgeChipsDropdownHeader}>
        <span>What&apos;s in your fridge</span>
        <button type="button" className={styles.fridgeChipsClose} onClick={onClose} aria-label="Close">
          <X />
        </button>
      </div>
      <div className={styles.chipsInner}>
        {ingredients.length === 0 ? (
          <div className={styles.scanStateCard}>
            <Refrigerator className={styles.scanStateIcon} />
            <div className={styles.scanStateHeading}>Nothing detected in your fridge</div>
            <div className={styles.scanStateSub}>Try a clearer photo with better lighting, or continue without a photo</div>
          </div>
        ) : (
          <>
            {primary.map(i => (
              <Chip key={i.name} ingredient={i} other={false} />
            ))}
            {secondary.length > 0 && (
              <div className={styles.otherFridgeItems}>
                <button type="button" className={styles.otherFridgeToggle} onClick={() => setExpanded(e => !e)}>
                  <PlusCircle />
                  <span>
                    {secondary.length} other item{secondary.length === 1 ? '' : 's'} in your fridge
                  </span>
                  <ChevronDown className={`${styles.otherFridgeChevron} ${expanded ? styles.open : ''}`} />
                </button>
                {expanded && (
                  <div className={styles.otherFridgeChipsWrap}>
                    {secondary.map(i => (
                      <Chip key={i.name} ingredient={i} other />
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
