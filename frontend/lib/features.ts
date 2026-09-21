// Mirrors fridge_to_fork/features.py.
//
// FOOD_ORDERING_ENABLED: the deterministic Food flow (FoodOrderSheet -> /api/food/*). SWITCHED ON (2026-09-21) as a
// deliberate decision, before any real Food order had been placed end to end; see the note in features.py for what was
// and was not verified. It is also the kill switch: set it to false (and in features.py) and deploy, and the "Order the
// dish" card is disabled and the backend refuses every /api/food route.
//
// The old Gemini-agent path for ordering the dish (POST /api/order action=order_dish) is deleted, not switched off:
// it invented order IDs and misreported success. The backend only answers a stale page that still calls it.
export const FOOD_ORDERING_ENABLED = true;

export const FOOD_UNAVAILABLE_MESSAGE = 'Ordering the finished dish is temporarily unavailable. Order the ingredients instead.';
