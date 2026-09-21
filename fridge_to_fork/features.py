"""Feature switches. Deliberately plain constants (no env override): turning something on or off is a code change."""

# The deterministic Food flow (fridge_to_fork/food.py, routes under /api/food): search -> cart -> review -> checkout ->
# track. SWITCHED ON (2026-09-21) as a deliberate decision, not because it was proven end to end: no real Food order had
# been placed on this integration when it went live. Verified on a real account: search, cart, review, coupons, the
# 1000-rupee cap, per-restaurant/per-amount COD, real Swiggy error messages. Known open question: whether a coupon from
# the COD-filtered list still holds when the order is paid by UPI (only a real checkout shows it). Food carts built through
# the API also never appear in the Swiggy app (the environment is production: real orders, real charges).
# Turning it off is the kill switch: set this to False and deploy. While False, every /api/food route refuses (before it
# looks at auth) and the frontend disables the "Order the dish" card. Mirrored in frontend/lib/features.ts;
# tests/test_food_disabled.py pins the value, so flipping it is always a visible change there too.
FOOD_ORDERING_ENABLED = True

# The old Gemini-agent path for ordering the dish no longer exists: it invented order IDs, read success out of free
# text and had no confirmation step, and its code has been deleted. POST /api/order action=order_dish only tells a
# stale page to reload.
FOOD_UNAVAILABLE_MESSAGE = "Ordering the finished dish is temporarily unavailable. Order the ingredients instead."
FOOD_MOVED_MESSAGE = "Ordering the finished dish has moved. Please refresh the page and try again."
