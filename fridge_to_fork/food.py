"""
Deterministic Swiggy Food ordering over MCP (POST mcp.swiggy.com/food).

Replaces the Gemini-agent path for "order the dish". Written against Swiggy's Food reference pages
(search_restaurants, search_menu, get_restaurant_menu, update_food_cart, get_food_cart, flush_food_cart,
place_food_order, get_food_orders, get_payment_options, get_addresses); nothing is carried over from the old agent.

Stages, each its own request so the user confirms before real money moves:
  search_dish (search_restaurants + search_menu)  ->  build_cart (flush_food_cart, update_food_cart, get_food_cart)
  ->  checkout (place_food_order, guarded)

What the docs do NOT say, and how that is handled (see also _cart_item):
  * The shape of one `cartItems` element in update_food_cart is not documented (only `object[]`). It is built in ONE
    place from the documented response/reorder shapes, and the cart Swiggy sends back is verified against what the
    user picked (item, quantity, every chosen variant and add-on), so a wrongly-shaped request can never quietly
    order the wrong food: it is refused instead.
  * Whether update_food_cart replaces or merges is not documented, so flush_food_cart runs first, and the cart is
    checked to hold exactly the one item that was reviewed.
"""

import asyncio
import logging
import os

from mcp import ClientSession

from . import swiggy_common
from .swiggy_common import (
    SwiggyError, _call, _fetch_payment as _fetch_payment_common, _num, _outcome, _pick_address, _public_address, _saved_addresses,
    _same_address_id, _same_id, _account, _attempts, _inflight, _remember,
)

log = logging.getLogger("uvicorn.error")

FOOD_MCP_URL = os.environ.get("SWIGGY_FOOD_MCP_URL", "https://mcp.swiggy.com/food")
MAX_RESULTS = 8
MAX_QUANTITY = 20
# Phase 1 completes cash on delivery only; the UPI bridge/polling flow is added with the payment phase.
OFFERED_PAYMENT_TYPES = {"cod"}

_FAILED_STATUSES = {"FAILED", "FAILURE", "CANCELLED", "CANCELED", "REJECTED"}


def _session(token: str):
    return swiggy_common.open_session(FOOD_MCP_URL, token)


def _in_stock(value) -> bool:
    """`inStock` is a number on menu items and a boolean on search dishes; absent = not known to be out."""
    return value not in (0, False)


def _veg(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str) and value.strip():
        return value.strip().casefold() in {"1", "true", "veg", "yes"}
    return None


# ---------------------------------------------------------------------------
# Address (Food's get_addresses is the same shared tool as Instamart's, but ids are still matched tolerantly)
# ---------------------------------------------------------------------------

async def _resolve_address(session: ClientSession, address_id: str | None) -> dict:
    addresses = await _saved_addresses(session)
    if not addresses:
        raise SwiggyError("no_address", "Add a delivery address first, then try again.")
    if address_id is None:
        return _pick_address(addresses)
    match = next((a for a in addresses if _same_id(a["id"], address_id)), None) or next(
        (a for a in addresses if _same_address_id(a["id"], address_id) or _same_address_id(address_id, a["id"])), None
    )
    if match is None:
        log.warning("[FOOD] address not found: requested=%r saved_ids=%s", address_id, [str(a["id"]) for a in addresses])
        raise SwiggyError("address_not_found", "That address isn't saved on your Swiggy account anymore. Choose another.")
    return _public_address(match)


# ---------------------------------------------------------------------------
# Stage 1 + 2 — search a dish, with the customizations the cart will need (read-only)
# ---------------------------------------------------------------------------

def _options(variations: list[dict]) -> list[dict]:
    return [
        {
            "id": str(v["id"]), "name": v.get("name") or "", "price": _num(v.get("price")),
            "default": bool(v.get("default")), "available": _in_stock(v.get("inStock")),
        }
        for v in variations if v.get("id") not in (None, "")
    ]


