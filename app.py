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
import queue
import secrets
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from google import genai
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
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
from fridge_to_fork.step2_meal_planner import generate_top_up_suggestions, plan_meals_stream
from fridge_to_fork.features import FOOD_ORDERING_ENABLED, FOOD_UNAVAILABLE_MESSAGE
from fridge_to_fork.instamart_routes import make_router as make_instamart_router
from fridge_to_fork.step3_order_router import order_dish_from_swiggy
from fridge_to_fork.models import Decision, FridgeContents, MealPlan, MealSuggestion

app = FastAPI(title="Fridge to Fork", version="0.1.0")

DEFAULT_DELIVERY_ADDRESS = "Mumbai, India"

# SessionMiddleware must wrap the app before CORSMiddleware so it can
# read/write cookies before CORS headers are added.
#
# same_site="none" + https_only=True is required for the session cookie to
# survive a cross-origin request (frontend on Vercel, backend on Railway) —
# SameSite=None cookies must be Secure or browsers drop them. It's a
# harmless superset locally too (dev runs over http, so https_only is
# effectively bypassed by browsers for localhost).
_SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-fallback-change-in-prod")
_SESSION_MAX_AGE = 5 * 24 * 60 * 60  # 5 days, matching Swiggy token lifetime
app.add_middleware(
    SessionMiddleware,
    secret_key=_SECRET_KEY,
    max_age=_SESSION_MAX_AGE,
    same_site="none",
    https_only=True,
)

# FRONTEND_ORIGIN: the deployed frontend's origin (e.g. Vercel URL), unset
# in local dev where next.config.js proxies same-origin instead.
_frontend_origin = os.environ.get("FRONTEND_ORIGIN", "")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_frontend_origin] if _frontend_origin else ["*"],
    allow_credentials=bool(_frontend_origin),
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


_swiggy_client_id: str | None = None


async def _get_swiggy_client_id() -> str:
    """Register once via RFC 7591 Dynamic Client Registration, then cache."""
    global _swiggy_client_id
    if _swiggy_client_id:
        return _swiggy_client_id

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{SWIGGY_AUTH_BASE}/auth/register",
            json={
                "client_name": "Fridge to Fork",
                "redirect_uris": [_app_base_url() + "/auth/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
            },
        )
        resp.raise_for_status()
    _swiggy_client_id = resp.json()["client_id"]
    return _swiggy_client_id


def _safe_next_path(next_param: str | None) -> str:
    """
    Only ever redirect to a same-origin relative path after OAuth — a raw
    user-supplied `next` value redirected to unvalidated is an open redirect.
    Anything with a scheme or netloc (http://evil.com, //evil.com,
    javascript:...) or that isn't a real absolute-path ("/...") is rejected
    in favor of the safe "/" default.
    """
    if not next_param:
        return "/"
    parsed = urllib.parse.urlsplit(next_param)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not next_param.startswith("/") or next_param.startswith("//"):
        return "/"
    return next_param


_bearer_signer = URLSafeTimedSerializer(_SECRET_KEY, salt="f2f-bearer")


def _issue_bearer(access_token: str, expires_at: str) -> str:
    return _bearer_signer.dumps({"t": access_token, "exp": expires_at})


def _valid_pair(token: str | None, expires_at: str | None) -> tuple[str, str] | None:
    if not token or not expires_at:
        return None
    try:
        if datetime.fromisoformat(expires_at) > datetime.now(timezone.utc):
            return token, expires_at
    except ValueError:
        pass
    return None


def _session_auth(request: Request) -> tuple[str, str] | None:
    return _valid_pair(request.session.get("access_token"), request.session.get("expires_at"))


def _auth(request: Request) -> tuple[str, str] | None:
    """(swiggy_access_token, expires_at) from `Authorization: Bearer <signed>`
    (direct cross-origin calls, where the host-only session cookie isn't
    sent), else from the session cookie. None if neither is valid/unexpired."""
    header = request.headers.get("authorization", "")
    if header[:7].lower() == "bearer ":
        try:
            data = _bearer_signer.loads(header[7:].strip(), max_age=_SESSION_MAX_AGE)
            pair = _valid_pair(data.get("t"), data.get("exp"))
        except (BadSignature, AttributeError):
            pair = None
        if pair:
            return pair
    return _session_auth(request)


