// Tiny store for "is the orders sheet open, and on which order". Lives outside React so the
// header button and the order-placed screen can both open it without prop drilling.
import { useSyncExternalStore } from 'react';

export interface OrdersUiState {
  open: boolean;
  /** Order to jump straight into; null shows the list. */
  orderId: string | null;
  /** Bumped on every open so the sheet's internal navigation state starts fresh. */
  session: number;
}

const CLOSED: OrdersUiState = { open: false, orderId: null, session: 0 };
let state: OrdersUiState = CLOSED;
const listeners = new Set<() => void>();

function set(next: OrdersUiState) {
  state = next;
  listeners.forEach(l => l());
}

export const openOrders = (orderId: string | null = null) => set({ open: true, orderId, session: state.session + 1 });
export const closeOrders = () => set({ ...state, open: false });

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};

export function useOrdersUi(): OrdersUiState {
  return useSyncExternalStore(subscribe, () => state, () => CLOSED);
}
