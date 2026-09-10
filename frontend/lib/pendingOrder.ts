import type { ChecklistItem, TopUpSuggestion } from './types';

const STORAGE_KEY = 'f2f_pending_order';

export interface PendingOrderRestore {
  recommendedMeal: string;
  reasoning: string;
  checklist: ChecklistItem[];
  topUpSuggestions: TopUpSuggestion[];
  selectedTopUpNames: string[];
  reopenOrderSheet: boolean;
}

// Bridges the full-page OAuth redirect (/auth/login -> Swiggy -> /auth/callback
// -> "/") that a "Connect with Swiggy" click triggers. React state doesn't
// survive that navigation, so the minimum needed to put the user back where
// they were — recipe, checklist, top-up picks — is stashed here right before
// the redirect and consumed once on the next page load. sessionStorage
// (not localStorage) so a stale entry can never leak into an unrelated
// later session once the tab closes.
export function savePendingOrder(data: PendingOrderRestore): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // Storage unavailable (private browsing, quota) — the user just lands
    // on a fresh homepage after connecting, same as before this fix.
  }
}

// Reads and immediately clears the stash — restore is one-shot, never
// reapplied on a later, unrelated visit.
export function consumePendingOrder(): PendingOrderRestore | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(STORAGE_KEY);
    return JSON.parse(raw) as PendingOrderRestore;
  } catch {
    return null;
  }
}
