"""
Deterministic Swiggy Instamart ordering over MCP (POST mcp.swiggy.com/im).

Replaces the Gemini-agent path for groceries. Every tool name, parameter and
response field below was taken from Swiggy's reference docs
(https://mcp.swiggy.com/builders/docs/reference/instamart/ and the "Order
groceries end-to-end" recipe) — camelCase params, `{success, data | error}`
envelopes, domain failures arriving as HTTP 200 + success:false.

Three stages, each its own request so the user confirms before real money moves:
  search_ingredients -> build_cart (clear_cart, update_cart, get_cart) -> checkout
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

log = logging.getLogger("uvicorn.error")

INSTAMART_MCP_URL = os.environ.get("SWIGGY_INSTAMART_MCP_URL", "https://mcp.swiggy.com/im")
MIN_ORDER_INR = 99  # Instamart minimum, per the order-groceries recipe
MAX_OPTIONS_PER_ITEM = 5
SEARCH_CONCURRENCY = 4
# checkout reference: paymentMethod is "UPI" | "Cash" | "SwiggyPay". Cash is normally taken from
# get_payment_options.cod.id (echoed exactly); this is only the fallback if that id is blank.
COD_FALLBACK_ID = "Cash"
MAX_PAYMENT_POLL_SECONDS = 300

_FAILED_STATUSES = {"FAILED", "FAILURE", "CANCELLED", "CANCELED", "REJECTED"}


class InstamartError(Exception):
    """`code` is stable for the frontend; `message` is safe to show the user."""

    def __init__(self, code: str, message: str, status: int = 200):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


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


def _translate(exc: Exception) -> InstamartError:
    if isinstance(exc, InstamartError):
        return exc
    leaves = list(_leaves(exc))
    for leaf in leaves:
        if isinstance(leaf, httpx.HTTPStatusError) and leaf.response.status_code == 401:
            return InstamartError("auth_required", "Connect your Swiggy account to continue.", 401)
        if _AUTH_RE.search(str(leaf)):
            return InstamartError("auth_required", "Connect your Swiggy account to continue.", 401)
    log.error("[INSTAMART] transport failure: %s", "; ".join(f"{type(x).__name__}: {x}"[:200] for x in leaves))
    return InstamartError("upstream_unavailable", "Couldn't reach Swiggy. Please try again.", 502)


@asynccontextmanager
async def _session(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with streamablehttp_client(INSTAMART_MCP_URL, headers=headers) as (read, write, _):
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


def _tool_error(payload: dict) -> InstamartError:
    err = payload.get("error")
    message = (err.get("message") if isinstance(err, dict) else err) or payload.get("message") or "Swiggy rejected the request."
    message = str(message)
    if _AUTH_RE.search(message):
        return InstamartError("auth_required", "Connect your Swiggy account to continue.", 401)
    for marker, code in _DOMAIN_CODES.items():
        if marker in message:
            return InstamartError(code, message)
    return InstamartError("tool_error", message)


async def _call(session: ClientSession, name: str, **arguments) -> dict:
    """One MCP tool call. Returns the envelope's `data`; raises on isError OR success:false."""
    try:
        result = await session.call_tool(name, arguments)
    except McpError as exc:  # protocol-level refusal, e.g. a tool that isn't rolled out for this account
        raise InstamartError("tool_error", f"{name}: {exc}") from exc
    payload = _payload(result)
    if getattr(result, "isError", False) or payload.get("success") is False:
        raise _tool_error(payload)
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


# ---------------------------------------------------------------------------
# Normalizers (Swiggy shapes -> the small JSON the frontend renders)
# ---------------------------------------------------------------------------

def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
        return float(match.group()) if match else None
    return None


def _pick_address(addresses: list[dict]) -> dict:
    """Recipe: pick "Home" if present, else the first saved address. No phone number leaves the server."""
    def is_home(a: dict) -> bool:
        return "home" in f"{a.get('addressTag', '')} {a.get('addressCategory', '')}".lower()

    chosen = next((a for a in addresses if is_home(a)), addresses[0])
    return {
        "id": chosen["id"],
        "label": chosen.get("addressTag") or chosen.get("addressCategory") or "Saved address",
        "addressLine": chosen.get("addressLine", ""),
    }


