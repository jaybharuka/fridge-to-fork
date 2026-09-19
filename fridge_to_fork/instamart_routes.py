"""
HTTP surface for the staged Instamart flow (see instamart.py).

  POST /api/instamart/search    {items}                                   -> {address, results[]}
  POST /api/instamart/cart      {address_id, selections[]}                -> {review, adjustments[]}
  POST /api/instamart/checkout  {address_id, expected_total, idempotency_key} -> {order}

Every response is `{ok: true, ...}` or `{ok: false, error: {code, message}}`.
HTTP status is 401 for auth_required and 502 for upstream failures; Swiggy
domain failures (cart changed, minimum not met, ...) are 200 + ok:false, the
same way Swiggy itself reports them.
"""

from typing import Annotated, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

from . import instamart
from .instamart import InstamartError

Ingredient = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Id = Annotated[str, StringConstraints(min_length=1, max_length=120)]


class SearchRequest(BaseModel):
    items: list[Ingredient] = Field(min_length=1, max_length=25)


class Selection(BaseModel):
    spin_id: Id
    sku_id: Id
    quantity: int = Field(ge=1, le=20)


class CartRequest(BaseModel):
    address_id: Id
    selections: list[Selection] = Field(min_length=1, max_length=40)


class CheckoutRequest(BaseModel):
    address_id: Id
    expected_total: str = Field(min_length=1, max_length=32)
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
        return await run(request, lambda t: instamart.search_ingredients(t, _dedupe(body.items)))

    @router.post("/cart")
    async def cart(body: CartRequest, request: Request):
        selections = [s.model_dump() for s in body.selections]
        return await run(request, lambda t: instamart.build_cart(t, body.address_id, selections))

    @router.post("/checkout")
    async def checkout(body: CheckoutRequest, request: Request):
        async def act(token: str) -> dict:
            order = await instamart.checkout(token, body.address_id, body.expected_total, body.idempotency_key)
            return {"order": order}

        return await run(request, act)

    return router
