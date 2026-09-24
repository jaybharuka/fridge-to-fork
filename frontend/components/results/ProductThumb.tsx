'use client';

import { useState } from 'react';
import { ShoppingCart } from 'lucide-react';
import { Icon, type IconSize } from '@/components/ui/Icon';

interface ProductThumbProps {
  url: string | null;
  className: string;
  fallbackClassName: string;
  /** Icon audit (2026-09): was a 🛒 emoji sized by whatever font-size the fallback box's CSS happened to declare —
   *  now the same ShoppingCart icon already used elsewhere (ChoiceCard's "Order from Instamart") everywhere a
   *  product photo is missing/fails, sized deliberately per caller instead of inherited by accident. Defaults to
   *  'sm' (16px), matching most of this component's fallback boxes (~40-44px); pass 'md' for the larger ones. */
  size?: IconSize;
}

/** Product photo that degrades to a placeholder if it's missing or fails to load. */
export function ProductThumb({ url, className, fallbackClassName, size = 'sm' }: ProductThumbProps) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return (
      <div className={fallbackClassName} aria-hidden>
        <Icon icon={ShoppingCart} size={size} />
      </div>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img className={className} src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}
