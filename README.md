# 🍴 Fridge to Fork

> Snap your fridge. Get meal suggestions. Order missing ingredients — all powered by Google Gemini AI.

```
📷 fridge photo → 🤖 Gemini Vision → 🥦 ingredients → 🍳 meal plan → cook / 🛵 Swiggy order
```

## Demo

Open the mobile web app on your phone, take a photo of your fridge, and in ~30 seconds you'll see:
- Every ingredient detected with confidence scores
- Meal suggestions you can cook right now vs. what needs ordering
- Automatic Swiggy Instamart order for missing items

---

## Stack

| Layer | Tech |
|---|---|
| AI Vision & Planning | [Google Gemini 2.5 Flash](https://aistudio.google.com) |
| Web Backend | [FastAPI](https://fastapi.tiangolo.com) + SSE streaming |
| Mobile UI | Vanilla HTML/CSS/JS (camera capture, dark mode) |
| Order Routing | Swiggy Food & Instamart MCP (JSON-RPC 2.0) |

---

## Pipeline

| Step | File | What it does |
|---|---|---|
| 1 | `step1_fridge_vision.py` | Gemini Vision identifies ingredients from a fridge photo |
| 2 | `step2_meal_planner.py` | Gemini suggests meals, decides cook vs. order |
| 3 | `step3_order_router.py` | Routes to Swiggy Food or Swiggy Instamart MCP |
| — | `agent.py` | Orchestrates all three steps end-to-end |
| — | `app.py` | FastAPI web server with mobile UI |

---

## Setup

### 1. Install dependencies

```bash
pip install -e ".[dev]"
```

### 2. Get a free Gemini API key

1. Go to [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Sign in with a **personal Gmail** account (not a Workspace/org account)
3. Click **"Create API key"** → **"Create API key in new project"**

> ⚠️ Google Workspace accounts have Gemini free-tier quota set to 0. Use a personal Gmail account.

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and set your key:
# GOOGLE_API_KEY=AIzaSy...
```

---

## Run — Mobile Web App (recommended)

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Then open on your phone (same WiFi as your PC):

```
http://<your-pc-ip>:8000
```

Find your PC's IP with `ipconfig` (Windows) or `ifconfig` (Mac/Linux).

---

## Run — CLI

```bash
# Full pipeline (dry-run: no real Swiggy orders)
python -m fridge_to_fork.agent --image fridge.jpg --dry-run

# Test each layer in isolation
python -m fridge_to_fork.step1_fridge_vision --image fridge.jpg
python -m fridge_to_fork.step2_meal_planner --ingredients "eggs,butter,cheese"
python -m fridge_to_fork.step3_order_router --decision order_groceries --items "tomato,onion" --dry-run
```

---

## Test

```bash
pytest   # all layers mocked — no API key needed
```

---

## Project Structure

```
fridge-to-fork/
├── app.py                        # FastAPI web server + SSE streaming
├── templates/
│   └── index.html                # Mobile-first web UI (camera capture)
├── fridge_to_fork/
│   ├── models.py                 # Shared dataclasses (Ingredient, MealPlan, OrderResult…)
│   ├── step1_fridge_vision.py    # Gemini Vision layer
│   ├── step2_meal_planner.py     # Gemini meal planner
│   ├── step3_order_router.py     # Swiggy MCP client stubs
│   └── agent.py                  # End-to-end orchestrator
├── tests/
│   ├── test_step1_fridge_vision.py
│   ├── test_step2_meal_planner.py
│   └── test_step3_order_router.py
├── .env.example                  # Environment variable template
└── pyproject.toml
```

---

## Swiggy MCP Integration

`step3_order_router._call_mcp()` is the single seam for MCP communication.
It sends JSON-RPC 2.0 `tools/call` requests to the Swiggy MCP endpoints.

Replace the stub URLs with the official Swiggy MCP SDK endpoints once published.
Until then, use `--dry-run` to simulate orders.

**Swiggy Food tools:** `swiggy_food_search`, `swiggy_food_place_order`  
**Swiggy Instamart tools:** `instamart_search`, `instamart_place_order`

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | ✅ Yes | Google Gemini API key (from AI Studio) |
| `SWIGGY_INSTAMART_MCP_URL` | Optional | Instamart MCP endpoint (default: `localhost:8001`) |
| `SWIGGY_FOOD_MCP_URL` | Optional | Swiggy Food MCP endpoint (default: `localhost:8002`) |
| `DELIVERY_ADDRESS` | Optional | Default delivery address for orders |
