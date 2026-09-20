// Tiny store for "is the orders sheet open, and on which order". Lives outside React so the
// header button and the order-placed screen can both open it without prop drilling.
import { useSyncExternalStore } from 'react';

/** Which orders sheet is wanted: Instamart's or Food's (each has its own sheet and tools). */
export type OrdersKind = 'instamart' | 'food';

export interface OrdersUiState {
  open: boolean;
  /** Order to jump straight into; null shows the list. */
  orderId: string | null;
  kind: OrdersKind;
  /** Food: the address the order was placed to (get_food_orders needs one); null = the default. */
  addressId: string | null;
  /** Bumped on every open so the sheet's internal navigation state starts fresh. */
  session: number;
}

const CLOSED: OrdersUiState = { open: false, orderId: null, kind: 'instamart', addressId: null, session: 0 };
let state: OrdersUiState = CLOSED;
const listeners = new Set<() => void>();

function set(next: OrdersUiState) {
  state = next;
  listeners.forEach(l => l());
}

export const openOrders = (orderId: string | null = null, kind: OrdersKind = 'instamart', addressId: string | null = null) =>
  set({ open: true, orderId, kind, addressId, session: state.session + 1 });
export const closeOrders = () => set({ ...state, open: false });

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};

export function useOrdersUi(): OrdersUiState {
  return useSyncExternalStore(subscribe, () => state, () => CLOSED);
}
