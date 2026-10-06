/**
 * The error message of a "Report a problem" raised from an order's screen: the order id and nothing else. Swiggy's own
 * order status is free text ("Order delivered on 29 Sep 2026, 11:01 AM by <rider's name>") and can name a person, and a
 * report must hold identifiers only, so it is never put in here. Which tool failed (get_order_details for a past order,
 * get_delivery_status for a live one) already says what state the order was in.
 */
export const orderProblemMessage = (orderId: string): string => `Problem with order ${orderId}`;