def _customization(item: dict) -> dict:
    """Variant groups (pick exactly one per group) and add-on groups (optional, within min/max) for one menu item.

    `format` says which cart field the item uses: search_menu returns EITHER `variantsV2` OR `variations`, never both,
    and the cart must get the same one. `supported` is false when the item needs options we can't identify, so it is
    shown but not orderable here rather than ordered with a guessed default.
    """
    groups: list[dict] = []
    fmt = None
    supported = True
    if item.get("variantsV2"):
        fmt = "variantsV2"
        for g in item["variantsV2"]:
            options = _options(g.get("variations") or [])
            if g.get("groupId") in (None, "") or not options:
                supported = False
                continue
            groups.append({"groupId": str(g["groupId"]), "name": g.get("name") or "Choose one", "options": options})
    elif item.get("variations"):
        fmt = "variations"
        by_group: dict[str, list[dict]] = {}
        for v in item["variations"]:
            if v.get("groupId") in (None, ""):
                supported = False  # a legacy variation with no group id can't be paired with its group
                continue
            by_group.setdefault(str(v["groupId"]), []).append(v)
        for gid, variations in by_group.items():
            groups.append({"groupId": gid, "name": "Choose one", "options": _options(variations)})
    if item.get("hasVariants") and not groups:
        supported = False  # Swiggy says it has variants but gave none we can use
    addons = [
        {
            "groupId": str(g["groupId"]), "name": g.get("groupName") or "Add-ons", "min": int(g.get("minAddons") or 0),
            "max": g.get("maxAddons") if isinstance(g.get("maxAddons"), int) and g["maxAddons"] > 0 else None,
            "choices": [{"id": str(c["id"]), "name": c.get("name") or "", "price": _num(c.get("price"))} for c in g.get("choices") or [] if c.get("id") not in (None, "")],
        }
        for g in item.get("addons") or [] if g.get("groupId") not in (None, "")
    ]
    if item.get("hasAddons") and not addons:
        supported = False
    return {"format": fmt, "variantGroups": groups, "addonGroups": [a for a in addons if a["choices"]], "supported": supported}


def _restaurant(item: dict, known: dict | None) -> dict:
    known = known or {}
    return {
        "id": str(item.get("restaurant_id")),
        "name": known.get("name") or item.get("restaurant_name") or "",
        "area": known.get("areaName"),
        "etaMinutes": known.get("deliveryTimeMinutes"),
        "etaRange": known.get("deliveryTimeRange"),
        "distanceKm": known.get("distanceKm"),
        "rating": known.get("avgRating"),
        "costForTwo": known.get("costForTwo"),
        "offer": known.get("offer"),
        "open": None if not known.get("availabilityStatus") else str(known["availabilityStatus"]).strip().upper() == "OPEN",
    }


def _menu_result(item: dict, restaurants: dict[str, dict]) -> dict | None:
    if not (item.get("menu_item_id") and item.get("restaurant_id") and item.get("name")):
        return None  # can't be added to a cart without both ids
    return {
        "menuItemId": str(item["menu_item_id"]),
        "name": item["name"],
        "price": _num(item.get("price")),
        "isVeg": _veg(item.get("isVeg")),
        "imageUrl": item.get("imageUrl"),
        "rating": item.get("rating"),
        "ratingCount": item.get("totalRatings"),
        "bestseller": bool(item.get("isBestseller")),
        "available": _in_stock(item.get("inStock")),
        "restaurant": _restaurant(item, restaurants.get(str(item["restaurant_id"]))),
        "customization": _customization(item),
    }


async def _restaurants_or_none(session: ClientSession, address_id: str, dish: str) -> dict | None:
    """search_restaurants is Swiggy's primary search and the only source of open/closed and ETA; if it fails the
    dishes are still shown (the cart step re-checks), never the whole search."""
    try:
        return await _call(session, "search_restaurants", addressId=address_id, query=dish)
    except SwiggyError as exc:
        if exc.code == "auth_required":
            raise
        log.info("[FOOD] search_restaurants unavailable: %s", exc.message)
        return None


