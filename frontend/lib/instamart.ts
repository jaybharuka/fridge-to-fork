// Client for the staged Instamart flow (backend: fridge_to_fork/instamart_routes.py).
// search -> cart (+review) -> checkout. Real products and a real cart are shown
// before the user's separate, explicit "Place order" action.

import { authHeaders, markDisconnected } from './auth';
import { BACKEND_URL } from './backend';

export interface InstamartAddress { id: string; label: string; addressLine: string; category?: string | null }

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
export interface CouponList {
  available: boolean;
  items: Coupon[];
  /** Food: how Swiggy filtered the offers (e.g. cash-on-delivery compatible). */
  filter?: string | null;
}

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
  constructor(public code: string, message: string, public status: number, public tool: string | null = null) {
    super(message);
  }
}

/** POST to `/api/<prefix>/<path>` with the caller's auth. Shared by the Instamart and Food clients (same envelope and errors). */
export async function postJson<T>(prefix: string, path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BACKEND_URL}/api/${prefix}/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(body),
    credentials: 'include',
  });
  let data: { ok?: boolean; error?: { code?: string; message?: string; tool?: string } } | null = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body — handled below */
  }
  if (!data?.ok) {
    const code = data?.error?.code ?? 'unexpected_response';
    if (code === 'auth_required') markDisconnected();
    throw new InstamartApiError(code, data?.error?.message ?? 'Something went wrong. Please try again.', res.status, data?.error?.tool ?? null);
  }
  return data as T;
}

const post = <T>(path: string, body: unknown) => postJson<T>('instamart', path, body);

export const instamartSearch = (items: string[], addressId: string | null = null) =>
  post<{ address: InstamartAddress; results: InstamartSearchResult[] }>('search', { items, ...(addressId ? { address_id: addressId } : {}) });

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

// ---- Order history, live status, details (backend: fridge_to_fork/instamart_orders.py) ----

export interface OrderSummary {
  orderId: string;
  status: string;
  createdAt: string | null;
  estimatedDeliveryTime: string | null;
  itemCount: number | null;
  totalAmount: number | null;
  paymentMethod: string | null;
  items: { name: string; quantity: number | null }[];
  deliveryAddress: string | null;
  /** Recovered by matching the order's address text to a saved address; null if it can't be identified. */
  addressId: string | null;
}

export interface DeliveryStatus {
  statusText: string | null;
  etaText: string | null;
  minutesLeft: number | null;
  delivered: boolean;
  cancelled: boolean;
  /** Swiggy: stop polling once delivered or cancelled. */
  terminal: boolean;
  pollIntervalSec: number;
}

export interface TrackingInfo {
  title: string | null;
  subtitle: string | null;
  statusMessage: string | null;
  subStatusMessage: string | null;
  etaMinutes: number | null;
  etaText: string | null;
  store: string | null;
  paymentMessage: string | null;
  riderLocation: { lat: number; lng: number } | null;
  storeLocation: { lat: number; lng: number } | null;
  pollIntervalSec: number;
}

export interface OrderStatusResult {
  delivery: DeliveryStatus | null;
  /** track_order data; only present when real delivery coordinates were supplied (captured at address creation). */
  tracking: TrackingInfo | null;
  notes: string[];
}

export type OrderDetails =
  | {
      available: true;
      orderId: string | null;
      status: string | null;
      totalBill: number | null;
      hasRefunds: boolean;
      items: { name: string; quantity: number | null; finalPrice: number | null; removed: boolean }[];
      bill: { lineItems: { name: string | null; amount: string | null }[]; grandTotal: string | null };
    }
  | { available: false; message: string };

export const instamartOrders = (activeOnly = false) =>
  post<{ orders: OrderSummary[]; hasMore: boolean }>('orders', { active_only: activeOnly });

export const instamartOrderStatus = (orderId: string, addressId: string | null, coords: { lat: number; lng: number } | null = null) =>
  post<OrderStatusResult>('order-status', {
    order_id: orderId,
    ...(addressId ? { address_id: addressId } : {}),
    ...(coords ? { lat: coords.lat, lng: coords.lng } : {}),
  });

export const instamartOrderDetails = (orderId: string) =>
  post<{ details: OrderDetails }>('order-details', { order_id: orderId });

/** Delivered / cancelled orders are history: no live polling. ("Out for delivery" is still live.) */
export const isPastOrder = (status: string): boolean => /\bdelivered\b|cancel|reject|fail/i.test(status);

// ---- Saved addresses and "your usual items" (backend: fridge_to_fork/instamart_addresses.py) ----

export interface AddressList { addresses: InstamartAddress[]; defaultId: string | null }

/** create_address fields. Swiggy requires the account holder's name and phone. */
export interface NewAddress {
  full_address: string;
  address_line: string;
  address_line2: string;
  city: string;
  postal_code: string;
  address_category: 'HOME' | 'WORK' | 'OFFICE' | 'FRIENDS_AND_FAMILY' | 'OTHER';
  user_name: string;
  user_phone: string;
  locality?: string;
  address_tag?: string;
  /** Real coordinates only (device location the user chose to share); both or neither. */
  latitude?: number;
  longitude?: number;
}

export const instamartAddresses = () => post<AddressList>('addresses', {});

export const instamartCreateAddress = (fields: NewAddress) => post<AddressList & { addressId: string }>('address', fields);

export const instamartDeleteAddress = (addressId: string) => post<AddressList>('address-delete', { address_id: addressId });

export const instamartGoToItems = (addressId: string) =>
  post<{ results: InstamartSearchResult[] }>('go-to-items', { address_id: addressId });

// ---- Report a problem (backend: fridge_to_fork/instamart_support.py -> Swiggy's report_error) ----

/** Identifiers report_error accepts as toolContext. Names and phone numbers are deliberately not among them. */
export type ReportContext = Partial<
  Record<'orderId' | 'addressId' | 'spinId' | 'couponCode' | 'query' | 'cartId' | 'paymentMethod' | 'restaurantId' | 'menu_item_id', string>
>;

export interface ReportInput {
  /** The Swiggy tool that failed (e.g. "checkout" for Instamart, "place_food_order" for Food). */
  tool: string;
  errorMessage: string;
  flow?: string;
  context?: ReportContext;
  notes?: string;
}

/** `mailto` is Swiggy's pre-filled email to their MCP team; the user sends it themselves. */
export interface ProblemReport { mailto: string | null; subject: string | null; body: string | null }

export const instamartReport = (r: ReportInput) =>
  post<{ report: ProblemReport }>('report', {
    tool: r.tool,
    error_message: r.errorMessage,
    ...(r.flow ? { flow: r.flow } : {}),
    ...(r.context && Object.keys(r.context).length ? { context: r.context } : {}),
    ...(r.notes ? { notes: r.notes } : {}),
  });

/** Plain-text version of a report, for when Swiggy can't prepare one: nothing personal, just what failed. */
export function localReportText(r: ReportInput, product = 'Instamart'): string {
  const lines = [`Problem with ${product} in Fridge to Fork`, `Tool: ${r.tool}`, `Error: ${r.errorMessage}`];
  if (r.flow) lines.push(`What I was doing: ${r.flow}`);
  for (const [key, value] of Object.entries(r.context ?? {})) lines.push(`${key}: ${value}`);
  if (r.notes) lines.push(`Notes: ${r.notes}`);
  lines.push(`Time: ${new Date().toISOString()}`);
  return lines.join('\n');
}