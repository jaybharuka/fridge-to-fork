// Mirrors fridge_to_fork/features.py.
//
// FOOD_ORDERING_ENABLED: the deterministic Food flow (FoodOrderSheet -> /api/food/*). Off until it has been walked
// through on a real account; the "Order the dish" card is disabled and the backend refuses every /api/food route.
//
// The old Gemini-agent path for ordering the dish (POST /api/order action=order_dish) is retired regardless of this
// flag: it invented order IDs and misreported success. useScanStream.placeOrder and the backend both refuse it.
export const FOOD_ORDERING_ENABLED = false;

export const FOOD_UNAVAILABLE_MESSAGE = 'Ordering the finished dish is temporarily unavailable. Order the ingredients instead.';
