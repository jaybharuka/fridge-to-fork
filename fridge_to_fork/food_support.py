"""
"Report a problem" for Food (POST mcp.swiggy.com/food), via Swiggy's report_error tool: the same flow, the same
argument names and the same PII rules as Instamart's (see instamart_support.py), with domain "food".
"""

from . import food
from .swiggy_common import _prepare_report

# Identifier keys the Food docs list for toolContext that this app has (orderId, restaurantId, addressId, menu_item_id,
# couponCode, query, cartId, paymentMethod). slotId, guestCount, itemId and spinId belong to other servers. Anything
# else is rejected by the request model, so names, phone numbers and addresses can never ride along.
CONTEXT_KEYS = ("orderId", "restaurantId", "addressId", "menu_item_id", "couponCode", "query", "cartId", "paymentMethod")


async def report_problem(
    token: str, tool: str, error_message: str, flow: str | None, context: dict[str, str], notes: str | None
) -> dict:
    async with food._session(token) as session:
        return await _prepare_report(session, domain="food", tool=tool, error_message=error_message, flow=flow, context=context, notes=notes)
