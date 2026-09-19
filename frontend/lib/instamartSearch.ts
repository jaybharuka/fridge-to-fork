// App-wide product-match caches: the checklist prefetches into them, the order sheet reads from them
// (see searchCache.ts). One cache per delivery address, because price and stock depend on where it's going.
import { instamartSearch } from './instamart';
import { createSearchCache } from './searchCache';

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