def _access_token(request: Request) -> str | None:
    auth = _auth(request)
    return auth[0] if auth else None


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _run_plan_meals_stream(fridge, target_dish, servings, q: "queue.Queue") -> None:
    """
    Runs plan_meals_stream() (a blocking generator) on a background thread
    and forwards each ("partial"|"result", payload) item into `q`, so the
    async SSE stream in /api/scan can consume it via asyncio.to_thread(q.get)
    without blocking the event loop.
    """
    try:
        for kind, payload in plan_meals_stream(fridge, target_dish=target_dish, servings=servings):
            q.put((kind, payload))
    except Exception as e:
        q.put(("error", e))
    finally:
        q.put(("done", None))


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
# Root — the UI lives on the Next.js frontend; the old vanilla page
# (templates/index.html) is retired and no longer served.
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index(request: Request):
    target = (_frontend_origin or _app_base_url()).rstrip("/") + "/"
    if urllib.parse.urlsplit(target).netloc == request.url.netloc:
        # Unconfigured (local dev defaults APP_BASE_URL to this server): don't redirect to ourselves.
        return JSONResponse({"detail": "Frontend origin not configured. Set FRONTEND_ORIGIN."}, status_code=404)
    return RedirectResponse(target, status_code=307)


@app.get("/health")
async def health():
    return {"status": "ok", "api_key_set": bool(os.environ.get("GOOGLE_API_KEY"))}


# ---------------------------------------------------------------------------
# YouTube recipe video — best-effort lookup for the "How to make it" card.
# Returns {} (no video section rendered) on any failure or empty result.
# ---------------------------------------------------------------------------

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


async def _youtube_search(client: httpx.AsyncClient, api_key: str, query: str) -> list[dict]:
    """One YouTube search.php-equivalent call. Never raises — a failed/
    malformed query just contributes zero items to the merged result."""
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "videoEmbeddable": "true",
        "videoDuration": "medium",
        "maxResults": 4,
        "key": api_key,
    }
    try:
        resp = await client.get(YOUTUBE_SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except (httpx.HTTPError, ValueError):
        return []


@app.get("/api/youtube")
async def youtube_recipe_video(dish: str):
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return {"videos": [], "first_thumbnail": ""}

    # Four searches in parallel — a single English-biased query (the old
    # behavior) regularly misses regional recipe channels entirely for
    # dishes that are mostly cooked/filmed in Hindi or another Indian
    # language. Order matters for the merge below: results are kept in
    # this same query order (general first, since it's usually the best
    # single match), and within each query in YouTube's own relevance order.
    queries = [
        f"{dish} recipe",
        f"{dish} recipe Hindi",
        f"{dish} recipe in English",
        f"{dish} recipe Marathi OR Kannada OR Telugu",
    ]
    t_youtube = time.time()
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(_youtube_search(client, api_key, q) for q in queries))
    print(f"[TIMING] youtube_api_call (4 parallel queries): {time.time() - t_youtube:.2f}s")

    videos = []
    seen_ids = set()
    for items in results:
        for item in items:
            video_id = item.get("id", {}).get("videoId")
            if not video_id or video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            videos.append({
                "id": video_id,
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                # "medium" is guaranteed to exist for every YouTube video,
                # unlike e.g. maxresdefault which frequently 404s.
                "thumbnail": item["snippet"]["thumbnails"]["medium"]["url"],
                "embed_url": f"https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1&color=white",
            })
            if len(videos) == 4:
                break
        if len(videos) == 4:
            break

    return {
        "videos": videos,
        "first_thumbnail": videos[0]["thumbnail"] if videos else "",
    }


