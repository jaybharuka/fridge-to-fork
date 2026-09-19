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

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

log = logging.getLogger("uvicorn.error")

INSTAMART_MCP_URL = os.environ.get("SWIGGY_INSTAMART_MCP_URL", "https://mcp.swiggy.com/im")
MIN_ORDER_INR = 99  # Instamart minimum, per the order-groceries recipe
MAX_OPTIONS_PER_ITEM = 5
SEARCH_CONCURRENCY = 4
PAYMENT_METHOD = "COD"
PAYMENT_POLL_CAP_SECONDS = 120

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
    result = await session.call_tool(name, arguments)
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


def _cod_available(data: dict) -> bool:
    methods = data.get("availablePaymentMethods")
    options = data.get("paymentOptions") or {}
    if not methods and not options:
        return True  # nothing to check against; checkout itself will refuse if COD is off
    return bool(options.get("cod")) or any(re.search(r"cod|cash", str(m), re.I) for m in methods or [])


def _review(cart: dict) -> dict:
    """get_cart `data` -> the review shown before "Place order", including why checkout is blocked."""
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
    if not _cod_available(cart):
        blockers.append("Cash on delivery isn't available for this cart.")

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
        "paymentMethod": PAYMENT_METHOD,
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

async def build_cart(token: str, address_id: str, selections: list[dict]) -> dict:
    """Make Swiggy's cart exactly `selections`, then return the real cart for review.

    clear_cart first: update_cart's replace/merge semantics aren't documented, and a
    stale item left in the cart would be ordered.
    """
    items = [{"spinId": s["spin_id"], "skuId": s["sku_id"], "quantity": s["quantity"]} for s in selections]
    async with _session(token) as session:
        await _call(session, "clear_cart")
        updated = await _call(session, "update_cart", selectedAddressId=address_id, items=items)
        cart = await _call(session, "get_cart")
    review = _review(cart)
    if review["address"]["id"] and review["address"]["id"] != address_id:
        raise InstamartError("address_mismatch", "The cart's delivery address changed. Please start again.")
    adjustments = [f"{i.get('itemName', 'An item')} was removed (out of stock)." for i in updated.get("removedOutOfStockItems") or []]
    adjustments += [
        f"{r.get('itemName', 'An item')}: quantity reduced from {r.get('requestedQuantity')} to {r.get('cappedQuantity')}."
        for r in updated.get("reducedQuantityItems") or []
    ]
    return {"review": review, "adjustments": adjustments}


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


def _outcome(status: str, message: str, order_ids: list[str] | None = None, verified: bool = False, total=None) -> dict:
    return {"status": status, "orderIds": order_ids or [], "message": message, "verified": verified, "total": total}


async def _await_upi(session: ClientSession, data: dict) -> dict:
    """PENDING_PAYMENT path (UPI). We only request COD, so this is defensive: poll
    check_payment_status(paasId), then confirm_order(orderId, paasId) unless already confirmed."""
    paas_id, order_id = data.get("paasId"), data.get("orderId")
    interval = min(max((data.get("pollingIntervalInMs") or 3000) / 1000, 1), 10)
    limit = min((data.get("maxTimeToPollForInMs") or PAYMENT_POLL_CAP_SECONDS * 1000) / 1000, PAYMENT_POLL_CAP_SECONDS)
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        status = await _call(session, "check_payment_status", paasId=paas_id, orderId=order_id)
        if status.get("isTerminalFailure"):
            return _outcome("failed", "The payment didn't go through. Nothing was ordered.")
        if status.get("isTerminalSuccess"):
            if status.get("confirmed"):
                return _outcome("placed", "Order placed.", [str(order_id)], verified=True)
            confirmed = await _call(session, "confirm_order", orderId=order_id, paasId=paas_id)
            if confirmed.get("result") == "success":
                return _outcome("placed", "Order placed.", [str(order_id)], verified=True)
            if confirmed.get("result") == "failed":
                return _outcome("failed", "Swiggy couldn't complete the order after payment.")
        await asyncio.sleep(interval)
    return _outcome("unknown", "Payment is still pending. Check the Swiggy app before trying again.", [str(order_id)])


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


async def checkout(token: str, address_id: str, expected_total: str, key: str) -> dict:
    if key in _attempts:
        return _attempts[key][1]  # a replayed click / network retry never runs checkout twice
    account = _account(token)
    if account in _inflight:
        raise InstamartError("checkout_in_progress", "An order is already being placed. Give it a moment.")
    _inflight.add(account)
    try:
        return _remember(key, await _checkout_locked(token, address_id, expected_total))
    finally:
        _inflight.discard(account)


async def _checkout_locked(token: str, address_id: str, expected_total: str) -> dict:
    async with _session(token) as session:
        review = _review(await _call(session, "get_cart"))
        if review["address"]["id"] != address_id:
            raise InstamartError("address_mismatch", "The delivery address changed. Please review your cart again.")
        if review["blockers"]:
            raise InstamartError("cart_blocked", review["blockers"][0])
        if review["total"] != expected_total:
            raise InstamartError("cart_changed", "Your cart total changed. Please review it again before ordering.")

        before = await _active_order_ids(session)
        log.info("[INSTAMART] placing COD order, total=%s", review["total"])
        try:
            data = await _call(session, "checkout", addressId=address_id, paymentMethod=PAYMENT_METHOD)
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
            return await _verify(token, await _await_upi(session, data), before)
        return await _verify(token, _read_checkout(data), before)
