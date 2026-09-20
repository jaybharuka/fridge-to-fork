// Client for the staged Food flow (backend: fridge_to_fork/food_routes.py).
// search -> (item options) -> cart + review -> checkout. Real dishes from real restaurants and the real cart Swiggy
// will bill are shown before the user's separate, explicit "Place order" action.

import { InstamartApiError, postJson, type AppliedCoupon, type CouponList, type DeliveryStatus, type InstamartAddress, type PaymentOption } from './instamart';

export { formatInr, newIdempotencyKey } from './instamart';
export type { AppliedCoupon, Coupon, CouponList, DeliveryStatus, InstamartAddress, PaymentOption } from './instamart';

/** Same error type and envelope as Instamart (`ok: false, error: {code, message}`). */
export const FoodApiError = InstamartApiError;

export interface FoodRestaurant {
  id: string;
  name: string;
  area: string | null;
  etaMinutes: number | null;
  etaRange: string | null;
  distanceKm: number | null;
  rating: number | null;
  costForTwo: string | null;
  offer: string | null;
  /** null = search_restaurants didn't list it, so open/closed isn't known yet (the cart step re-checks). */
  open: boolean | null;
}

export interface VariantOption { id: string; name: string; price: number | null; default: boolean; available: boolean }
export interface VariantGroup { groupId: string; name: string; options: VariantOption[] }
export interface AddonChoice { id: string; name: string; price: number | null }
export interface AddonGroup { groupId: string; name: string; min: number; max: number | null; choices: AddonChoice[] }

export interface FoodCustomization {
  /** Which cart field Swiggy expects: search_menu returns `variantsV2` OR `variations`, never both. */
  format: 'variantsV2' | 'variations' | null;
  variantGroups: VariantGroup[];
  addonGroups: AddonGroup[];
  /** false = the item needs options we can't identify, so it is shown but can't be ordered here. */
  supported: boolean;
}

export interface FoodResult {
  menuItemId: string;
  name: string;
  price: number | null;
  isVeg: boolean | null;
  imageUrl: string | null;
  rating: string | number | null;
  ratingCount: string | null;
  bestseller: boolean;
  available: boolean;
  restaurant: FoodRestaurant;
  customization: FoodCustomization;
}

export interface FoodCartLine {
  menuItemId: string;
  name: string;
  quantity: number;
  lineTotal: number | null;
  imageUrl: string | null;
  isVeg: boolean | null;
  available: boolean;
  variants: string[];
  addons: string[];
}

export interface FoodReview {
  address: { id: string; text: string; label: string | null };
  restaurant: { id: string | null; name: string | null; area: string | null; deliverySubtitle: string | null };
  items: FoodCartLine[];
  lineItems: { label: string; value: number | null; strikeoff?: number | null }[];
  /** The payable total as a number: echoed back at checkout to prove what the user saw. */
  total: number | null;
  warning: string | null;
  blockers: string[];
  canCheckout: boolean;
  payment: { options: PaymentOption[]; amount: string | null };
  coupon: { code: string | null; discount: number } | null;
}

/** A started UPI payment: open `bridgeUrl` (scan-or-tap page) while we poll. Food confirms with the echoed
 *  addressId/cartId/lat/lng from place_food_order (never paasId), so they are handed back on every poll. */
export interface FoodPendingPayment {
  orderId: string;
  paasId: string;
  bridgeUrl: string;
  pollIntervalMs: number;
  maxPollMs: number;
  addressId: string;
  cartId: string | null;
  lat: number | null;
  lng: number | null;
}

export interface FoodOutcome {
  status: 'placed' | 'failed' | 'unknown' | 'pending_payment' | 'partial';
  orderIds: string[];
  message: string;
  verified: boolean;
  total: number | string | null;
  payment?: FoodPendingPayment | null;
  detail?: { restaurant: string | null; eta: string | null; items: string[] } | null;
  /** Set when Swiggy placed the order at a different total than the one reviewed. */
  notice?: string;
}