def _describe_search(menu: dict, found: dict | None, results: list[dict], closed: int) -> str:
    items = [i for i in menu.get("items") or [] if isinstance(i, dict)]
    first = items[0] if items else {}
    rows = (found or {}).get("restaurants") or []
    return (
        f"menu_items={len(items)} hasMore={menu.get('hasMore')!r} restaurants={len(rows)} dishes={len((found or {}).get('dishes') or [])} "
        f"status={sorted({str(r.get('availabilityStatus')) for r in rows if isinstance(r, dict)})} "
        f"joined={sum(1 for r in results if r['restaurant']['open'] is not None)}/{len(results)} closed_dropped={closed} "
        f"customizable={sum(1 for r in results if r['customization']['variantGroups'] or r['customization']['addonGroups'])} "
        f"unsupported={sum(1 for r in results if not r['customization']['supported'])} "
        f"first_item_fields={ {k: type(v).__name__ for k, v in first.items()} }"
    )


async def search_dish(token: str, dish: str, address_id: str | None = None) -> dict:
    async with _session(token) as session:
        address = await _resolve_address(session, address_id)
        found, menu = await asyncio.gather(
            _restaurants_or_none(session, address["id"], dish),
            _call(session, "search_menu", addressId=address["id"], query=dish),
        )
    restaurants = {str(r["id"]): r for r in (found or {}).get("restaurants") or [] if isinstance(r, dict) and r.get("id")}
    parsed = [r for r in (_menu_result(i, restaurants) for i in menu.get("items") or [] if isinstance(i, dict)) if r]
    # Docs: only recommend restaurants whose availabilityStatus is OPEN. A restaurant that search_restaurants
    # didn't list has no known status; it is kept (the cart step re-checks) but sorted after the confirmed-open ones.
    open_or_unknown = [r for r in parsed if r["restaurant"]["open"] is not False]
    closed = len(parsed) - len(open_or_unknown)
    open_or_unknown.sort(key=lambda r: (not r["available"], r["restaurant"]["open"] is None))  # stable: Swiggy's ranking kept
    results = open_or_unknown[:MAX_RESULTS]
    log.warning("[FOOD][diag] search: %s", _describe_search(menu, found, results, closed))
    return {"address": address, "dish": dish, "results": results, "hasMore": bool(menu.get("hasMore"))}


# ---------------------------------------------------------------------------
# Stage 3 + 4 — cart and review
# ---------------------------------------------------------------------------

def _cart_item(sel: dict) -> dict:
    """One `cartItems` element for update_food_cart.

    The docs leave this shape undefined. What they do document: the item id is `menu_item_id`; customizations are
    `variants` OR `variantsV2` (never both, the same one the item has); and the reorder items in get_food_orders,
    which exist to be fed back into the cart, are {menu_item_id, quantity, variants:[{variation_id, group_id}],
    addons:[{addon_id, group_id}]}. This follows that. It is the one place to change if Swiggy's real validation
    says otherwise; _check_cart verifies the outcome regardless.
    """
    item: dict = {"menu_item_id": sel["menu_item_id"], "quantity": sel["quantity"]}
    if sel["variants"]:
        item["variantsV2" if sel.get("format") == "variantsV2" else "variants"] = [
            {"group_id": v["group_id"], "variation_id": v["variation_id"]} for v in sel["variants"]
        ]
    if sel["addons"]:
        item["addons"] = [{"group_id": a["group_id"], "addon_id": a["addon_id"], "quantity": a["quantity"]} for a in sel["addons"]]
    return item


def _inner(cart: dict) -> dict:
    """get_food_cart/update_food_cart `data`: the live cart sits under `data.data`."""
    return cart["data"] if isinstance(cart.get("data"), dict) else cart


def _ids(entries, *keys: str) -> set[str]:
    return {str(e[k]) for e in entries or [] if isinstance(e, dict) for k in keys if e.get(k) not in (None, "")}


