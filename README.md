# 🍴 Fridge to Fork

> Snap your fridge. Tell us what you want to eat. Get meal suggestions. Order missing ingredients — all powered by Google Gemini AI.

```
[Target Dish] + [Fridge Photo] → 🤖 Gemini Vision → 🥦 Ingredients → 🍳 AI Planner → 🛵 Swiggy Order Router
```


---

## Deep Dive: What are we building?

Fridge to Fork is a highly intelligent, **Target-Dish Centric AI Agent Pipeline** designed to bridge the gap between what you *want* to eat and what you *actually have* in your fridge. 

Instead of just giving you random recipes, it operates like a personal culinary assistant integrated directly with quick-commerce.

### The Core Architecture

The system is built as a sequential agentic pipeline with three distinct phases:

#### 1. 👁️ Step 1: Fridge Vision (`step1_fridge_vision.py`)
You upload a photo of your fridge. We use **Google Gemini 2.5 Flash**'s multimodal capabilities to scan every shelf, drawer, and door pocket. The AI returns a highly structured, strict JSON payload containing every identified ingredient, a rough estimate of its quantity, and a confidence score.

#### 2. 🧠 Step 2: Target-Dish Centric Meal Planner (`step2_meal_planner.py`)
This is the brain of the operation. You tell the app what you want to eat (e.g., *"Mushroom Risotto"*). The AI cross-references the recipe for your Target Dish against the ingredients found in your fridge. 

It explicitly evaluates:
*   **What do you have?**
*   **What is missing?**
*   **The Decision Engine:** 
    *   If you have everything → `cook` (No order needed).
    *   If you are missing a few items (e.g., arborio rice and mushrooms) → `order_groceries` (Route to Swiggy Instamart).
    *   If you are missing almost everything or the dish is too complex to cook with your current inventory → `order_dish` (Route to Swiggy Food).

