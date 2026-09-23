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
  /** A real Swiggy dish photo, found once the Food order sheet's own search turns one up — free (no extra Swiggy
   *  call: the search already ran for the picker). Only ever an upgrade over the stock waterfall photo below; never
   *  fetched for this component's own sake, and null for anyone who hasn't opened the order sheet. */
  swiggyImageUrl?: string | null;
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
  swiggyImageUrl,
}: DishHeroSectionProps) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  // The real Swiggy photo, once actually decoded — preload-then-swap, same idiom as TopUpCard's image fallback, so
  // a slow or failed load never flashes a broken image over the photo/placeholder already showing underneath.
  const [swiggyReady, setSwiggyReady] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setImageUrl(null);
    setLoaded(false);
    setSwiggyReady(null); // a new dish means any earlier upgrade no longer applies
    resolveDishHeroImage(dishName, fetchYoutubeFirstThumbnail).then(url => {
      if (!cancelled) setImageUrl(url);
    });
    return () => {
      cancelled = true;
    };
  }, [dishName, fetchYoutubeFirstThumbnail]);

  useEffect(() => {
    if (!swiggyImageUrl) return;
    let cancelled = false;
    const probe = new Image();
    probe.onload = () => {
      if (!cancelled) setSwiggyReady(swiggyImageUrl);
    };
    probe.src = swiggyImageUrl;
    return () => {
      cancelled = true;
    };
  }, [swiggyImageUrl]);

  // Mounted at opacity 0 first, then '.loaded' is added a frame later — same forced-reflow trick as LoadingOverlay's
  // fade-in, so the CSS opacity transition actually has a 0 to animate from instead of painting straight at 1.
  const [swiggyVisible, setSwiggyVisible] = useState(false);
  useEffect(() => {
    if (!swiggyReady) {
      setSwiggyVisible(false);
      return;
    }
    const frame = requestAnimationFrame(() => setSwiggyVisible(true));
    return () => cancelAnimationFrame(frame);
  }, [swiggyReady]);

  return (
    <div className={styles.dishHeroSection}>
      <div className={styles.dishHeroImageWrap}>
        {imageUrl && (
          <img
            className={`${styles.dishHeroImg} ${loaded ? styles.loaded : ''}`}
            src={imageUrl}
            alt={`${dishName} recipe`}
            onLoad={() => setLoaded(true)}
            onError={() => setImageUrl(null)}
          />
        )}
        {/* The real Swiggy photo, layered over the waterfall photo/placeholder and faded in once decoded — an
            upgrade, never a replacement while it loads, and never a hard cut. */}
        {swiggyReady && (
          <img
            className={`${styles.dishHeroImg} ${styles.dishHeroSwiggyImg} ${swiggyVisible ? styles.loaded : ''}`}
            src={swiggyReady}
            alt=""
            aria-hidden="true"
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
