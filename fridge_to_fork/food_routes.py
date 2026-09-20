"""
HTTP surface for the staged Food flow (see food.py).

  POST /api/food/search    {dish, address_id?}                                        -> {address, dish, results[], hasMore}
  POST /api/food/cart      {address_id, selection}                                    -> {review, adjustments[], coupons}
  POST /api/food/coupon    {address_id, coupon_code}                                  -> {review, coupon, coupons}
  POST /api/food/checkout  {address_id, expected_total, idempotency_key, payment_key} -> {order}
  POST /api/food/payment-status {order_id, paas_id, address_id, cart_id?, lat?, lng?, final} -> {order}
  POST /api/food/orders    {address_id?, active_only}                                 -> {address, orders[]}
  POST /api/food/order-status  {order_id}                                             -> {delivery, tracking, notes[]}
  POST /api/food/order-details {order_id}                                             -> {details}

Every response is `{ok: true, ...}` or `{ok: false, error: {code, message}}`, the same envelope as the Instamart
routes. While FOOD_ORDERING_ENABLED is off every route refuses, before it even looks at auth.
"""

from typing import Annotated, Awaitable, Callable, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StringConstraints

from . import features, food, food_orders
from .swiggy_common import SwiggyError, error_response

Id = Annotated[str, StringConstraints(min_length=1, max_length=120)]


class SearchRequest(BaseModel):
    dish: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    address_id: Id | None = None  # a saved address the user picked; verified server-side. Omitted = Home/first.


class VariantPick(BaseModel):
    group_id: Id
    variation_id: Id


class AddonPick(BaseModel):
    group_id: Id
    addon_id: Id
    quantity: int = Field(default=1, ge=1, le=10)


class Selection(BaseModel):
    restaurant_id: Id
    restaurant_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    menu_item_id: Id
    quantity: int = Field(ge=1, le=food.MAX_QUANTITY)
    # Which cart field the item's customizations use (search_menu returns one or the other, never both).
    format: Literal["variants", "variantsV2"] | None = None
    variants: list[VariantPick] = Field(default_factory=list, max_length=10)
    addons: list[AddonPick] = Field(default_factory=list, max_length=30)


class CartRequest(BaseModel):
    address_id: Id
    selection: Selection


class CouponRequest(BaseModel):
    address_id: Id
    coupon_code: str = Field(min_length=1, max_length=64)


class PaymentStatusRequest(BaseModel):
    order_id: Id
    paas_id: Id
    # Echoed from place_food_order's PENDING_PAYMENT reply: Food confirms with these, not with paasId.
    address_id: Id
    cart_id: Id | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    final: bool = False  # polling deadline reached: confirm once and let Swiggy reconcile


class OrdersRequest(BaseModel):
    address_id: Id | None = None  # get_food_orders needs an address; omitted = Home/first
    active_only: bool = False


class OrderRefRequest(BaseModel):
    order_id: Id


class CheckoutRequest(BaseModel):
    address_id: Id
    expected_total: float = Field(gt=0, lt=100_000)
    # One of the option keys from the review's `payment.options`; re-validated against Swiggy at checkout.
    payment_key: str = Field(min_length=1, max_length=200)
    # One key per reviewed cart: a double-click or network retry replays the stored result instead of
    # running place_food_order (documented as NOT idempotent) twice.
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def make_router(get_token: Callable[[Request], str | None]) -> APIRouter:
    """`get_token` resolves the caller's Swiggy access token (bearer header or session cookie)."""
    router = APIRouter(prefix="/api/food")

    async def run(request: Request, action: Callable[[str], Awaitable[dict]]):
        if not features.FOOD_ORDERING_ENABLED:
            return error_response(SwiggyError("food_disabled", features.FOOD_UNAVAILABLE_MESSAGE, 403))
        token = get_token(request)
        if not token:
            return error_response(SwiggyError("auth_required", "Connect your Swiggy account to continue.", 401))
        try:
            return {"ok": True, **await action(token)}
        except SwiggyError as exc:
            return error_response(exc)

    @router.post("/search")
    async def search(body: SearchRequest, request: Request):
        return await run(request, lambda t: food.search_dish(t, body.dish, body.address_id))

    @router.post("/cart")
    async def cart(body: CartRequest, request: Request):
        return await run(request, lambda t: food.build_cart(t, body.address_id, body.selection.model_dump()))

    @router.post("/coupon")
    async def coupon(body: CouponRequest, request: Request):
        return await run(request, lambda t: food.apply_coupon(t, body.address_id, body.coupon_code))

    @router.post("/payment-status")
    async def payment_status(body: PaymentStatusRequest, request: Request):
        async def act(token: str) -> dict:
            order = await food.payment_status(token, body.order_id, body.paas_id, body.address_id, body.cart_id, body.lat, body.lng, body.final)
            return {"order": order}

        return await run(request, act)

    @router.post("/orders")
    async def orders(body: OrdersRequest, request: Request):
        return await run(request, lambda t: food_orders.list_orders(t, body.address_id, body.active_only))

    @router.post("/order-status")
    async def order_status(body: OrderRefRequest, request: Request):
        return await run(request, lambda t: food_orders.order_status(t, body.order_id))

    @router.post("/order-details")
    async def order_details(body: OrderRefRequest, request: Request):
        return await run(request, lambda t: food_orders.order_details(t, body.order_id))

    @router.post("/checkout")
    async def checkout(body: CheckoutRequest, request: Request):
        async def act(token: str) -> dict:
            order = await food.checkout(token, body.address_id, body.expected_total, body.idempotency_key, body.payment_key)
            return {"order": order}

        return await run(request, act)

    return router
