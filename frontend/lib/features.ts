// Mirrors fridge_to_fork/features.py. Ordering a finished dish from Swiggy Food is off: the agent behind it
// can invent order IDs and misreport success, and has no explicit confirmation step. The backend refuses it too.
export const FOOD_ORDERING_ENABLED = false;

export const FOOD_UNAVAILABLE_MESSAGE = 'Ordering the finished dish is temporarily unavailable. Order the ingredients instead.';
