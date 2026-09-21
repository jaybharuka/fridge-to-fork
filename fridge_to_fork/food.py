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
import json
import logging
import os
import re

from mcp import ClientSession

from . import swiggy_common
from .swiggy_common import (
    SwiggyError, _call, _fetch_payment as _fetch_payment_common, _num, _outcome, _pick_address, _public_address, _saved_addresses,
    _same_address_id, _same_id, _account, _attempts, _inflight, _remember, _pending_outcome, _settle_payment,
)

log = logging.getLogger("uvicorn.error")

FOOD_MCP_URL = os.environ.get("SWIGGY_FOOD_MCP_URL", "https://mcp.swiggy.com/food")
MAX_RESULTS = 8
MAX_QUANTITY = 20
# Every payment type get_payment_options can list that this app can complete: cash, UPI via the bridge page (QR or an app).
OFFERED_PAYMENT_TYPES = {"cod", "upi_qr", "upi_intent"}

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


def _review(cart: dict, payment: dict, address: dict, fallback_restaurant: dict | None = None) -> dict:
    """`fallback_restaurant` ({id, name}) fills in what the cart doesn't say: the docs type the cart's `restaurant` as
    optional ("the cart API does not always return it"). It only ever comes from the request that built or reviewed
    this very cart, and the cart's own id wins whenever it has one."""
    inner = _inner(cart)
    pricing = inner.get("pricing") or {}
    offers = inner.get("offers") or {}
    restaurant = inner.get("restaurant") or {}
    fallback = fallback_restaurant or {}
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
        "restaurant": {
            "id": restaurant.get("id") if restaurant.get("id") not in (None, "") else (fallback.get("id") or None),
            "name": restaurant.get("name") or fallback.get("name") or None,
            "area": restaurant.get("area"),
            "deliverySubtitle": restaurant.get("deliverySubtitle"),
        },
        "items": items,
        "lineItems": lines,
        "total": to_pay,
        "warning": None,
        "blockers": blockers,
        "canCheckout": not blockers and to_pay is not None,
        "payment": payment,
        "coupon": {"code": offers.get("coupon_applied"), "discount": discount} if discount > 0 else None,
    }


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_CODE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


def _coupon_code(item: dict) -> str:
    """The text apply_food_coupon takes as `couponCode`. The docs give a coupon an `id` and no code field; on a real
    account every id was a UUID (applying with one was refused with an empty body) and the code was the `title`
    ('FLAVORFUL', 'SWIGGYIT': the same text the cart later reports as coupon_applied). So: an id that isn't a UUID is
    the code; otherwise the title, if it is shaped like a code; otherwise there is no usable code ("")."""
    raw_id, title = str(item.get("id") or "").strip(), str(item.get("title") or "").strip()
    if raw_id and not _UUID.match(raw_id):
        return raw_id
    return title if _CODE.match(title) else ""


def _coupon(item: dict) -> dict:
    """One fetch_food_coupons entry; apply_coupon only counts a coupon as applied if the cart then shows the discount."""
    code = _coupon_code(item)
    status = str(item.get("applicabilityStatus") or "").upper()
    applied = status == "APPLIED"  # docs: "already applied to the cart": there is nothing left to apply
    applicable = not applied and item.get("applicable") is not False and (item.get("applicable") is True or status == "APPLICABLE")
    if status == "NOT_APPLICABLE":
        applicable = False
    terms = item.get("terms_and_conditions") or {}
    described, subtitle = item.get("description"), item.get("subtitle")
    message = None if applicable else (subtitle or described)  # why it can't be used, as Swiggy worded it
    description = described or (subtitle if applicable else None)
    return {
        "code": code,
        "title": item.get("title") or code,
        "ribbon": item.get("ribbon_text") if isinstance(item.get("ribbon_text"), str) else None,  # e.g. "₹125 OFF"
        "description": None if description == message else description,  # never the same sentence twice
        "applicable": applicable,
        "applied": applied,
        "message": message,
        "terms": [t for t in terms.get("bullet_texts") or [] if isinstance(t, str)],
    }


