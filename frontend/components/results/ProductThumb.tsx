'use client';

import { useState } from 'react';

interface ProductThumbProps {
  url: string | null;
  className: string;
  fallbackClassName: string;
}

/** Product photo that degrades to a placeholder if it's missing or fails to load. */
export function ProductThumb({ url, className, fallbackClassName }: ProductThumbProps) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) return <div className={fallbackClassName} aria-hidden>🛒</div>;
  // eslint-disable-next-line @next/next/no-img-element
  return <img className={className} src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}
