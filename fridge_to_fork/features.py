"""Feature switches. Deliberately plain constants (no env override): turning something back on is a code change."""

# The deterministic Food flow (fridge_to_fork/food.py, routes under /api/food): search -> cart -> review ->
# checkout. Off until it has been walked through on a real account; nothing in it runs while this is False.
FOOD_ORDERING_ENABLED = False

# The old Gemini-agent path for "order the dish" (POST /api/order action=order_dish, swiggy_agent.py). It invents
# order IDs, reads success out of free text and has no confirmation step, so it stays off no matter what the flag
# above says. Kept only until the new flow is live, then deleted; never turn this on.
FOOD_AGENT_ENABLED = False

FOOD_UNAVAILABLE_MESSAGE = "Ordering the finished dish is temporarily unavailable. Order the ingredients instead."
