"""
HTTP surface for the fridge-scan persistence layer — vision-accuracy
overhaul, Phase C.

  POST  /api/fridge-scans                       {ingredients[], user_session_id?} -> {scan, items[]}
  GET   /api/fridge-scans/{scan_id}              -> {scan, items[]}
  PATCH /api/fridge-scans/{scan_id}/items/{item_id}  {any editable field}         -> {item}
  POST  /api/fridge-scans/{scan_id}/confirm      -> {scan}

Additive only: these routes don't exist today, and nothing in the current
frontend calls them yet — the live /api/scan handler in app.py is
untouched. Once this router is included in app.py and deployed, these
endpoints ARE reachable over HTTP like any other route; "isolated" here
means "the current frontend doesn't call them and existing behavior is
unchanged," not "they don't exist" — worth being precise about that
distinction rather than implying zero surface area.

No auth required — a fridge scan is independent of the Swiggy-account
flow (FridgeScan.user_session_id is nullable, anonymous scans are fine),
unlike the instamart/food routers which require a Swiggy token.
"""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db


class EstimatedQuantity(BaseModel):
    type: Literal["count", "level"]
    value: str | int
    unit: Optional[str] = None


class IngredientIn(BaseModel):
    """Mirrors fridge_to_fork.models.Ingredient's extended (Phase B) fields —
    a separate model rather than reusing the dataclass directly, since this
    is the wire/validation boundary (Pydantic), not the internal pipeline
    shape."""
    name: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0, le=1)
    category: Optional[str] = None
    estimated_quantity: Optional[EstimatedQuantity] = None
    state: Optional[str] = None
    tier: Literal["confirmed", "probable", "uncertain"] = "confirmed"
    needs_confirmation: bool = False
    possible_matches: list[str] = Field(default_factory=list)


class CreateScanRequest(BaseModel):
    ingredients: list[IngredientIn] = Field(default_factory=list)
    user_session_id: Optional[str] = None


class UpdateItemRequest(BaseModel):
    """Every field optional — a PATCH sends only what changed. Validated
    against db.EDITABLE_ITEM_FIELDS again at the DB layer regardless of
    what's expressible here, so the allowlist has one real source of truth."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    category: Optional[str] = None
    quantity_type: Optional[Literal["count", "level"]] = None
    quantity_value: Optional[str] = None
    quantity_unit: Optional[str] = None
    state: Optional[str] = None
    removed: Optional[bool] = None


def _ingredient_to_item_fields(ing: IngredientIn) -> dict:
    quantity_type = quantity_value = quantity_unit = None
    if ing.estimated_quantity:
        quantity_type = ing.estimated_quantity.type
        quantity_value = str(ing.estimated_quantity.value)
        quantity_unit = ing.estimated_quantity.unit
    return {
        "name": ing.name,
        "category": ing.category or "specialty",
        "quantity_type": quantity_type,
        "quantity_value": quantity_value,
        "quantity_unit": quantity_unit,
        "state": ing.state,
        "confidence": ing.confidence * 100,  # Ingredient.confidence is 0-1; fridge_items.confidence is 0-100, matching step1_fridge_vision.py's own scale
        "tier": ing.tier,
        "needs_confirmation": int(ing.needs_confirmation),
        "possible_matches": ing.possible_matches,
    }


def make_router() -> APIRouter:
    router = APIRouter(prefix="/api/fridge-scans")

    @router.post("")
    async def create_scan(body: CreateScanRequest):
        async with db.get_connection() as conn:
            await db.init_db(conn)
            scan_id = await db.create_scan(conn, user_session_id=body.user_session_id)
            for ing in body.ingredients:
                await db.add_item(conn, scan_id, **_ingredient_to_item_fields(ing))
            scan = await db.get_scan(conn, scan_id)
            items = await db.list_items(conn, scan_id)
        return {"scan": scan, "items": items}

    @router.get("/{scan_id}")
    async def get_scan(scan_id: int):
        async with db.get_connection() as conn:
            await db.init_db(conn)  # first request against a fresh DB must 404, not 500 on a missing table
            scan = await db.get_scan(conn, scan_id)
            if scan is None:
                raise HTTPException(status_code=404, detail="scan not found")
            items = await db.list_items(conn, scan_id)
        return {"scan": scan, "items": items}

    @router.patch("/{scan_id}/items/{item_id}")
    async def update_item(scan_id: int, item_id: int, body: UpdateItemRequest):
        async with db.get_connection() as conn:
            await db.init_db(conn)
            existing = await db.get_item(conn, item_id)
            if existing is None or existing["scan_id"] != scan_id:
                raise HTTPException(status_code=404, detail="item not found on this scan")
            fields = {k: (int(v) if k == "removed" else v) for k, v in body.model_dump(exclude_unset=True).items()}
            updated = await db.update_item(conn, item_id, **fields)
        return {"item": updated}

    @router.post("/{scan_id}/confirm")
    async def confirm_scan(scan_id: int):
        async with db.get_connection() as conn:
            await db.init_db(conn)
            scan = await db.confirm_scan(conn, scan_id)
            if scan is None:
                raise HTTPException(status_code=404, detail="scan not found")
        return {"scan": scan}

    return router
