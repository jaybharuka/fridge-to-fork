# Fridge to Fork

Fridge to Fork is an AI kitchen assistant: tell it what you want to eat, optionally show it your fridge, and it gives you a full recipe with a checklist of what you need — then hands off to deterministic, staged Swiggy flows (Instamart for whatever's missing, Food for the finished dish) that show you the real cart before any money moves.

GitHub: https://github.com/jaybharuka/fridge-to-fork

```
[Dish name] + [optional Fridge Photo]
        -> Gemini generates the recipe (ingredients, quantities, steps)
        -> Deterministic matching marks pantry staples + fridge-photo items as "have"
        -> You check off anything else you already have
        -> Swiggy Instamart (missing items) or Swiggy Food (the dish): staged search -> cart -> review -> checkout -> tracking
```

---

## 1. What this is

A FastAPI backend with a single mobile web page (`templates/index.html`), styled after the Swiggy/Instamart app (white background, orange accent, no dark theme). There's one flow: type a dish, optionally scan your fridge, get a real recipe with a checklist, decide for yourself what you're missing, and order it.

There is no separate pantry/inventory tab or database — that entire feature was removed. Nothing is guessed on your behalf beyond pantry staples and whatever your fridge photo actually shows; everything else is a manual checkbox.

## 2. The flow

- Text input for a target dish ("Dal Makhani", "Biryani", etc.), a servings picker (1–10), and a **Get Recipe** button that works with no photo at all.
- A secondary **Scan Fridge** button (camera or gallery) is optional — if you skip it, every non-staple ingredient just starts unchecked.
- The pipeline streams live over Server-Sent Events: a 3-step progress bar (vision → planner → order), then a recipe card with:
  - Dish name, cuisine, prep time, and a numbered "How to make it" recipe (collapsible).
  - An ingredient checklist, Instamart-style: checkbox, name, quantity per row.
    - **Pantry staples** (salt, oil, onions, rice, spices, etc. — see `_STAPLES` in `step2_meal_planner.py`) are pre-checked as "have," greyed out, and tagged `Staple`.
    - **Fridge-photo matches** (fuzzy-matched against whatever the scan detected) are pre-checked and tagged `📷 in fridge`.
    - Everything else starts unchecked. Tap any row to toggle it either way — the app never assumes you're out of something, and never assumes you have something it didn't actually detect.
- A **"What do you want to do?"** card shows two equal, un-ranked options — there's no AI recommendation or "best choice" badge:
  - **Order missing items from Instamart** — the unchecked ingredients, searched, carted and reviewed through the staged Instamart flow.
  - **Order the dish from Swiggy** — the finished dish, searched, customized, carted and reviewed through the staged Food flow.
- A **Top Up** row suggests small Instamart add-ons (as Instamart-style product cards with an emoji placeholder and an Add button) that pair well with the meal — filtered so nothing already on your missing-items list gets suggested twice.
- Prices are computed throughout (`estimated_price_inr` on every ingredient) but are not shown anywhere in the UI by design — they stay in the data, not on screen.

## 3. The pipeline: Vision → Meal Planner → Staged Swiggy flows

**Step 1, Vision (`fridge_to_fork/step1_fridge_vision.py`)** — optional.
Sends the fridge photo to Gemini with a strict JSON prompt and gets back a list of ingredients, each with a rough quantity and a 0–1 confidence score, plus a one-paragraph description of the fridge. Tries a chain of models (`gemini-2.5-flash` down through `gemini-2.0-flash-lite`) so one model's exhausted quota doesn't stop the request, and falls back to a small hardcoded ingredient list if every model fails. If you don't take a photo, this step is skipped entirely and the ingredient list is just empty.

**Step 2, Meal Planner (`fridge_to_fork/step2_meal_planner.py`)**
Given a target dish (and optionally what the fridge scan found, used only for inspiration), Gemini returns a complete recipe: description, cuisine, prep time, a fully-quantified ingredient list scaled to the requested servings, a numbered cooking method, and a price estimate per ingredient. Gemini is **not** asked to decide what you already have — that classification is done deterministically in Python afterwards:
- `_is_pantry_staple()` fuzzy-matches each ingredient against a hardcoded staples list.
- `_fuzzy_ingredient_match()` fuzzy-matches each ingredient against whatever the fridge photo actually detected (handles plurals, "fresh"/"chopped" etc., and British/American spelling variants like chilli/chili).

There is no cook/order_groceries/order_dish AI decision anymore — the app just reports what's missing and lets you choose how to handle it. A separate `generate_top_up_suggestions()` call produces up to 3 upsell items, filtered against the missing-ingredients list with the same fuzzy matcher so nothing gets suggested twice.

**Step 3, Staged ordering (no AI in the loop)**
Neither flow lets a model pick tools or report success. Both are deterministic MCP call sequences written against Swiggy's documented tool schemas, exposed as staged endpoints so the user confirms before any real money moves, with the shared transport, address, payment-classification and checkout-guard logic in `fridge_to_fork/swiggy_common.py`:

- **Groceries: `fridge_to_fork/instamart.py`** (`/api/instamart/*`): `search` (real products, prices and photos, read-only), `cart` (clears the cart, adds the user's picks by `spinId`/`skuId`, returns the real `get_cart` review), `coupon`, `checkout` (only after a separate "Place order": re-checks address and total, checks `get_orders` before and after, idempotent per reviewed cart, UPI via a payment page and polling), plus orders, live tracking, addresses and "Report a problem".
- **The dish: `fridge_to_fork/food.py`** (`/api/food/*`): `search` (`search_restaurants` + `search_menu`, only open restaurants), `cart` (flushes the cart, adds the chosen dish with its variants and add-ons, then verifies Swiggy's cart is exactly what was picked before offering it), `coupon`, `checkout` (`place_food_order`, documented as not idempotent, so the same guards as Instamart), `payment-status`, `orders` / `order-status` / `order-details` (live tracking) and `report` ("Report a problem" via Swiggy's `report_error`, identifiers only). `fridge_to_fork/features.py`'s `FOOD_ORDERING_ENABLED` is its kill switch.

The old Gemini/Google ADK agent that used to order the dish (it invented order IDs and read success out of free text) has been deleted. `swiggy_agent.py` now only simulates orders for the CLI's `--dry-run` and refuses real ones; `POST /api/order` only handles `cook`.

## 4. Smart Cart

The Smart Cart modal is the legacy (vanilla page) version of the shared "add these items to Instamart" flow used both by the recipe checklist's missing-items button and by each Top Up suggestion's Add button.

- `openSmartCart(items)` (in `templates/index.html`) checks `/auth/status`.
- Not connected: shows a preview list and a "Connect Swiggy to order" button, plus a manual fallback that opens Instamart's search page.
- Connected: groceries now use the staged Instamart flow below. `/api/cart-fill` and the agent-based grocery path were removed, so this legacy modal's connected mode no longer works — the Next.js frontend's order sheet replaces it.

## 5. Tech stack

| Layer | Technology |
|---|---|
| AI orchestration | Google GenAI SDK, Gemini 2.5 Flash (with fallback chain to lite/older models) |
| Backend API | FastAPI, Server-Sent Events for streaming pipeline progress |
| Session / auth | Starlette `SessionMiddleware`, OAuth 2.1 with PKCE against Swiggy's auth server |
| Frontend | Single vanilla HTML/CSS/JS page, no build step, no framework, `lucide` + Phosphor icons over CDN |
| Swiggy transport | MCP Python SDK (`streamablehttp_client`), deterministic call sequences (no agent framework) |
| Commerce integration | Swiggy Food, Instamart, and Dineout MCP servers over streamable HTTP |
| Testing | pytest, pytest-asyncio, pytest-httpx (network calls mocked) |

## 6. Project structure

```text
fridge-to-fork/
├── app.py                        # FastAPI app: page, scan/order SSE endpoints, OAuth, Instamart routes
├── templates/
│   └── index.html                # The whole frontend: recipe flow, checklist, Smart Cart — single page, vanilla JS
├── fridge_to_fork/
│   ├── models.py                 # Ingredient, RecipeIngredient, FridgeContents, MealSuggestion, MealPlan, OrderResult
│   ├── step1_fridge_vision.py    # Gemini Vision ingredient identification (optional step)
│   ├── step2_meal_planner.py     # Gemini recipe generation + deterministic staple/fridge matching + top-up upsells
│   ├── step3_order_router.py     # CLI entry point (route_order): simulates or refuses, the web app doesn't use it
│   ├── swiggy_agent.py           # CLI --dry-run simulation + refusals (the LLM agent was deleted)
│   ├── swiggy_common.py          # Transport, addresses, payment classifier, checkout guards, report_error (Instamart + Food)
│   ├── instamart.py              # Staged Instamart flow (+ instamart_routes/orders/addresses/support)
│   ├── food.py                   # Staged Food flow (+ food_routes/orders/support)
│   ├── features.py               # FOOD_ORDERING_ENABLED kill switch
│   ├── agent.py                  # End-to-end CLI orchestrator (fridge-to-fork console script)
│   └── swiggy_live_mcp.py        # Legacy stdio MCP stub, not used by the running app
├── tests/
│   ├── test_step1_fridge_vision.py
│   ├── test_step2_meal_planner.py
│   └── test_step3_order_router.py
├── .env.example                  # Environment variable template
└── pyproject.toml
```

## 7. Setup

**1. Install dependencies**

```bash
pip install -e ".[dev]"
```

**2. Get a free Gemini API key**

Go to [Google AI Studio](https://aistudio.google.com/app/apikey), sign in with a personal Gmail account (Workspace accounts have a zero free tier quota), and create a key.

**3. Configure environment**

```bash
cp .env.example .env
```

Edit `.env` and set at minimum `GOOGLE_API_KEY`. Everything else has a working default for local development.

**4. Run the server**

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

**5. Open the app**

On the same machine: `http://localhost:8000`. On your phone, over the same WiFi network: `http://<your-pc-ip>:8000` (find your IP with `ipconfig` on Windows or `ifconfig` on Mac/Linux — look for the Wi-Fi adapter's IPv4 address, not a virtual/WSL adapter).

**6. (Optional) Connect Swiggy**

Set `APP_BASE_URL` in `.env` (the app registers itself with Swiggy via Dynamic Client Registration, so no client ID is needed), then tap "Connect Swiggy" in the header. Without this, the app still works end to end using dry run order simulation.

**7. Run the test suite**

```bash
pytest --ignore=tests/test_step1_fridge_vision.py
```

All network calls and LLM calls in the test suite are mocked, so no API key is required to run tests.

## 8. Environment variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | Yes | Google Gemini API key from AI Studio |
| `GEMINI_TEXT_MODEL` | Optional | Primary model for meal planning (default `gemini-2.5-flash`) |
| `GEMINI_VISION_MODEL` | Optional | Primary model for fridge vision (default `gemini-2.5-flash`) |
| `SWIGGY_FOOD_MCP_URL` | Optional | Swiggy Food MCP endpoint (default `https://mcp.swiggy.com/food`) |
| `SWIGGY_INSTAMART_MCP_URL` | Optional | Swiggy Instamart MCP endpoint (default `https://mcp.swiggy.com/im`) |
| `SWIGGY_DINEOUT_MCP_URL` | Optional | Swiggy Dineout MCP endpoint (default `https://mcp.swiggy.com/dineout`) |
| `APP_BASE_URL` | For real orders | Base URL this app is reachable at, used to build the OAuth redirect URI |
| `SECRET_KEY` | Recommended | Signs session cookies via `itsdangerous`, set a real random value in production |
| `DELIVERY_ADDRESS` | Optional | Legacy default delivery address for the CLI (default `Mumbai, India`) |

## 9. Swiggy MCP integration

The app talks to Swiggy's MCP servers directly, one deterministic client per product:

- `SWIGGY_FOOD_MCP_URL`, restaurant delivery (`food.py`)
- `SWIGGY_INSTAMART_MCP_URL`, grocery delivery (`instamart.py`)
- `SWIGGY_DINEOUT_MCP_URL`, table reservations (not used by the web app)

**Transport.** `swiggy_common.open_session()` opens a streamable-HTTP MCP session with the user's Bearer token; every tool result goes through one envelope reader (`{success, data | error}`, domain failures arrive as HTTP 200 + `success:false`). Nothing is inferred from free text.

**Auth.** `app.py` implements OAuth 2.1 with PKCE itself: `/auth/login` generates a code verifier and S256 challenge and redirects to Swiggy's authorize endpoint, `/auth/callback` exchanges the returned code for a Bearer access token and stores it in the session, `/auth/status` reports whether that token is still valid, and `/auth/logout` clears it. The Bearer token is sent as the `Authorization` header of every MCP session (`swiggy_common.open_session`).

**Token lifetime.** Swiggy MCP issues a 5 day access token with no refresh token, so that token is the entire session. `swiggy_common` maps a 401 (or an `invalid_token`/unauthorized tool error) to `auth_required`, and the frontend surfaces a "Connect Swiggy" prompt rather than retrying silently in the background.

**Dry run.** `run_swiggy_agent(..., dry_run=True)` returns a simulated `OrderResult` without contacting Swiggy at all, used by the CLI's `--dry-run` flag and exercised in the test suite. Without `dry_run` it refuses.

## 10. Architecture

```
                              +---------------------+
                              |   templates/          |
                              |   index.html           |
                              | (recipe flow + Smart   |
                              |  Cart, single page)    |
                              +----+--------------+----+
                                   |              |
                    POST /api/scan |              | POST /api/instamart
                    POST /api/order|              |
                                   v              v
+----------------------------------------------------------------+
|                            app.py (FastAPI)                     |
|         SSE streaming, session/OAuth, order routing             |
+----+------------------------+-----------------------------------+
     |                        |
     v                        v
+-----------+        +------------------------+
| step1_    |        | step2_meal_planner.py   |
| fridge_   | -----> | Gemini recipe +         |
| vision.py |        | deterministic staple /  |
| Gemini    |        | fridge-photo matching   |
| Vision    |        | (no AI decision)        |
+-----------+        +-----------+-------------+
                                  |
                                  v
                        +-----------------------+
                        | instamart.py / food.py  |
                        | staged, deterministic   |
                        +-----------+-------------+
                                    |
                                    v
                        +-----------------------+
                        | swiggy_common.py        |
                        | MCP session + envelope  |
                        | + payment/checkout guards|
                        +----+------+------+------+
                             |      |      |
                  StreamableHTTP    |      |
                             v      v      v
                       +-------+ +-------+ +---------+
                       | Food  | | Insta-| | Dineout |
                       | MCP   | | mart  | | MCP     |
                       |       | | MCP   | |         |
                       +-------+ +-------+ +---------+
```