async def _default_address(session: ClientSession) -> dict:
    data = await _call(session, "get_addresses")
    addresses = [a for a in (data.get("addresses") or []) if a.get("id")]
    if not addresses:
        raise InstamartError("no_address", "Add a delivery address in the Swiggy app first, then try again.")
    return _pick_address(addresses)


def _options(product: dict) -> list[dict]:
    """One option per purchasable variation — the cart takes SKU-level ids, never the parent product."""
    product_ok = product.get("inStock") is not False and product.get("isAvail") is not False
    options = []
    for v in product.get("variations") or []:
        if not v.get("spinId") or not v.get("skuId"):
            continue
        price = v.get("price") or {}
        options.append({
            "spinId": v["spinId"],
            "skuId": v["skuId"],
            "name": v.get("displayName") or product.get("displayName") or "",
            "brand": product.get("brand"),
            "size": v.get("quantityDescription"),
            "price": _num(price.get("offerPrice")),
            "mrp": _num(price.get("mrp")),
            "imageUrl": v.get("imageUrl"),
            "available": bool(v.get("isInStockAndAvailable")) and product_ok,
            "maxQuantity": v.get("maxQuantity"),
        })
    return options


async def _search_one(session: ClientSession, address_id: str, ingredient: str) -> dict:
    data = await _call(session, "search_products", addressId=address_id, query=ingredient)
    products = data.get("products") or []
    options = [o for p in products for o in _options(p)]
    options.sort(key=lambda o: not o["available"])  # stable: in-stock first, Swiggy's ranking kept
    shown = options[:MAX_OPTIONS_PER_ITEM]
    if not products:
        note = "No match on Instamart"
    elif not any(o["available"] for o in options):
        note = "Out of stock nearby"
    else:
        note = None
    return {"ingredient": ingredient, "options": shown, "note": note}


def _cart_item(item: dict) -> dict:
    return {
        "spinId": item.get("spinId"),
        "skuId": item.get("skuId"),
        "name": item.get("itemName") or "",
        "variant": item.get("itemVariant"),
        "quantity": item.get("quantity") or 0,
        "price": _num(item.get("discountedFinalPrice")),
        "mrp": _num(item.get("mrp")),
        "imageUrl": item.get("imageUrl"),
        "available": item.get("isInStockAndAvailable") is not False,
    }


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
    methods = view.get("allMethods") or [
        m for group in (view.get("platforms") or {}).values() for m in (group or {}).get("methods") or []
    ]
    has_qr = False
    for m in methods:
        if m.get("enabled") is False or not m.get("id"):
            continue
        if m.get("kind") == "qr" and not has_qr:
            has_qr = True
            options.append({"key": "upi_qr", "type": "upi_qr", "label": m.get("displayName") or "Pay with UPI", "methodId": m["id"]})
        elif m.get("kind") == "intent":
            options.append({"key": f"upi_intent:{m['id']}", "type": "upi_intent", "label": m.get("displayName") or "UPI app", "methodId": m["id"]})
    return options


async def _fetch_payment(session: ClientSession, cart: dict) -> dict:
    """Live payment choices for the current cart. get_cart embeds the same view (`paymentOptions`),
    used as a fallback if get_payment_options itself is unavailable or comes back empty."""
    view: dict | None = None
    try:
        view = await _call(session, "get_payment_options")
    except InstamartError as exc:
        if exc.code == "auth_required":
            raise
    options = _payment_options(view)
    if not options and cart.get("paymentOptions"):
        view = cart["paymentOptions"]
        options = _payment_options(view)
    return {"options": options, "amount": (view or {}).get("paymentAmount")}


