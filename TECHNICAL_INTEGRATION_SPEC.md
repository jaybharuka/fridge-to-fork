# Fridge to Fork — Technical Integration Specification for Swiggy MCP

**Prepared for:** Swiggy Engineering / Partnerships
**Prepared by:** Fridge to Fork
**Date:** 2026-08-21
**Purpose:** Fulfil Clause 2.1(v) of the Integration Agreement (signed 16-Aug-2026) — full and complete technical details, specifications, and particulars of how Fridge to Fork plans to use, invoke, and integrate the Swiggy MCP — submitted for Swiggy's written consent ahead of receiving staging/sandbox credentials.

---

## 1. App Overview

Fridge to Fork is a web app that turns "what can I eat right now?" into an answer in seconds. A user either names a dish they want to cook or takes photos of their fridge. The app uses Google Gemini vision to detect what ingredients are actually present, then uses Gemini again to produce a full recipe (ingredients, quantities, cooking steps) scaled to the requested number of servings. It deterministically compares the recipe's ingredient list against what was detected in the fridge (plus a staples list) to work out exactly what's missing. The user is then given a choice: cook it themselves, order the missing ingredients for delivery (Swiggy Instamart), or order the finished dish for delivery (Swiggy Food). This document concerns only that last step — placing the order via Swiggy.

## 2. Current Architecture Relevant to the Integration

**Backend:** FastAPI (Python), single-process server (`app.py`), session-based auth via signed cookies (`SessionMiddleware`).

**`/api/scan` (SSE flow).** This is the main analysis pipeline, triggered when the user submits fridge photos and/or a target dish. It is a `POST` endpoint returning a Server-Sent Events stream. The real event sequence emitted, in order, is:

1. `progress` (step 1) — "Scanning your fridge with AI vision…"
2. `step1` — vision results: detected ingredients with name/quantity/confidence, or an empty list if the user skipped straight to a named recipe.
3. `progress` (step 2) — "Evaluating '<dish>'…" or "Planning your meals…"
4. `step2_partial` — repeated events streaming the raw text of the recipe/meal-plan generation as it's produced.
5. `step2` — the finished plan: decision, recommended meal, recipe ingredients (with `found_in_fridge`/`is_staple`/estimated price), cooking steps.
6. `awaiting_user_choice` — signals the frontend to render the "how do you want to handle this?" choice card, with the computed missing-ingredients list and total estimated price. **No order has been placed at this point** — this is purely informational, waiting on the user.
7. `top_up` (optional, best-effort) — 4–5 small upsell suggestions (Instamart or Swiggy Food items) generated separately by Gemini; never blocks the main flow and is silently skipped on failure.
8. `complete` — stream end.
9. `error` — on unrecoverable failure (falls back to a local, non-AI meal plan where possible rather than failing outright).
10. `auth_required` — emitted if a downstream call needs a Swiggy session token that isn't present or has expired (see §3 — this can occur today only via the separate cart-fill flow described below, not from `/api/scan` itself, since `/api/scan` does not call Swiggy).

**Where `swiggy_agent.py` currently sits.** `fridge_to_fork/swiggy_agent.py` is the module responsible for all outbound Swiggy calls. Today it implements:

- **OAuth 2.1 + PKCE session handling** is actually done in `app.py` (`/auth/login`, `/auth/callback`, `/auth/status`, `/auth/logout`), not in `swiggy_agent.py` itself. `app.py` redirects the user to `https://mcp.swiggy.com/auth/authorize`, exchanges the resulting code for a bearer access token at `https://mcp.swiggy.com/auth/token`, and stores it in the signed session cookie with an expiry.
- **`run_swiggy_agent(plan, delivery_address, access_token, dry_run=False)`** — the single entry point that all ordering goes through. It builds a natural-language instruction from the `MealPlan` (e.g. "order X from Swiggy Food" or "order these missing ingredients from Instamart"), and hands it to a Google ADK (Agent Development Kit) `Agent` backed by Gemini. That agent is configured with three `MCPToolset`s pointed at `https://mcp.swiggy.com/food`, `https://mcp.swiggy.com/im` (Instamart), and `https://mcp.swiggy.com/dineout`, each authenticated with the user's bearer token (`Authorization: Bearer <access_token>`) via `StreamableHTTPConnectionParams`. The agent is left to autonomously choose which MCP tools to call to fulfil the instruction — **we do not hardcode specific MCP tool/method names or a request schema today**; that decision is delegated to the LLM agent based on whatever tools the MCP server exposes to it at connect time.
- Response parsing is regex-based against the agent's free-text final response (looking for an order-ID-shaped token, an ETA in minutes, and words like "confirmed"/"placed" to infer success). This is a placeholder approach pending real MCP request/response schemas from Swiggy — see §4.
- A `dry_run=True` path exists that fabricates a fake `OrderResult` (a `SWG-XXXXXXXX` ID, canned ETA) without calling Swiggy at all — used for local development without credentials, and is **not** wired into the production request path described below.

`fridge_to_fork/step3_order_router.py` is a thin wrapper: `order_dish_from_swiggy()` and `order_groceries_from_instamart()` each build a minimal `MealPlan` and call `run_swiggy_agent()`.

## 3. Proposed MCP Integration Point

The real-time MCP call described in Section 2 of the Agreement ("Partner will make a real time MCP call to Swiggy to confirm the details and availability of the Listings for the customer to place the Orders") is triggered at exactly one place in the app: the `/api/order` endpoint in `app.py`.

**Trigger sequence:**
1. After `/api/scan` completes and the choice card renders (from `awaiting_user_choice`), the user taps either "Order missing items from Instamart" or "Order the dish from Swiggy."
2. For the Instamart path, tapping the choice card first opens a review sheet (`confirmOrderGroceries()` / `openOrderSheet()` in `templates/index.html`) showing the missing-items list and any top-up upsells, and the user confirms from there via `chooseAction('order_groceries', ...)`. For the Swiggy Food path, `chooseAction('order_dish', ...)` fires directly from the choice card.
3. `chooseAction()` posts to `POST /api/order` (`app.py:892`) with `action` (`order_groceries` | `order_dish`), `meal_name`, and a comma-separated `missing_ingredients` list.
4. `place_order()` (`app.py:892`) checks for a valid session access token (redirecting to `auth_required` if absent), then calls `order_groceries_from_instamart()` or `order_dish_from_swiggy()` (`fridge_to_fork/step3_order_router.py`), which delegates to `run_swiggy_agent()` (`fridge_to_fork/swiggy_agent.py:65`) — **this is the function where the real-time MCP call to Swiggy occurs.**

This is currently the only code path that talks to the Swiggy MCP endpoints. `/api/scan` and its meal-planning pipeline never call Swiggy — they only produce the plan the user chooses from. There is also a secondary, separate use of the same `run_swiggy_agent()` function via `/api/cart-fill` (`app.py:373`), used by the recipe checklist's "Add to Instamart" button to search-and-add individual items one at a time; it goes through the identical MCP call path described above, just item-by-item instead of as one order.

## 4. Data Flow

**What we send today (constructed server-side, not yet MCP-schema-validated):**
- A bearer access token obtained via the OAuth 2.1/PKCE flow described in §2, sent as `Authorization: Bearer <token>` on the MCP connection.
- For an Instamart order: the list of missing ingredient names (plain strings, e.g. `"paneer"`, `"kasuri methi"`) derived from the recipe-vs-fridge comparison, plus the delivery address (currently a plain string, e.g. `"Mumbai, India"`, sourced from `DELIVERY_ADDRESS` env var or a hardcoded default — see §5).
- For a Swiggy Food order: the recommended dish name (plain string) and the same delivery address.
- All of the above is currently wrapped into a single natural-language instruction string handed to a Gemini-backed ADK agent, which then autonomously selects and invokes whatever MCP tools the Swiggy MCP server exposes to it. **We do not currently construct a structured MCP request payload ourselves** — this is the main gap this document flags for Swiggy's review.