def _describe_coupons(data: dict) -> str:
    """Diagnostic: the fields Swiggy sends per coupon entry, to tell a real coupon code from an internal id (the documented
    schema has an `id` and no code field, yet some ids are UUIDs). Offer text only, nothing personal; truncated."""
    def cut(v):
        return None if v is None else str(v)[:60]
    entries = [
        {"id": cut(c.get("id")), "title": cut(c.get("title")), "ribbon": cut(c.get("ribbon_text")), "status": c.get("applicabilityStatus"),
         "keys": sorted(c)}
        for section in data.get("coupon_sections") or [] for c in (section or {}).get("coupons") or [] if isinstance(c, dict)
    ][:12]
    return f"filter_applied={(data.get('summary') or {}).get('filter_applied')!r} n={len(entries)} entries={entries}"


async def _list_coupons(session: ClientSession, restaurant_id: str, address_id: str) -> dict:
    data = await _logged(session, "fetch_food_coupons", restaurantId=restaurant_id, addressId=address_id)
    log.warning("[FOOD][diag] coupons listed: %s", _describe_coupons(data))
    seen: dict[str, dict] = {}
    for section in data.get("coupon_sections") or []:
        for raw in (section or {}).get("coupons") or []:
            coupon = _coupon(raw) if isinstance(raw, dict) else None
            if coupon and coupon["code"]:
                seen.setdefault(coupon["code"].lower(), coupon)
    return {"items": list(seen.values()), "filter": (data.get("summary") or {}).get("filter_applied")}


async def _coupons_or_none(session: ClientSession, restaurant_id: str | None, address_id: str) -> dict:
    """`available: False` = coupons couldn't be listed. Never fails the cart over it; auth problems still propagate."""
    if not restaurant_id:
        return {"available": False, "items": [], "filter": None}
    try:
        return {"available": True, **await _list_coupons(session, str(restaurant_id), address_id)}
    except SwiggyError as exc:
        if exc.code == "auth_required":
            raise
        log.info("[FOOD] fetch_food_coupons unavailable: %s", exc.message)
        return {"available": False, "items": [], "filter": None}


def _describe_cart(update: dict, cart: dict) -> str:
    inner, first = _inner(cart), next((i for i in _inner(cart).get("items") or [] if isinstance(i, dict)), {})
    return (
        f"update_keys={sorted(update)} update_statusCode={update.get('statusCode')!r} update_statusMessage={update.get('statusMessage')!r} "
        f"cart_keys={sorted(cart)} inner_keys={sorted(inner)} item_count={inner.get('item_count')!r} items={len(inner.get('items') or [])} "
        f"restaurant_fields={sorted(inner.get('restaurant') or {})} pricing={inner.get('pricing')} offers={inner.get('offers')} "
        f"first_item_fields={ {k: type(v).__name__ for k, v in first.items()} } "
        f"first_item_raw={json.dumps({k: v for k, v in first.items() if k != 'imageUrl'}, ensure_ascii=False, default=str)[:900]} "
        f"first_item_variants={first.get('variants')!r} first_item_addons={first.get('addons')!r} "
        f"valid_addon_groups={[(g.get('group_id') or g.get('groupId')) for g in first.get('valid_addons') or [] if isinstance(g, dict)]}"
    )


def _describe_identity(cart: dict, address_id: str) -> str:
    """Cart-sync diagnostic: the cart's id, and whether Swiggy returned the (documented as optional) restaurant block.
    Ids and flags only (no names, no amounts), so it is safe to log."""
    inner = _inner(cart)
    restaurant = inner.get("restaurant")
    return (
        f"cart_id={inner.get('cart_id', inner.get('cartId'))!r} restaurant_block_present={isinstance(restaurant, dict) and bool(restaurant)} "
        f"restaurant_id_present={bool(isinstance(restaurant, dict) and restaurant.get('id'))} "
        f"id_like_keys={sorted(k for k in inner if 'id' in k.lower())} items={len(inner.get('items') or [])} addressId={address_id!r}"
    )


