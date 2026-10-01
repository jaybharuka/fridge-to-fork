// Confirm-before-flush for "Choose options". Loading a dish's options empties the user's real Swiggy cart, so the
// picker asks first; the backend call (`load`) only ever runs from confirmGate, never from asking or cancelling.
// Pure (no React, no network) so that is unit tested in plain Node: see loadGate.test.ts.

/** The dish (menuItemId) waiting for the user's yes/no, or null. */
export type Gate = string | null;

export const askGate = (_gate: Gate, id: string): Gate => id;

export const cancelGate = (): Gate => null;

/** Runs `load` once, and only if this exact dish is the one that was asked about. Always closes the question. */
export function confirmGate(gate: Gate, id: string, load: () => void): Gate {
  if (gate === id) load();
  return null;
}
