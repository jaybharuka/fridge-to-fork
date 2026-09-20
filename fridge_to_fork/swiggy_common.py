"""
What Swiggy's Instamart (/im) and Food (/food) MCP servers have in common, so the two integrations cannot drift apart:

  * transport and the `{success, data | error}` envelope (domain failures arrive as HTTP 200 + success:false)
  * saved addresses (get_addresses is one shared tool) and the compound-address-id rule
  * payment choices: get_payment_options is one shared tool, so the classification of its methods is too
  * the checkout guards: a replay cache keyed by idempotency key and one in-flight order per account

Every rule here was confirmed against a real account or Swiggy's reference docs; see the comments.
"""

import hashlib
import json
import logging
import re
import time
from contextlib import asynccontextmanager

import httpx
from fastapi.responses import JSONResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

log = logging.getLogger("uvicorn.error")

# Cash is normally taken from get_payment_options.cod.id (echoed exactly); this is only the fallback if it is blank.
COD_FALLBACK_ID = "Cash"


class SwiggyError(Exception):
    """`code` is stable for the frontend; `message` is safe to show the user."""

    def __init__(self, code: str, message: str, status: int = 200, tool: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.tool = tool  # the Swiggy tool that refused, when known (used to file a report)


def error_response(exc: SwiggyError) -> JSONResponse:
    error = {"code": exc.code, "message": exc.message, **({"tool": exc.tool} if exc.tool else {})}
    return JSONResponse({"ok": False, "error": error}, status_code=exc.status)


# ---------------------------------------------------------------------------
# Transport + envelope handling
# ---------------------------------------------------------------------------

_AUTH_RE = re.compile(r"\b401\b|unauthori[sz]ed|unauthenticated|token[_ ]expired|invalid_token|-32001", re.I)
_DOMAIN_CODES = {
    "MIN_ORDER_NOT_MET": "min_order_not_met",
    "ADDRESS_NOT_SERVICEABLE": "unserviceable",
    "ITEM_OUT_OF_STOCK": "out_of_stock",
    "CART_EXPIRED": "cart_expired",
}


def _leaves(exc: BaseException):
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _leaves(inner)
    else:
        yield exc


def _translate(exc: Exception) -> SwiggyError:
    if isinstance(exc, SwiggyError):
        return exc
    leaves = list(_leaves(exc))
    for leaf in leaves:
        if isinstance(leaf, httpx.HTTPStatusError) and leaf.response.status_code == 401:
            return SwiggyError("auth_required", "Connect your Swiggy account to continue.", 401)
        if _AUTH_RE.search(str(leaf)):
            return SwiggyError("auth_required", "Connect your Swiggy account to continue.", 401)
    log.error("[SWIGGY] transport failure: %s", "; ".join(f"{type(x).__name__}: {x}"[:200] for x in leaves))
    return SwiggyError("upstream_unavailable", "Couldn't reach Swiggy. Please try again.", 502)


@asynccontextmanager
async def open_session(url: str, token: str):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    except Exception as exc:
        raise _translate(exc) from exc


def _payload(result) -> dict:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        inner = structured.get("result")
        return inner if set(structured) == {"result"} and isinstance(inner, dict) else structured
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            return {"success": not getattr(result, "isError", False), "message": text}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _tool_error(payload: dict) -> SwiggyError:
    err = payload.get("error")
    message = (err.get("message") if isinstance(err, dict) else err) or payload.get("message") or "Swiggy rejected the request."
    message = str(message)
    if _AUTH_RE.search(message):
        return SwiggyError("auth_required", "Connect your Swiggy account to continue.", 401)
    for marker, code in _DOMAIN_CODES.items():
        if marker in message:
            return SwiggyError(code, message)
    return SwiggyError("tool_error", message)


async def _call(session: ClientSession, name: str, **arguments) -> dict:
    """One MCP tool call. Returns the envelope's `data`; raises on isError OR success:false."""
    try:
        result = await session.call_tool(name, arguments)
    except McpError as exc:  # protocol-level refusal, e.g. a tool that isn't rolled out for this account
        raise SwiggyError("tool_error", f"{name}: {exc}", tool=name) from exc
    payload = _payload(result)
    if getattr(result, "isError", False) or payload.get("success") is False:
        error = _tool_error(payload)
        error.tool = name
        raise error
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
        return float(match.group()) if match else None
    return None


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------

def _public_address(a: dict) -> dict:
    """The address as the frontend sees it. The phone number never leaves the server."""
    return {
        "id": a["id"],
        "label": a.get("addressTag") or (a.get("addressCategory") or "").replace("_", " ").title() or "Saved address",
        "addressLine": a.get("addressLine", ""),
        "category": a.get("addressCategory"),
    }


def _pick_address(addresses: list[dict]) -> dict:
    """Recipe: pick "Home" if present, else the first saved address."""
    def is_home(a: dict) -> bool:
        return "home" in f"{a.get('addressTag', '')} {a.get('addressCategory', '')}".lower()

    return _public_address(next((a for a in addresses if is_home(a)), addresses[0]))


MAX_ADDRESS_PAGES = 3  # get_addresses pages by 10; more than 30 saved addresses is not a real case


async def _saved_addresses(session: ClientSession) -> list[dict]:
    """Raw saved addresses (with phone numbers, server-side only), following get_addresses pagination."""
    found: list[dict] = []
    for page in range(1, MAX_ADDRESS_PAGES + 1):
        data = await _call(session, "get_addresses", page=page, pageSize=10)
        found += [a for a in data.get("addresses") or [] if a.get("id")]
        if not (data.get("pagination") or {}).get("hasMore"):
            break
    return found


async def _resolve_address(session: ClientSession, address_id: str | None) -> dict:
    """The user's chosen address, verified against their saved list, else the Home/first default."""
    addresses = await _saved_addresses(session)
    if not addresses:
        raise SwiggyError("no_address", "Add a delivery address first, then try again.")
    if address_id is None:
        return _pick_address(addresses)
    match = next((a for a in addresses if a["id"] == address_id), None)
    if match is None:
        raise SwiggyError("address_not_found", "That address isn't saved on your Swiggy account anymore. Choose another.")
    return _public_address(match)


_COMPOUND_SEP = "__"


def _same_id(a, b) -> bool:
    """Ids compare as strings: Swiggy documents them as strings, but nothing guarantees one tool doesn't
    hand back 123 where another hands back "123", and a type difference is not an address change."""
    return a is not None and b is not None and str(a).strip() == str(b).strip()


def _same_address_id(full_id, other_id) -> bool:
    """Is `other_id` the same Swiggy address as `full_id`?

    Confirmed on a real account: get_addresses returns compound ids ("<base>__<token>") while get_cart's
    selectedAddressDetails.id reports only the base. So `other_id` matches when it is identical, or when it
    is exactly the part of `full_id` before its FIRST "__". Deliberately narrow: not an arbitrary prefix or
    substring, not the reverse direction, not a different token on the same base. Anything else is a real
    mismatch and still blocks.
    """
    if _same_id(full_id, other_id):
        return True
    if full_id is None or other_id is None:
        return False
    base, sep, _ = str(full_id).strip().partition(_COMPOUND_SEP)
    other = str(other_id).strip()
    return bool(sep and other and base == other)


# ---------------------------------------------------------------------------
# Payment choices (get_payment_options is one tool shared by every Swiggy server)
# ---------------------------------------------------------------------------

def _view_methods(view: dict) -> list[dict]:
    """The payment methods a PaymentOptionsView lists: allMethods, else the platform groups' methods."""
    return view.get("allMethods") or [
        m for group in (view.get("platforms") or {}).values() for m in (group or {}).get("methods") or []
    ]


# Friendly names for UPI app URI schemes, used only when Swiggy sends no displayName.
_UPI_APP_NAMES = {
    "gpay": "Google Pay", "phonepe": "PhonePe", "paytmmp": "Paytm", "bhim": "BHIM", "credpay": "CRED", "super": "super.money",
}


def _method_kind(m: dict) -> str | None:
    """Is this method a UPI "qr" or an app "intent"? Swiggy's types make `kind` optional and a real account
    sends none at all, so: use `kind` when it is valid, else classify by `groupName` (real values seen: "UPI",
    "COD", "SWIGGYPAY") and the id. Inside the UPI group an id with a URI scheme ("gpay://upi/") is an app,
    and an id naming a QR ("PayWithQR") is the QR method. Anything else is not something we can complete."""
    kind = m.get("kind")
    if kind in ("qr", "intent"):
        return kind
    if str(m.get("groupName") or "").strip().casefold() != "upi":
        return None
    method_id = str(m.get("id") or "")
    if "://" in method_id:
        return "intent"
    if "qr" in method_id.casefold():
        return "qr"
    return None


def _intent_label(m: dict) -> str:
    if m.get("displayName"):
        return m["displayName"]
    scheme = str(m.get("id") or "").partition("://")[0].casefold()
    return _UPI_APP_NAMES.get(scheme) or (f"UPI app ({scheme})" if scheme else "UPI app")


def _explain_methods(view: dict) -> list[str]:
    """One entry per method Swiggy listed, with how it was classified and why it was offered or dropped
    (mirrors _payment_options)."""
    seen_qr, out = False, []
    for m in _view_methods(view)[:20]:
        method_id, kind, enabled, group = m.get("id"), m.get("kind"), m.get("enabled"), m.get("groupName")
        as_kind = _method_kind(m)
        if enabled is False:
            why = "dropped: enabled=false"
        elif not method_id:
            why = "dropped: no id"
        elif as_kind == "qr":
            why = "dropped: extra qr" if seen_qr else "offered"
            seen_qr = True
        elif as_kind == "intent":
            why = "offered"
        elif str(group or "").strip().casefold() == "cod":
            why = "dropped: cash is offered from the cod object"
        else:
            why = f"dropped: not a UPI qr/app method (group={group!r})"
        out.append(f"{method_id!r} kind={kind!r} enabled={enabled!r} group={group!r} as={as_kind!r} -> {why}")
    return out


def _payment_options(view: dict | None) -> list[dict]:
    """PaymentOptionsView -> the choices this app can complete. `methodId` is echoed to
    checkout exactly as Swiggy returned it (never reconstructed). One UPI-QR choice at most:
    its bridgeUrl page offers both a scannable QR and an "open in your UPI app" button."""
    view = view or {}
    options: list[dict] = []
    cod = view.get("cod") or {}
    if cod.get("available"):
        options.append({
            "key": "cod", "type": "cod",
            "label": cod.get("displayName") or "Cash on delivery",
            "methodId": cod.get("id") or COD_FALLBACK_ID,
        })
    has_qr = False
    for m in _view_methods(view):
        if m.get("enabled") is False or not m.get("id"):
            continue
        kind = _method_kind(m)
        if kind == "qr" and not has_qr:
            has_qr = True
            options.append({"key": "upi_qr", "type": "upi_qr", "label": m.get("displayName") or "Pay with UPI (scan QR)", "methodId": m["id"]})
        elif kind == "intent":
            options.append({"key": f"upi_intent:{m['id']}", "type": "upi_intent", "label": _intent_label(m), "methodId": m["id"]})
    return options


async def _fetch_payment(
    session: ClientSession, embedded_view: dict | None, *, tag: str, stage: str, cart_note: str, **tool_args
) -> dict:
    """Live payment choices for the current cart. The cart response embeds the same view (`paymentOptions`),
    used as a fallback if get_payment_options itself is unavailable or comes back empty."""
    view: dict | None = None
    source, tool_error = "get_payment_options", None
    try:
        view = await _call(session, "get_payment_options", **tool_args)
    except SwiggyError as exc:
        if exc.code == "auth_required":
            raise
        source, tool_error = "none", exc.message
    options = _payment_options(view)
    if not options and embedded_view:
        view = embedded_view
        options = _payment_options(view)
        source = "cart.paymentOptions (fallback)"
    _log_payment_view(tag, stage, source, tool_error, view, options, cart_note)
    return {"options": options, "amount": (view or {}).get("paymentAmount")}


def _log_payment_view(tag: str, stage: str, source: str, tool_error: str | None, view: dict | None, options: list[dict], cart_note: str) -> None:
    """Diagnostic: exactly what Swiggy listed before our filtering, next to the cart's value, so "Swiggy offered
    only cash" can be told from "we filtered a method out". Identifiers and amounts only; nothing personal."""
    view = view if isinstance(view, dict) else {}
    platforms = {name: len((group or {}).get("methods") or []) for name, group in (view.get("platforms") or {}).items()}
    log.warning(
        "[%s][diag] payment options (%s): source=%s tool_error=%r view_keys=%s cod=%s allMethods=%d platform_methods=%s "
        "paymentAmount=%r | offered=%s | methods=%s | cart: %s",
        tag, stage, source, tool_error, sorted(view), view.get("cod"), len(view.get("allMethods") or []), platforms,
        view.get("paymentAmount"), [o["key"] for o in options], _explain_methods(view), cart_note,
    )


# ---------------------------------------------------------------------------
# Checkout guards (in-process; fine for the single Render instance, WEB_CONCURRENCY=1)
# ---------------------------------------------------------------------------

_attempts: dict[str, tuple[float, dict]] = {}  # idempotency key -> (time, result)
_inflight: set[str] = set()  # accounts with a checkout running (shared by Instamart and Food on purpose)
ATTEMPT_TTL_SECONDS = 6 * 3600


def _account(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _remember(key: str, result: dict) -> dict:
    now = time.time()
    for k in [k for k, (t, _) in _attempts.items() if now - t > ATTEMPT_TTL_SECONDS]:
        del _attempts[k]
    _attempts[key] = (now, result)
    return result


def _outcome(
    status: str, message: str, order_ids: list[str] | None = None, verified: bool = False, total=None, payment: dict | None = None
) -> dict:
    return {"status": status, "orderIds": order_ids or [], "message": message, "verified": verified, "total": total, "payment": payment}
