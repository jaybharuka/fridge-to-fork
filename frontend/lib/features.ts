// Mirrors fridge_to_fork/features.py.
//
// FOOD_ORDERING_ENABLED: the deterministic Food flow (FoodOrderSheet -> /api/food/*). Switched ON for the first real
// order (a plain dish, cash on delivery); it is also the kill switch: set to false, the "Order the dish" card is
// disabled and the backend refuses every /api/food route.
//
// The old Gemini-agent path for ordering the dish (POST /api/order action=order_dish) is deleted, not switched off:
// it invented order IDs and misreported success. The backend only answers a stale page that still calls it.
export const FOOD_ORDERING_ENABLED = true;

export const FOOD_UNAVAILABLE_MESSAGE = 'Ordering the finished dish is temporarily unavailable. Order the ingredients instead.';
