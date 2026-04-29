# Fridge to Fork

AI agent that looks at your fridge and decides what to cook — or orders it for you.

```
fridge photo → Claude Vision → ingredients → Claude meal plan → cook / Swiggy order
```

## Pipeline

| Step | File | What it does |
|------|------|-------------|
| 1 | `step1_fridge_vision.py` | Claude Vision identifies ingredients from a fridge photo |
| 2 | `step2_meal_planner.py` | Claude suggests meals and decides cook vs order |
| 3 | `step3_order_router.py` | Routes to Swiggy Food or Swiggy Instamart MCP |
| — | `agent.py` | Orchestrates all three steps end-to-end |

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env
# add your ANTHROPIC_API_KEY to .env
```

## Run

```bash
# Full pipeline (dry-run: no real Swiggy orders)
fridge-to-fork --image fridge.jpg --dry-run

# Test each layer in isolation
python -m fridge_to_fork.step1_fridge_vision --image fridge.jpg
python -m fridge_to_fork.step2_meal_planner --ingredients "eggs,butter,cheese"
python -m fridge_to_fork.step3_order_router --decision order_groceries --items "tomato,onion"
```

## Test

```bash
pytest                  # 33 tests, all layers mocked — no API key needed
```

## Architecture

```
fridge_to_fork/
├── models.py                 # shared dataclasses (Ingredient, MealPlan, OrderResult …)
├── step1_fridge_vision.py    # Claude Vision layer
├── step2_meal_planner.py     # Claude meal planner
├── step3_order_router.py     # Swiggy MCP client stubs
└── agent.py                  # end-to-end orchestrator
tests/
├── test_step1_fridge_vision.py
├── test_step2_meal_planner.py
└── test_step3_order_router.py
```

### Swiggy MCP integration

`step3_order_router._call_mcp()` is the single seam for MCP communication.
It sends JSON-RPC 2.0 `tools/call` requests. Replace it with the official
Swiggy MCP SDK once published. Until then use `--dry-run` to simulate orders.

**Swiggy Food tools used:** `swiggy_food_search`, `swiggy_food_place_order`  
**Swiggy Instamart tools used:** `instamart_search`, `instamart_place_order`
