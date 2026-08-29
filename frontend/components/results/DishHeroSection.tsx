'use client';

import { useEffect, useState } from 'react';
import { resolveDishHeroImage } from '@/lib/dishHeroImage';
import styles from './results.module.css';

interface DishHeroSectionProps {
  dishName: string;
  servings: number;
  cookTime: string | null;
  /** Injected so the underlying YouTube call can share a cache with
   *  YoutubeCarousel (Task 12) rather than each component fetching
   *  independently. */
  fetchYoutubeFirstThumbnail: () => Promise<string>;
}

// Ported from templates/index.html:1980-1987 (markup), 1078-1157 (CSS),
// loadDishHeroImage()/setHeroImage() (lines 3599-3652). Text and the
// placeholder initial render immediately (no network wait); the real
// photo resolves best-effort via resolveDishHeroImage's waterfall and
// fades in over the placeholder once it loads.
export function DishHeroSection({
  dishName,
  servings,
  cookTime,
  fetchYoutubeFirstThumbnail,
}: DishHeroSectionProps) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setImageUrl(null);
    setLoaded(false);
    resolveDishHeroImage(dishName, fetchYoutubeFirstThumbnail).then(url => {
      if (!cancelled) setImageUrl(url);
    });
    return () => {
      cancelled = true;
    };
  }, [dishName, fetchYoutubeFirstThumbnail]);

  return (
    <div className={styles.dishHeroSection}>
      <div className={styles.dishHeroImageWrap}>
        {imageUrl && (
          <img
            className={`${styles.dishHeroImg} ${loaded ? styles.loaded : ''}`}
            src={imageUrl}
            alt={dishName}
            onLoad={() => setLoaded(true)}
            onError={() => setImageUrl(null)}
          />
        )}
        <div className={styles.dishHeroGradient} />
        <div className={styles.dishHeroOverlay}>
          <h1 className={styles.dishHeroName}>{dishName}</h1>
          <p className={styles.dishHeroMeta}>
            For {servings} {servings === 1 ? 'person' : 'people'} · {cookTime || '25 min'}
          </p>
        </div>
        <div className={`${styles.dishHeroPlaceholder} ${loaded ? styles.hidden : ''}`}>
          <span className={styles.dishHeroInitial}>{dishName.charAt(0).toUpperCase()}</span>
        </div>
      </div>
    </div>
  );
}
