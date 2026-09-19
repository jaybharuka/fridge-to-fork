// The app-wide product-match cache: the checklist prefetches into it, the order
// sheet reads from it (see searchCache.ts).
import { instamartSearch } from './instamart';
import { createSearchCache } from './searchCache';

export const productCache = createSearchCache(instamartSearch);
