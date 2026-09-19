"""
HTTP surface for the staged Instamart flow (see instamart.py).

  POST /api/instamart/search    {items, address_id?}                      -> {address, results[]}
  POST /api/instamart/addresses {}                                        -> {addresses[], defaultId}
  POST /api/instamart/address   {...new address}                          -> {addressId, addresses[], defaultId}
  POST /api/instamart/address-delete {address_id}                         -> {addresses[], defaultId}
  POST /api/instamart/go-to-items {address_id}                            -> {results[]}
  POST /api/instamart/cart      {address_id, selections[]}                -> {review, adjustments[], coupons}
  POST /api/instamart/coupon    {address_id, coupon_code}                 -> {review, coupon, coupons}
  POST /api/instamart/checkout  {address_id, expected_total, idempotency_key, payment_key} -> {order}
  POST /api/instamart/payment-status {order_id, paas_id, final}           -> {order}
  POST /api/instamart/orders    {active_only}                             -> {orders[], hasMore}
  POST /api/instamart/order-status  {order_id, address_id?, lat?, lng?}   -> {delivery, tracking, notes[]}
  POST /api/instamart/order-details {order_id}                            -> {details}

Every response is `{ok: true, ...}` or `{ok: false, error: {code, message}}`.
HTTP status is 401 for auth_required and 502 for upstream failures; Swiggy
domain failures (cart changed, minimum not met, ...) are 200 + ok:false, the
same way Swiggy itself reports them.
"""

from typing import Annotated, Awaitable, Callable, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints, model_validator

from . import instamart, instamart_addresses, instamart_orders
from .instamart import InstamartError

Ingredient = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Id = Annotated[str, StringConstraints(min_length=1, max_length=120)]


class SearchRequest(BaseModel):
    items: list[Ingredient] = Field(min_length=1, max_length=25)
    # A saved address the user picked; verified server-side. Omitted = Home/first.
    address_id: Id | None = None


class Selection(BaseModel):
    spin_id: Id
    sku_id: Id
    quantity: int = Field(ge=1, le=20)


class CartRequest(BaseModel):
    address_id: Id
    selections: list[Selection] = Field(min_length=1, max_length=40)


Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+?\d{10,15}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None


class AddressRequest(BaseModel):
    """Fields of create_address. The account holder's name/phone are required by Swiggy."""
    full_address: Text
    address_line: Text
    address_line2: Text
    city: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    postal_code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]
    address_category: Literal["HOME", "WORK", "OFFICE", "FRIENDS_AND_FAMILY", "OTHER"]
    user_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    user_phone: Phone
    locality: OptText = None
    address_tag: OptText = None
    # Real coordinates only (e.g. from the device's location, with the user's consent); Swiggy
    # auto-resolves them if omitted but never returns what it resolved. Both or neither.
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _both_coordinates_or_none(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class AddressDeleteRequest(BaseModel):
    address_id: Id


class GoToRequest(BaseModel):
    address_id: Id


class OrdersRequest(BaseModel):
    active_only: bool = False


class OrderStatusRequest(BaseModel):
    order_id: Id
    address_id: Id | None = None
    # track_order needs real delivery coordinates (Swiggy exposes none); both or neither.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _both_coordinates_or_none(self):
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must be provided together")
        return self


class OrderDetailsRequest(BaseModel):
    order_id: Id


class CouponRequest(BaseModel):
    address_id: Id
    coupon_code: str = Field(min_length=1, max_length=64)


class PaymentStatusRequest(BaseModel):
    order_id: Id
    paas_id: Id
    final: bool = False  # polling deadline reached: confirm once and let Swiggy reconcile


class CheckoutRequest(BaseModel):
    address_id: Id
    expected_total: str = Field(min_length=1, max_length=32)
    # One of the option keys from the review's `payment.options`; re-validated against Swiggy at checkout.
    payment_key: str = Field(min_length=1, max_length=200)
    # One key per reviewed cart: a double-click or network retry replays the
    # stored result instead of running checkout (non-idempotent) twice.
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _error(exc: InstamartError) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)


def _dedupe(items: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for item in items:
        seen.setdefault(item.lower(), item)
    return list(seen.values())


def make_router(get_token: Callable[[Request], str | None]) -> APIRouter:
    """`get_token` resolves the caller's Swiggy access token (bearer header or session cookie)."""
    router = APIRouter(prefix="/api/instamart")

    async def run(request: Request, action: Callable[[str], Awaitable[dict]]):
        token = get_token(request)
        if not token:
            return _error(InstamartError("auth_required", "Connect your Swiggy account to continue.", 401))
        try:
            return {"ok": True, **await action(token)}
        except InstamartError as exc:
            return _error(exc)

    @router.post("/search")
    async def search(body: SearchRequest, request: Request):
        return await run(request, lambda t: instamart.search_ingredients(t, _dedupe(body.items), body.address_id))

    @router.post("/cart")
    async def cart(body: CartRequest, request: Request):
        selections = [s.model_dump() for s in body.selections]
        return await run(request, lambda t: instamart.build_cart(t, body.address_id, selections))

    @router.post("/coupon")
    async def coupon(body: CouponRequest, request: Request):
        return await run(request, lambda t: instamart.apply_coupon(t, body.address_id, body.coupon_code))

    @router.post("/checkout")
    async def checkout(body: CheckoutRequest, request: Request):
        async def act(token: str) -> dict:
            order = await instamart.checkout(token, body.address_id, body.expected_total, body.idempotency_key, body.payment_key)
            return {"order": order}

        return await run(request, act)

    @router.post("/payment-status")
    async def payment_status(body: PaymentStatusRequest, request: Request):
        async def act(token: str) -> dict:
            return {"order": await instamart.payment_status(token, body.order_id, body.paas_id, body.final)}

        return await run(request, act)

    @router.post("/addresses")
    async def addresses(request: Request):
        return await run(request, instamart_addresses.list_addresses)

    @router.post("/address")
    async def create_address(body: AddressRequest, request: Request):
        return await run(request, lambda t: instamart_addresses.create_address(t, body.model_dump(exclude_none=True)))

    @router.post("/address-delete")
    async def delete_address(body: AddressDeleteRequest, request: Request):
        return await run(request, lambda t: instamart_addresses.delete_address(t, body.address_id))

    @router.post("/go-to-items")
    async def go_to_items(body: GoToRequest, request: Request):
        return await run(request, lambda t: instamart_addresses.go_to_items(t, body.address_id))

    @router.post("/orders")
    async def orders(body: OrdersRequest, request: Request):
        return await run(request, lambda t: instamart_orders.list_orders(t, body.active_only))

    @router.post("/order-status")
    async def order_status(body: OrderStatusRequest, request: Request):
        return await run(request, lambda t: instamart_orders.order_status(t, body.order_id, body.address_id, body.lat, body.lng))

    @router.post("/order-details")
    async def order_details(body: OrderDetailsRequest, request: Request):
        return await run(request, lambda t: instamart_orders.order_details(t, body.order_id))

    return router