*(Fallback: If you don't provide a target dish, the AI intelligently suggests 3-5 meals based entirely on what is already in your fridge).*

#### 3. 🛵 Step 3: Order Router (`step3_order_router.py` + `swiggy_agent.py`)
Based on the Planner's decision, the Order Router hands off to a real **Google ADK agent** (`swiggy_agent.py`) rather than following a hardcoded tool-call sequence. See [Architecture](#-architecture) below for details.

---

## 🏗 Architecture

**Step 3 is a Google ADK agent, not procedural routing.** `swiggy_agent.py` builds a `google.adk.agents.Agent` backed by Gemini and wires it to Swiggy's MCP servers via `MCPToolset` + `StreamableHTTPConnectionParams`. Rather than the app calling specific named tools in a fixed order, the meal-plan decision is translated into a natural-language instruction (e.g. *"order 'Butter Chicken' from Swiggy Food, delivered to ..."*), and the agent autonomously decides which of Swiggy's available tools to call and in what order to fulfill it.

- **Two independent MCP servers** are wired, one per domain:
  - `SWIGGY_FOOD_MCP_URL` (default `https://mcp.swiggy.com/food`) — used when the decision is `order_dish`
  - `SWIGGY_INSTAMART_MCP_URL` (default `https://mcp.swiggy.com/im`) — used when the decision is `order_groceries`
- **Auth:** the app performs the OAuth 2.1 + PKCE flow itself (`app.py`'s `/auth/login` → `/auth/callback`, real code_verifier/S256 challenge, no static API key). The resulting Bearer access token is forwarded straight into `MCPToolset`'s `StreamableHTTPConnectionParams(headers=...)` — Google ADK has no built-in OAuth hook, so this Bearer-header pattern is the correct integration point for ADK specifically.
- **`step3_order_router.py`** now only adapts existing call sites (`order_dish_from_swiggy`, `order_groceries_from_instamart`, `route_order`) onto the agent, preserving their signatures so `app.py` and the CLI needed no changes.
- **401 / expired token:** a 5-day access token is the whole session (no refresh token in Swiggy MCP v1.0) — on auth failure the app surfaces an `auth_required` event so the user reconnects via `/auth/login`.

---

## 💻 Tech Stack

| Layer | Technology |
|---|---|
| **AI Orchestration** | Google GenAI SDK (`gemini-2.5-flash`) |
| **Backend API** | [FastAPI](https://fastapi.tiangolo.com) with Server-Sent Events (SSE) streaming |
| **Mobile UI** | Vanilla HTML/CSS/JS (Dark mode, glassmorphism, camera capture) |
| **Agent Framework** | Google ADK (`Agent` + `MCPToolset`) for autonomous Swiggy tool selection |
| **E-Commerce Integration** | Swiggy Food & Instamart MCP (streamable HTTP, OAuth 2.1 + PKCE) |

---

## 🚀 Setup & Installation

### 1. Install dependencies

```bash
pip install -e ".[dev]"
```

### 2. Get a free Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with a **personal Gmail** account (not a Workspace/org account)
3. Click **"Create API key"** → **"Create API key in new project"**

> ⚠️ **Note:** Google Workspace accounts currently have the Gemini free-tier quota set to 0. You must use a personal Gmail account to avoid `429 RESOURCE_EXHAUSTED` errors.

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and set your key:
# GOOGLE_API_KEY=AIzaSy...
```

---

## 📱 Run — Mobile Web App (Recommended)

Start the local server with hot-reloading:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Then open the app on your phone (ensure you are on the same WiFi network as your PC):

```
http://<your-pc-ip>:8000
```
*(Find your PC's IP with `ipconfig` on Windows or `ifconfig` on Mac/Linux).*

---

## 🖥️ Run — CLI Orchestrator

You can bypass the web UI and run the entire pipeline directly from your terminal:

```bash
# Run the full pipeline with a specific target dish (dry-run mode prevents real orders)
python -m fridge_to_fork.agent --image fridge.jpg --target-dish "Mushroom Risotto" --dry-run

# Run the pipeline without a target dish (triggers open-ended suggestions)
python -m fridge_to_fork.agent --image fridge.jpg --dry-run
```

**Test each layer in isolation:**
```bash
python -m fridge_to_fork.step1_fridge_vision --image fridge.jpg
python -m fridge_to_fork.step2_meal_planner --ingredients "eggs,butter,cheese" --target-dish "Omelette"
python -m fridge_to_fork.step3_order_router --decision order_groceries --items "tomato,onion" --dry-run
```

---

## 🧪 Testing

Run the test suite. All LLM calls and network requests are mocked out, so no API key is required to run the tests.

```bash
pytest --ignore=tests/test_step1_fridge_vision.py
```

---

## 📁 Project Structure

```text
fridge-to-fork/
├── app.py                        # FastAPI web server + SSE streaming
├── templates/
│   └── index.html                # Mobile-first web UI (camera capture + dynamic rendering)
├── fridge_to_fork/
│   ├── models.py                 # Shared dataclasses (Ingredient, MealPlan, OrderResult…)
│   ├── step1_fridge_vision.py    # Gemini Vision processing layer
│   ├── step2_meal_planner.py     # Gemini Target-Dish planning layer
│   ├── step3_order_router.py     # Swiggy MCP client stubs
│   └── agent.py                  # End-to-end CLI orchestrator
├── tests/
│   ├── test_step2_meal_planner.py
│   └── test_step3_order_router.py
├── .env.example                  # Environment variable template
└── pyproject.toml
```

---

## 🔌 Swiggy MCP Integration

`swiggy_agent.py` connects to Swiggy's real hosted MCP servers over standard
streamable HTTP (`google.adk.tools.mcp_tool.mcp_toolset.MCPToolset` +
`StreamableHTTPConnectionParams`) — no stub servers, no hand-rolled JSON-RPC.
The agent discovers whichever tools each server exposes at connection time
rather than the app hardcoding specific tool names.

Use `--dry-run` (CLI) or an unauthenticated session (web UI) to simulate
orders without calling Swiggy for real.

---

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | ✅ Yes | Google Gemini API key (from AI Studio) |
| `SWIGGY_INSTAMART_MCP_URL` | Optional | Instamart MCP endpoint (default: `https://mcp.swiggy.com/im`) |
| `SWIGGY_FOOD_MCP_URL` | Optional | Swiggy Food MCP endpoint (default: `https://mcp.swiggy.com/food`) |
| `SWIGGY_AGENT_MODEL` | Optional | Gemini model the ADK agent uses for tool selection (default: `gemini-2.5-flash`) |
| `SWIGGY_CLIENT_ID` | For real orders | OAuth 2.1 client ID issued by Swiggy for the PKCE login flow |
| `APP_BASE_URL` | For real orders | Base URL this app is reachable at, used to build the OAuth redirect_uri |
| `DELIVERY_ADDRESS` | Optional | Default delivery address for orders |
