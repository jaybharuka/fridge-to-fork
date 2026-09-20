"""
"Report a problem" for Instamart (POST mcp.swiggy.com/im), via Swiggy's report_error tool (see
swiggy_common._prepare_report, shared with Food). Docs: "always include toolContext with the specific
identifiers from the failed tool call".
"""

from . import instamart
from .swiggy_common import _prepare_report

# Identifier keys the docs list for toolContext that this app has. Anything else is rejected upstream by the
# request model, so free-form data (names, phone numbers, addresses) can never ride along.
CONTEXT_KEYS = ("orderId", "addressId", "spinId", "couponCode", "query", "cartId", "paymentMethod")


async def report_problem(
    token: str, tool: str, error_message: str, flow: str | None, context: dict[str, str], notes: str | None
) -> dict:
    async with instamart._session(token) as session:
        return await _prepare_report(session, domain="im", tool=tool, error_message=error_message, flow=flow, context=context, notes=notes)
