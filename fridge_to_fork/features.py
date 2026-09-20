"""Feature switches. Deliberately plain constants (no env override): turning something on or off is a code change."""

# The deterministic Food flow (fridge_to_fork/food.py, routes under /api/food): search -> cart -> review -> checkout ->
# track. Shipped OFF: it has never run against a real Swiggy account, and switching it on is a deliberate, separate step
# (a real order), never something that rides along with a deploy. It is also the kill switch: set to False, every
# /api/food route refuses (before it looks at auth) and the frontend disables the "Order the dish" card. Mirrored in
# frontend/lib/features.ts; tests/test_food_disabled.py pins the value so flipping it is a visible change.
FOOD_ORDERING_ENABLED = False

# The old Gemini-agent path for ordering the dish no longer exists: it invented order IDs, read success out of free
# text and had no confirmation step, and its code has been deleted. POST /api/order action=order_dish only tells a
# stale page to reload.
FOOD_UNAVAILABLE_MESSAGE = "Ordering the finished dish is temporarily unavailable. Order the ingredients instead."
FOOD_MOVED_MESSAGE = "Ordering the finished dish has moved. Please refresh the page and try again."
