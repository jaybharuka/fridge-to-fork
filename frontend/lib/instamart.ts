// Client for the staged Instamart flow (backend: fridge_to_fork/instamart_routes.py).
// search -> cart (+review) -> checkout. Real products and a real cart are shown
// before the user's separate, explicit "Place order" action.

import { authHeaders, markDisconnected } from './auth';
import { BACKEND_URL } from './backend';

export interface InstamartAddress { id: string; label: string; addressLine: string }

export interface InstamartOption {
  spinId: string;
  skuId: string;
  name: string;
  brand: string | null;
  size: string | null;
  price: number | null;
  mrp: number | null;
  imageUrl: string | null;
  available: boolean;
  maxQuantity: number | null;
}

export interface InstamartSearchResult { ingredient: string; options: InstamartOption[]; note: string | null }

export interface InstamartCartItem {
  spinId: string; skuId: string; name: string; variant: string | null;
  quantity: number; price: number | null; mrp: number | null; imageUrl: string | null; available: boolean;
}

export interface InstamartReview {
  address: { id: string | null; text: string; label: string | null };
  items: InstamartCartItem[];
  lineItems: { label: string; value: string }[];
  /** Exactly as Swiggy returned it — echoed back at checkout to prove what the user saw. */
  total: string | null;
  totalLabel: string;
  minimumOrder: number;
  warning: string | null;
  blockers: string[];
  canCheckout: boolean;
  paymentMethod: string;
}

export interface InstamartOutcome {
  status: 'placed' | 'partial' | 'failed' | 'unknown';
  orderIds: string[];
  message: string;
  verified: boolean;
  total: string | null;
}

export interface CartSelection { spin_id: string; sku_id: string; quantity: number }

export class InstamartApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BACKEND_URL}/api/instamart/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(body),
    credentials: 'include',
  });
  let data: { ok?: boolean; error?: { code?: string; message?: string } } | null = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body — handled below */
  }
  if (!data?.ok) {
    const code = data?.error?.code ?? 'unexpected_response';
    if (code === 'auth_required') markDisconnected();
    throw new InstamartApiError(code, data?.error?.message ?? 'Something went wrong. Please try again.', res.status);
  }
  return data as T;
}

export const instamartSearch = (items: string[]) =>
  post<{ address: InstamartAddress; results: InstamartSearchResult[] }>('search', { items });

export const instamartCart = (addressId: string, selections: CartSelection[]) =>
  post<{ review: InstamartReview; adjustments: string[] }>('cart', { address_id: addressId, selections });

export const instamartCheckout = (addressId: string, expectedTotal: string, idempotencyKey: string) =>
  post<{ order: InstamartOutcome }>('checkout', {
    address_id: addressId,
    expected_total: expectedTotal,
    idempotency_key: idempotencyKey,
  });

/** Swiggy's own top-ranked in-stock match: what gets pre-picked, and what the checklist previews. */
export function topAvailable(result: InstamartSearchResult | null): InstamartOption | null {
  return result?.options.find(o => o.available) ?? null;
}

export function formatInr(amount: number | null): string {
  if (amount === null) return '';
  return `₹${Number.isInteger(amount) ? amount : amount.toFixed(2)}`;
}

/** One key per reviewed cart: re-clicking Place order replays the stored result instead of ordering twice. */
export function newIdempotencyKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}
