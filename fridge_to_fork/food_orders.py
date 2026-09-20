"""
Food order history, live delivery status and order details (POST mcp.swiggy.com/food).

Written against Swiggy's Food reference pages (get_food_orders, get_food_delivery_status, track_food_order,
get_food_order_details):

  get_food_orders(addressId, activeOnly)  -> data.orders[]: orderId, restaurantName, orderTotal (string), orderStatus,
                                             orderDeliveryStatus?, orderedItems (string), orderedTime (string), isActiveOrder
  get_food_delivery_status(orderId)       -> ETA + delivered/cancelled flags, pollIntervalSec (same shape as Instamart's)
  track_food_order(orderId?)              -> orders[]: title, subtitle, etaText, orderStatus, progressPercentage.
                                             Without an orderId it returns ALL active orders, so the entry for the
                                             requested order is picked out by id and nothing else is ever shown.
  get_food_order_details(orderId)         -> data.order: items, charges, totals, status. `OrderItem` and
                                             `DeliveryAddress` are not defined in the docs, so items are read
                                             tolerantly and the delivery address (personal data) is never forwarded.

Unlike Instamart, no tool here needs coordinates. get_food_orders requires an addressId and the docs don't say
whether it scopes the list to that address, so the address used is returned (and logged) with the list.
Cancellation has no tool: Swiggy says to call customer care.
"""

import re

from . import food
from .instamart_orders import _delivery
from .swiggy_common import SwiggyError, _call, _num, log

CANCEL_HELP = "To cancel an order, call Swiggy customer care on 080-67466729."
UNAVAILABLE_DETAILS = "Order details aren't available for this order."


def _order_row(o: dict) -> dict:
    return {
        "orderId": str(o["orderId"]),
        "restaurant": o.get("restaurantName") or "",
        "area": o.get("restaurantAreaName"),
        "status": o.get("orderStatus") or "",
        "deliveryStatus": o.get("orderDeliveryStatus"),
        "total": o.get("orderTotal"),  # a display string exactly as Swiggy formats it
        "items": o.get("orderedItems"),  # likewise a display string
        "orderedTime": o.get("orderedTime"),  # format isn't documented: shown as given, never parsed
        # Swiggy's own boolean, not a guess from the status text (whose values aren't documented)
        "active": bool(o.get("isActiveOrder")),
    }


def _describe_orders(data, address_id: str, active_only: bool) -> str:
    """Shape of a get_food_orders `data` for the log: counts, field names, status values, timestamps. No addresses,
    names, phone numbers or item names, only structure and identifiers."""
    if not isinstance(data, dict):
        return f"data is {type(data).__name__}"
    raw = data.get("orders")
    orders = [o for o in raw if isinstance(o, dict)] if isinstance(raw, list) else []
    first = orders[0] if orders else {}
    return (
        f"addressId={address_id!r} activeOnly={active_only} data_keys={sorted(data)} orders_is={type(raw).__name__} returned={len(orders)} "
        f"without_orderId={sum(1 for o in orders if not o.get('orderId'))} "
        f"orderStatus={sorted({str(o.get('orderStatus')) for o in orders})} orderDeliveryStatus={sorted({str(o.get('orderDeliveryStatus')) for o in orders})} "
        f"isActiveOrder={sorted({str(o.get('isActiveOrder')) for o in orders})} orderedTime={[o.get('orderedTime') for o in orders][:5]} "
        f"action_types={sorted({str(a.get('type')) for o in orders for a in o.get('actions') or [] if isinstance(a, dict)})} "
        f"first_order_fields={ {k: type(v).__name__ for k, v in first.items()} } orderIds={[str(o.get('orderId')) for o in orders][:10]}"
    )


async def list_orders(token: str, address_id: str | None, active_only: bool = False) -> dict:
    async with food._session(token) as session:
        address = await food._resolve_address(session, address_id)
        data = await _call(session, "get_food_orders", addressId=address["id"], activeOnly=active_only)
    log.warning("[FOOD][diag] get_food_orders: %s", _describe_orders(data, address["id"], active_only))
    orders = [_order_row(o) for o in data.get("orders") or [] if isinstance(o, dict) and o.get("orderId")]
    log.warning("[FOOD][diag] get_food_orders parsed: kept=%d active=%d", len(orders), sum(1 for o in orders if o["active"]))
    return {"address": address, "orders": orders}


