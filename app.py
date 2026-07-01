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

from fridge_to_fork.step1_fridge_vision import identify_ingredients
from fridge_to_fork.step2_meal_planner import plan_meals
from fridge_to_fork.step3_order_router import route_order
from fridge_to_fork.models import Decision, MealPlan, MealSuggestion

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
            reasoning="Temporary fallback while generating a meal plan.",
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
        reasoning="Temporary fallback while generating a meal plan.",
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
    file: UploadFile = File(...),
    target_dish: str | None = Form(None),
):
    img_bytes = await file.read()
    suffix = Path(file.filename or "image.jpg").suffix or ".jpg"
    delivery_address = os.environ.get("DELIVERY_ADDRESS", "Mumbai, India")
    access_token: str | None = request.session.get("access_token")

    async def stream():
        tmp_path = None
        fridge = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name

            # ── Step 1: Vision ──────────────────────────────────────────────
            yield _sse({"type": "progress", "step": 1, "message": "Scanning your fridge with AI vision…"})
            fridge = await asyncio.to_thread(identify_ingredients, tmp_path)
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
                plan = await asyncio.to_thread(plan_meals, fridge, target_dish=target_dish)
            except Exception:
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
            })

            # ── Step 3: Order routing ───────────────────────────────────────
            needs_order = plan.decision in (Decision.ORDER_DISH, Decision.ORDER_GROCERIES)

            if needs_order and not access_token:
                yield _sse({
                    "type": "auth_required",
                    "message": "Connect your Swiggy account to place this order",
                })
                yield _sse({"type": "complete"})
                return

            yield _sse({"type": "progress", "step": 3, "message": "Routing your order…"})
            result = await route_order(
                plan, delivery_address, dry_run=False, access_token=access_token
            )

            # 401 from a real MCP call will raise an httpx.HTTPStatusError;
            # catch it here and tell the frontend to re-authenticate.
            yield _sse({
                "type": "step3",
                "decision": plan.decision.value,
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
                })
                yield _sse({
                    "type": "step3",
                    "decision": plan.decision.value,
                    "placed": False,
                    "order_id": None,
                    "platform": None,
                    "items": [],
                    "eta_minutes": None,
                })
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
