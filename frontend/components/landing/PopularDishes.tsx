'use client';

import { useEffect, useState } from 'react';
import { Drumstick, Wheat, Soup, Flame, ChefHat, Sunrise } from 'lucide-react';
import { fetchUnsplashDishImage } from '@/lib/dishHeroImage';
import { Card } from '@/components/ui/Card';
import styles from './landing.module.css';

interface PopularDishesProps {
  onSelectDish: (name: string) => void;
}

const DISHES = [
  { name: 'Butter Chicken', tag: 'North Indian', Icon: Drumstick },
  { name: 'Matar Pulao', tag: 'Rice', Icon: Wheat },
  { name: 'Dal Makhani', tag: 'North Indian', Icon: Soup },
  { name: 'Paneer Tikka', tag: 'Starter', Icon: Flame },
  { name: 'Biryani', tag: 'Rice', Icon: ChefHat },
  { name: 'Poha', tag: 'Breakfast', Icon: Sunrise },
] as const;

// Module-level, so every mount of the landing page (e.g. "start over") reuses what a previous mount already found —
// these six dishes are fixed, not per-scan data, so a page-lifetime cache is enough (no need for pollution guards).
const imageCache = new Map<string, string | null>();

function DishThumb({ name, Icon }: { name: string; Icon: (typeof DISHES)[number]['Icon'] }) {
  const [url, setUrl] = useState<string | null>(imageCache.get(name) ?? null);

  useEffect(() => {
    if (imageCache.has(name)) return; // already resolved (found or not) by an earlier mount
    let cancelled = false;
    fetchUnsplashDishImage(name).then(found => {
      imageCache.set(name, found);
      if (!cancelled) setUrl(found);
    });
    return () => {
      cancelled = true;
    };
  }, [name]);

  return (
    <div className={styles.popularDishThumb}>
      {url ? (
        <img src={url} alt="" className={styles.popularDishImg} />
      ) : (
        <Icon className={styles.popularDishIcon} aria-hidden="true" />
      )}
    </div>
  );
}

// Ported from templates/index.html:1834-1880; Phase 2 (2026-09) swaps the generic icon-in-a-box placeholder for a
// real photo via the same Unsplash source the recipe hero uses (fetchUnsplashDishImage), keeping the icon as the
// fallback shown until a photo resolves or if Unsplash has nothing for that name — same idiom as TopUpCard's own
// icon-then-photo swap, not a new pattern.
export function PopularDishes({ onSelectDish }: PopularDishesProps) {
  return (
    <div className={styles.popularDishesSection}>
      <div className={styles.popularDishesLabel}>Popular right now</div>
      <div className={styles.popularDishesGrid}>
        {DISHES.map(({ name, tag, Icon }) => (
          <button key={name} type="button" className={styles.popularDishBtn} onClick={() => onSelectDish(name)}>
            <Card padding="none" className={styles.popularDishCard}>
              <DishThumb name={name} Icon={Icon} />
              <div className={styles.popularDishInfo}>
                <span className={styles.popularDishName}>{name}</span>
                <span className={styles.popularDishTag}>{tag}</span>
              </div>
            </Card>
          </button>
        ))}
      </div>
    </div>
  );
}