def _review(cart: dict, payment: dict) -> dict:
    """get_cart `data` + live payment choices -> the review shown before "Place order", including why checkout is blocked."""
    items = [_cart_item(i) for i in cart.get("items") or []]
    details = cart.get("selectedAddressDetails") or {}
    bill = cart.get("billBreakdown") or {}
    to_pay = bill.get("toPay") or {}
    unserviceable = [i.get("itemName") or "" for i in cart.get("unserviceableItems") or []]
    item_total = _num(cart.get("cartTotalAmount"))

    blockers = []
    if cart.get("cartAbsent") or not items:
        blockers.append("Your Instamart cart is empty.")
    if unserviceable:
        blockers.append(f"Not deliverable to this address: {', '.join(unserviceable)}.")
    if any(not i["available"] for i in items):
        blockers.append("Some items in your cart are out of stock.")
    if item_total is not None and item_total < MIN_ORDER_INR:
        blockers.append(f"Instamart's minimum order is ₹{MIN_ORDER_INR}.")
    if cart.get("addressWarning"):
        blockers.append(str(cart["addressWarning"]))
    if not payment["options"]:
        blockers.append("No payment method is available for this cart.")

    warning = cart.get("cartWarning") or {}
    return {
        "address": {
            "id": details.get("id"),
            "text": ", ".join(p for p in (details.get("address"), details.get("area")) if p) or cart.get("selectedAddress") or "",
            "label": details.get("name") or details.get("category"),
        },
        "items": items,
        "lineItems": [{"label": li.get("label"), "value": li.get("value")} for li in bill.get("lineItems") or []],
        "total": to_pay.get("value"),
        "totalLabel": to_pay.get("label") or "To pay",
        "itemTotal": cart.get("cartTotalAmount"),
        "minimumOrder": MIN_ORDER_INR,
        "warning": warning.get("message"),
        "blockers": blockers,
        "canCheckout": not blockers and to_pay.get("value") is not None,
        "payment": payment,
    }


# ---------------------------------------------------------------------------
# Stage 1 — search (read-only)
# ---------------------------------------------------------------------------

async def search_ingredients(token: str, ingredients: list[str]) -> dict:
    async with _session(token) as session:
        address = await _default_address(session)
        gate = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def one(name: str) -> dict:
            async with gate:
                try:
                    return await _search_one(session, address["id"], name)
                except InstamartError as exc:
                    if exc.code == "auth_required":
                        raise
                    return {"ingredient": name, "options": [], "note": exc.message}

        results = await asyncio.gather(*(one(n) for n in ingredients))
    return {"address": address, "results": list(results)}


# ---------------------------------------------------------------------------
# Stage 2+3 — cart + review
# ---------------------------------------------------------------------------

def _coupon(item: dict) -> dict:
    tnc = item.get("tnc") or {}
    code = item.get("couponCode") or ""
    return {
        "code": code,
        "title": item.get("title") or code,
        "description": item.get("description"),
        "applicable": bool(item.get("isApplicable")),
        "message": item.get("applicabilityMessage"),
        "terms": tnc.get("bulletTexts") or [],
    }


async def _list_coupons(session: ClientSession, address_id: str) -> list[dict]:
    data = await _call(session, "list_coupons", addressId=address_id)
    return [c for c in map(_coupon, data.get("availableCoupons") or []) if c["code"]]


async def _coupons_or_none(session: ClientSession, address_id: str) -> list[dict] | None:
    """None = coupons unavailable (the docs say list_coupons isn't rolled out to every account).
    Never fails the cart over it; auth problems still propagate."""
    try:
        return await _list_coupons(session, address_id)
    except InstamartError as exc:
        if exc.code == "auth_required":
            raise
        log.info("[INSTAMART] list_coupons unavailable: %s", exc.message)
        return None


def _coupon_block(coupons: list[dict] | None) -> dict:
    return {"available": coupons is not None, "items": coupons or []}


async def build_cart(token: str, address_id: str, selections: list[dict]) -> dict:
    """Make Swiggy's cart exactly `selections`, then return the real cart for review.

    clear_cart first: update_cart's replace/merge semantics aren't documented, and a
    stale item left in the cart would be ordered. (It also drops any coupon: there is no
    remove-coupon tool, so rebuilding the cart is the only way to un-apply one.)
    """
    items = [{"spinId": s["spin_id"], "skuId": s["sku_id"], "quantity": s["quantity"]} for s in selections]
    async with _session(token) as session:
        await _call(session, "clear_cart")
        updated = await _call(session, "update_cart", selectedAddressId=address_id, items=items)
        cart = await _call(session, "get_cart")
        payment = await _fetch_payment(session, cart)
        coupons = await _coupons_or_none(session, address_id)
    review = _review(cart, payment)
    if review["address"]["id"] and review["address"]["id"] != address_id:
        raise InstamartError("address_mismatch", "The cart's delivery address changed. Please start again.")
    adjustments = [f"{i.get('itemName', 'An item')} was removed (out of stock)." for i in updated.get("removedOutOfStockItems") or []]
    adjustments += [
        f"{r.get('itemName', 'An item')}: quantity reduced from {r.get('requestedQuantity')} to {r.get('cappedQuantity')}."
        for r in updated.get("reducedQuantityItems") or []
    ]
    return {"review": review, "adjustments": adjustments, "coupons": _coupon_block(coupons)}