def _percent(value) -> float | None:
    """progressPercentage is a string ("75"). Read it strictly, sign included (the shared _num ignores a minus), then clamp."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*%?\s*", str(value or ""))
        if not match:
            return None
        number = float(match.group(1))
    return min(max(number, 0.0), 100.0)


def _tracking(data: dict, order_id: str) -> dict | None:
    """track_food_order `data`: only the entry for `order_id`. It returns every active order when asked without one
    and may return more than the one asked for; another order's status must never be shown as this one's."""
    entry = next((o for o in data.get("orders") or [] if isinstance(o, dict) and str(o.get("orderId")) == order_id), None)
    if entry is None:
        return None
    return {
        "title": entry.get("title"),
        "subtitle": entry.get("subtitle"),
        "etaText": entry.get("etaText"),
        "status": entry.get("orderStatus"),
        "progress": _percent(entry.get("progressPercentage")),
    }


async def order_status(token: str, order_id: str) -> dict:
    """Live status for one order. Each source degrades independently: an unrolled-out tool leaves that part null with
    a note, never an error for the whole screen. No coordinates are needed for either tool."""
    delivery = tracking = None
    notes: list[str] = []
    async with food._session(token) as session:
        try:
            data = await _call(session, "get_food_delivery_status", orderId=order_id)
            if str(data.get("orderId")) == order_id:
                delivery = _delivery(data)
            else:
                log.warning("[FOOD] get_food_delivery_status answered for another order: asked=%r got=%r", order_id, data.get("orderId"))
        except SwiggyError as exc:
            if exc.code == "auth_required":
                raise
            log.info("[FOOD] get_food_delivery_status unavailable: %s", exc.message)
            notes.append("Live delivery status isn't available for this order right now.")
        try:
            data = await _call(session, "track_food_order", orderId=order_id)
            tracking = _tracking(data, order_id)
            log.warning(
                "[FOOD][diag] track_food_order: keys=%s orders=%d matched=%s statuses=%s",
                sorted(data), len(data.get("orders") or []), tracking is not None,
                sorted({str(o.get("orderStatus")) for o in data.get("orders") or [] if isinstance(o, dict)}),
            )
        except SwiggyError as exc:
            if exc.code == "auth_required":
                raise
            log.info("[FOOD] track_food_order unavailable: %s", exc.message)
    return {"delivery": delivery, "tracking": tracking, "notes": notes}


def _detail_item(i: dict) -> dict:
    """OrderItem isn't documented: read the fields a cart line has, tolerantly, and show only what is found."""
    price = next((n for n in (_num(i.get(k)) for k in ("final_price", "total", "subtotal", "price")) if n is not None), None)
    return {
        "name": i.get("name") or i.get("item_name") or "",
        "quantity": i.get("quantity"),
        "price": price,
        "options": [x.get("name") for k in ("variants", "addons") for x in i.get(k) or [] if isinstance(x, dict) and x.get("name")],
    }


def _details(data: dict, order_id: str) -> dict:
    o = data.get("order")
    if not isinstance(o, dict) or str(o.get("order_id")) != order_id:
        return {"available": False, "message": UNAVAILABLE_DETAILS}  # never show a different order's details
    address = o.get("delivery_address")
    log.warning(
        "[FOOD][diag] get_food_order_details: order_fields=%s item_fields=%s delivery_address_fields=%s charge_labels=%s",
        sorted(o), sorted({k for i in o.get("order_items") or [] if isinstance(i, dict) for k in i}),
        sorted(address) if isinstance(address, dict) else type(address).__name__, sorted(o.get("charges") or {}),
    )
    charges = o.get("charges") if isinstance(o.get("charges"), dict) else {}
    return {
        "available": True,
        "orderId": order_id,
        "status": o.get("order_status"),
        "restaurant": {"name": o.get("restaurant_name"), "area": o.get("restaurant_area_name") or o.get("restaurant_locality")},
        "items": [_detail_item(i) for i in o.get("order_items") or [] if isinstance(i, dict)],
        "charges": [{"label": str(k), "value": str(v)} for k, v in charges.items()],
        "itemTotal": _num(o.get("item_total")),
        "delivery": _num(o.get("order_delivery_charge")),
        "tax": _num(o.get("order_tax")),
        "discount": _num(o.get("order_discount")),
        "coupon": {"code": o.get("coupon_applied"), "discount": _num(o.get("coupon_discount"))} if o.get("is_coupon_applied") and o.get("coupon_applied") else None,
        "total": _num(o.get("order_total")),
        "paymentMethod": o.get("payment_method"),
        "orderTime": o.get("order_time"),
        "cancellable": bool(o.get("is_cancellable")),
        "cancelHelp": CANCEL_HELP if o.get("is_cancellable") else None,
    }


async def order_details(token: str, order_id: str) -> dict:
    """Itemized order. A refusal is reported as unavailable (the UI falls back to the list row), not as a failure."""
    async with food._session(token) as session:
        try:
            return {"details": _details(await _call(session, "get_food_order_details", orderId=order_id), order_id)}
        except SwiggyError as exc:
            if exc.code == "auth_required":
                raise
            log.info("[FOOD] get_food_order_details unavailable: %s", exc.message)
            return {"details": {"available": False, "message": UNAVAILABLE_DETAILS}}