async def _logged(session: ClientSession, name: str, **arguments) -> dict:
    """_call, but a refusal is logged with Swiggy's own message first (the route only hands it to the browser), so the
    first real attempt shows WHY a tool said no. Auth expiry is routine and not logged."""
    try:
        return await _call(session, name, **arguments)
    except SwiggyError as exc:
        if exc.code != "auth_required":
            log.warning("[FOOD][diag] %s refused: code=%s message=%.300r", name, exc.code, exc.message)
        raise


async def build_cart(token: str, address_id: str, sel: dict) -> dict:
    """Make Swiggy's Food cart exactly the one reviewed item, then return the real cart.

    flush_food_cart first (a stale item left in the cart would be ordered, and replace-vs-merge isn't documented);
    then the cart is checked to hold exactly what was picked before it is ever offered for ordering.
    """
    async with _session(token) as session:
        address = await _resolve_address(session, address_id)
        await _logged(session, "flush_food_cart")
        name_arg = {"restaurantName": sel["restaurant_name"]} if sel.get("restaurant_name") else {}
        cart_items = [_cart_item(sel)]
        # The cartItems shape is not documented (see _cart_item): log exactly what was sent so it can be checked against
        # what Swiggy accepts. Ids only; the restaurant name is left out.
        log.warning("[FOOD][diag] update_food_cart sent: restaurantId=%r addressId=%r cartItems=%s", sel["restaurant_id"], address["id"], json.dumps(cart_items))
        update = await _logged(session, "update_food_cart", restaurantId=sel["restaurant_id"], cartItems=cart_items, addressId=address["id"], **name_arg)
        cart = await _logged(session, "get_food_cart", addressId=address["id"], **name_arg)
        log.warning("[FOOD][diag] cart: %s", _describe_cart(update, cart))
        log.warning("[FOOD][diag] cart identity: %s", _describe_identity(cart, address["id"]))
        mismatch = _check_cart(cart, sel)
        if mismatch:
            log.warning("[FOOD] cart refused: %s requested_variants=%d requested_addons=%d format=%s", mismatch, len(sel["variants"]), len(sel["addons"]), sel.get("format"))
            raise SwiggyError("cart_mismatch", f"{mismatch} Nothing was ordered. Try again, or order in the Swiggy app.", tool="update_food_cart")
        payment = await _fetch_payment(session, cart, address["id"], stage="cart")
        coupons = await _coupons_or_none(session, sel["restaurant_id"], address["id"])
    review = _review(cart, payment, address, {"id": sel["restaurant_id"], "name": sel.get("restaurant_name")})
    return {"review": review, "adjustments": [], "coupons": coupons}


def _same_items(a: dict, b: dict) -> bool:
    key = lambda review: sorted((i["menuItemId"], i["quantity"]) for i in review["items"])  # noqa: E731
    return key(a) == key(b)


