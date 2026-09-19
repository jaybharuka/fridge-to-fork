"""Feature switches. Deliberately plain constants (no env override): turning something back on is a code change."""

# Ordering a finished dish from Swiggy Food goes through a Gemini agent that can invent order IDs, read
# success/failure out of free text, and place an order with no explicit confirmation step. Off until it is
# rebuilt like the Instamart flow (fridge_to_fork/instamart.py). The code stays; nothing reaches it.
FOOD_ORDERING_ENABLED = False

FOOD_UNAVAILABLE_MESSAGE = "Ordering the finished dish is temporarily unavailable. Order the ingredients instead."