_DISCOUNT_LINE = re.compile(r"discount|coupon|saving|offer|promo", re.I)


def _discount_reflected(before: dict, after: dict) -> tuple[bool, float | None]:
    """Swiggy: only treat a coupon as applied once the cart itself shows the discount."""
    b, a = _num(before["total"]), _num(after["total"])
    if b is not None and a is not None:
        return a < b, (round(b - a, 2) if a < b else None)
    old_labels = {li["label"] for li in before["lineItems"]}
    return any(_DISCOUNT_LINE.search(li["label"] or "") and li["label"] not in old_labels for li in after["lineItems"]), None


async def apply_coupon(token: str, address_id: str, coupon_code: str) -> dict:
    """Apply one of the coupons Swiggy currently lists for this cart, then re-read the cart.

    Everything is re-verified server-side, never trusted from the client: the cart must still be
    for this address, the coupon must still be listed AND applicable now (it may have expired or
    the cart changed since the user saw it), and the total must actually drop afterwards.
    """
    async with _session(token) as session:
        before_cart = await _call(session, "get_cart")
        before = _review(before_cart, await _fetch_payment(session, before_cart))
        if before["address"]["id"] != address_id:
            raise InstamartError("address_mismatch", "The delivery address changed. Please review your cart again.")
        if before["blockers"]:
            raise InstamartError("cart_blocked", before["blockers"][0])

        listed = await _list_coupons(session, address_id)
        match = next((c for c in listed if c["code"].lower() == coupon_code.strip().lower()), None)
        if match is None:
            raise InstamartError("coupon_not_found", "That coupon isn't available for this cart anymore.")
        if not match["applicable"]:
            raise InstamartError("coupon_not_applicable", match["message"] or "That coupon can't be applied to this cart.")

        await _call(session, "apply_coupon", couponCode=match["code"])
        after_cart = await _call(session, "get_cart")
        payment = await _fetch_payment(session, after_cart)
        relisted = await _coupons_or_none(session, address_id)
    after = _review(after_cart, payment)
    if after["address"]["id"] != address_id:
        raise InstamartError("address_mismatch", "The delivery address changed. Please review your cart again.")
    reflected, savings = _discount_reflected(before, after)
    if not reflected:
        raise InstamartError(
            "coupon_not_reflected",
            "Swiggy accepted the code but your total didn't change, so it wasn't counted. Use Edit items to rebuild the cart if you want to be sure.",
        )
    return {
        "review": after,
        "coupon": {"code": match["code"], "title": match["title"], "savings": savings},
        "coupons": _coupon_block(relisted),
    }


# ---------------------------------------------------------------------------
# Stage 4 — checkout (real money)
# ---------------------------------------------------------------------------

# In-process guards; fine for the single Render instance (WEB_CONCURRENCY=1).
_attempts: dict[str, tuple[float, dict]] = {}  # idempotency key -> (time, result)
_inflight: set[str] = set()  # accounts with a checkout running
ATTEMPT_TTL_SECONDS = 6 * 3600