@app.get("/api/dish-suggestions")
async def dish_suggestions(q: str):
    if len(q) < 2:
        return {"suggestions": []}

    suggestions_api_key = os.environ.get("GEMINI_SUGGESTIONS_API_KEY")
    if not suggestions_api_key:
        return {"suggestions": []}
    suggestions_client = genai.Client(api_key=suggestions_api_key)

    try:
        response = suggestions_client.models.generate_content(
            model="gemini-flash-latest",
            contents=(
                f'Give exactly 6 dish name suggestions that start with or contain "{q}".\n'
                "Mix Indian and international dishes. Include both veg and non-veg.\n"
                "Return ONLY a JSON array of strings, nothing else, no markdown, no explanation.\n"
                'Example format: ["Palak Paneer", "Paneer Tikka", "Paneer Butter Masala"]'
            ),
        )
        text = (response.text or "").strip().replace("```json", "").replace("```", "").strip()
        suggestions = json.loads(text)
        return {"suggestions": suggestions[:6]}
    except Exception:
        return {"suggestions": []}


UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"


@app.get("/api/dish-image")
async def get_dish_image(dish: str):
    """Best-effort dish hero image via the real Unsplash Search API
    (Unsplash Source, the old redirect-based endpoint, was discontinued in
    2023 and always 503s now). Never raises — a missing key, no results,
    or a network/parse failure all just return found=False so the
    frontend keeps its placeholder."""
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if not unsplash_key:
        return {"image_url": "", "found": False}

    t_dish_image = time.time()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                UNSPLASH_SEARCH_URL,
                params={
                    "query": f"{dish} food recipe",
                    "per_page": 1,
                    "orientation": "landscape",
                },
                headers={"Authorization": f"Client-ID {unsplash_key}"},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                image_url = results[0]["urls"]["regular"]
                print(f"[TIMING] dish_image_call: {time.time() - t_dish_image:.2f}s")
                return {"image_url": image_url, "found": True}
    except Exception:
        pass
    print(f"[TIMING] dish_image_call (not found): {time.time() - t_dish_image:.2f}s")
    return {"image_url": "", "found": False}


@app.get("/api/ingredient-image")
async def get_ingredient_image(name: str):
    """Best-effort Top Up product image via the same Unsplash key as
    /api/dish-image (replaces the old Google Custom Search-backed
    version). Never raises — a missing key, no results, or a
    network/parse failure all just return found=False so the frontend
    keeps its emoji fallback."""
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if not unsplash_key:
        return {"image_url": "", "found": False}

    t_ingredient_image = time.time()
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                UNSPLASH_SEARCH_URL,
                params={
                    "query": f"{name} ingredient food",
                    "per_page": 1,
                    "orientation": "squarish",
                },
                headers={"Authorization": f"Client-ID {unsplash_key}"},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                image_url = results[0]["urls"]["small"]
                print(f"[TIMING] ingredient_image_call: {time.time() - t_ingredient_image:.2f}s")
                return {"image_url": image_url, "found": True}
    except Exception:
        pass
    print(f"[TIMING] ingredient_image_call (not found): {time.time() - t_ingredient_image:.2f}s")
    return {"image_url": "", "found": False}


# ---------------------------------------------------------------------------
# Auth routes — Swiggy OAuth 2.1 with PKCE
# ---------------------------------------------------------------------------

@app.get("/auth/login")
async def auth_login(request: Request, next: str = "/"):
    verifier = _pkce_verifier()
    challenge = _pkce_challenge(verifier)
    state = secrets.token_urlsafe(16)

    request.session["pkce_verifier"] = verifier
    request.session["oauth_state"] = state
    # Stored server-side in the signed session, keyed implicitly to this
    # login attempt (popped alongside pkce_verifier/oauth_state in the
    # callback below) rather than passed through as a raw redirect URL.
    request.session["oauth_next"] = _safe_next_path(next)

    try:
        client_id = await _get_swiggy_client_id()
    except (httpx.HTTPError, KeyError, ValueError):
        return HTMLResponse(
            "<h2>Couldn't reach Swiggy to start login.</h2><p><a href='/'>Go back</a></p>",
            status_code=502,
        )
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
    # Re-validated on the way out too — defense in depth against a session
    # value ever ending up somewhere unexpected.
    next_path = _safe_next_path(request.session.pop("oauth_next", None))
    redirect_uri = _app_base_url() + "/auth/callback"
    client_id = await _get_swiggy_client_id()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SWIGGY_AUTH_BASE}/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
            },
        )
        resp.raise_for_status()
        token_data = resp.json()

    expires_in = token_data.get("expires_in", 5 * 24 * 60 * 60)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    request.session["access_token"] = token_data["access_token"]
    request.session["expires_at"] = expires_at

    return RedirectResponse(next_path)


