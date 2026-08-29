'use client';

import { useEffect, useState } from 'react';
import type { TopUpSuggestion } from '@/lib/types';
import { simplifyIngredientName, getEmojiForIngredient } from '@/lib/foodEmoji';
import styles from './results.module.css';

interface TopUpCardProps {
  item: TopUpSuggestion;
}

interface IngredientImageResponse {
  found?: boolean;
  image_url?: string;
}

// Ported from templates/index.html:2988-3019 (loadTopUpImage) and
// 3910-3918/928-936 (markup/CSS). The emoji fallback shows immediately and
// is unmounted only once the real photo has actually finished loading — the
// photo is preloaded via a throwaway Image() and only swapped in after
// onload fires, so a 404/failed fetch never shows a broken-image icon and
// never hides the fallback (fallback is position:absolute and would
// otherwise paint over the <img> per CSS stacking order).
export function TopUpCard({ item }: TopUpCardProps) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const query = simplifyIngredientName(item.name);
        const res = await fetch(`/api/ingredient-image?name=${encodeURIComponent(query)}`);
        const data: IngredientImageResponse = await res.json();
        if (cancelled || !data.found || !data.image_url) return;

        const url = data.image_url;
        const probe = new Image();
        probe.onload = () => {
          if (!cancelled) setImageUrl(url);
        };
        probe.onerror = () => {
          // Keep the emoji fallback — no crash.
        };
        probe.src = url;
      } catch {
        // Keep the emoji fallback — no crash.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [item.name]);

  return (
    <div className={styles.topupSheetCard}>
      <div className={styles.topupSheetImgWrap}>
        <img
          className={`${styles.topupSheetImg} ${imageUrl ? styles.loaded : ''}`}
          src={imageUrl ?? ''}
          alt={item.name}
        />
        {!imageUrl && (
          <div className={styles.topupSheetEmojiFallback}>{getEmojiForIngredient(item.name)}</div>
        )}
      </div>
      <div className={styles.topupSheetInfo}>
        <p className={styles.topupSheetName}>{item.name}</p>
        <p className={styles.topupSheetPrice}>~₹{item.estimated_price || 0}</p>
      </div>
    </div>
  );
}