def _account(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _remember(key: str, result: dict) -> dict:
    now = time.time()
    for k in [k for k, (t, _) in _attempts.items() if now - t > ATTEMPT_TTL_SECONDS]:
        del _attempts[k]
    _attempts[key] = (now, result)
    return result


async def _active_order_ids(session: ClientSession) -> set[str] | None:
    """None = couldn't check (callers must then treat an ambiguous checkout as unknown)."""
    try:
        data = await _call(session, "get_orders", orderType="INSTAMART", activeOnly=True, count=10)
    except Exception:
        return None
    return {str(o["orderId"]) for o in data.get("orders") or [] if o.get("orderId")}


def _outcome(
    status: str, message: str, order_ids: list[str] | None = None, verified: bool = False, total=None, payment: dict | None = None
) -> dict:
    return {"status": status, "orderIds": order_ids or [], "message": message, "verified": verified, "total": total, "payment": payment}


def _pending_outcome(data: dict) -> dict:
    """checkout returned PENDING_PAYMENT (UPI). The browser opens `bridgeUrl` (a scan-or-tap page)
    and polls payment_status(); nothing is held open server-side."""
    order_id = str(data.get("orderId") or "")
    bridge = data.get("bridgeUrl")
    if not (order_id and data.get("paasId") and isinstance(bridge, str) and urlsplit(bridge).scheme == "https"):
        return _outcome(
            "unknown", "Payment was started but Swiggy didn't give us a payment page. Check the Swiggy app before trying again.",
            [order_id] if order_id else None,
        )
    payment = {
        "orderId": order_id,
        "paasId": str(data["paasId"]),
        "bridgeUrl": bridge,
        "pollIntervalMs": min(max(int(data.get("pollingIntervalInMs") or 3000), 1000), 10_000),
        "maxPollMs": min(int(data.get("maxTimeToPollForInMs") or 120_000), MAX_PAYMENT_POLL_SECONDS * 1000),
    }
    return _outcome("pending_payment", "Complete the payment to place your order.", [order_id], total=data.get("cartTotal"), payment=payment)


_PAYMENT_FAILED_STATES = {"failed", "cancelled", "cart_changed", "refund-initiated"}
_PAYMENT_MESSAGES = {
    "cancelled": "The payment was cancelled. If money was debited it will be refunded — check the Swiggy app.",
    "refund-initiated": "The payment couldn't be completed and a refund has started. Check the Swiggy app.",
    "cart_changed": "Prices or stock changed while paying, so the order wasn't placed. Review your cart and order again.",
}


async def payment_status(token: str, order_id: str, paas_id: str, final: bool = False) -> dict:
    """One poll of a pending UPI payment. Per the payment recipe: on terminal success that isn't
    already confirmed, call confirm_order(orderId, paasId) once; at the polling deadline (`final`)
    call it once more and let Swiggy reconcile a late payment. Never confirms after a failure."""
    async with _session(token) as session:
        status = await _call(session, "check_payment_status", paasId=paas_id, orderId=order_id)
        state = str(status.get("status") or "").lower()
        if status.get("isTerminalFailure") or state in _PAYMENT_FAILED_STATES:
            return _outcome("failed", _PAYMENT_MESSAGES.get(state, "The payment didn't go through. Nothing was ordered."))
        succeeded = bool(status.get("isTerminalSuccess")) or state in {"success", "paid"}
        if succeeded and status.get("confirmed"):
            outcome = _outcome("placed", "Order placed.", [order_id])
        elif succeeded or final:
            confirmed = await _call(session, "confirm_order", orderId=order_id, paasId=paas_id)
            result = str(confirmed.get("result") or "").lower()
            if result == "success":
                outcome = _outcome("placed", "Order placed.", [order_id])
            elif result == "failed":
                return _outcome("failed", "Swiggy couldn't complete the order after payment. Check the Swiggy app.")
            elif final:
                return _outcome("unknown", "We couldn't confirm the payment yet. Check the Swiggy app before trying again.", [order_id])
            else:
                return _outcome("pending_payment", "Confirming your payment…", [order_id])
        else:
            return _outcome("pending_payment", "Waiting for your payment…", [order_id])
    return await _verify(token, outcome, None)


def _read_checkout(data: dict) -> dict:
    """checkout `data` -> outcome. Multi-store carts return `orders[]`."""
    orders = data.get("orders")
    if isinstance(orders, list):
        ids = [str(o["orderId"]) for o in orders if o.get("orderId")]
        if data.get("allSucceeded") and ids:
            return _outcome("placed", "Order placed.", ids, total=data.get("cartTotal"))
        if ids:
            return _outcome("partial", f"Only some orders went through ({data.get('successCount')} of {data.get('orderCount')}). Check the Swiggy app.", ids)
        return _outcome("failed", "Swiggy couldn't place the order.")
    order_id, status = data.get("orderId"), str(data.get("status") or "").upper()
    if not order_id or status in _FAILED_STATUSES:
        return _outcome("failed", "Swiggy couldn't place the order.")
    return _outcome("placed", "Order placed.", [str(order_id)], total=data.get("cartTotal"))


async def _verify(token: str, outcome: dict, before: set[str] | None) -> dict:
    """Cross-check against get_orders: confirms a claimed order, and rescues an ambiguous/failed
    checkout that actually went through (a naive retry would double-order). Uses a fresh
    session because the checkout one may be dead after a transport drop."""
    try:
        async with _session(token) as session:
            after = await _active_order_ids(session)
    except InstamartError:
        return outcome
    if after is None:
        return outcome
    new_ids = sorted(after - (before or set()))
    if outcome["status"] == "placed":
        return {**outcome, "verified": all(i in after for i in outcome["orderIds"])}
    if outcome["status"] in ("failed", "unknown") and new_ids and before is not None:
        return _outcome("placed", "Order placed.", new_ids, verified=True)
    return outcome


async def checkout(token: str, address_id: str, expected_total: str, key: str, payment_key: str) -> dict:
    if key in _attempts:
        return _attempts[key][1]  # a replayed click / network retry never runs checkout twice
    account = _account(token)
    if account in _inflight:
        raise InstamartError("checkout_in_progress", "An order is already being placed. Give it a moment.")
    _inflight.add(account)
    try:
        return _remember(key, await _checkout_locked(token, address_id, expected_total, payment_key))
    finally:
        _inflight.discard(account)


def _checkout_args(address_id: str, choice: dict) -> dict:
    """Arguments for checkout, straight from the option Swiggy listed (ids echoed, not rebuilt)."""
    base = {"addressId": address_id}
    if choice["type"] == "cod":
        return {**base, "paymentMethod": choice["methodId"]}
    if choice["type"] == "upi_qr":
        return {**base, "paymentMethod": "UPI", "generateUPIQR": True}
    return {**base, "paymentMethod": "UPI", "intentApp": choice["methodId"]}


async def _checkout_locked(token: str, address_id: str, expected_total: str, payment_key: str) -> dict:
    async with _session(token) as session:
        cart = await _call(session, "get_cart")
        review = _review(cart, await _fetch_payment(session, cart))
        if review["address"]["id"] != address_id:
            raise InstamartError("address_mismatch", "The delivery address changed. Please review your cart again.")
        if review["blockers"]:
            raise InstamartError("cart_blocked", review["blockers"][0])
        # The total the user confirmed already includes any coupon (get_cart bills the discounted
        # amount), so this also refuses if a coupon lapsed, was added, or anything else moved.
        if review["total"] != expected_total:
            raise InstamartError("cart_changed", "Your cart total changed. Please review it again before ordering.")
        choice = next((o for o in review["payment"]["options"] if o["key"] == payment_key), None)
        if choice is None:
            raise InstamartError("payment_unavailable", "That payment method isn't available anymore. Please choose again.")

        before = await _active_order_ids(session)
        log.info("[INSTAMART] placing %s order, total=%s", choice["type"], review["total"])
        try:
            data = await _call(session, "checkout", **_checkout_args(address_id, choice))
        except InstamartError as exc:
            if exc.code == "auth_required":
                raise
            ambiguous = exc.code == "upstream_unavailable"
            fallback = (
                _outcome("unknown", "We couldn't confirm whether the order went through. Check the Swiggy app before trying again.")
                if ambiguous else _outcome("failed", exc.message)
            )
            return await _verify(token, fallback, before)
        except Exception as exc:  # transport drop mid-call: outcome unknown, never assume failure
            log.error("[INSTAMART] checkout transport error: %s", exc)
            fallback = _outcome("unknown", "We couldn't confirm whether the order went through. Check the Swiggy app before trying again.")
            return await _verify(token, fallback, before)

        if str(data.get("status") or "").upper() == "PENDING_PAYMENT":
            return _pending_outcome(data)  # not an order yet: the payment page + payment_status() finish it
        return await _verify(token, _read_checkout(data), before)
