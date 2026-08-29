'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Camera, CircleCheck } from 'lucide-react';
import type { ChecklistItem } from '@/lib/types';
import { buildRecipeHookText } from '@/hooks/useRecipeChecklist';
import styles from './IngredientChecklistCard.module.css';

interface IngredientChecklistCardProps {
  checklist: ChecklistItem[];
  toggleChecklistItem: (index: number) => void;
}

// Counts a stat number up from 0 to `target` over 600ms, eased — ported
// from animateStatNumbers() (templates/index.html:3664-3678). Re-runs
// whenever `target` changes (i.e. every toggle), matching the original
// re-calling animateStatNumbers() on every buildRecipeStatsHtml() rebuild.
function StatNumber({ target, className }: { target: number; className?: string }) {
  const [value, setValue] = useState(0);

  useEffect(() => {
    let raf = 0;
    const duration = 600;
    const start = performance.now();
    function tick(now: number) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(eased * target));
      if (progress < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);

  return <span className={className}>{value}</span>;
}

// Ported from templates/index.html:3231-3261 (renderRecipeChecklistCard
// markup), 583-664 (CSS — see IngredientChecklistCard.module.css),
// 3490-3494 (buildRecipeStatsHtml), 3680-3707 (buildRecipeRowsHtml).
//
// The scroll-fix: .rows (styles.rows) is the internally-scrollable
// container (max-height 46vh/52vh, themed thin scrollbar) — a leaf inside
// this card, which is itself a sibling of ResultTabBar/StickySummaryBar
// (Task 7, position: sticky) under the page body, not a parent or child of
// them. A short checklist that fits within max-height never overflows, so
// no scrollbar/fade appears for it.
export function IngredientChecklistCard({ checklist, toggleChecklistItem }: IngredientChecklistCardProps) {
  const rowsRef = useRef<HTMLDivElement>(null);
  const [hasMoreBelow, setHasMoreBelow] = useState(false);

  useEffect(() => {
    const el = rowsRef.current;
    if (!el) return;
    const update = () => setHasMoreBelow(el.scrollTop + el.clientHeight < el.scrollHeight - 1);
    update();
    el.addEventListener('scroll', update);
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => {
      el.removeEventListener('scroll', update);
      ro.disconnect();
    };
  }, [checklist.length]); // re-measure when the row count changes, matching updateRecipeRowsFade() being re-run after toggleRecipeItem()

  if (!checklist.length) return null;

  const haveCount = checklist.filter(i => i.checked).length;
  const total = checklist.length;
  const toOrderCount = total - haveCount;

  return (
    <div className={styles.card}>
      <div className={styles.statsRow}>
        <p className={styles.statLine}>
          You already have <StatNumber target={haveCount} /> of <StatNumber target={total} /> ingredient{total === 1 ? '' : 's'}. Just{' '}
          <StatNumber target={toOrderCount} className={styles.statZ} /> item{toOrderCount === 1 ? '' : 's'} to order.
        </p>
      </div>
      <p className={styles.hookLine}>{buildRecipeHookText(checklist)}</p>
      <div className={`${styles.rowsWrap} ${hasMoreBelow ? styles.hasMoreBelow : ''}`}>
        <div className={styles.rows} ref={rowsRef}>
          {checklist.map((ing, idx) => {
            let tag: ReactNode = null;
            if (ing.checked) {
              if (ing.foundInFridge) {
                tag = (
                  <span className={`${styles.rowTag} ${styles.rowTagFridge}`}>
                    <Camera /> in fridge
                  </span>
                );
              } else if (ing.isStaple) {
                tag = <span className={`${styles.rowTag} ${styles.rowTagStaple}`}>Staple</span>;
              }
            } else if (ing.isStaple) {
              tag = <span className={styles.rowTagWillOrder}>Will be ordered</span>;
            }

            return (
              <div
                key={idx}
                className={`${styles.row} ${ing.checked ? styles.checked : ''} ${ing.isStaple ? styles.isStaple : ''}`}
                onClick={() => toggleChecklistItem(idx)}
              >
                <span className={styles.rowCheckbox}>{ing.checked && <CircleCheck />}</span>
                <div className={styles.rowInfo}>
                  <div className={styles.rowName}>{ing.name}</div>
                  <div className={styles.rowQty}>{ing.quantity}</div>
                </div>
                <div className={styles.rowRight}>{tag}</div>
              </div>
            );
          })}
        </div>
        <div className={styles.rowsFade} />
      </div>
    </div>
  );
}
