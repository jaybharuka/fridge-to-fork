import type { ChecklistItem, TopUpSuggestion } from './types';

const STORAGE_KEY = 'f2f_results_snapshot';

export interface ResultsSnapshot {
  recommendedMeal: string;
  reasoning: string;
  checklist: ChecklistItem[];
  topUpSuggestions: TopUpSuggestion[];
  targetDish: string;
  servings: number;
  tab: 'order' | 'recipe';
}

// A scan/recipe result lives only in useScanStream's in-memory reducer, so
// leaving "/" for any other in-app route (the About/FAQ/Contact footer
// links) unmounts Home and loses it — a client-side route change never
// unloads the document, so it isn't covered by lib/pendingOrder.ts's
// OAuth-redirect bridge either. This stashes just enough to restore the
// Order tab (mirrors that file's shape/reasoning), written right before the
// page actually goes away and read once on the next mount. sessionStorage,
// not localStorage — same reasoning as pendingOrder.ts: a stale entry can
// never leak into an unrelated later session once the tab closes.
export function saveResultsSnapshot(data: ResultsSnapshot): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // Storage unavailable (private browsing, quota) — the user just lands
    // on a fresh homepage on return, same as before this fix.
  }
}

// Reads and immediately clears the stash — restore is one-shot. The next
// "leaving" event re-saves a fresh snapshot if there are still live results,
// so this never needs to be reapplied; keeping it around after a read would
// only risk resurrecting stale results after an explicit reset.
export function consumeResultsSnapshot(): ResultsSnapshot | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(STORAGE_KEY);
    return JSON.parse(raw) as ResultsSnapshot;
  } catch {
    return null;
  }
}

// "Start over" clears the in-memory state; without this, a stale snapshot
// from before the reset would still be sitting in sessionStorage and would
// wrongly resurrect the old results the next time the user leaves and returns.
export function clearResultsSnapshot(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to do — same as save/consume, storage may just be unavailable.
  }
}
