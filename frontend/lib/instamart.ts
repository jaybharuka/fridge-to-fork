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

/** A way to pay that Swiggy currently offers for this cart (from get_payment_options). */
export interface PaymentOption {
  /** Stable id sent back at checkout, where the server re-validates it against Swiggy. */
  key: string;
  type: 'cod' | 'upi_qr' | 'upi_intent';
  label: string;
}

export interface Coupon {
  code: string;
  title: string;
  description: string | null;
  applicable: boolean;
  /** Why it can't be applied (or extra detail), as Swiggy worded it. */
  message: string | null;
  terms: string[];
}

/** `available: false` means Swiggy doesn't offer coupons on this account (not rolled out to everyone). */
export interface CouponList { available: boolean; items: Coupon[] }

export interface AppliedCoupon { code: string; title: string; savings: number | null }

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
  payment: { options: PaymentOption[]; amount: string | null };
}

/** A started UPI payment: open `bridgeUrl` (scan-or-tap page) while we poll payment-status. */
export interface PendingPayment {
  orderId: string;
  paasId: string;
  bridgeUrl: string;
  pollIntervalMs: number;
  maxPollMs: number;
}

export interface InstamartOutcome {
  status: 'placed' | 'partial' | 'failed' | 'unknown' | 'pending_payment';
  orderIds: string[];
  message: string;
  verified: boolean;
  total: string | null;
  payment: PendingPayment | null;
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
  post<{ review: InstamartReview; adjustments: string[]; coupons: CouponList }>('cart', { address_id: addressId, selections });

export const instamartApplyCoupon = (addressId: string, couponCode: string) =>
  post<{ review: InstamartReview; coupon: AppliedCoupon; coupons: CouponList }>('coupon', { address_id: addressId, coupon_code: couponCode });

export const instamartCheckout = (addressId: string, expectedTotal: string, idempotencyKey: string, paymentKey: string) =>
  post<{ order: InstamartOutcome }>('checkout', {
    address_id: addressId,
    expected_total: expectedTotal,
    idempotency_key: idempotencyKey,
    payment_key: paymentKey,
  });

export const instamartPaymentStatus = (orderId: string, paasId: string, final: boolean) =>
  post<{ order: InstamartOutcome }>('payment-status', { order_id: orderId, paas_id: paasId, final });

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
