// The scan screen's "first look": what the backend's step1_partial events show while pass 2 is still running.
// Pure (no React) so it is unit tested in plain Node: see firstLook.test.ts.
//
// The rules that keep it honest: the early list only ever GROWS (mergeFirstLook, in hooks/scanReducer.ts), nothing shown is dropped when the final
// list lands (reconcileFinal keeps every shown row, swapping the few that the final merge replaced with a higher-confidence
// variant, as reported by the backend's early_superseded), and the final list is what the results page uses.

import type { DetectedIngredient } from './types';

export interface Superseded { from: string; to: string }

const key = (name: string) => name.trim().toLowerCase();

/** The rows to show when the final list arrives: the rows already on screen (a row the final merge replaced is swapped in
 *  place for its replacement), then the final items not shown yet, in the final order. `appendedFrom` is the index where the
 *  not-yet-shown rows start, so a caller animates only those. With nothing shown this is just the final list, all new. */
export function reconcileFinal(
  shown: readonly DetectedIngredient[],
  finalList: readonly DetectedIngredient[],
  superseded: readonly Superseded[] = [],
): { rows: DetectedIngredient[]; appendedFrom: number } {
  const byName = new Map(finalList.map(i => [key(i.name), i] as const));
  const swap = new Map(superseded.map(s => [key(s.from), s.to] as const));
  const rows = shown.map(row => {
    const replacement = swap.get(key(row.name));
    return replacement ? byName.get(key(replacement)) ?? { ...row, name: replacement } : row;
  });
  const have = new Set(rows.map(r => key(r.name)));
  const appended = finalList.filter(i => i.name && i.name.trim() !== '' && !have.has(key(i.name)) && have.add(key(i.name)));
  return { rows: [...rows, ...appended], appendedFrom: rows.length };
}
