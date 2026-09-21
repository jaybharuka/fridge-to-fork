// App-wide product-match caches: the checklist prefetches into them, the order sheet reads from them
// (see searchCache.ts). One cache per delivery address, because price and stock depend on where it's going.
import { instamartSearch } from './instamart';
import { createSearchCache } from './searchCache';
import { MAX_SEARCH_ROWS } from './instamartSearchRows';

type ProductCache = ReturnType<typeof createSearchCache>;
const caches = new Map<string, ProductCache>();

/** `null` = the default address (Home / first) chosen by the backend. */
export function productCacheFor(addressId: string | null): ProductCache {
  const key = addressId ?? '';
  let cache = caches.get(key);
  if (!cache) {
    cache = createSearchCache(items => instamartSearch(items, addressId));
    caches.set(key, cache);
  }
  return cache;
}

// The search box has its own caches: it asks for the whole first page of results (up to MAX_SEARCH_ROWS variations), while the
// checklist caches above keep only the top 5 per ingredient. Sharing one cache would hand the box the checklist's 5.
const boxCaches = new Map<string, ProductCache>();

export function searchBoxCacheFor(addressId: string): ProductCache {
  let cache = boxCaches.get(addressId);
  if (!cache) {
    cache = createSearchCache(items => instamartSearch(items, addressId, MAX_SEARCH_ROWS));
    boxCaches.set(addressId, cache);
  }
  return cache;
}