@app.get("/auth/status")
async def auth_status(request: Request):
    auth = _auth(request)
    return {"authenticated": bool(auth), "expires_at": auth[1] if auth else None}


@app.get("/auth/session-token")
async def auth_session_token(request: Request):
    """Cookie-only, same-origin (proxied) — hands the frontend a signed bearer
    for its direct cross-origin /api calls. Swiggy issues no refresh token, so
    expiry means re-authorization, never a silent refresh."""
    auth = _session_auth(request)
    body = (
        {"authenticated": True, "token": _issue_bearer(*auth), "expires_at": auth[1]}
        if auth
        else {"authenticated": False}
    )
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


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
    fridge_photo_0: UploadFile | None = File(None),
    fridge_photo_1: UploadFile | None = File(None),
    fridge_photo_2: UploadFile | None = File(None),
    target_dish: str | None = Form(None),
    mode: str | None = Form(None),
    servings: int = Form(2),
):
    scan_mode = mode
    t_upload = time.time()
    # `file` is the legacy single-photo field (kept for backwards
    # compatibility); the multi-photo upload area sends up to 3 as
    # fridge_photo_0/1/2. Whichever arrived, end up with one ordered list —
    # identify_ingredients() always gets a plain list of paths.
    photo_uploads = [f for f in [file, fridge_photo_0, fridge_photo_1, fridge_photo_2] if f is not None][:3]
    photo_bytes = [await f.read() for f in photo_uploads]
    photo_suffixes = [Path(f.filename or "image.jpg").suffix or ".jpg" for f in photo_uploads]
    print(f"[TIMING] image_upload_handling: {time.time() - t_upload:.2f}s")

    async def stream():
        t_total = time.time()
        tmp_paths: list[str] = []
        fridge = None
        top_up_task = None
        try:
            if scan_mode == "recipe":
                # ── Step 1: No fridge data at all — recipe checklist starts
                #    with everything marked missing until the user checks
                #    off items or scans their fridge from inside the card ──
                yield _sse({"type": "progress", "step": 1, "message": "Preparing your recipe…"})
                fridge = FridgeContents(
                    ingredients=[],
                    raw_description="No fridge scan yet — every ingredient starts as missing until you check off what you have.",
                )
                yield _sse({
                    "type": "step1",
                    "raw_description": fridge.raw_description,
                    "ingredients": [],
                    "source": "recipe",
                })
            else:
                for content, suffix in zip(photo_bytes, photo_suffixes):
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                        tmp.write(content)
                        tmp_paths.append(tmp.name)

                # ── Step 1: Vision — all photos analysed in one Gemini call ──
                yield _sse({"type": "progress", "step": 1, "message": "Scanning your fridge with AI vision…"})
                t_vision = time.time()
                vision_timed_out = False
                try:
                    fridge = await asyncio.wait_for(
                        asyncio.to_thread(identify_ingredients, tmp_paths, target_dish or ""),
                        timeout=60.0,  # hard limit — a hung Gemini call must not hang the whole scan
                    )
                except asyncio.TimeoutError:
                    print(f"[STEP1 TIMEOUT] identify_ingredients exceeded 60s ({time.time() - t_vision:.2f}s), continuing with empty fridge")
                    vision_timed_out = True
                    fridge = FridgeContents(ingredients=[])
                except Exception as e:
                    import traceback
                    print(f"[STEP1 ERROR] identify_ingredients failed: {e}")
                    traceback.print_exc()
                    raise  # re-raise so the outer handler catches it
                print(f"[TIMING] identify_ingredients: {time.time() - t_vision:.2f}s")
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
                    **({"timed_out": True} if vision_timed_out else {}),
                })

            # ── Step 2: Meal planning ───────────────────────────────────────
            if target_dish:
                yield _sse({"type": "progress", "step": 2, "message": f"Evaluating '{target_dish}'…"})
            else:
                yield _sse({"type": "progress", "step": 2, "message": "Planning your meals…"})

            try:
                plan = None
                t_plan = time.time()
                first_token_seen = False
                stream_queue: queue.Queue = queue.Queue()
                threading.Thread(
                    target=_run_plan_meals_stream,
                    args=(fridge, target_dish, servings, stream_queue),
                    daemon=True,
                ).start()
                while True:
                    kind, payload = await asyncio.to_thread(stream_queue.get)
                    if kind == "partial":
                        if not first_token_seen:
                            first_token_seen = True
                            print(f"[TIMING] plan_meals_stream_first_token: {time.time() - t_plan:.2f}s")
                        yield _sse({"type": "step2_partial", "text": payload})
                    elif kind == "result":
                        plan = payload
                        # generate_top_up_suggestions() needs the resolved
                        # recommended_meal (with its enriched
                        # missing_ingredients) and decision, so it can't
                        # start any earlier than this — but from here on it
                        # can run in the background while we yield step2/
                        # awaiting_user_choice, instead of waiting until
                        # after both to start it.
                        if plan.recommended_meal is not None:
                            top_up_task = asyncio.create_task(
                                asyncio.to_thread(
                                    generate_top_up_suggestions,
                                    fridge, plan.recommended_meal, plan.decision,
                                )
                            )
                    elif kind == "error":
                        raise payload
                    elif kind == "done":
                        break
                print(f"[TIMING] plan_meals_stream_complete: {time.time() - t_plan:.2f}s")
                if plan is None:
                    plan = _local_fallback_plan(fridge, target_dish)
            except Exception as e:
                import traceback
                print(f"[STEP2 ERROR] plan_meals failed: {e}")
                traceback.print_exc()
                plan = _local_fallback_plan(fridge, target_dish)
                top_up_task = None

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
                        "estimated_price_inr": ri.estimated_price_inr,
                        "found_in_fridge": ri.found_in_fridge,
                        "is_staple": ri.is_staple,
                        "category": ri.category,
                    }
                    for ri in (
                        plan.recommended_meal.recipe_ingredients
                        if plan.recommended_meal
                        and getattr(plan.recommended_meal, "recipe_ingredients", None)
                        else []
                    )
                ],
                "cooking_steps": (
                    plan.recommended_meal.cooking_steps
                    if plan.recommended_meal
                    and getattr(plan.recommended_meal, "cooking_steps", None)
                    else []
                ),
                "matched_fridge_items": plan.matched_fridge_items or [],
            })

            # ── Step 3: let the user choose — no AI recommendation ──────────
            yield _sse({
                "type": "awaiting_user_choice",
                "reasoning": plan.reasoning,
                "recommended_meal": plan.recommended_meal.name if plan.recommended_meal else None,
                "missing_ingredients": (
                    plan.recommended_meal.missing_ingredients if plan.recommended_meal else []
                ),
                "total_order_price_inr": (
                    plan.recommended_meal.total_order_price_inr if plan.recommended_meal else 0
                ),
            })

            # ── Top-up suggestions — best-effort upsell, never blocks the choice
            # above. top_up_task was already started in the background the
            # moment the plan resolved (see the "result" branch above), so
            # this is usually just picking up an already-finished result
            # rather than paying for the call sequentially here. Falls back
            # to running it now if that background start didn't happen
            # (e.g. plan came from the local fallback, not the stream). ──
            if plan.recommended_meal is not None:
                t_topup = time.time()
                if top_up_task is not None:
                    top_up_suggestions = await top_up_task
                else:
                    top_up_suggestions = await asyncio.to_thread(
                        generate_top_up_suggestions, fridge, plan.recommended_meal, plan.decision
                    )
                print(f"[TIMING] top_up_call: {time.time() - t_topup:.2f}s")
                print(f"[TOP_UP] Generated {len(top_up_suggestions)} suggestions: {_ascii_safe(top_up_suggestions)}")
                if top_up_suggestions:
                    yield _sse({"type": "top_up", "suggestions": top_up_suggestions})

            print(f"[TIMING] TOTAL: {time.time() - t_total:.2f}s")
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
                            "estimated_price_inr": ri.estimated_price_inr,
                            "found_in_fridge": ri.found_in_fridge,
                            "is_staple": ri.is_staple,
                        }
                        for ri in (
                            plan.recommended_meal.recipe_ingredients
                            if plan.recommended_meal
                            and getattr(plan.recommended_meal, "recipe_ingredients", None)
                            else []
                        )
                    ],
                    "cooking_steps": (
                        plan.recommended_meal.cooking_steps
                        if plan.recommended_meal
                        and getattr(plan.recommended_meal, "cooking_steps", None)
                        else []
                    ),
                    "matched_fridge_items": plan.matched_fridge_items or [],
                })
                yield _sse({
                    "type": "awaiting_user_choice",
                    "reasoning": plan.reasoning,
                    "recommended_meal": plan.recommended_meal.name if plan.recommended_meal else None,
                    "missing_ingredients": (
                        plan.recommended_meal.missing_ingredients if plan.recommended_meal else []
                    ),
                    "total_order_price_inr": (
                        plan.recommended_meal.total_order_price_inr if plan.recommended_meal else 0
                    ),
                })

                if plan.recommended_meal is not None:
                    t_topup = time.time()
                    top_up_suggestions = await asyncio.to_thread(
                        generate_top_up_suggestions, fridge, plan.recommended_meal, plan.decision
                    )
                    print(f"[TIMING] top_up_call: {time.time() - t_topup:.2f}s")
                    print(f"[TOP_UP] Generated {len(top_up_suggestions)} suggestions: {_ascii_safe(top_up_suggestions)}")
                    if top_up_suggestions:
                        yield _sse({"type": "top_up", "suggestions": top_up_suggestions})

                print(f"[TIMING] TOTAL: {time.time() - t_total:.2f}s")
                yield _sse({"type": "complete"})
            else:
                yield _sse({"type": "error", "message": "Unable to complete analysis."})
        finally:
            for tmp_path in tmp_paths:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            # If an exception hit before the top_up section ever awaited
            # this, don't leave the background thread's task dangling.
            if top_up_task is not None and not top_up_task.done():
                top_up_task.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Vision-only scan — used by the inline "Scan fridge" button inside the
