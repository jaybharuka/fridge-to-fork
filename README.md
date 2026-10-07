# Fridge to Fork

**Scan your fridge. Get a recipe you can actually make. Order only what's missing, straight through Swiggy.**

Fridge to Fork is an AI kitchen assistant. Type a dish or photograph your fridge, and it builds a full recipe, works out exactly which ingredients you already have, and then hands off to deterministic, staged Swiggy flows: **Instamart** for the ingredients you're missing and **Swiggy Food** for the finished dish. You always see the real cart, the real total and the real payment options before any money moves.

- Live app: https://fridge-to-fork-cyan.vercel.app
- Backend API: https://fridge-to-fork-j584.onrender.com (`/health`)
- Source: https://github.com/jaybharuka/fridge-to-fork

```
Dish name and/or fridge photo
   -> Gemini Vision identifies what is in the fridge
   -> Gemini plans the recipe (ingredients, quantities, steps)
   -> Deterministic matching marks pantry staples and fridge items as "have"
   -> "6 of 9 ingredients, 3 to order"
   -> Swiggy Instamart (missing items) or Swiggy Food (the dish):
      search -> cart -> review -> checkout -> live tracking
```

---

## Contents

1. [What it does](#1-what-it-does)
2. [Architecture](#2-architecture)
3. [The app, screen by screen](#3-the-app-screen-by-screen)
4. [AI pipeline](#4-ai-pipeline)
5. [Gemini resilience](#5-gemini-resilience)
6. [Swiggy integration](#6-swiggy-integration)
7. [Security](#7-security)
8. [Progressive web app](#8-progressive-web-app)
9. [Tech stack](#9-tech-stack)
10. [Project structure](#10-project-structure)
11. [Local development](#11-local-development)
12. [Configuration reference](#12-configuration-reference)
13. [Testing](#13-testing)
14. [Deployment](#14-deployment)
15. [Known limitations](#15-known-limitations)

---

## 1. What it does

- **Starts from a dish or a fridge.** Search for a dish (with live suggestions and a popular-dishes shelf), or photograph your fridge and let vision identify what is in it. You can do both.
- **Builds a real recipe.** A dish name, cuisine, prep time, a fully quantified ingredient list scaled to your servings, numbered cooking steps and a how-to video.
- **Knows what you have, and what you don't.** Pantry staples and anything the scan actually saw are marked as "have" by deterministic matching in Python, not by asking a model to guess. The result reads like "6 of 9 ingredients, 3 to order".
- **Orders what's missing.** The unchecked ingredients go through a staged Instamart flow, and the finished dish can go through a staged Swiggy Food flow. Neither flow lets a model pick tools or report success.
- **Keeps you in control.** Nothing is added to a cart or ordered until you review the real cart and press place order. Order history and live tracking are one tap away.

## 2. Architecture

The app is two deployables that talk to each other across origins.

```
                   +--------------------------------------+
                   |  Browser / installed PWA              |
                   +---------+--------------------+-------+
                             |                    |
          pages, /auth/*     |                    | /api/* (scan and order streams,
          (same origin)      |                    |  Instamart, Food, images)
                             v                    | cross-origin, Authorization: Bearer
              +--------------------------+        |
              |  Next.js frontend         |        |
              |  Vercel   (frontend/)     |        |
              |  rewrites /auth/* ------- | ----+  |
              +--------------------------+     |  |
                                               v  v
                          +--------------------------------------------+
                          |  FastAPI backend   (Render, app.py)         |
                          |  SSE scan pipeline, OAuth 2.1 + PKCE,       |
                          |  staged Instamart and Food flows            |
                          +----+-----------------+----------------+----+
                               |                 |                |
                               v                 v                v
                       +--------------+  +---------------+  +----------------+
                       | Gemini API   |  | Swiggy MCP    |  | Unsplash,      |
                       | vision+plan  |  | Instamart and |  | YouTube        |
                       | (key pools)  |  | Food servers  |  | (images,videos)|
                       +--------------+  +---------------+  +----------------+
```

- **Frontend:** a Next.js 16 (App Router, React 19, TypeScript) app in `frontend/`, deployed on Vercel. It has no server logic of its own.
- **Backend:** a FastAPI app (`app.py`) in a Docker container on Render. It owns the AI pipeline, the Swiggy OAuth session and every Swiggy call.
- **Why `/auth/*` is proxied but `/api/*` is not.** Vercel rewrites `/auth/*` to the backend, so the Swiggy OAuth session cookie is set on the frontend's own origin. Long-running calls (the scan stream and the order flows) go straight from the browser to Render, because a serverless proxy is the wrong place for a streaming connection. A host-only cookie cannot reach another origin, so the page fetches a short-lived **sealed bearer** from `/auth/session-token` and sends it in an `Authorization` header on those direct calls. It is held in memory only.
- **CORS** is locked to the real frontend origin (`FRONTEND_ORIGIN`). There is no wildcard and no fallback to one. See [Security](#7-security).
- `templates/index.html` is the original vanilla-JS page. It is **retired and no longer served**: `GET /` on the backend redirects to the frontend. It remains in the repository for reference only.

## 3. The app, screen by screen

**Landing.** A hero and two independent, optional routes joined by an "or": a dish search box with live suggestions, and a fridge card (up to three photos, camera or gallery) whose button, "Add a fridge photo", only adds the photo. Below them are a servings picker (1 to 8), one main button and a popular-dishes shelf. The button's label follows what was given: "Get recipe" for a dish, "Find dishes from my fridge" for photos alone, "Get recipe using my fridge" for both. It stays disabled, with a line saying why, until there is a dish or at least one photo, and a blank dish counts as empty. Photos are downscaled in the browser to at most 1200 px on the long edge and re-encoded as JPEG before upload, using native decoder downscaling where the browser supports it, which keeps memory use low for large phone photos. A dish with no photo works without a scan, and photos with no dish scan the fridge and suggest dishes.

**Scan and planning screens.** A full-screen photo scan screen shows the scan line, a progress bar and detected ingredients as they arrive. Recipe planning has its own progress view. Both are fed by Server-Sent Events from the backend (`progress`, `step1_partial` (a first look at the pass-1 ingredients while pass 2 still runs), `step1`, `step2`, `awaiting_user_choice`, `top_up`, `complete`, plus `auth_required` and `error`), and both can be backed out of. A stalled or failed scan lands on a clear, retryable error state.

**Results.** A dish hero photo, a sticky summary bar ("6 of 9 ingredients, 3 to order"), and two tabs:

- **Order** holds the ingredient checklist. Staples and fridge matches are pre-checked and labelled; tap any row to override. Each missing ingredient previews its real Instamart match. Below it are two equal choices, **Order missing items from Instamart** and **Order the dish from Swiggy**, with no AI "best choice" badge. Top Up suggestions, your usual Instamart items and a "Report a problem" path sit alongside.
- **Recipe** holds the numbered method and a how-to video carousel.

**Ordering sheets.** Both flows are bottom sheets driven by the real Swiggy cart: pick products or a dish (with variants and add-ons), review items and totals, choose cash on delivery or UPI, place the order, then follow it. Instamart and Food each have their own order history and live tracking sheet.

**Header and account menu.** One control in the header opens the account menu: connection status, **Instamart orders**, **Food orders** (while Food ordering is enabled) and a light/dark theme switch. Every deep screen has a consistent back button. The app defaults to a dark theme and follows the stored or system preference.

**Other pages.** About, FAQ, Contact and a design-system reference page.

## 4. AI pipeline

All Gemini work happens on the backend in `fridge_to_fork/`.

**Step 1, vision (`step1_fridge_vision.py`)** is optional. It sends the fridge photos to Gemini with a strict JSON prompt that walks the fridge zone by zone, and gets back ingredients with rough quantities and 0 to 1 confidence scores. With no photo, the step is skipped.

**Step 2, meal planner (`step2_meal_planner.py`)** takes the target dish (and, only as inspiration, what the scan found) and returns a complete recipe scaled to the requested servings, with a price estimate per ingredient. Gemini is **not** asked what you already have. That classification is deterministic:

- A pantry-staple check compares each ingredient against a staples list.
- A strict ingredient matcher (`ingredient_matching.py`) compares each ingredient with what the scan actually detected: two names are the same ingredient only when their head nouns agree, and the matcher handles plurals, preparation words ("fresh", "chopped") and regional spellings (chilli/chili, capsicum/bell pepper).

A separate `generate_top_up_suggestions()` call proposes a few Instamart add-ons, filtered against the missing list with the same matcher so nothing is suggested twice. Dish autocomplete (`/api/dish-suggestions`) uses its own Gemini key so typing never competes with scans for quota.

**Model chains.** Each chain is tried in order, per key. The first entry is configurable.

| Step | Chain (in order) |
|---|---|
| Vision | `GEMINI_VISION_MODEL` (default `gemini-2.5-flash`), `gemini-3.8-flash`, `gemini-flash-latest`, `gemini-flash-lite-latest`, `gemini-3.1-pro-preview` |
| Planner | `GEMINI_TEXT_MODEL` (default `gemini-2.5-flash`), `gemini-3.8-flash`, `gemini-2.5-flash-lite`, `gemini-flash-latest`, `gemini-flash-lite-latest`, `gemini-3.1-pro-preview` |

**Multi-key rotation.** `gemini_keys.py` reads `GOOGLE_API_KEY` plus `GOOGLE_API_KEY_2` through `GOOGLE_API_KEY_9`, skipping blanks and duplicate values. Vision and planner calls try every configured key for a model before moving to a weaker one. Gemini's free-tier daily quota is scoped **per Google Cloud project**, not per key, so extra keys only add headroom when they belong to separate projects. The live deployment runs keys from four independent projects.

**Prompt style.** `prompt_rules.py` appends one shared style rule to every prompt (vision, planning, top-up) so generated copy never uses em dashes. The prompts themselves are free of them as well.

**Streaming and limits.** `/api/scan` streams its progress over SSE. The vision step has a hard 60 second ceiling, and each individual Gemini call is capped at 15 seconds for vision and top-up and 18 seconds for the meal plan (overridable with `GEMINI_VISION_TIMEOUT_SECONDS`, `GEMINI_PLAN_TIMEOUT_SECONDS` and `GEMINI_TOP_UP_TIMEOUT_SECONDS`), so one hung call can never hold a scan hostage. Every successful call logs its duration as `[TIMING] gemini_call <step> <model> on <key>: <seconds>s`.

## 5. Gemini resilience

`gemini_resilience.py` is the shared policy both fallback loops use. Each failure says something different about what to try next, so each is handled differently:

| Failure | What it means | Reaction |
|---|---|---|
| Timeout (504, deadline exceeded), or a plan stream that goes quiet | The model is slow on Google's side, not a key problem | Move to the **next model** and skip the slow model for 10 minutes |
| Quota (429, resource exhausted) | This project's quota is spent | Try the **next key** (each project has its own quota) |
| Overloaded (503, high demand) | Transient | Next key once, then the **next model** after two overloaded answers |
| Unavailable (404 "no longer available to new users") | Google has withheld the model from that key's project | Never retry that model and key pair; skip it for 6 hours |
| Anything else (for example malformed JSON) | One-off | Retry in place, then the next key |

**Stalled plan streams.** The meal plan is streamed. Once its first chunk has arrived, 8 seconds without another chunk counts as a stall and fails over straight away, instead of waiting out the 18 second cutoff (`GEMINI_PLAN_STREAM_IDLE_SECONDS` overrides the 8). It is handled exactly like a timeout. Waiting for the first chunk is not a stall, the 18 second cutoff stays the ceiling, and each healthy stream logs its chunk count and longest silence (`[TIMING] plan_stream`) so the limit can be tuned.

If every model is on cooldown, all are tried anyway, so a total outage still gets a real attempt.

**Thinking mode is tuned for speed.** These calls are structured extraction and templated JSON, which do not benefit from long reasoning. `thinking_config_for()` turns thinking off for `gemini-2.5-flash` variants (a vision call that used to time out now answers in about 9 seconds) and sets the lowest thinking level for non-Pro `gemini-3.x` models. Aliases such as `gemini-flash-latest` and Pro models keep their defaults, because what an alias points at can change and an unsupported setting would be rejected.

## 6. Swiggy integration

The app talks to Swiggy's MCP servers directly, with one deterministic client per product. There is no agent framework and no model in the ordering path. Each flow is a fixed sequence of calls written against Swiggy's documented tool schemas.

**Transport** (`swiggy_common.py`). A streamable-HTTP MCP session opened with the user's bearer token. Every tool result goes through one envelope reader (`{success, data | error}`; domain failures arrive as HTTP 200 with `success: false`), so nothing is inferred from free text.

**Auth.** `app.py` implements OAuth 2.1 with PKCE itself, registering the app with Swiggy through Dynamic Client Registration (no client ID to configure). `/auth/login` redirects to Swiggy with a code challenge, `/auth/callback` exchanges the code for an access token, `/auth/status` reports validity, and `/auth/logout` clears the session. Swiggy issues a five day access token and **no refresh token**, so the token is the whole session. An expired or rejected token maps to `auth_required` and the app asks the user to reconnect rather than retrying in the background.

**Instamart** (`instamart.py`, mounted at `/api/instamart/*`):

- `search` finds real products, prices and photos (read-only).
- `cart` clears the cart, adds the user's picks by `spinId` and `skuId`, and returns Swiggy's own `get_cart` review.
- `coupon` applies a code and confirms the total actually changed.
- `checkout` runs only after a separate place-order tap. It re-checks the address and total, is idempotent per reviewed cart, supports cash on delivery and UPI (a payment page with status polling), and cross-checks Swiggy's order list before and after.
- Also: saved addresses, "usual items", order history, order details, live tracking and "Report a problem".

**Swiggy Food** (`food.py`, mounted at `/api/food/*`): restaurant and menu search (open restaurants only), a cart that is flushed and rebuilt with the chosen dish, variants and add-ons and then **verified against Swiggy's cart before it is offered**, coupons, checkout (documented as not idempotent, so it uses the same guards), payment status, order history, tracking and "Report a problem". It is enabled by the `FOOD_ORDERING_ENABLED` switch in `features.py` and `frontend/lib/features.ts`, which is also its kill switch.

**Checkout guards** (shared in `swiggy_common.py`): a replay cache keyed by idempotency key, one in-flight order per account, a re-check of the total the user reviewed, and an `unknown` outcome that never offers a retry when an order may already exist.

Dry-run order simulation and a console entry point (`fridge-to-fork`) remain for command-line use only. They do not touch Swiggy.

## 7. Security

- **The Swiggy token is never stored or sent in plaintext.** `token_vault.py` seals it with Fernet (AES-128-CBC with an HMAC-SHA256 integrity tag and an issue timestamp), keyed from `SECRET_KEY`. The same sealed blob is what the session cookie holds and what `/auth/session-token` hands the page as its bearer. A tampered, expired, too-old or wrongly keyed blob simply fails to open.
- **`SECRET_KEY` is required in production.** It signs the session cookie and also keys the token encryption. Set a long random value. The code ships a development fallback (`dev-secret-fallback-change-in-prod`) which is for local use only and must never reach production. Rotating `SECRET_KEY` invalidates every session, so each user reconnects once.
- **No server-side revocation.** The app is stateless by design (the host has an ephemeral disk), so a sealed token stays valid until it expires. Logging out clears the cookie and the in-memory bearer.
- **CORS is locked to one origin.** `FRONTEND_ORIGIN` is the only allowed cross-origin caller. If it is unset, only `http://localhost:3000` and `http://127.0.0.1:3000` are allowed, and a startup log line says so. There is never a wildcard. Methods and headers are limited to what the frontend sends (`GET`, `POST`, `OPTIONS`; `Authorization`, `Content-Type`).
- **Session cookie:** `SameSite=None`, `Secure`, five day lifetime.
- **Money safety:** orders require a separate explicit confirmation, are re-validated server side, and are idempotent per reviewed cart (see [Swiggy integration](#6-swiggy-integration)).
- **Problem reports** contain identifiers and fixed text only. The app never adds names, phone numbers, addresses or order status text. The one free-text part is the optional note the user types themselves.

## 8. Progressive web app

Fridge to Fork is installable. A web manifest (`app/manifest.ts`, served at `/manifest.webmanifest`) declares the app name, a standalone display mode, theme colours, and 192 px, 512 px and maskable icons, so browsers offer **Add to Home Screen** and launch it without browser chrome.

A deliberately small service worker (`frontend/public/sw.js`, registered by `ServiceWorkerRegister`) caches the **app shell only**:

- It pre-caches the icons and manifest, and serves Next.js's content-hashed `/_next/static/` assets cache-first.
- It intercepts **same-origin GET requests only**. Pages, `/api/*`, the scan and order streams and every cross-origin request (the backend, fonts, YouTube, dish images) are never touched and always hit the network.
- It is versioned (`CACHE_VERSION`), and old caches are evicted on activation.

There is no offline mode, because the product is live AI and live ordering.

## 9. Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, CSS Modules, lucide icons, deployed on Vercel |
| Backend | Python 3.11, FastAPI, Server-Sent Events, deployed on Render (Docker) |
| AI | Google GenAI SDK, Gemini 2.5 and 3.x Flash families with a fallback chain |
| Swiggy | MCP Python SDK over streamable HTTP, OAuth 2.1 with PKCE and Dynamic Client Registration |
| Auth and crypto | Starlette `SessionMiddleware`, `cryptography` (Fernet), `itsdangerous` |
| Images and video | Unsplash (dish and ingredient photos), YouTube Data API (how-to videos) |
| Testing | pytest, pytest-asyncio, pytest-httpx (backend); Node's built-in test runner (frontend) |

## 10. Project structure

```text
fridge-to-fork/
├── app.py                          # FastAPI app: CORS, sessions, OAuth, SSE scan pipeline, image/video endpoints
├── frontend/                       # The app: Next.js frontend (see frontend/README.md)
│   ├── app/                        #   routes: landing, about, faq, contact, design-system, manifest, icons
│   ├── components/                 #   landing, loading, results (checklist, order sheets), shared (back button, PWA)
│   ├── hooks/                      #   scan stream, auth, theme, ordering and order-history hooks
│   ├── lib/                        #   pure, unit-tested logic (scan guard, image sizing, account menu, polling)
│   └── public/                     #   service worker and icons
├── fridge_to_fork/
│   ├── step1_fridge_vision.py      # Gemini Vision ingredient identification
│   ├── step2_meal_planner.py       # Gemini recipe planning, deterministic matching, top-up suggestions
│   ├── gemini_keys.py              # Loads GOOGLE_API_KEY and _2.._9 into a key pool
│   ├── gemini_resilience.py        # Per-failure-kind fallback policy, cooldowns, timeouts, thinking config
│   ├── prompt_rules.py             # Shared style rule appended to every prompt
│   ├── token_vault.py              # Fernet sealing of the Swiggy token
│   ├── swiggy_common.py            # MCP transport, envelope, addresses, payments, checkout guards
│   ├── instamart.py                # Staged Instamart flow
│   ├── instamart_routes.py         #   its HTTP routes
│   ├── instamart_orders.py         #   order history, status, details
│   ├── instamart_addresses.py      #   saved addresses
│   ├── instamart_support.py        #   "Report a problem"
│   ├── food.py                     # Staged Swiggy Food flow
│   ├── food_routes.py              #   its HTTP routes
│   ├── food_orders.py              #   order history, status, details
│   ├── food_support.py             #   "Report a problem"
│   ├── features.py                 # FOOD_ORDERING_ENABLED switch
│   ├── scan_routes.py, db.py       # Fridge-scan persistence layer (SQLite), not yet called by the app
│   ├── ingredient_matching.py      # One strict "same ingredient?" rule shared by vision dedupe and planner matching
│   ├── seed_canonical_ingredients.py # Seeds the canonical ingredient table (scan persistence layer)
│   ├── models.py                   # Pydantic models
│   ├── agent.py, step3_order_router.py, swiggy_agent.py
│   │                               # Command-line entry point and dry-run simulation
│   └── swiggy_live_mcp.py          # Legacy stdio MCP stub, unused by the running app
├── templates/index.html            # Legacy vanilla-JS page. Retired, not served
├── tests/                          # Backend tests (37 test files) and eval harnesses
├── scripts/                        # Developer scripts (SSE scan runner, live checks)
├── docs/                           # Design proposals and implementation plans
├── Dockerfile                      # Backend image
├── render.yaml                     # Render blueprint
├── DEPLOY.md                       # Deployment guide (Render and Vercel)
├── .env.example                    # Environment variable template
└── pyproject.toml
```

## 11. Local development

You need Python 3.11 or newer, a current Node.js LTS release and a free Gemini API key.

**1. Backend**

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                # set at least GOOGLE_API_KEY
```

Get a key at [Google AI Studio](https://aistudio.google.com/app/apikey) using a personal Gmail account (Workspace accounts have a zero free tier). In `.env`, set `APP_BASE_URL=http://localhost:3000` so the Swiggy OAuth callback returns to the frontend. Then:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

**2. Frontend**

```bash
cd frontend
npm install
npm run dev                          # http://localhost:3000
```

The dev server proxies `/api/*` and `/auth/*` to `http://localhost:8000` (override with `BACKEND_URL`). The backend allows `http://localhost:3000` by default, so no `FRONTEND_ORIGIN` is needed locally.

**3. Open the app** at http://localhost:3000. Dish search and recipes work with just a Gemini key. To place real orders, tap **Connect Swiggy** and complete the OAuth flow. Orders on a connected account are real orders with real charges.

For the frontend's own details see [`frontend/README.md`](frontend/README.md). For deployment see [`DEPLOY.md`](DEPLOY.md).

## 12. Configuration reference

### Backend (`.env` locally, the Render dashboard in production)

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | Yes | Gemini API key from AI Studio |
| `GOOGLE_API_KEY_2` to `GOOGLE_API_KEY_9` | No | Extra keys for rotation. Gaps are fine. Only add headroom when they belong to **separate Google Cloud projects**, because the free-tier quota is per project |
| `GEMINI_SUGGESTIONS_API_KEY` | No | Dedicated key for dish autocomplete. Without it, suggestions are simply empty |
| `GOOGLE_API_KEY_EVAL` | Eval harness only | Key for `tests/eval_vision_accuracy.py`, deliberately separate from production keys so evaluation runs never consume user quota |
| `GEMINI_VISION_MODEL` | No | First model in the vision chain (default `gemini-2.5-flash`) |
| `GEMINI_TEXT_MODEL` | No | First model in the planner chain (default `gemini-2.5-flash`) |
| `SECRET_KEY` | **Yes in production** | Signs the session cookie and keys the Swiggy token encryption. Long and random. Rotating it logs everyone out. The built-in default is for local development only |
| `FRONTEND_ORIGIN` | **Yes in production** | The deployed frontend's origin (for example the Vercel URL). The only origin allowed by CORS. Unset means localhost only, never a wildcard |
| `APP_BASE_URL` | For real orders | Base URL used to build the OAuth redirect URI. Locally the frontend, `http://localhost:3000` |
| `UNSPLASH_ACCESS_KEY` | No | Dish hero photos (`/api/dish-image`) and ingredient photos (`/api/ingredient-image`). Without it the UI falls back to placeholders |
| `YOUTUBE_API_KEY` | No | How-to videos (`/api/youtube`) |
| `SWIGGY_INSTAMART_MCP_URL` | No | Default `https://mcp.swiggy.com/im` |
| `SWIGGY_FOOD_MCP_URL` | No | Default `https://mcp.swiggy.com/food` |
| `DELIVERY_ADDRESS` | No | Default address for the command-line entry point only (default `Mumbai, India`) |
| `FRIDGE_DB_PATH` | No | SQLite path for the scan persistence layer (default `fridge_to_fork.db`) |

### Frontend (Vercel project settings, or `frontend/.env.local`)

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | In production | The backend's public origin. Used by the browser for the direct, authenticated `/api` calls. Empty falls back to the same-origin dev proxy |
| `BACKEND_URL` | No | Where the Next.js server proxies `/api` and `/auth` (default `http://localhost:8000`) |

## 13. Testing

```bash
# Backend (all network and LLM calls are mocked; no API key needed)
pytest --continue-on-collection-errors

# Frontend
cd frontend && npm test
```

**Backend.** `tests/` holds 37 test files covering key rotation, Gemini failure handling and timeouts, the vision tiers, ingredient matching, token sealing and CORS, bearer auth, the scan routes, and the Instamart and Food flows (cart, checkout guards, payments, addresses, orders, support). **Frontend.** 19 test files (180 tests, all passing) cover the pure logic: scan state, image sizing, account menu, order polling, search, theme and a guard that keeps em dashes out of UI copy.

**Known failures.** The backend suite is not fully green, and contributors should know before running it:

- `tests/test_step1_fridge_vision.py` fails at import (`_is_url` no longer exists in `step1_fridge_vision.py`).
- `tests/test_step3_order_router.py` fails at import (`order_dish_from_swiggy` no longer exists in `step3_order_router.py`).
- 7 tests in `tests/test_step2_meal_planner.py` fail: their mocked Gemini responses no longer reach the planner, which falls through its model chain instead.

The last full run was 675 passing, 7 failing and 2 collection errors. All three predate recent work and are stale tests, not known product bugs, but they are real and worth cleaning up. `--continue-on-collection-errors` lets the rest of the suite run past the two import failures.

## 14. Deployment

- **Backend:** Render, from `render.yaml` and the `Dockerfile`, on the `main` branch with auto-deploy. `GET /health` is the liveness check.
- **Frontend:** Vercel, project root `frontend/`.
- **Required wiring:** `FRONTEND_ORIGIN` on Render must equal the Vercel origin, and `NEXT_PUBLIC_BACKEND_URL` on Vercel must equal the Render origin. Set a real `SECRET_KEY` on Render.

Step-by-step instructions, including the Vercel proxy and cross-origin details, are in [`DEPLOY.md`](DEPLOY.md).

## 15. Known limitations

- **Swiggy has no refresh token.** Sessions last five days, then the user reconnects.
- **Orders are real.** On a connected production account, checkout places real orders with real charges. Food ordering was enabled before an end-to-end real Food order had been verified, and can be switched off with `FOOD_ORDERING_ENABLED`.
- **Instamart order history** is read from Swiggy's `get_orders`, which only returns the last 15 days, so an empty list means no recent orders, not none ever. Swiggy files Instamart orders under the order type `DASH`, so the history request sends no order type and the type of each order is logged.
- **Free-tier infrastructure.** The Render free plan spins down when idle, so the first request after a quiet period can be slow. Gemini's free tier is quota-limited per project, which is why the key pool exists.
- **No server-side token revocation** (see [Security](#7-security)).
