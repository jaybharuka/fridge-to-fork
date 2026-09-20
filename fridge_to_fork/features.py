"""Feature switches. Deliberately plain constants (no env override): turning something on or off is a code change."""

# The deterministic Food flow (fridge_to_fork/food.py, routes under /api/food): search -> cart -> review -> checkout ->
# track. SWITCHED OFF after the first real-account cart test: a cart built with update_food_cart did not appear in the
# Swiggy app's cart, and the docs don't say whether the MCP cart is the account's consumer cart or how `mcp.swiggy.com`
# relates to real charging. Until it is established that place_food_order places a real, charged order against this
# account (see the environment questions in the docs: production vs mcp-staging seeded data), the flow stays off.
# Turning it back on is a deliberate step, never something that rides along with a deploy. It is also the kill
# switch: while False, every /api/food route refuses (before it looks at auth) and the frontend disables the "Order
# the dish" card. Mirrored in frontend/lib/features.ts; tests/test_food_disabled.py pins the value.
FOOD_ORDERING_ENABLED = False

# The old Gemini-agent path for ordering the dish no longer exists: it invented order IDs, read success out of free
# text and had no confirmation step, and its code has been deleted. POST /api/order action=order_dish only tells a
# stale page to reload.
FOOD_UNAVAILABLE_MESSAGE = "Ordering the finished dish is temporarily unavailable. Order the ingredients instead."
FOOD_MOVED_MESSAGE = "Ordering the finished dish has moved. Please refresh the page and try again."