async def apply_coupon(token: str, address_id: str, coupon_code: str, restaurant_id: str | None = None, restaurant_name: str | None = None) -> dict:
    """Apply one of the coupons Swiggy currently lists for this cart, then re-read the cart.

    Everything is re-verified server-side, never trusted from the client: the cart must be orderable and hold the same
    items before and after, the coupon must still be listed AND applicable now, and the cart must then show a positive
    discount with a lower total. (Swiggy: a coupon with discount 0 is only a suggestion, not applied.)

    fetch_food_coupons needs a restaurantId, and the cart doesn't always name its restaurant. So the restaurant the
    reviewed cart was built for (`restaurant_id`, sent back by the review) is used when the cart is silent, and must
    agree with the cart whenever the cart does say. The name is passed to get_food_cart the way build_cart does.
    """
    async with _session(token) as session:
        address = await _resolve_address(session, address_id)
        name_arg = {"restaurantName": restaurant_name} if restaurant_name else {}
        before_cart = await _logged(session, "get_food_cart", addressId=address["id"], **name_arg)
        cart_restaurant = _inner(before_cart).get("restaurant") or {}
        cart_restaurant_id = cart_restaurant.get("id") if cart_restaurant.get("id") not in (None, "") else None
        log.warning(
            "[FOOD][diag] coupon: cart restaurant fields=%s cart_restaurant_id=%r supplied_restaurant_id=%r name_sent=%s",
            sorted(cart_restaurant), cart_restaurant_id, restaurant_id, bool(restaurant_name),
        )
        if cart_restaurant_id is not None and restaurant_id and str(cart_restaurant_id) != str(restaurant_id):
            raise SwiggyError("cart_changed", "Your cart is now for a different restaurant. Please review it again.")
        fallback = {"id": restaurant_id, "name": restaurant_name}
        before = _review(before_cart, await _fetch_payment(session, before_cart, address["id"], stage="coupon-before"), address, fallback)
        if before["blockers"]:
            raise SwiggyError("cart_blocked", before["blockers"][0])
        coupon_restaurant_id = before["restaurant"]["id"]
        if not coupon_restaurant_id:
            raise SwiggyError("cart_blocked", "Swiggy didn't say which restaurant this cart is for. Please review it again.")

        listed = (await _list_coupons(session, str(coupon_restaurant_id), address["id"]))["items"]
        match = next((c for c in listed if c["code"].lower() == coupon_code.strip().lower()), None)
        offers_before = _inner(before_cart).get("offers") or {}
        discount_before = _num(offers_before.get("coupon_discount")) or 0
        applied_before = str(offers_before.get("coupon_applied") or "").strip()
        log.warning(
            "[FOOD][diag] apply_food_coupon requested: couponCode=%r listed=%s offers_before={coupon_applied: %r, coupon_discount: %r}",
            coupon_code, [(c["code"], "applicable" if c["applicable"] else "applied" if c["applied"] else "not_applicable") for c in listed],
            applied_before or None, discount_before,
        )
        if match is None:
            raise SwiggyError("coupon_not_found", "That coupon isn't available for this cart anymore.")
        # Swiggy: coupon_applied with a discount of 0 is only a suggestion; only a positive discount is an applied coupon.
        already_applied = discount_before > 0 and applied_before != ""
        if match["applied"] or (already_applied and applied_before.lower() == match["code"].lower()):
            # Applying it again would only be rejected (or leave the total unchanged and read as a failure): it is already
            # on the cart, so report that, unchanged.
            return {
                "review": before,
                "coupon": {"code": match["code"], "title": match["title"], "savings": discount_before or None},
                "coupons": await _coupons_or_none(session, str(coupon_restaurant_id), address["id"]),
                "alreadyApplied": True,
            }
        if already_applied:
            # There is no remove-coupon tool, so a second coupon can't replace the first: say so instead of sending a call
            # Swiggy has no way to honour (rebuilding the cart is the only way to start without a coupon).
            raise SwiggyError(
                "coupon_already_applied",
                f"{applied_before} is already applied to this cart, and Swiggy doesn't let us swap it. Use Edit dish to rebuild the cart if you want a different coupon.",
            )
        if not match["applicable"]:
            raise SwiggyError("coupon_not_applicable", match["message"] or "That coupon can't be applied to this cart.")

        await _logged(session, "apply_food_coupon", couponCode=match["code"], addressId=address["id"])
        after_cart = await _logged(session, "get_food_cart", addressId=address["id"], **name_arg)
        payment = await _fetch_payment(session, after_cart, address["id"], stage="coupon-after")
        relisted = await _coupons_or_none(session, str(coupon_restaurant_id), address["id"])
        after = _review(after_cart, payment, address, fallback)

    offers = _inner(after_cart).get("offers") or {}
    discount = _num(offers.get("coupon_discount")) or 0
    applied = offers.get("coupon_applied")
    dropped = before["total"] is not None and after["total"] is not None and after["total"] < before["total"] - 0.005
    log.warning("[FOOD][diag] coupon: code_listed=%s applied=%r discount=%r total_before=%r total_after=%r", match["code"], applied, discount, before["total"], after["total"])
    if not _same_items(before, after):
        raise SwiggyError("cart_changed", "Your cart changed while applying the coupon. Please review it again.")
    if discount <= 0 or not dropped or (applied and str(applied).strip().lower() != match["code"].lower()):
        raise SwiggyError(
            "coupon_not_reflected",
            "Swiggy accepted the code but your total didn't change, so it wasn't counted. Use Edit dish to rebuild the cart if you want to be sure.",
        )
    return {
        "review": after,
        "coupon": {"code": match["code"], "title": match["title"], "savings": round(before["total"] - after["total"], 2)},
        "coupons": relisted,
    }


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


