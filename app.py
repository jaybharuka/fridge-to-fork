"""
Fridge to Fork — Web App Backend
=================================
FastAPI server with real-time SSE streaming and Swiggy OAuth 2.1 (PKCE).

Run:
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()


def _ascii_safe(value) -> str:
    """
    ASCII-only string repr for logging arbitrary LLM output (emoji, etc.)
    to stdout — printing raw Unicode crashes on Windows consoles (cp1252)
    or gets silently corrupted when stdout is a redirected/non-TTY stream.
    """
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


from fridge_to_fork.step1_fridge_vision import identify_ingredients
from fridge_to_fork.step2_meal_planner import generate_top_up_suggestions, plan_meals
from fridge_to_fork.step3_order_router import (
    order_dish_from_swiggy,
    order_groceries_from_instamart,
)
from fridge_to_fork.models import Decision, FridgeContents, Ingredient, MealPlan, MealSuggestion
from fridge_to_fork.inventory_db import (
    init_db, get_all_items, get_food_items,
    update_item_qty, adjust_item_qty, upsert_item,
    delete_item, log_consumption, fuzzy_match_items
)

app = FastAPI(title="Fridge to Fork", version="0.1.0")

# SessionMiddleware must wrap the app before CORSMiddleware so it can
# read/write cookies before CORS headers are added.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "dev-secret-fallback-change-in-prod"),
    max_age=5 * 24 * 60 * 60,  # 5 days, matching Swiggy token lifetime
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SWIGGY_AUTH_BASE = "https://mcp.swiggy.com"


@app.on_event("startup")
async def startup_event():
    await init_db()


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def _pkce_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _app_base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")


def _token_valid(request: Request) -> bool:
    token = request.session.get("access_token")
    expires_at = request.session.get("expires_at")
    if not token or not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) > datetime.now(timezone.utc)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Local fallback plan (unchanged)
# ---------------------------------------------------------------------------

def _local_fallback_plan(fridge, target_dish: str | None = None) -> MealPlan:
    if target_dish:
        suggestion = MealSuggestion(
            name=target_dish,
            description=f"A simple fallback suggestion for {target_dish}.",
            can_cook_now=False,
            missing_ingredients=["Review the recipe"],
            cuisine="Various",
            prep_time_minutes=30,
        )
        return MealPlan(
            suggestions=[suggestion],
            decision=Decision.ORDER_GROCERIES,
            recommended_meal=suggestion,
            reasoning="Based on what's in your fridge right now.",
        )

    ingredient_names = [ingredient.name.lower() for ingredient in fridge.ingredients]
    if any(name in ingredient_names for name in ["bread", "bread rolls", "flatbread"]):
        suggestion = MealSuggestion(
            name="Quick Toast",
            description="A fast fallback recipe based on what is already in the fridge.",
            can_cook_now=True,
            missing_ingredients=[],
            cuisine="Simple",
            prep_time_minutes=10,
        )
    else:
        suggestion = MealSuggestion(
            name="Simple Stir-fry",
            description="A practical fallback meal using available ingredients.",
            can_cook_now=True,
            missing_ingredients=[],
            cuisine="Asian",
            prep_time_minutes=15,
        )

    return MealPlan(
        suggestions=[suggestion],
        decision=Decision.COOK,
        recommended_meal=suggestion,
        reasoning="Based on what's in your fridge right now.",
    )


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
async def health():
    return {"status": "ok", "api_key_set": bool(os.environ.get("GOOGLE_API_KEY"))}


# ---------------------------------------------------------------------------
# Inventory CRUD
# ---------------------------------------------------------------------------

@app.get("/api/inventory")
async def api_get_inventory():
    items = await get_all_items()
    normalized = []
    for item in items:
        normalized.append({
            "id":        item["id"],
            "name":      item["name"],
            "category":  item["category"],
            "qty":       item["qty"],
            "threshold": item["threshold"],
            "unit":      item["unit"],
            "dailyUse":  item["daily_use"],
            "barcode":   item["barcode"] or "",
        })
    return {"items": normalized, "count": len(normalized)}


@app.post("/api/inventory/item")
async def api_upsert_item(request: Request):
    body = await request.json()
    await upsert_item(body)
    return {"success": True}


@app.delete("/api/inventory/item/{item_id}")
async def api_delete_item(item_id: str):
    await delete_item(item_id)
    return {"success": True}


@app.post("/api/inventory/adjust")
async def api_adjust_qty(request: Request):
    body = await request.json()
    item_id = body.get("itemId")
    delta = body.get("delta", 0)
    new_qty = await adjust_item_qty(item_id, delta)
    return {"success": True, "newQty": new_qty}


@app.post("/api/inventory/consume")
async def api_consume(request: Request):
    body = await request.json()
    dish_name = body.get("dishName", "Unknown dish")
    items = body.get("items", [])

    updated = []
    for item in items:
        item_id = item.get("itemId")
        delta = item.get("delta", 0)
        if delta > 0:
            delta = -delta  # ensure deduction
        new_qty = await adjust_item_qty(item_id, delta)
        if new_qty is not None:
            updated.append({"itemId": item_id, "newQty": new_qty})

    await log_consumption(dish_name, items)
    return {"success": True, "updated": updated}


@app.post("/api/inventory/restock")
async def api_restock(request: Request):
    body = await request.json()
    names = body.get("itemNames", [])

    all_items = await get_all_items()
    matches = await fuzzy_match_items(names, all_items)

    restocked = []
    for match in matches:
        if match["matched"]:
            inv_item = next(
                (i for i in all_items if i["id"] == match["item_id"]), None
            )
            if inv_item:
                restock_qty = inv_item["daily_use"] * 14
                if restock_qty == 0:
                    restock_qty = inv_item["threshold"] * 5
                await update_item_qty(match["item_id"], restock_qty)
                restocked.append({
                    "name":    match["name"],
                    "item_id": match["item_id"],
                    "new_qty": restock_qty
                })
    return {"success": True, "restocked": restocked}


@app.get("/api/inventory/food")
async def api_food_items():
    """Returns food items formatted for the meal planner prompt."""
    items = await get_food_items()
    ingredient_list = []
    for item in items:
        ingredient_list.append({
            "id":      item["id"],
            "name":    item["name"],
            "qty":     item["qty"],
            "unit":    item["unit"],
            "dailyUse": item["daily_use"],
        })
    return {"ingredients": ingredient_list}


@app.post("/api/inventory/cart-fill")
async def cart_fill(request: Request):
    """
    SSE stream that uses the Google ADK agent to search each
    low-stock item on Instamart and add it to the user's cart.
    Requires valid Swiggy Bearer token from session.
    """
    body = await request.json()
    items = body.get("items", [])
    # items = [{"id": "d1", "name": "Basmati Rice", "qty_needed": 5, "unit": "kg"}]

    access_token = request.session.get("access_token")

    async def stream():
        if not access_token:
            yield _sse({"type": "auth_required"})
            return

        for item in items:
            yield _sse({
                "type": "item_searching",
                "itemId": item["id"],
                "itemName": item["name"]
            })

            try:
                from fridge_to_fork.swiggy_agent import run_swiggy_agent
                from fridge_to_fork.models import (
                    Decision, MealPlan, MealSuggestion
                )

                # Build a mini meal plan just for this item
                suggestion = MealSuggestion(
                    name=item["name"],
                    description="",
                    can_cook_now=False,
                    missing_ingredients=[item["name"]],
                    cuisine="",
                    prep_time_minutes=0
                )
                plan = MealPlan(
                    suggestions=[suggestion],
                    decision=Decision.ORDER_GROCERIES,
                    recommended_meal=suggestion,
                    reasoning=""
                )

                result = await run_swiggy_agent(
                    plan=plan,
                    delivery_address=os.environ.get(
                        "DELIVERY_ADDRESS", "Mumbai, India"
                    ),
                    access_token=access_token,
                    dry_run=False
                )

                if result and result.success:
                    yield _sse({
                        "type": "item_added",
                        "itemId": item["id"],
                        "itemName": item["name"]
                    })
                else:
                    error = result.error if result else "unknown"
                    if error == "auth_required":
                        yield _sse({"type": "auth_required"})
                        return
                    yield _sse({
                        "type": "item_failed",
                        "itemId": item["id"],
                        "itemName": item["name"]
                    })

            except Exception as e:
                print(f"[CART_FILL] Error for {item['name']}: {e}")
                yield _sse({
                    "type": "item_failed",
                    "itemId": item["id"],
                    "itemName": item["name"]
                })

        yield _sse({"type": "cart_complete"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ---------------------------------------------------------------------------
# Auth routes — Swiggy OAuth 2.1 with PKCE
# ---------------------------------------------------------------------------

@app.get("/auth/login")
async def auth_login(request: Request):
    verifier = _pkce_verifier()
    challenge = _pkce_challenge(verifier)
    state = secrets.token_urlsafe(16)

    request.session["pkce_verifier"] = verifier
    request.session["oauth_state"] = state

    client_id = os.environ.get("SWIGGY_CLIENT_ID", "")
    redirect_uri = _app_base_url() + "/auth/callback"

    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": "mcp:tools",
    })

    return RedirectResponse(f"{SWIGGY_AUTH_BASE}/auth/authorize?{params}")


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = ""):
    stored_state = request.session.get("oauth_state")
    if not state or state != stored_state:
        return HTMLResponse(
            "<h2>Auth error: invalid state parameter.</h2><p><a href='/'>Go back</a></p>",
            status_code=400,
        )

    verifier = request.session.pop("pkce_verifier", None)
    request.session.pop("oauth_state", None)
    redirect_uri = _app_base_url() + "/auth/callback"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SWIGGY_AUTH_BASE}/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "client_id": os.environ.get("SWIGGY_CLIENT_ID", ""),
            },
        )
        resp.raise_for_status()
        token_data = resp.json()

    expires_in = token_data.get("expires_in", 5 * 24 * 60 * 60)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    request.session["access_token"] = token_data["access_token"]
    request.session["expires_at"] = expires_at

    return RedirectResponse("/")


@app.get("/auth/status")
async def auth_status(request: Request):
    authenticated = _token_valid(request)
    return {
        "authenticated": authenticated,
        "expires_at": request.session.get("expires_at") if authenticated else None,
    }


@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.pop("access_token", None)
    request.session.pop("expires_at", None)
    return RedirectResponse("/")


# ---------------------------------------------------------------------------
# Scan endpoint
# ---------------------------------------------------------------------------

@app.post("/api/scan")
async def scan(
    request: Request,
    file: UploadFile | None = File(None),
    target_dish: str | None = Form(None),
    mode: str | None = Form(None),
    household_mode: str | None = Form(None),
    servings: int = Form(2),
):
    scan_mode = mode or household_mode
    img_bytes = await file.read() if file is not None else b""
    suffix = Path(file.filename or "image.jpg").suffix or ".jpg" if file is not None else ".jpg"

    async def stream():
        tmp_path = None
        fridge = None
        try:
            if scan_mode == "inventory":
                # ── Step 1: Skip vision, read from household inventory ──────
                yield _sse({"type": "progress", "step": 1, "message": "Reading your home pantry…"})
                food_items = await get_food_items()
                ingredients = [
                    Ingredient(
                        name=item["name"],
                        quantity=f"{item['qty']} {item['unit']}",
                        confidence=1.0,
                    )
                    for item in food_items
                    if item["qty"] > 0
                ]
                fridge = FridgeContents(
                    ingredients=ingredients,
                    raw_description=f"Household inventory: {len(ingredients)} food items available",
                )
                yield _sse({
                    "type": "step1",
                    "raw_description": fridge.raw_description,
                    "ingredients": [
                        {
                            "name": i.name,
                            "quantity": i.quantity or "available",
                            "confidence": 100,
                        }
                        for i in fridge.ingredients
                    ],
                    "source": "inventory",
                })
            else:
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name

                # ── Step 1: Vision ──────────────────────────────────────────
                yield _sse({"type": "progress", "step": 1, "message": "Scanning your fridge with AI vision…"})
                try:
                    fridge = await asyncio.to_thread(identify_ingredients, tmp_path)
                except Exception as e:
                    import traceback
                    print(f"[STEP1 ERROR] identify_ingredients failed: {e}")
                    traceback.print_exc()
                    raise  # re-raise so the outer handler catches it
                yield _sse({
                    "type": "step1",
                    "raw_description": fridge.raw_description,
                    "ingredients": [
                        {
                            "name": i.name,
                            "quantity": i.quantity or "—",
                            "confidence": round(i.confidence * 100),
                        }
                        for i in sorted(fridge.ingredients, key=lambda x: -x.confidence)
                    ],
                })

            # ── Step 2: Meal planning ───────────────────────────────────────
            if target_dish:
                yield _sse({"type": "progress", "step": 2, "message": f"Evaluating '{target_dish}'…"})
            else:
                yield _sse({"type": "progress", "step": 2, "message": "Planning your meals…"})

            try:
                plan = await asyncio.to_thread(
                    plan_meals, fridge, target_dish=target_dish, servings=servings
                )
            except Exception as e:
                import traceback
                print(f"[STEP2 ERROR] plan_meals failed: {e}")
                traceback.print_exc()
                plan = _local_fallback_plan(fridge, target_dish)

            yield _sse({
                "type": "step2",
                "decision": plan.decision.value,
                "recommended_meal": plan.recommended_meal.name if plan.recommended_meal else None,
                "reasoning": plan.reasoning,
                "suggestions": [
                    {
                        "name": s.name,
                        "description": s.description,
                        "cuisine": s.cuisine,
                        "can_cook_now": s.can_cook_now,
                        "missing_ingredients": s.missing_ingredients,
                        "prep_time_minutes": s.prep_time_minutes,
                    }
                    for s in plan.suggestions
                ],
                "recipe_ingredients": [
                    {
                        "name": ri.name,
                        "quantity": ri.quantity,
                        "is_staple": ri.is_staple,
                    }
                    for ri in (
                        plan.recommended_meal.recipe_ingredients
                        if plan.recommended_meal
                        and getattr(plan.recommended_meal, "recipe_ingredients", None)
                        else []
                    )
                ],
            })

            # ── Step 3: hand the decision to the user ───────────────────────
            yield _sse({
                "type": "awaiting_user_choice",
                "ai_recommendation": plan.decision.value,
                "reasoning": plan.reasoning,
                "recommended_meal": plan.recommended_meal.name if plan.recommended_meal else None,
                "missing_ingredients": (
                    plan.recommended_meal.missing_ingredients if plan.recommended_meal else []
                ),
            })

            # ── Top-up suggestions — best-effort upsell, never blocks the choice above ──
            if plan.recommended_meal is not None:
                top_up_suggestions = await asyncio.to_thread(
                    generate_top_up_suggestions, fridge, plan.recommended_meal, plan.decision
                )
                print(f"[TOP_UP] Generated {len(top_up_suggestions)} suggestions: {_ascii_safe(top_up_suggestions)}")
                if top_up_suggestions:
                    yield _sse({"type": "top_up", "suggestions": top_up_suggestions})

            yield _sse({"type": "complete"})

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                request.session.pop("access_token", None)
                request.session.pop("expires_at", None)
                yield _sse({"type": "auth_required", "message": "Session expired, reconnect Swiggy"})
            else:
                yield _sse({"type": "error", "message": f"Order service error: {exc.response.status_code}"})

        except Exception:
            if fridge is not None:
                plan = _local_fallback_plan(fridge, target_dish)
                yield _sse({
                    "type": "step2",
                    "decision": plan.decision.value,
                    "recommended_meal": plan.recommended_meal.name if plan.recommended_meal else None,
                    "reasoning": plan.reasoning,
                    "suggestions": [
                        {
                            "name": s.name,
                            "description": s.description,
                            "cuisine": s.cuisine,
                            "can_cook_now": s.can_cook_now,
                            "missing_ingredients": s.missing_ingredients,
                            "prep_time_minutes": s.prep_time_minutes,
                        }
                        for s in plan.suggestions
                    ],
                    "recipe_ingredients": [
                        {
                            "name": ri.name,
                            "quantity": ri.quantity,
                            "is_staple": ri.is_staple,
                        }
                        for ri in (
                            plan.recommended_meal.recipe_ingredients
                            if plan.recommended_meal
                            and getattr(plan.recommended_meal, "recipe_ingredients", None)
                            else []
                        )
                    ],
                })
                yield _sse({
                    "type": "awaiting_user_choice",
                    "ai_recommendation": plan.decision.value,
                    "reasoning": plan.reasoning,
                    "recommended_meal": plan.recommended_meal.name if plan.recommended_meal else None,
                    "missing_ingredients": (
                        plan.recommended_meal.missing_ingredients if plan.recommended_meal else []
                    ),
                })

                if plan.recommended_meal is not None:
                    top_up_suggestions = await asyncio.to_thread(
                        generate_top_up_suggestions, fridge, plan.recommended_meal, plan.decision
                    )
                    print(f"[TOP_UP] Generated {len(top_up_suggestions)} suggestions: {_ascii_safe(top_up_suggestions)}")
                    if top_up_suggestions:
                        yield _sse({"type": "top_up", "suggestions": top_up_suggestions})

                yield _sse({"type": "complete"})
            else:
                yield _sse({"type": "error", "message": "Unable to complete analysis."})
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Order endpoint — fires only after the user picks an action
# ---------------------------------------------------------------------------

@app.post("/api/order")
async def place_order(
    request: Request,
    action: str = Form(...),  # "cook" | "order_groceries" | "order_dish"
    meal_name: str = Form(...),
    missing_ingredients: str = Form(""),  # comma-separated
):
    delivery_address = os.environ.get("DELIVERY_ADDRESS", "Mumbai, India")
    access_token: str | None = request.session.get("access_token")

    async def stream():
        try:
            if action == "cook":
                yield _sse({
                    "type": "cook_confirmed",
                    "message": "Great! Here is what to cook.",
                })
                yield _sse({"type": "complete"})
                return

            if action not in ("order_groceries", "order_dish"):
                yield _sse({"type": "error", "message": f"Unknown action: {action}"})
                yield _sse({"type": "complete"})
                return

            if not access_token:
                yield _sse({
                    "type": "auth_required",
                    "message": "Connect your Swiggy account to place this order",
                })
                yield _sse({"type": "complete"})
                return

            yield _sse({"type": "progress", "step": 3, "message": "Routing your order…"})

            if action == "order_groceries":
                items = [i.strip() for i in missing_ingredients.split(",") if i.strip()]
                result = await order_groceries_from_instamart(items, delivery_address, access_token)
            else:
                result = await order_dish_from_swiggy(meal_name, delivery_address, access_token)

            if result and result.error == "auth_required":
                yield _sse({
                    "type": "auth_required",
                    "message": "Connect your Swiggy account to place this order",
                })
                yield _sse({"type": "complete"})
                return

            yield _sse({
                "type": "step3",
                "decision": action,
                "placed": bool(result and result.success),
                "order_id": result.order_id if result else None,
                "platform": result.platform if result else None,
                "items": result.items if result else [],
                "eta_minutes": result.estimated_minutes if result else None,
            })

            yield _sse({"type": "complete"})

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                request.session.pop("access_token", None)
                request.session.pop("expires_at", None)
                yield _sse({"type": "auth_required", "message": "Session expired, reconnect Swiggy"})
            else:
                yield _sse({"type": "error", "message": f"Order service error: {exc.response.status_code}"})
            yield _sse({"type": "complete"})

        except Exception as e:
            import traceback
            print(f"[ORDER ERROR] place_order failed: {e}")
            traceback.print_exc()
            yield _sse({"type": "error", "message": "Unable to place order."})
            yield _sse({"type": "complete"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
