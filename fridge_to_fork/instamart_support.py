"""
"Report a problem" for Instamart (POST mcp.swiggy.com/im), via Swiggy's report_error tool.

From the reference docs: report_error(tool, errorMessage, domain?, flowDescription?, toolContext?, userNotes?)
returns data.mailto (a pre-filled mailto: link) and data.summary {subject, body}. Nothing is sent by the tool:
the user opens the email and sends it to the Swiggy MCP team themselves. Identity and token come from the
authenticated session, never from arguments. Docs: "always include toolContext with the specific identifiers
from the failed tool call".
"""

from . import instamart
from .instamart import InstamartError, _call

# Identifier keys the docs list for toolContext that this app has. Anything else is rejected upstream by the
# request model, so free-form data (names, phone numbers, addresses) can never ride along.
CONTEXT_KEYS = ("orderId", "addressId", "spinId", "couponCode", "query", "cartId", "paymentMethod")


async def report_problem(
    token: str, tool: str, error_message: str, flow: str | None, context: dict[str, str], notes: str | None
) -> dict:
    args: dict = {"tool": tool, "errorMessage": error_message, "domain": "im"}
    if flow:
        args["flowDescription"] = flow
    if context:
        args["toolContext"] = context
    if notes:
        args["userNotes"] = notes
    async with instamart._session(token) as session:
        data = await _call(session, "report_error", **args)
    mailto = data.get("mailto")
    if not (isinstance(mailto, str) and mailto.lower().startswith("mailto:")):
        # Only ever hand the browser a real mailto: link, whatever the tool returned.
        mailto = None
    summary = data.get("summary") or {}
    if not mailto and not summary.get("body"):
        raise InstamartError("tool_error", "Swiggy didn't return a report to send.")
    return {"report": {"mailto": mailto, "subject": summary.get("subject"), "body": summary.get("body")}}
