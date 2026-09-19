'use client';
import { useEffect, useSyncExternalStore } from 'react';
import { productCache } from '../lib/instamartSearch';
import { MAX_SEARCH_ITEMS, type CacheSnapshot } from '../lib/searchCache';

export function useProductMatches(): CacheSnapshot {
  return useSyncExternalStore(productCache.subscribe, productCache.getSnapshot, productCache.getServerSnapshot);
}

/** Searches Instamart for `names` as soon as they're known (debounced so a run of
 *  checkbox toggles becomes one request). Failures land in the cache as "failed"
 *  entries — the checklist just renders those rows plainly. */
export function usePrefetchProducts(names: string[], enabled: boolean): void {
  // JSON keeps the dependency a stable string without a magic separator character.
  const key = JSON.stringify(names);
  useEffect(() => {
    if (!enabled) return;
    const list: string[] = JSON.parse(key);
    if (list.length === 0) return;
    const timer = setTimeout(() => { void productCache.ensure(list.slice(0, MAX_SEARCH_ITEMS)); }, 250);
    return () => clearTimeout(timer);
  }, [key, enabled]);
}
