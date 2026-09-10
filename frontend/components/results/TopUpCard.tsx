'use client';

import { useEffect, useState } from 'react';
import { CircleCheck } from 'lucide-react';
import type { TopUpSuggestion } from '@/lib/types';
import { simplifyIngredientName, getEmojiForIngredient } from '@/lib/foodEmoji';
import styles from './results.module.css';

interface TopUpCardProps {
  item: TopUpSuggestion;
  selected: boolean;
  onToggle: () => void;
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
// Click-to-add: the original vanilla app (templates/index.html:3910-3943)
// never actually wired a click handler on these cards despite styling
// `cursor: pointer` and a `:active` press effect — they were purely
// visual upsell suggestions, never addable, never sent to the backend.
// This is a genuinely new feature, not a preserved-behavior port.
export function TopUpCard({ item, selected, onToggle }: TopUpCardProps) {
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
    <button
      type="button"
      className={`${styles.topupSheetCard} ${selected ? styles.selected : ''}`}
      onClick={onToggle}
      aria-pressed={selected}
      aria-label={`${selected ? 'Remove' : 'Add'} ${item.name} ${selected ? 'from' : 'to'} order`}
    >
      <div className={styles.topupSheetImgWrap}>
        <img
          className={`${styles.topupSheetImg} ${imageUrl ? styles.loaded : ''}`}
          src={imageUrl ?? ''}
          alt={item.name}
        />
        {!imageUrl && (
          <div className={styles.topupSheetEmojiFallback}>{getEmojiForIngredient(item.name)}</div>
        )}
        {selected && (
          <div className={styles.topupSheetCheckBadge}>
            <CircleCheck />
          </div>
        )}
      </div>
      <div className={styles.topupSheetInfo}>
        <p className={styles.topupSheetName}>{item.name}</p>
        <p className={styles.topupSheetPrice}>~₹{item.estimated_price || 0}</p>
      </div>
    </button>
  );
}
