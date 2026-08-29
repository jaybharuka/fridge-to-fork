'use client';
import { useMemo, useState, useCallback } from 'react';
import { INSTANT_DISHES } from '@/lib/instantDishes';

export function useAutocomplete(query: string) {
  const [activeIndex, setActiveIndex] = useState(-1);

  const suggestions = useMemo(() => {
    const q = query.trim();
    if (q.length < 2) return [];
    const qLower = q.toLowerCase();
    const startsWith: string[] = [];
    const contains: string[] = [];
    for (const d of INSTANT_DISHES) {
      const dLower = d.toLowerCase();
      if (dLower.startsWith(qLower)) startsWith.push(d);
      else if (dLower.includes(qLower)) contains.push(d);
    }
    return [...startsWith, ...contains].slice(0, 7);
  }, [query]);

  return { suggestions, activeIndex, setActiveIndex };
}
