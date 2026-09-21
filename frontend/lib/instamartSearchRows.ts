// Turns one Instamart search answer into the rows the "Looking for something else?" box shows, and an add-ready result for the
// order sheet. Pure (no React, no network) so it is unit-tested in plain Node: see instamartSearchRows.test.ts.
import type { InstamartOption, InstamartSearchResult } from './instamart';

/** Cards shown per search: what the box asks the backend for (`max_options`) and never exceeds. One page of Instamart search is ~20
 *  products / up to ~46 variations, and there is no further page (offset does not return new products). */
export const MAX_SEARCH_ROWS = 40;

export interface SearchRow {
  option: InstamartOption;
  /** Unique key for this item among everything already in the sheet (the sheet keys its items by this name). */
  label: string;
  /** This exact variation is already part of the order. */
  added: boolean;
  canAdd: boolean;
}

/** `addedSpinIds`: variations currently chosen in the order. `takenLabels`: names the sheet already uses for its items. */
export function rowsFrom(
  result: InstamartSearchResult | null,
  addedSpinIds: ReadonlySet<string>,
  takenLabels: ReadonlySet<string>,
): SearchRow[] {
  if (!result) return [];
  const used = new Set(takenLabels);
  // Stable: in-stock first, Swiggy's ranking kept within each group.
  const ordered = [...result.options].sort((a, b) => Number(!a.available) - Number(!b.available)).slice(0, MAX_SEARCH_ROWS);
  return ordered.map(option => {
    const label = uniqueLabel(option, used);
    used.add(label);
    const added = addedSpinIds.has(option.spinId);
    return { option, label, added, canAdd: option.available && !added };
  });
}

function uniqueLabel(option: InstamartOption, used: ReadonlySet<string>): string {
  const name = option.name.trim() || option.brand?.trim() || 'Item';
  if (!used.has(name)) return name;
  const sized = option.size ? `${name} · ${option.size}` : name;
  if (!used.has(sized)) return sized;
  return `${sized} (${option.spinId})`; // a last resort that keeps the key unique
}

/** What the sheet's add path (`addProduct`) takes: just this variation, so it is the one picked. */
export function toCartResult(row: SearchRow): InstamartSearchResult {
  return { ingredient: row.label, options: [row.option], note: null };
}
