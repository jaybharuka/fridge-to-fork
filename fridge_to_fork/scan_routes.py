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
from .step2_meal_planner import _normalize_ingredient_words


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


async def _resolve_canonical_ids(conn, names: list[str]) -> list[Optional[int]]:
    """Best-effort canonical_id resolution for a batch of item names against
    the same canonical_ingredients table _fuzzy_ingredient_match's own
    in-memory cache resolves against (step2_meal_planner.py, Phase D) — a
    separate lookup built fresh from this request's own already-open async
    connection, not a shared cache: this route has no real traffic yet (see
    the module docstring), so a per-request rebuild is simpler than adding a
    second cache-invalidation story for a cold path. Exact normalized-word-
    set equality against a canonical name/alias, not the looser subset-
    containment _fuzzy_ingredient_match uses for comparing two arbitrary
    ingredient phrases — this is "does this name correspond to exactly this
    known concept," not "are these two phrases related." Any failure
    (corrupt table, etc.) just leaves every name unresolved (None) rather
    than blocking scan creation."""
    try:
        rows = await db.list_canonical_ingredients(conn)
    except Exception:
        return [None] * len(names)
    lookup: dict[frozenset, int] = {}
    for row in rows:
        for candidate_name in [row["canonical_name"], *row["aliases"]]:
            words = frozenset(_normalize_ingredient_words(candidate_name))
            if words:
                lookup[words] = row["id"]
    return [lookup.get(frozenset(_normalize_ingredient_words(name))) for name in names]


def make_router() -> APIRouter:
    router = APIRouter(prefix="/api/fridge-scans")

    @router.post("")
    async def create_scan(body: CreateScanRequest):
        async with db.get_connection() as conn:
            await db.init_db(conn)
            scan_id = await db.create_scan(conn, user_session_id=body.user_session_id)
            canonical_ids = await _resolve_canonical_ids(conn, [ing.name for ing in body.ingredients])
            for ing, canonical_id in zip(body.ingredients, canonical_ids):
                fields = _ingredient_to_item_fields(ing)
                if canonical_id is not None:
                    fields["canonical_id"] = canonical_id
                await db.add_item(conn, scan_id, **fields)
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