def _read_placed(data: dict, expected: float | None = None) -> dict:
    """place_food_order `data` -> outcome. COD is placed immediately (status CONFIRMED)."""
    status = str(data.get("status") or "").upper()
    order_id = data.get("orderId")
    if not order_id or status in _FAILED_STATUSES or str(data.get("normalizedStatus") or "").lower() == "failed":
        return _outcome("failed", "Swiggy couldn't place the order.")
    outcome = _placed_outcome([str(order_id)], data)
    charged = _num(data.get("totalAmount"))
    if expected is not None and charged is not None and abs(charged - expected) > 0.005:
        # e.g. a coupon that only holds for online payment: the order exists, but not at the price the user reviewed
        log.warning("[FOOD] placed total differs from the reviewed total: reviewed=%s placed=%s", expected, charged)
        outcome["notice"] = f"Swiggy's order total is ₹{charged:g}, not the ₹{expected:g} you reviewed. Check the Swiggy app."
    return outcome


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _food_pending(data: dict, address_id: str) -> dict:
    """place_food_order returned PENDING_PAYMENT. Food confirms with addressId + cartId + lat + lng echoed from this
    response (not paasId), so they ride along in `payment` and come back on every poll."""
    echo = {"addressId": str(data.get("addressId") or address_id), "cartId": None if data.get("cartId") in (None, "") else str(data["cartId"]), "lat": _number(data.get("lat")), "lng": _number(data.get("lng"))}
    log.warning("[FOOD][diag] place_food_order pending: keys=%s has_paasId=%s has_bridgeUrl=%s has_cartId=%s has_lat_lng=%s", sorted(data), bool(data.get("paasId")), bool(data.get("bridgeUrl")), echo["cartId"] is not None, echo["lat"] is not None and echo["lng"] is not None)
    return _pending_outcome(data, total=data.get("totalAmount"), echo=echo)


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
    base = {"addressId": address_id}
    if choice["type"] == "cod":
        return {**base, "paymentMethod": choice["methodId"]}
    if choice["type"] == "upi_qr":
        return {**base, "paymentMethod": "UPI", "generateUPIQR": True}
    return {**base, "paymentMethod": "UPI", "intentApp": choice["methodId"]}


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
        place_args = _checkout_args(address["id"], choice)
        # The exact payment method value sent (cod.id echoed, or the documented "Cash" fallback) is an open question.
        log.warning("[FOOD][diag] place_food_order sent: %s", json.dumps(place_args))
        try:
            data = await _call(session, "place_food_order", **place_args)
        except SwiggyError as exc:
            if exc.code == "auth_required":
                raise
            log.warning("[FOOD][diag] place_food_order refused: code=%s message=%.300r", exc.code, exc.message)
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
        if str(data.get("status") or "").upper() == "PENDING_PAYMENT":
            return _food_pending(data, address["id"])  # not an order yet: the payment page + payment_status() finish it
        return await _verify(token, address["id"], _read_placed(data, expected_total), before)


async def payment_status(
    token: str, order_id: str, paas_id: str, address_id: str, cart_id: str | None, lat: float | None, lng: float | None, final: bool = False
) -> dict:
    """One poll of a pending UPI payment (see swiggy_common._settle_payment). Food is identified by orderId + the
    addressId/cartId/lat/lng that place_food_order returned, echoed exactly; it never uses paasId to confirm."""
    echo = {"addressId": address_id, **({"cartId": cart_id} if cart_id else {}), **({"lat": lat} if lat is not None else {}), **({"lng": lng} if lng is not None else {})}
    async with _session(token) as session:
        outcome = await _settle_payment(
            session, order_id, check_args={"paasId": paas_id, "orderId": order_id, **echo}, confirm_args={"orderId": order_id, **echo}, final=final
        )
    return await _verify(token, address_id, outcome, None) if outcome["status"] == "placed" else outcome
