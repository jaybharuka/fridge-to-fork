# Fridge to Fork

Fridge to Fork is an AI kitchen assistant that closes the loop between what you want to eat, what you already have, and getting the rest delivered. Point a phone camera at your fridge (or skip the camera and use a live household inventory instead), tell it what you want to cook, and Google Gemini identifies your ingredients, decides whether you can cook it now or need to order something, and hands off to a real Google ADK agent that talks to Swiggy's Food, Instamart, and Dineout MCP servers to place the order. A second tab turns the same inventory into a running pantry tracker with barcode-ready item entry, low stock alerts, and a one tap "Smart Cart" that fills an Instamart cart automatically once you connect your Swiggy account.

GitHub: https://github.com/jaybharuka/fridge-to-fork

```
[Target Dish] + [Fridge Photo or Pantry Inventory]
        -> Gemini Vision (or live inventory read)
        -> Gemini Meal Planner (cook / order groceries / order dish)
        -> Google ADK Agent -> Swiggy Food / Instamart / Dineout MCP
```

---

## 1. What this is

A FastAPI backend with a single mobile web page (`templates/index.html`) split into two tabs. The Cook tab runs the vision -> planner -> agent pipeline against either a fridge photo or a live household inventory. The Pantry tab is a persistent SQLite backed inventory tracker for the same household, with its own low stock alerts and a Smart Cart flow that fills an Instamart cart through the same Swiggy agent used for meal ordering.

## 2. The two tabs

### Cook tab