**What we expect back:** per Clause 2.1(iii) of the Agreement, an order confirmation / listing-validity / success message. Today we parse this out of the agent's free-text response using regex heuristics (order ID pattern, ETA in minutes, presence of words like "confirmed"). This is explicitly a placeholder, not a real integration against a documented schema.

**What we're asking Swiggy for:** the exact expected MCP request schema (tool/method names, required and optional parameters, how a dish/listing is identified, how quantities and units should be expressed for grocery items, how delivery address/geo should be passed) and the exact response schema (order confirmation object shape, success/failure signaling, error codes, listing-availability responses). Our current understanding is based solely on the Agreement's language ("confirm the details and availability of the Listings"), not on any API documentation we've seen — we need Swiggy to confirm or share this before we can replace the current agent-autonomous/regex-parsing approach with a real, schema-validated integration.

## 5. Environments and Credentials Needed

We do not yet have Swiggy MCP staging/sandbox credentials. We are requesting them so we can build and test this integration end-to-end — real MCP calls against a non-production environment — before any production use, per the Agreement's requirement that we obtain written consent to these details first.

We already have an established pattern for storing API credentials securely: all secrets (Google Gemini API key, YouTube/Unsplash keys, Swiggy client ID, session-signing secret, etc.) are loaded from environment variables via a local `.env` file (see `.env.example` in the repo root for the full list of variable names — no actual values are included here or in that file, which is a template). The same pattern will be used for Swiggy MCP staging credentials once issued: `SWIGGY_CLIENT_ID`, and MCP endpoint URLs are already environment-configurable today (`SWIGGY_FOOD_MCP_URL`, `SWIGGY_INSTAMART_MCP_URL`, `SWIGGY_DINEOUT_MCP_URL`), currently pointed at what we believe are the production MCP hosts (`https://mcp.swiggy.com/...`). We will point these at staging URLs once provided, and will not invoke production MCP endpoints until Swiggy has confirmed the integration details in this document and issued production access separately.

## 6. Compliance Notes

- **"Powered by Swiggy" (Clause 3.4(ii)):** Not yet implemented in the current UI — we found no such badge in `templates/index.html` today. We plan to add it to the order-related surfaces: the choice card where the user picks Instamart/Swiggy Food, and the order confirmation state shown after `/api/order` completes. We will confirm exact placement and treatment with Swiggy before shipping.
- **Customer data use (Clause 3.3):** The only customer data sent toward Swiggy today is the OAuth bearer token (for authenticating the user's own Swiggy account), the delivery address, and the specific item/dish names and quantities needed to fulfil the order the user explicitly requested. No other customer data is transmitted to Swiggy or stored by us beyond what's needed for order fulfilment (the access token and its expiry are held only in the signed session cookie).
- **Exclusivity:** The current codebase integrates with no other food delivery or quick-commerce platform. Swiggy Food, Instamart, and Dineout (via MCP) are the only external ordering integrations present.

## 7. Open Questions for Swiggy

- Staging/sandbox MCP credentials and endpoint URLs, so we can build and test against a non-production environment.
- The exact MCP request/response schema for confirming listing details/availability and placing an order (tool names, parameters, response shape, error codes) — and any SDK, reference client, or documentation we should use instead of, or alongside, the Google ADK autonomous-agent approach described in §2–3.
- Rate limits on the MCP endpoints (per-user and/or per-partner), so we can build appropriate client-side throttling/retry behavior.
- Confirmation of the customer support SLA process referenced in Section 7 of the Agreement, so we know how order-fulfilment issues should be escalated once live.
