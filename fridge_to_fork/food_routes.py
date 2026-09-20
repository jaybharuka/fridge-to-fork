"""
HTTP surface for the staged Food flow (see food.py).

  POST /api/food/search    {dish, address_id?}                                        -> {address, dish, results[], hasMore}
  POST /api/food/cart      {address_id, selection}                                    -> {review, adjustments[]}
  POST /api/food/checkout  {address_id, expected_total, idempotency_key, payment_key} -> {order}

Every response is `{ok: true, ...}` or `{ok: false, error: {code, message}}`, the same envelope as the Instamart
routes. While FOOD_ORDERING_ENABLED is off every route refuses, before it even looks at auth.
"""

from typing import Annotated, Awaitable, Callable, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StringConstraints

from . import features, food
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

    @router.post("/checkout")
    async def checkout(body: CheckoutRequest, request: Request):
        async def act(token: str) -> dict:
            order = await food.checkout(token, body.address_id, body.expected_total, body.idempotency_key, body.payment_key)
            return {"order": order}

        return await run(request, act)

    return router