- Text input for a target dish ("Dal Makhani", "Biryani", etc), or leave it blank for open ended meal suggestions.
- Two source pills: **Scan Photo** (camera or gallery upload, analyzed by Gemini Vision) and **Use Pantry** (skips vision entirely and reads live quantities from the Pantry tab's inventory).
- Renders the three pipeline stages live over Server-Sent Events: detected ingredients as confidence-colored chips, meal suggestions as cards, then a cook / order groceries / order dish choice with the AI's recommendation highlighted.
- A "top up" strip suggests three small Instamart or Swiggy Food add-ons for whichever meal you land on.
- After confirming "cook" (in pantry mode), the app posts a consumption event to `/api/inventory/consume` so the pantry reflects what was used.

### Pantry tab

- Full CRUD inventory grid seeded with 64 default household items (food, bathroom, cosmetics, household) backed by SQLite (`fridge_to_fork/inventory_db.py`).
- Category filter pills, a "Running out soon" horizontal strip sorted by days of stock remaining, and per-item +/- quantity controls with a "Purchased" button that restocks to a 14 day supply.
- "What can I cook?" jumps straight to the Cook tab in pantry mode.
- **Smart Cart**: a button showing the live count of items below their restock threshold. Tapping it opens a bottom sheet that checks `/auth/status` and branches:
  - Not connected: a priced preview list and a "Connect Swiggy to order" button, plus a manual fallback that copies the list to the clipboard and opens Instamart's search for the first item.
  - Connected: streams live per-item progress (searching / added / not found) from `/api/inventory/cart-fill`, which drives the same `run_swiggy_agent` used by meal ordering, one item at a time.
- A floating add button opens a modal for manually adding items, including barcode entry via the browser's `BarcodeDetector` API where supported.

## 3. The pipeline: Vision -> Meal Planner -> Swiggy ADK Agent

**Step 1, Vision (`fridge_to_fork/step1_fridge_vision.py`)**
Sends the fridge photo to Gemini with a strict JSON prompt and gets back a list of ingredients, each with a rough quantity and a 0 to 1 confidence score, plus a one paragraph description of the fridge. Tries a chain of models (`gemini-2.5-flash` down through `gemini-2.0-flash-lite`) so one model's exhausted quota does not stop the request, and falls back to a small hardcoded ingredient list if every model fails.

In pantry mode (`mode=inventory` on `/api/scan`), this step is skipped entirely: `app.py` reads `get_food_items()` from the inventory database and builds the same `FridgeContents` shape directly from live quantities.

**Step 2, Meal Planner (`fridge_to_fork/step2_meal_planner.py`)**
Given the ingredient list and an optional target dish, Gemini returns 1 to 5 meal suggestions, each with a `can_cook_now` flag and a list of missing ingredients, plus one decision: `cook`, `order_groceries`, or `order_dish`. The prompt hardcodes a list of pantry staples (salt, oil, onions, rice, tea, etc) that must never be reported as missing, so the AI does not recommend ordering groceries you almost certainly already have. Uses the same model fallback chain pattern as Step 1. A separate `generate_top_up_suggestions()` call produces the three small upsell items shown after the main decision.

**Step 3, Order Router + Swiggy Agent (`fridge_to_fork/step3_order_router.py` + `fridge_to_fork/swiggy_agent.py`)**
`step3_order_router.py` no longer contains hardcoded per-platform logic. It builds a `MealPlan` and hands it to `run_swiggy_agent()`, a real `google.adk.agents.Agent` wired to all three Swiggy MCP servers at once via `MCPToolset` + `StreamableHTTPConnectionParams`. The meal plan decision is translated into a natural language instruction (for example, "order Butter Chicken from Swiggy Food, deliver to ..."), and the agent decides for itself which tools to call and in what order. See [section 9](#9-swiggy-mcp-integration) for the full integration details.

## 4. Smart Cart

Smart Cart is the Pantry tab's bulk ordering flow, separate from the Cook tab's single meal order. It targets every item at or below its restock threshold in one action instead of one dish's missing ingredients.

- `openSmartCart()` (in `templates/index.html`) filters the live inventory for `qty < threshold` (or `qty === 0`) and checks `/auth/status`.
- If Swiggy is not connected, the modal shows a priced preview and a Connect button, so there is always a usable path even without OAuth.
- If connected, `/api/inventory/cart-fill` (new endpoint in `app.py`) streams one SSE event per item as it builds a one-item `MealPlan` with `Decision.ORDER_GROCERIES` and runs it through `run_swiggy_agent()`, the same function the Cook tab's order flow uses.
- A manual fallback always works regardless of auth state: it copies the full item list to the clipboard and opens Instamart's search page for the first item.

## 5. Tech stack

| Layer | Technology |
|---|---|
| AI orchestration | Google GenAI SDK, Gemini 2.5 Flash (with fallback chain to lite/older models) |
| Backend API | FastAPI, Server-Sent Events for streaming pipeline progress |
| Session / auth | Starlette `SessionMiddleware`, OAuth 2.1 with PKCE against Swiggy's auth server |
| Inventory storage | SQLite via `aiosqlite`, single file at project root |
| Frontend | Single vanilla HTML/CSS/JS page, no build step, no framework, `lucide` icons over CDN |
| Agent framework | Google ADK (`Agent`, `Runner`, `MCPToolset`, `StreamableHTTPConnectionParams`) |
| Commerce integration | Swiggy Food, Instamart, and Dineout MCP servers over streamable HTTP |
| Testing | pytest, pytest-asyncio, pytest-httpx (network calls mocked) |

## 6. Project structure

```text
fridge-to-fork/
├── app.py                        # FastAPI app: pages, inventory API, scan/order SSE endpoints, OAuth
├── templates/
│   └── index.html                # Cook tab + Pantry tab + Smart Cart, single page, vanilla JS
├── fridge_to_fork/
│   ├── models.py                 # Ingredient, FridgeContents, MealSuggestion, MealPlan, OrderResult
│   ├── step1_fridge_vision.py    # Gemini Vision ingredient identification
│   ├── step2_meal_planner.py     # Gemini meal suggestions + cook/order decision + top-up upsells
│   ├── step3_order_router.py     # Thin adapters onto swiggy_agent.py, preserves old call signatures
│   ├── swiggy_agent.py           # Google ADK agent wired to all 3 Swiggy MCP servers
│   ├── inventory_db.py           # aiosqlite persistence, 64 default items, adjust/consume/restock helpers
│   ├── agent.py                  # End-to-end CLI orchestrator (fridge-to-fork console script)
│   └── swiggy_live_mcp.py        # Legacy stdio MCP stub, not used by the running app
├── tests/
│   ├── test_step1_fridge_vision.py
│   ├── test_step2_meal_planner.py
│   └── test_step3_order_router.py
├── .env.example                  # Environment variable template
├── inventory.db                  # SQLite file, created at startup, gitignored
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

On the same machine: `http://localhost:8000`. On your phone, over the same WiFi network: `http://<your-pc-ip>:8000` (find your IP with `ipconfig` on Windows or `ifconfig` on Mac/Linux).

**6. (Optional) Connect Swiggy**

Set `SWIGGY_CLIENT_ID` and `APP_BASE_URL` in `.env`, then tap "Connect Swiggy" in the header. Without this, the app still works end to end using dry run order simulation.

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
| `SWIGGY_AGENT_MODEL` | Optional | Gemini model the ADK agent uses for tool selection (default `gemini-2.5-flash`) |
| `SWIGGY_CLIENT_ID` | For real orders | OAuth 2.1 client ID for the Swiggy PKCE login flow |
| `APP_BASE_URL` | For real orders | Base URL this app is reachable at, used to build the OAuth redirect URI |
| `SECRET_KEY` | Recommended | Signs session cookies via `itsdangerous`, set a real random value in production |
| `DELIVERY_ADDRESS` | Optional | Default delivery address passed to the agent (default `Mumbai, India`) |

## 9. Swiggy MCP integration

All three Swiggy MCP servers are wired into a single agent at the same time, so the agent picks the right platform for the request instead of the app's own decision logic restricting it up front:

- `SWIGGY_FOOD_MCP_URL`, restaurant delivery
- `SWIGGY_INSTAMART_MCP_URL`, grocery delivery
- `SWIGGY_DINEOUT_MCP_URL`, table reservations

**Agent.** `swiggy_agent.py` builds a `google.adk.agents.Agent` backed by Gemini with a `MCPToolset` per server, each using `StreamableHTTPConnectionParams` over standard streamable HTTP. There is no hand-rolled JSON-RPC and no stub server in the active path. The agent discovers whichever tools each server exposes at connection time rather than the app hardcoding tool names.

**Auth.** `app.py` implements OAuth 2.1 with PKCE itself: `/auth/login` generates a code verifier and S256 challenge and redirects to Swiggy's authorize endpoint, `/auth/callback` exchanges the returned code for a Bearer access token and stores it in the session, `/auth/status` reports whether that token is still valid, and `/auth/logout` clears it. The Bearer token is forwarded directly into every `MCPToolset`'s `StreamableHTTPConnectionParams(headers=...)`, which is the integration point ADK exposes for authenticated MCP calls.

**Token lifetime.** Swiggy MCP issues a 5 day access token with no refresh token, so that token is the entire session. `swiggy_agent.py` treats both raised 401 exceptions and agent responses that mention 401, unauthorized, or a similar phrase as `auth_required`, and the frontend surfaces a "Connect Swiggy" prompt rather than retrying silently in the background.

**Dry run.** `run_swiggy_agent(..., dry_run=True)` returns a simulated `OrderResult` without contacting Swiggy at all, used by the CLI's `--dry-run` flag and exercised in the test suite.

## 10. Architecture

```
                              +-------------------+
                              |   templates/       |
                              |   index.html        |
                              |  Cook tab | Pantry   |
                              +----+---------+-------+
                                   |         |
                    POST /api/scan |         | /api/inventory/*
                    POST /api/order|         | /api/inventory/cart-fill
                                   v         v
+----------------------------------------------------------------+
|                            app.py (FastAPI)                     |
|  SSE streaming, session/OAuth, inventory CRUD                   |
+----+------------------------+------------------------+---------+
     |                        |                        |
     v                        v                        v
+-----------+        +-------------------+      +----------------+
| step1_    |        | step2_            |      | inventory_db.py|
| fridge_   | -----> | meal_planner.py    |      | (SQLite,       |
| vision.py |        | Gemini decision:   |      |  aiosqlite)    |
| Gemini    |        | cook / order_dish /|      +----------------+
| Vision    |        | order_groceries    |
+-----------+        +---------+---------+
                                |
                                v
                      +-------------------+
                      | step3_order_       |
                      | router.py           |
                      | (thin adapter)       |
                      +---------+-----------+
                                |
                                v
                      +-------------------+
                      | swiggy_agent.py     |
                      | google.adk.agents   |
                      | .Agent + MCPToolset |
                      +----+------+------+--+
                           |      |      |
                StreamableHTTP    |      |
                           v      v      v
                     +-------+ +-------+ +---------+
                     | Food  | | Insta-| | Dineout |
                     | MCP   | | mart  | | MCP     |
                     |       | | MCP   | |         |
                     +-------+ +-------+ +---------+
```
