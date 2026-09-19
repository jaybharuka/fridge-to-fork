// Shared cache for /api/instamart/search, keyed by ingredient name.
//
// The checklist prefetches product matches as soon as the missing list is
// known; the order sheet asks for the same ingredients later. Both go through
// ensure(), which only requests what isn't already cached or in flight, so
// opening the sheet after the checklist loaded costs no network at all.
//
// Pure and dependency-injected (search function + clock) so it can be unit
// tested in plain Node — see searchCache.test.ts. The real singleton lives in
// instamartSearch.ts.

import type { InstamartAddress, InstamartSearchResult } from './instamart';

export type EntryStatus = 'loading' | 'ready' | 'failed';

export interface CacheEntry {
  status: EntryStatus;
  /** Present when ready. An empty `options` list is a valid answer ("no match"). */
  result: InstamartSearchResult | null;
  at: number;
}

export interface CacheSnapshot {
  entries: ReadonlyMap<string, CacheEntry>;
  address: InstamartAddress | null;
}

export interface SearchResponse {
  address: InstamartAddress;
  results: InstamartSearchResult[];
}

export type SearchFn = (items: string[]) => Promise<SearchResponse>;

export interface EnsureOutcome {
  address: InstamartAddress | null;
  /** One entry per requested ingredient (deduped, case-insensitive), keyed by keyOf(). */
  entries: ReadonlyMap<string, CacheEntry>;
  /** First search error among the requested items, else null. Never thrown. */
  error: unknown;
}

/** Backend accepts at most this many ingredients per search. */
export const MAX_SEARCH_ITEMS = 25;
const DEFAULT_TTL_MS = 10 * 60 * 1000;

export const keyOf = (name: string): string => name.trim().toLowerCase();

const EMPTY: CacheSnapshot = { entries: new Map(), address: null };

interface Options {
  /** Ready entries older than this are searched again (prices/stock move). */
  ttlMs?: number;
  now?: () => number;
}

export function createSearchCache(search: SearchFn, { ttlMs = DEFAULT_TTL_MS, now = Date.now }: Options = {}) {
  let snapshot: CacheSnapshot = EMPTY;
  const listeners = new Set<() => void>();
  const inflight = new Map<string, Promise<void>>();
  const errors = new Map<string, unknown>();

  function publish(patch: (entries: Map<string, CacheEntry>) => void, address?: InstamartAddress) {
    const entries = new Map(snapshot.entries);
    patch(entries);
    snapshot = { entries, address: address ?? snapshot.address };
    listeners.forEach(l => l());
  }

  const isUsable = (e: CacheEntry | undefined) =>
    !!e && (e.status === 'loading' || (e.status === 'ready' && now() - e.at < ttlMs));

  async function fetchBatch(names: string[]): Promise<void> {
    const keys = names.map(keyOf);
    try {
      const { address, results } = await search(names);
      const byKey = new Map(results.map(r => [keyOf(r.ingredient), r]));
      keys.forEach(k => errors.delete(k));
      publish(entries => {
        for (const k of keys) {
          const result = byKey.get(k) ?? null;
          entries.set(k, { status: result ? 'ready' : 'failed', result, at: now() });
        }
      }, address);
    } catch (err) {
      keys.forEach(k => errors.set(k, err));
      publish(entries => keys.forEach(k => entries.set(k, { status: 'failed', result: null, at: now() })));
    } finally {
      keys.forEach(k => inflight.delete(k));
    }
  }

  async function ensure(names: readonly string[]): Promise<EnsureOutcome> {
    const wanted = new Map<string, string>(); // key -> first name as given
    for (const name of names) {
      const key = keyOf(name);
      if (key && !wanted.has(key)) wanted.set(key, name.trim());
    }

    const missing = [...wanted].filter(([key]) => !inflight.has(key) && !isUsable(snapshot.entries.get(key)));
    if (missing.length > 0) {
      publish(entries => missing.forEach(([key]) => entries.set(key, { status: 'loading', result: null, at: now() })));
      const batch = fetchBatch(missing.map(([, name]) => name));
      missing.forEach(([key]) => inflight.set(key, batch));
    }

    await Promise.all([...wanted.keys()].map(key => inflight.get(key)));

    const entries = new Map<string, CacheEntry>();
    let error: unknown = null;
    for (const key of wanted.keys()) {
      const entry = snapshot.entries.get(key);
      if (entry) entries.set(key, entry);
      if (error === null && errors.has(key)) error = errors.get(key);
    }
    return { address: snapshot.address, entries, error };
  }

  return {
    ensure,
    getSnapshot: (): CacheSnapshot => snapshot,
    getServerSnapshot: (): CacheSnapshot => EMPTY,
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}