/** The cart request: every id exactly as Swiggy returned it. */
export interface FoodSelection {
  restaurant_id: string;
  restaurant_name: string | null;
  menu_item_id: string;
  quantity: number;
  format: 'variants' | 'variantsV2' | null;
  variants: { group_id: string; variation_id: string }[];
  addons: { group_id: string; addon_id: string; quantity: number }[];
}

const post = <T>(path: string, body: unknown) => postJson<T>('food', path, body);

export const foodSearch = (dish: string, addressId: string | null = null) =>
  post<{ address: InstamartAddress; dish: string; results: FoodResult[]; hasMore: boolean }>('search', {
    dish,
    ...(addressId ? { address_id: addressId } : {}),
  });

export const foodCart = (addressId: string, selection: FoodSelection) =>
  post<{ review: FoodReview; adjustments: string[]; coupons: CouponList }>('cart', { address_id: addressId, selection });

export const foodApplyCoupon = (addressId: string, couponCode: string) =>
  post<{ review: FoodReview; coupon: AppliedCoupon; coupons: CouponList }>('coupon', { address_id: addressId, coupon_code: couponCode });

export const foodPaymentStatus = (payment: FoodPendingPayment, final: boolean) =>
  post<{ order: FoodOutcome }>('payment-status', {
    order_id: payment.orderId,
    paas_id: payment.paasId,
    address_id: payment.addressId,
    ...(payment.cartId ? { cart_id: payment.cartId } : {}),
    ...(payment.lat !== null ? { lat: payment.lat } : {}),
    ...(payment.lng !== null ? { lng: payment.lng } : {}),
    final,
  });

export const foodCheckout = (addressId: string, expectedTotal: number, idempotencyKey: string, paymentKey: string) =>
  post<{ order: FoodOutcome }>('checkout', {
    address_id: addressId,
    expected_total: expectedTotal,
    idempotency_key: idempotencyKey,
    payment_key: paymentKey,
  });

// ---- Order history, live status, details (backend: fridge_to_fork/food_orders.py) ----

export interface FoodOrderRow {
  orderId: string;
  restaurant: string;
  area: string | null;
  status: string;
  deliveryStatus: string | null;
  /** Display strings exactly as Swiggy formats them. */
  total: string | null;
  items: string | null;
  orderedTime: string | null;
  /** Swiggy's own isActiveOrder flag (not guessed from the status text). */
  active: boolean;
}

export interface FoodTracking { title: string | null; subtitle: string | null; etaText: string | null; status: string | null; progress: number | null }

export interface FoodOrderStatus { delivery: DeliveryStatus | null; tracking: FoodTracking | null; notes: string[] }

export type FoodOrderDetails =
  | {
      available: true;
      orderId: string;
      status: string | null;
      restaurant: { name: string | null; area: string | null };
      items: { name: string; quantity: number | string | null; price: number | null; options: string[] }[];
      charges: { label: string; value: string }[];
      itemTotal: number | null;
      delivery: number | null;
      tax: number | null;
      discount: number | null;
      coupon: { code: string; discount: number | null } | null;
      total: number | null;
      paymentMethod: string | null;
      orderTime: string | null;
      cancellable: boolean;
      /** There is no cancel tool: Swiggy says to call customer care. */
      cancelHelp: string | null;
    }
  | { available: false; message: string };

/** get_food_orders needs an address (the docs don't say whether it scopes the list): the one used comes back with it. */
export const foodOrders = (addressId: string | null, activeOnly = false) =>
  post<{ address: InstamartAddress; orders: FoodOrderRow[] }>('orders', { active_only: activeOnly, ...(addressId ? { address_id: addressId } : {}) });

export const foodOrderStatus = (orderId: string) => post<FoodOrderStatus>('order-status', { order_id: orderId });

export const foodOrderDetails = (orderId: string) => post<{ details: FoodOrderDetails }>('order-details', { order_id: orderId });