def _check_cart(cart: dict, sel: dict) -> str | None:
    """None when Swiggy's cart is exactly what the user picked, else why not. Nothing is ordered on a mismatch."""
    inner = _inner(cart)
    items = [i for i in inner.get("items") or [] if isinstance(i, dict)]
    restaurant_id = (inner.get("restaurant") or {}).get("id")
    if restaurant_id not in (None, "") and str(restaurant_id) != str(sel["restaurant_id"]):
        return "Swiggy's cart is for a different restaurant than the one you chose."
    if len(items) != 1 or str(items[0].get("menu_item_id")) != str(sel["menu_item_id"]):
        return "Swiggy's cart doesn't match the dish you chose (it holds other items)."
    item = items[0]
    if int(item.get("quantity") or 0) != sel["quantity"]:
        return "Swiggy's cart has a different quantity than you chose."
    have_variants = _ids(item.get("variants"), "variation_id", "variationId", "id")
    if any(v["variation_id"] not in have_variants for v in sel["variants"]):
        return "Swiggy's cart didn't confirm your size/option choice."
    have_addons = _ids(item.get("addons"), "addon_id", "id", "variation_id", "variationId")
    if any(a["addon_id"] not in have_addons for a in sel["addons"]):
        return "Swiggy's cart didn't confirm your add-ons."
    return None


def _cart_line(item: dict) -> dict:
    line_total = _num(item.get("total"))
    return {
        "menuItemId": str(item.get("menu_item_id") or ""),
        "name": item.get("name") or "",
        "quantity": int(item.get("quantity") or 0),
        "lineTotal": line_total if line_total is not None else _num(item.get("final_price")),
        "imageUrl": item.get("imageUrl"),
        "isVeg": _veg(item.get("is_veg")),
        "available": item.get("in_stock") is not False,
        "variants": [v.get("name") for v in item.get("variants") or [] if isinstance(v, dict) and v.get("name")],
        "addons": [a.get("name") for a in item.get("addons") or [] if isinstance(a, dict) and a.get("name")],
    }


def _cart_note(cart: dict) -> str:
    pricing = _inner(cart).get("pricing") or {}
    return (
        f"availablePaymentMethods={cart.get('availablePaymentMethods')} has_paymentOptions={bool(cart.get('paymentOptions'))} "
        f"itemTotal={pricing.get('item_total')!r} toPay={pricing.get('to_pay')!r}"
    )


async def _fetch_payment(session: ClientSession, cart: dict, address_id: str, stage: str) -> dict:
    payment = await _fetch_payment_common(
        session, cart.get("paymentOptions"), tag="FOOD", stage=stage, cart_note=_cart_note(cart), addressId=address_id
    )
    return {**payment, "options": [o for o in payment["options"] if o["type"] in OFFERED_PAYMENT_TYPES]}


def _review(cart: dict, payment: dict, address: dict) -> dict:
    inner = _inner(cart)
    pricing = inner.get("pricing") or {}
    offers = inner.get("offers") or {}
    restaurant = inner.get("restaurant") or {}
    items = [_cart_line(i) for i in inner.get("items") or [] if isinstance(i, dict)]
    to_pay = _num(pricing.get("to_pay"))
    discount = _num(offers.get("coupon_discount")) or 0

    blockers = []
    if not items:
        blockers.append("Your Swiggy cart is empty.")
    if any(not i["available"] for i in items):
        blockers.append("An item in your cart is out of stock.")
    if to_pay is None:
        blockers.append("Swiggy didn't return a total for this cart.")
    if not payment["options"]:
        blockers.append("No payment method is available for this cart.")

    lines = [{"label": "Item total", "value": _num(pricing.get("item_total"))}]
    if pricing.get("delivery_charge") is not None:
        lines.append({"label": "Delivery fee", "value": _num(pricing.get("delivery_charge")), "strikeoff": _num(pricing.get("delivery_charge_strikeoff"))})
    if pricing.get("taxes_and_charges") is not None:
        lines.append({"label": "Taxes and charges", "value": _num(pricing.get("taxes_and_charges"))})
    if discount > 0:  # only a positive discount counts: coupon_applied with 0 is just Swiggy's suggestion
        lines.append({"label": f"Coupon {offers.get('coupon_applied') or ''}".strip(), "value": -discount})
    return {
        "address": {"id": address["id"], "text": address["addressLine"], "label": address["label"]},
        "restaurant": {"id": restaurant.get("id"), "name": restaurant.get("name"), "area": restaurant.get("area"), "deliverySubtitle": restaurant.get("deliverySubtitle")},
        "items": items,
        "lineItems": lines,
        "total": to_pay,
        "warning": None,
        "blockers": blockers,
        "canCheckout": not blockers and to_pay is not None,
        "payment": payment,
        "coupon": {"code": offers.get("coupon_applied"), "discount": discount} if discount > 0 else None,
    }


