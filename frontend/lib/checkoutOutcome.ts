// When a checkout call fails, did the order possibly happen? Pure (no React) so it is unit tested in plain Node: see
// checkoutOutcome.test.ts.
//
// The "unknown" screen never offers a retry or a way back to the cart (the order may exist; a second one would be charged twice).
// A plain "failed" screen does. Getting this wrong in the "failed" direction is how a user could be told "Order not placed, try
// again" for an order that went through.

/** Error codes that mean "no usable answer to the checkout request": the browser got no response, a garbled one, or the server
 *  could not reach Swiggy. For the first two the request may have been processed. The backend now turns an unreachable Swiggy
 *  after the request was sent into an "unknown" outcome itself (and says "checkout_not_sent" when nothing left the server), so
 *  `upstream_unavailable` here only comes from an older backend; treating it as ambiguous is the safe reading either way. */
const AMBIGUOUS = new Set(['network', 'unexpected_response', 'upstream_unavailable']);

export const isAmbiguousCheckoutError = (code: string): boolean => AMBIGUOUS.has(code);
