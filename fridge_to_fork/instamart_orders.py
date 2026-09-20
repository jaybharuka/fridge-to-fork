"""
Order history, live delivery status and order details for Instamart (POST mcp.swiggy.com/im).

Written against Swiggy's reference docs (reference/instamart/get_orders, get_delivery_status,
track_order, get_order_details):

  get_orders(orderType, activeOnly, count)     -> data.orders[] (address is text only, no id)
  get_delivery_status(orderId, addressId)      -> ETA + delivered/cancelled flags, pollIntervalSec
  track_order(orderId, lat, lng)               -> rich tracking; lat/lng are REQUIRED and Swiggy
                                                  offers no source for them (get_addresses omits
                                                  coordinates), so it is only called when the
                                                  caller supplies real ones. Never guessed.
  get_order_details(orderId)                   -> itemized bill; "not rolled out for every user"
"""

import re

from . import instamart
from .instamart import InstamartError, _call, _num, log

MIN_POLL_SECONDS = 10  # the docs' floor: never poll a tracking tool faster than it asks
MAX_POLL_SECONDS = 60
DEFAULT_POLL_SECONDS = 30


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _poll_seconds(value) -> int:
    seconds = _num(value)
    return int(min(max(seconds, MIN_POLL_SECONDS), MAX_POLL_SECONDS)) if seconds else DEFAULT_POLL_SECONDS


def _match_address_id(address_line: str | None, saved: list[dict]) -> str | None:
    """get_orders only returns the address as text; recover its id from the saved addresses."""
    want = _norm(address_line)
    if not want:
        return None
    for a in saved:
        if _norm(a.get("addressLine")) == want:
            return a.get("id")
    for a in saved:  # tolerate one side being a truncated form of the other
        have = _norm(a.get("addressLine"))
        if have and (have in want or want in have):
            return a.get("id")
    return None


def _order_summary(order: dict, saved: list[dict]) -> dict:
    line = (order.get("deliveryAddress") or {}).get("addressLine")
    return {
        "orderId": str(order.get("orderId") or ""),
        "status": order.get("currentStatus") or order.get("status") or "",
        "createdAt": order.get("createdAt"),
        "estimatedDeliveryTime": order.get("estimatedDeliveryTime"),
        "itemCount": order.get("itemCount"),
        "totalAmount": _num(order.get("totalAmount")),
        "paymentMethod": order.get("paymentMethod"),
        "items": [{"name": i.get("name") or "", "quantity": i.get("quantity")} for i in order.get("items") or []],
        "deliveryAddress": line,
        "addressId": _match_address_id(line, saved),
    }


def _describe_orders(data) -> str:
    """Shape of a get_orders `data` for the log: counts, field names, status values, timestamps. No addresses,
    names, phone numbers or item names, only structure and identifiers."""
    if not isinstance(data, dict):
        return f"data is {type(data).__name__}"
    raw = data.get("orders")
    orders = [o for o in raw if isinstance(o, dict)] if isinstance(raw, list) else []
    first = orders[0] if orders else {}
    address = first.get("deliveryAddress")
    return (
        f"data_keys={sorted(data)} orders_is={type(raw).__name__} returned={len(orders)} hasMore={data.get('hasMore')!r} "
        f"without_orderId={sum(1 for o in orders if not o.get('orderId'))} "
        f"status={sorted({str(o.get('status')) for o in orders})} currentStatus={sorted({str(o.get('currentStatus')) for o in orders})} "
        f"isActive={sorted({str(o.get('isActive')) for o in orders})} createdAt={[o.get('createdAt') for o in orders][:10]} "
        f"first_order_fields={ {k: type(v).__name__ for k, v in first.items()} } "
        f"first_deliveryAddress_fields={sorted(address) if isinstance(address, dict) else type(address).__name__} "
        f"orderIds={[str(o.get('orderId')) for o in orders][:10]}"
    )


async def _probe_without_order_type(session) -> str:
    """Diagnostic only, run when INSTAMART came back empty: does get_orders with no orderType (Swiggy's own default)
    list anything? Logged, never shown."""
    try:
        return _describe_orders(await _call(session, "get_orders", activeOnly=False, count=10))
    except InstamartError as exc:
        return f"probe failed: {exc.code} {exc.message}"


async def list_orders(token: str, active_only: bool = False) -> dict:
    async with instamart._session(token) as session:
        data = await _call(session, "get_orders", orderType="INSTAMART", activeOnly=active_only, count=10)
        log.warning("[INSTAMART][diag] get_orders (orderType=INSTAMART activeOnly=%s count=10): %s", active_only, _describe_orders(data))
        if not (data.get("orders") or []):
            log.warning("[INSTAMART][diag] get_orders returned nothing; raw data=%.300r | same call with no orderType: %s", data, await _probe_without_order_type(session))
        try:
            saved = (await _call(session, "get_addresses")).get("addresses") or []
        except InstamartError as exc:
            if exc.code == "auth_required":
                raise
            saved = []
    orders = [_order_summary(o, saved) for o in data.get("orders") or [] if o.get("orderId")]
    log.warning("[INSTAMART][diag] get_orders parsed: kept=%d with_address_id=%d", len(orders), sum(1 for o in orders if o["addressId"]))
    return {"orders": orders, "hasMore": bool(data.get("hasMore"))}


