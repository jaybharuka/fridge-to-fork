// Which saved address the user chose to order to, and any real coordinates captured for an address.
// Both live on this device only (localStorage). The selection is a hint: the backend verifies it against
// the account's saved addresses on every search and falls back to the default if it's gone.
import { useSyncExternalStore } from 'react';

export interface Coords { lat: number; lng: number }

const ID_KEY = 'f2f_address_id';
const COORDS_KEY = 'f2f_address_coords';

function read<T>(key: string, fallback: T): T {
  try {
    const raw = typeof window === 'undefined' ? null : window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable (private mode): the choice just doesn't persist */
  }
}

let selected: string | null = read<string | null>(ID_KEY, null);
let coords: Record<string, Coords> = read<Record<string, Coords>>(COORDS_KEY, {});
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(l => l());

export function setSelectedAddressId(id: string | null) {
  selected = id;
  write(ID_KEY, id);
  notify();
}

export const getSelectedAddressId = () => selected;

/** Real coordinates the user shared for an address (device location at creation); never guessed. */
export function rememberCoords(addressId: string, c: Coords) {
  coords = { ...coords, [addressId]: c };
  write(COORDS_KEY, coords);
}

export function forgetAddress(addressId: string) {
  coords = Object.fromEntries(Object.entries(coords).filter(([id]) => id !== addressId));
  write(COORDS_KEY, coords);
  if (selected === addressId) setSelectedAddressId(null);
}

export const coordsFor = (addressId: string | null): Coords | null => (addressId ? coords[addressId] ?? null : null);

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};

export function useSelectedAddressId(): string | null {
  return useSyncExternalStore(subscribe, () => selected, () => null);
}
