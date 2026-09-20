// Client for the staged Food flow (backend: fridge_to_fork/food_routes.py).
// search -> (item options) -> cart + review -> checkout. Real dishes from real restaurants and the real cart Swiggy
// will bill are shown before the user's separate, explicit "Place order" action.

import { InstamartApiError, postJson, type InstamartAddress, type PaymentOption } from './instamart';

export { formatInr, newIdempotencyKey } from './instamart';
export type { InstamartAddress, PaymentOption } from './instamart';

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

export interface FoodOutcome {
  status: 'placed' | 'failed' | 'unknown' | 'pending_payment' | 'partial';
  orderIds: string[];
  message: string;
  verified: boolean;
  total: number | string | null;
  detail: { restaurant: string | null; eta: string | null; items: string[] } | null;
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
  post<{ review: FoodReview; adjustments: string[] }>('cart', { address_id: addressId, selection });

export const foodCheckout = (addressId: string, expectedTotal: number, idempotencyKey: string, paymentKey: string) =>
  post<{ order: FoodOutcome }>('checkout', {
    address_id: addressId,
    expected_total: expectedTotal,
    idempotency_key: idempotencyKey,
    payment_key: paymentKey,
  });