def _delivery(data: dict) -> dict:
    """get_delivery_status `data`. ETA math uses Swiggy's own serverNow, not our clock."""
    delivery_by, server_now = data.get("deliveryBy"), data.get("serverNow")
    minutes = None
    if isinstance(delivery_by, (int, float)) and isinstance(server_now, (int, float)):
        minutes = max(round((delivery_by - server_now) / 60_000), 0)
    delivered, cancelled = bool(data.get("delivered")), bool(data.get("cancelled"))
    return {
        "statusText": data.get("statusText"),
        "etaText": data.get("etaText"),
        "minutesLeft": minutes,
        "delivered": delivered,
        "cancelled": cancelled,
        "terminal": delivered or cancelled,  # docs: stop polling when either is true
        "pollIntervalSec": _poll_seconds(data.get("pollIntervalSec")),
    }


def _point(loc: dict | None) -> dict | None:
    if not isinstance(loc, dict) or loc.get("latitude") is None or loc.get("longitude") is None:
        return None
    return {"lat": loc["latitude"], "lng": loc["longitude"]}


def _tracking(data: dict) -> dict:
    """track_order `data`."""
    status = data.get("status") or {}
    map_info = data.get("mapInfo") or {}
    return {
        "title": data.get("orderTitle"),
        "subtitle": data.get("orderSubtitle"),
        "statusMessage": status.get("statusMessage"),
        "subStatusMessage": status.get("subStatusMessage"),
        "etaMinutes": status.get("etaMinutes"),
        "etaText": status.get("etaText"),
        "store": (data.get("storeInfo") or {}).get("name"),
        "paymentMessage": (data.get("paymentInfo") or {}).get("message"),
        "riderLocation": _point(map_info.get("riderLocation")),
        "storeLocation": _point(map_info.get("storeLocation")),
        "pollIntervalSec": _poll_seconds(data.get("pollingIntervalSeconds")),
    }


async def order_status(token: str, order_id: str, address_id: str | None, lat: float | None, lng: float | None) -> dict:
    """Live status for one order. Each source degrades independently: a missing address id or an
    unrolled-out tool leaves that part null with a note, never an error for the whole screen."""
    delivery = tracking = None
    notes: list[str] = []
    async with instamart._session(token) as session:
        if address_id:
            try:
                delivery = _delivery(await _call(session, "get_delivery_status", orderId=order_id, addressId=address_id))
            except InstamartError as exc:
                if exc.code == "auth_required":
                    raise
                log.info("[INSTAMART] get_delivery_status unavailable: %s", exc.message)
                notes.append("Live delivery status isn't available for this order right now.")
        else:
            notes.append("Live delivery status needs the order's delivery address, which we couldn't identify.")
        if lat is not None and lng is not None:
            try:
                tracking = _tracking(await _call(session, "track_order", orderId=order_id, lat=lat, lng=lng))
            except InstamartError as exc:
                if exc.code == "auth_required":
                    raise
                log.info("[INSTAMART] track_order unavailable: %s", exc.message)
    return {"delivery": delivery, "tracking": tracking, "notes": notes}


def _details(data: dict) -> dict:
    bill = data.get("bill") or {}
    return {
        "available": True,
        "orderId": data.get("orderId"),
        "status": data.get("status"),
        "totalBill": _num(data.get("totalBill")),
        "hasRefunds": bool(data.get("hasRefunds")),
        "items": [
            {"name": i.get("name") or "", "quantity": i.get("quantity"), "finalPrice": _num(i.get("finalPrice")), "removed": bool(i.get("removed"))}
            for i in data.get("items") or []
        ],
        "bill": {
            "lineItems": [{"name": li.get("name"), "amount": li.get("amount")} for li in bill.get("lineItems") or []],
            "grandTotal": bill.get("grandTotal"),
        },
    }


async def order_details(token: str, order_id: str) -> dict:
    """Itemized order. The docs say get_order_details isn't rolled out to every account, so a
    refusal is reported as unavailable (the UI falls back to the list row), not as a failure."""
    async with instamart._session(token) as session:
        try:
            return {"details": _details(await _call(session, "get_order_details", orderId=order_id))}
        except InstamartError as exc:
            if exc.code == "auth_required":
                raise
            log.info("[INSTAMART] get_order_details unavailable: %s", exc.message)
            return {"details": {"available": False, "message": "Order details aren't available for this order."}}