# recipe checklist card to refresh have_it/missing status without
# re-running the whole plan_meals pipeline.
# ---------------------------------------------------------------------------

@app.post("/api/scan/vision-only")
async def scan_vision_only(file: UploadFile = File(...)):
    img_bytes = await file.read()
    suffix = Path(file.filename or "image.jpg").suffix or ".jpg"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        fridge = await asyncio.to_thread(identify_ingredients, tmp_path)

        return {
            "raw_description": fridge.raw_description,
            "ingredients": [
                {
                    "name": i.name,
                    "quantity": i.quantity or "—",
                    "confidence": round(i.confidence * 100),
                }
                for i in sorted(fridge.ingredients, key=lambda x: -x.confidence)
            ],
        }
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Instamart groceries — staged search -> cart -> checkout (fridge_to_fork/instamart.py)
# ---------------------------------------------------------------------------

app.include_router(make_instamart_router(_access_token))


# ---------------------------------------------------------------------------
# Order endpoint — "cook" and Swiggy Food dish orders. Groceries never go
# through here: they use the explicit-confirmation flow above.
# ---------------------------------------------------------------------------

@app.post("/api/order")
async def place_order(
    request: Request,
    action: str = Form(...),  # "cook" | "order_dish"
    meal_name: str = Form(...),
):
    delivery_address = os.environ.get("DELIVERY_ADDRESS", DEFAULT_DELIVERY_ADDRESS)
    access_token = _access_token(request)

    async def stream():
        try:
            if action == "cook":
                yield _sse({
                    "type": "cook_confirmed",
                    "message": "Great! Here is what to cook.",
                })
                yield _sse({"type": "complete"})
                return

            if action not in ("order_dish",):
                yield _sse({"type": "error", "message": f"Unknown action: {action}"})
                yield _sse({"type": "complete"})
                return

            if not FOOD_ORDERING_ENABLED:
                # Refused before auth or the agent: a bypassed frontend guard still can't place a Food order.
                yield _sse({"type": "error", "message": FOOD_UNAVAILABLE_MESSAGE})
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
