// Mirrors fridge_to_fork/features.py.
//
// FOOD_ORDERING_ENABLED: the deterministic Food flow (FoodOrderSheet -> /api/food/*). SWITCHED OFF until it is
// established that place_food_order places a real, charged order against the connected account (a cart built through
// the API did not appear in the Swiggy app's cart, and the docs don't explain why). Turning it on is a deliberate
// step, not part of a deploy. While off, the "Order the dish" card is disabled and the backend refuses every
// /api/food route (it is also the kill switch).
//
// The old Gemini-agent path for ordering the dish (POST /api/order action=order_dish) is deleted, not switched off:
// it invented order IDs and misreported success. The backend only answers a stale page that still calls it.
export const FOOD_ORDERING_ENABLED = false;

export const FOOD_UNAVAILABLE_MESSAGE = 'Ordering the finished dish is temporarily unavailable. Order the ingredients instead.';