def _describe_cart(update: dict, cart: dict) -> str:
    inner, first = _inner(cart), next((i for i in _inner(cart).get("items") or [] if isinstance(i, dict)), {})
    return (
        f"update_keys={sorted(update)} update_statusCode={update.get('statusCode')!r} update_statusMessage={update.get('statusMessage')!r} "
        f"cart_keys={sorted(cart)} inner_keys={sorted(inner)} item_count={inner.get('item_count')!r} items={len(inner.get('items') or [])} "
        f"restaurant_fields={sorted(inner.get('restaurant') or {})} pricing={inner.get('pricing')} offers={inner.get('offers')} "
        f"first_item_fields={ {k: type(v).__name__ for k, v in first.items()} } "
        f"first_item_variants={first.get('variants')!r} first_item_addons={first.get('addons')!r} "
        f"valid_addon_groups={[(g.get('group_id') or g.get('groupId')) for g in first.get('valid_addons') or [] if isinstance(g, dict)]}"
    )


async def build_cart(token: str, address_id: str, sel: dict) -> dict:
    """Make Swiggy's Food cart exactly the one reviewed item, then return the real cart.

    flush_food_cart first (a stale item left in the cart would be ordered, and replace-vs-merge isn't documented);
    then the cart is checked to hold exactly what was picked before it is ever offered for ordering.
    """
    async with _session(token) as session:
        address = await _resolve_address(session, address_id)
        await _call(session, "flush_food_cart")
        name_arg = {"restaurantName": sel["restaurant_name"]} if sel.get("restaurant_name") else {}
        update = await _call(
            session, "update_food_cart", restaurantId=sel["restaurant_id"], cartItems=[_cart_item(sel)], addressId=address["id"], **name_arg
        )
        cart = await _call(session, "get_food_cart", addressId=address["id"], **name_arg)
        log.warning("[FOOD][diag] cart: %s", _describe_cart(update, cart))
        mismatch = _check_cart(cart, sel)
        if mismatch:
            log.warning("[FOOD] cart refused: %s requested_variants=%d requested_addons=%d format=%s", mismatch, len(sel["variants"]), len(sel["addons"]), sel.get("format"))
            raise SwiggyError("cart_mismatch", f"{mismatch} Nothing was ordered. Try again, or order in the Swiggy app.", tool="update_food_cart")
        payment = await _fetch_payment(session, cart, address["id"], stage="cart")
    return {"review": _review(cart, payment, address), "adjustments": []}


# ---------------------------------------------------------------------------
# Stage 5 — checkout (real money)
# ---------------------------------------------------------------------------

async def _active_order_ids(session: ClientSession, address_id: str) -> set[str] | None:
    """None = couldn't check (callers must then treat an ambiguous checkout as unknown)."""
    try:
        data = await _call(session, "get_food_orders", addressId=address_id, activeOnly=True)
    except Exception:
        return None
    return {str(o["orderId"]) for o in data.get("orders") or [] if isinstance(o, dict) and o.get("orderId")}


def _placed_outcome(order_ids: list[str], data: dict | None = None, verified: bool = False) -> dict:
    data = data or {}
    outcome = _outcome("placed", "Order placed.", order_ids, verified=verified, total=data.get("totalAmount"))
    return {**outcome, "detail": {"restaurant": data.get("restaurantName"), "eta": data.get("estimatedDelivery"), "items": [i.get("name") for i in data.get("items") or [] if isinstance(i, dict) and i.get("name")]}}


def _read_placed(data: dict) -> dict:
    """place_food_order `data` -> outcome. COD is placed immediately (status CONFIRMED)."""
    status = str(data.get("status") or "").upper()
    if status == "PENDING_PAYMENT":  # never requested in this phase (only cash is offered), but never call it an order
        order_id = str(data.get("orderId") or "")
        return _outcome("unknown", "A payment was started that we can't complete here. Check the Swiggy app before trying again.", [order_id] if order_id else None)
    order_id = data.get("orderId")
    if not order_id or status in _FAILED_STATUSES or str(data.get("normalizedStatus") or "").lower() == "failed":
        return _outcome("failed", "Swiggy couldn't place the order.")
    return _placed_outcome([str(order_id)], data)


async def _verify(token: str, address_id: str, outcome: dict, before: set[str] | None) -> dict:
    """Cross-check against get_food_orders: confirms a claimed order, and rescues an ambiguous/failed checkout that
    actually went through (place_food_order is documented as NOT idempotent: a blind retry would double-order).
    Uses a fresh session because the checkout one may be dead after a transport drop."""
    try:
        async with _session(token) as session:
            after = await _active_order_ids(session, address_id)
    except SwiggyError:
        return outcome
    if after is None:
        return outcome
    new_ids = sorted(after - (before or set()))
    if outcome["status"] == "placed":
        return {**outcome, "verified": all(i in after for i in outcome["orderIds"])}
    if outcome["status"] in ("failed", "unknown") and new_ids and before is not None:
        return {**_placed_outcome(new_ids, verified=True), "detail": None}
    return outcome


def _checkout_args(address_id: str, choice: dict) -> dict:
    """Arguments for place_food_order, straight from the option Swiggy listed (ids echoed, not rebuilt)."""
    return {"addressId": address_id, "paymentMethod": choice["methodId"]}


async def checkout(token: str, address_id: str, expected_total: float, key: str, payment_key: str) -> dict:
    if key in _attempts:
        return _attempts[key][1]  # a replayed click / network retry never places an order twice
    account = _account(token)
    if account in _inflight:
        raise SwiggyError("checkout_in_progress", "An order is already being placed. Give it a moment.")
    _inflight.add(account)
    try:
        return _remember(key, await _checkout_locked(token, address_id, expected_total, payment_key))
    finally:
        _inflight.discard(account)


async def _checkout_locked(token: str, address_id: str, expected_total: float, payment_key: str) -> dict:
    async with _session(token) as session:
        address = await _resolve_address(session, address_id)
        cart = await _call(session, "get_food_cart", addressId=address["id"])
        review = _review(cart, await _fetch_payment(session, cart, address["id"], stage="checkout"), address)
        if review["blockers"]:
            raise SwiggyError("cart_blocked", review["blockers"][0])
        # The total the user confirmed already includes any coupon (the cart bills the discounted amount), so this
        # also refuses if a coupon lapsed or was added, or the delivery charge for this address moved.
        if review["total"] is None or abs(review["total"] - expected_total) > 0.005:
            raise SwiggyError("cart_changed", "Your cart total changed. Please review it again before ordering.")
        choice = next((o for o in review["payment"]["options"] if o["key"] == payment_key), None)
        if choice is None:
            raise SwiggyError("payment_unavailable", "That payment method isn't available anymore. Please choose again.")

        before = await _active_order_ids(session, address["id"])
        log.info("[FOOD] placing %s order, total=%s", choice["type"], review["total"])
        try:
            data = await _call(session, "place_food_order", **_checkout_args(address["id"], choice))
        except SwiggyError as exc:
            if exc.code == "auth_required":
                raise
            ambiguous = exc.code == "upstream_unavailable"
            fallback = (
                _outcome("unknown", "We couldn't confirm whether the order went through. Check the Swiggy app before trying again.")
                if ambiguous else _outcome("failed", exc.message)
            )
            return await _verify(token, address["id"], fallback, before)
        except Exception as exc:  # transport drop mid-call: outcome unknown, never assume failure
            log.error("[FOOD] place_food_order transport error: %s", exc)
            fallback = _outcome("unknown", "We couldn't confirm whether the order went through. Check the Swiggy app before trying again.")
            return await _verify(token, address["id"], fallback, before)

        log.warning("[FOOD][diag] place_food_order: keys=%s status=%r normalizedStatus=%r has_orderId=%s", sorted(data), data.get("status"), data.get("normalizedStatus"), bool(data.get("orderId")))
        return await _verify(token, address["id"], _read_placed(data), before)
