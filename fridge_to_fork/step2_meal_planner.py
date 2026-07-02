"""
Step 2 — Meal Planner
=====================
Takes identified fridge contents and uses Google Gemini to:
  1. Suggest 3–5 meals
  2. Decide whether to cook (ingredients present) or order
     (either the finished dish from Swiggy Food, or missing
      ingredients from Swiggy Instamart)

Run standalone:
    python -m fridge_to_fork.step2_meal_planner --ingredients "eggs,butter,cheese,bread"
"""

import argparse
import json
import os
import time
from typing import Optional

from dotenv import load_dotenv
from google import genai
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import Decision, FridgeContents, Ingredient, MealPlan, MealSuggestion

load_dotenv()

console = Console()


def _dedupe(models: list[str | None]) -> list[str]:
    """Remove falsy/duplicate entries while preserving order."""
    seen = set()
    result = []
    for m in models:
        if m and m not in seen:
            seen.add(m)
            result.append(m)
    return result


# Models tried in order until one succeeds. Each Gemini model has its own
# separate free-tier daily quota, so exhausting one doesn't mean they're
# all exhausted.
TEXT_MODEL_FALLBACK_CHAIN = _dedupe([
    os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash"),
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash-lite",
    "gemini-flash-lite-latest",
])

# ---------------------------------------------------------------------------
# Fallback suggestions (when API quota is exceeded)
# ---------------------------------------------------------------------------

def _fallback_meal_plan(
    fridge: FridgeContents,
    target_dish: Optional[str] = None
) -> MealPlan:
    """Return sensible defaults when Google API quota is exceeded."""
    if target_dish:
        # Small heuristic mapping for a few common dishes to create a sensible shopping list
        core_map = {
            "chole": ["chickpeas (dried or canned)", "onion", "garlic", "ginger", "tomato", "spices (cumin, coriander, garam masala)", "oil"],
            "bhature": ["all-purpose flour (maida)", "yeast or baking soda", "oil for frying"],
            "omelette": ["eggs", "salt", "pepper", "oil or butter"],
            "pancake": ["flour", "milk", "egg", "baking powder", "oil or butter"],
            "sandwich": ["bread", "butter", "cheese or spread", "vegetables"],
        }

        low = target_dish.lower()
        core = []
        for k, v in core_map.items():
            if k in low:
                core = v
                break

        if not core:
            # Generic fallback shopping list for an unknown target dish
            core = ["flour", "oil", "salt", "spices", "one fresh vegetable"]

        missing = [it for it in core if not any(it.split()[0].lower() in ing.name.lower() for ing in fridge.ingredients)]

        suggestions = [
            MealSuggestion(
                name=target_dish,
                description=f"A practical suggestion to make {target_dish}.",
                can_cook_now=(len(missing) == 0),
                missing_ingredients=missing or [],
                cuisine="Various",
                prep_time_minutes=30,
            )
        ]
        decision = Decision.COOK if len(missing) == 0 else Decision.ORDER_GROCERIES
        if len(missing) == 0:
            reasoning = f"You appear to have the core ingredients to make {target_dish}."
        else:
            reasoning = (
                f"You're missing {len(missing)} core items for {target_dish}. "
                f"Suggested quick grocery items: {', '.join(missing[:6])}."
            )
    else:
        has_eggs = any(ing.name.lower() in ["eggs", "egg"] for ing in fridge.ingredients)
        has_bread = any(ing.name.lower() in ["bread", "bread rolls", "flatbread"] for ing in fridge.ingredients)
        has_veggies = any(
            ing.name.lower() in ["tomato", "cucumber", "lettuce", "carrot", "onion"]
            for ing in fridge.ingredients
        )
        
        suggestions = []
        if has_eggs and has_bread:
            suggestions.append(MealSuggestion(
                name="Egg Toast", description="Quick breakfast.",
                can_cook_now=True, missing_ingredients=[], cuisine="Simple", prep_time_minutes=10,
            ))
        if has_veggies:
            suggestions.append(MealSuggestion(
                name="Vegetable Salad", description="Fresh & healthy.",
                can_cook_now=True, missing_ingredients=[], cuisine="International", prep_time_minutes=5,
            ))
        if len(fridge.ingredients) >= 3:
            suggestions.append(MealSuggestion(
                name="Stir-fry", description="With available ingredients.",
                can_cook_now=True, missing_ingredients=[], cuisine="Asian", prep_time_minutes=15,
            ))
        if not suggestions:
            suggestions.append(MealSuggestion(
                name="Order Food",
                description="You have limited usable ingredients — ordering a ready dish is recommended.",
                can_cook_now=False,
                missing_ingredients=["pantry staples: salt, oil, spices, flour"],
                cuisine="Any",
                prep_time_minutes=0,
            ))

        decision = Decision.COOK if any(s.can_cook_now for s in suggestions) else Decision.ORDER_DISH
        # Provide clearer reasoning so the UI can display something reviewer-friendly.
        reasoning = (
            "Local fallback: recommending a simple meal plan based on scanned items. "
            "If you want precise recipes, enable the live model or add a few pantry staples."
        )
    
    recommended = suggestions[0] if suggestions else None
    return MealPlan(suggestions=suggestions, decision=decision, recommended_meal=recommended, reasoning=reasoning)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_MISSING_INGREDIENT_RULES = """\
IMPORTANT RULES FOR MISSING INGREDIENTS:

1. PANTRY STAPLES — Never mark these as missing, assume the user has them:
   Salt, sugar, black pepper, red chili powder, turmeric, cumin, coriander
   powder, garam masala, mustard seeds, curry leaves, bay leaves, cooking oil
   (any kind), ghee, butter, flour (maida/atta), rice, basic lentils (dal),
   vinegar, soy sauce, baking soda, baking powder, water.

2. NON-FRIDGE ITEMS — Never mark these as missing just because they aren't
   in the fridge photo. These are commonly stored at room temperature:
   Onions, garlic, ginger, potatoes, tomatoes, bananas, bread, dry pasta,
   dry noodles, canned goods, packaged spices, tea, coffee.

3. DECISION LOGIC — Apply this strictly:
   - If the only "missing" items are pantry staples or non-fridge items
     from the lists above → decision must be "cook", not "order_groceries"
   - Only mark something as missing if it is a SPECIFIC ingredient that
     is genuinely uncommon to have at home (e.g. arborio rice, saffron,
     specific vegetables the dish is named after like bhindi/okra)
   - For "order_groceries": only list items that are genuinely missing and
     NOT on the pantry staples or non-fridge lists above
   - The dish the user asked for is their TARGET — try hard to find a way
     to cook it before deciding to order

4. EXAMPLE — For "Bhindi Fry":
   - Bhindi (okra) → check if in fridge. If not → missing (it's the main ingredient)
   - Cooking oil → assume available (pantry staple) → NOT missing
   - Salt → assume available (pantry staple) → NOT missing
   - Onion → assume available (non-fridge item) → NOT missing
   - Spices → assume available (pantry staples) → NOT missing
   - Result: only missing item is bhindi itself → decision: order_groceries
     (just order the bhindi), not order_dish
"""

_PROMPT_TEMPLATE = """\
You are an expert chef and nutritionist helping a busy person decide what to eat.

Available ingredients:
{ingredient_list}

Suggest 3 to 5 meals. For each meal state:
- Whether it can be cooked right now with the listed ingredients
- Which ingredients are missing (if any)

Also recommend ONE best action:
- "cook"             → cook the best available meal
- "order_dish"       → order the finished dish from a food-delivery service
- "order_groceries"  → order the 1-2 missing ingredients from a quick-commerce service and then cook

Prefer cooking when ≥70% of ingredients are present and missing items are few.
Prefer ordering the dish when the user would need to buy 5+ ingredients.
Prefer ordering groceries when the user needs just 1-3 ingredients.

""" + _MISSING_INGREDIENT_RULES + """

Return ONLY valid JSON (no markdown, no prose):
{{
  "suggestions": [
    {{
      "name": "<meal name>",
      "description": "<one sentence>",
      "can_cook_now": <true|false>,
      "missing_ingredients": ["<item>", ...],
      "cuisine": "<e.g. Indian, Italian, Mexican>",
      "prep_time_minutes": <integer>
    }}
  ],
  "decision": "<cook|order_dish|order_groceries>",
  "recommended_meal": "<meal name from the list above>",
  "reasoning": "<one or two sentences explaining the decision>"
}}
"""


_TARGET_DISH_PROMPT = """\
You are an expert chef and nutritionist helping a busy person.

The user explicitly wants to eat: "{target_dish}"

Available ingredients in their fridge:
{ingredient_list}

Evaluate if they can make "{target_dish}" with what they have.
State:
- Whether it can be cooked right now
- Exactly which ingredients are missing to make it

Recommend ONE best action:
- "cook"             → if they have everything needed to make "{target_dish}"
- "order_groceries"  → if they are missing a few ingredients and should order them via quick-commerce to cook it
- "order_dish"       → if they are missing almost everything and should just order the finished dish from a restaurant

""" + _MISSING_INGREDIENT_RULES + """

Return ONLY valid JSON (no markdown, no prose) with a single suggestion representing the target dish:
{{
  "suggestions": [
    {{
      "name": "<name of the target dish>",
      "description": "<one sentence describing the dish>",
      "can_cook_now": <true|false>,
      "missing_ingredients": ["<missing item 1>", ...],
      "cuisine": "<cuisine type>",
      "prep_time_minutes": <integer>
    }}
  ],
  "decision": "<cook|order_dish|order_groceries>",
  "recommended_meal": "<name of the target dish>",
  "reasoning": "<one or two sentences explaining why they should cook, order groceries, or order the dish>"
}}
"""


# ---------------------------------------------------------------------------
# Core planner function
# ---------------------------------------------------------------------------

def _call_text_model_with_retry(client: genai.Client, model: str, prompt: str) -> MealPlan:
    """
    Call `model` up to 3 times with exponential backoff, for transient
    errors (503/network blips). Raises the last exception if all
    attempts fail — the caller decides whether that means "try the next
    model in the fallback chain" or "give up".
    """
    max_retries = 3
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )

            raw_text = (response.text or "").strip()

            # Check if response looks like an error
            if "error" in raw_text.lower() or "resource_exhausted" in raw_text.lower():
                console.print(f"[yellow][WARNING] {model} API error detected in response[/yellow]")
                raise RuntimeError("API returned error-like payload")

            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            payload = json.loads(raw_text)

            suggestions = [
                MealSuggestion(
                    name=s["name"],
                    description=s.get("description", ""),
                    can_cook_now=bool(s.get("can_cook_now", False)),
                    missing_ingredients=s.get("missing_ingredients", []),
                    cuisine=s.get("cuisine", ""),
                    prep_time_minutes=int(s.get("prep_time_minutes", 0)),
                )
                for s in payload.get("suggestions", [])
            ]

            decision = Decision(payload.get("decision", Decision.COOK))
            recommended_name = payload.get("recommended_meal", "")
            recommended = next((s for s in suggestions if s.name == recommended_name), None)
            if recommended is None and suggestions:
                recommended = suggestions[0]

            return MealPlan(
                suggestions=suggestions,
                decision=decision,
                recommended_meal=recommended,
                reasoning=payload.get("reasoning", ""),
            )

        except Exception as e:
            console.print(f"[yellow]{model} attempt {attempt} failed:[/yellow] {type(e).__name__}: {e}")
            if attempt == max_retries:
                raise
            time.sleep(backoff)
            backoff *= 2

    raise RuntimeError(f"{model} failed after {max_retries} attempts")  # unreachable safeguard


def plan_meals(
    fridge: FridgeContents,
    *,
    target_dish: Optional[str] = None,
    model: str | None = None,
    client: Optional[genai.Client] = None,
) -> MealPlan:
    """
    Suggest meals and decide cook-vs-order given fridge contents.
    If target_dish is provided, evaluate that specific dish instead of suggesting random meals.

    Parameters
    ----------
    fridge:
        Output of step1 identify_ingredients().
    target_dish:
        Optional specific dish the user wants to make.
    model:
        Optional Gemini model override. If omitted, tries each model in
        TEXT_MODEL_FALLBACK_CHAIN in order until one succeeds.
    client:
        Optional pre-built Gemini client.

    Returns
    -------
    MealPlan with suggestions, a Decision, and the recommended meal.

    Retries transient API errors (quota/overload) up to 3 times with
    exponential backoff per model. If a model's quota is exhausted (or it
    keeps failing after retries), moves on to the next model in the
    fallback chain before giving up and returning a local fallback plan.
    """
    client = client or genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))

    # Build ingredient list for the prompt
    ingredient_list = "\n".join(
        f"- {ing.name}" + (f" ({ing.quantity})" if ing.quantity else "")
        for ing in fridge.ingredients
    )
    if not ingredient_list:
        ingredient_list = "(no ingredients detected)"

    if target_dish:
        prompt = _TARGET_DISH_PROMPT.format(
            ingredient_list=ingredient_list, target_dish=target_dish
        )
    else:
        prompt = _PROMPT_TEMPLATE.format(ingredient_list=ingredient_list)

    chain = _dedupe([model, *TEXT_MODEL_FALLBACK_CHAIN]) if model else TEXT_MODEL_FALLBACK_CHAIN

    for chain_model in chain:
        try:
            result = _call_text_model_with_retry(client, chain_model, prompt)
            console.print(f"[green][OK] Meal planning succeeded with model: {chain_model}[/green]")
            return result
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                console.print(f"[yellow][WARNING] {chain_model} quota exhausted, trying next model...[/yellow]")
            else:
                console.print(f"[yellow][WARNING] {chain_model} failed with: {e}, trying next...[/yellow]")

    console.print("[yellow][WARNING] All Gemini text models quota exhausted, using fallback[/yellow]")
    return _fallback_meal_plan(fridge, target_dish)


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------

def display_meal_plan(plan: MealPlan) -> None:
    decision_colors = {
        Decision.COOK: "green",
        Decision.ORDER_DISH: "red",
        Decision.ORDER_GROCERIES: "yellow",
    }
    decision_labels = {
        Decision.COOK: "Cook at home",
        Decision.ORDER_DISH: "Order the dish",
        Decision.ORDER_GROCERIES: "Order missing groceries",
    }

    console.rule("[bold blue]Meal Suggestions")

    table = Table(show_lines=True)
    table.add_column("Meal", style="cyan")
    table.add_column("Cuisine", style="magenta")
    table.add_column("Prep (min)", justify="right")
    table.add_column("Ready to cook?", justify="center")
    table.add_column("Missing")

    for s in plan.suggestions:
        ready = "[green]Yes[/green]" if s.can_cook_now else "[red]No[/red]"
        missing = ", ".join(s.missing_ingredients) if s.missing_ingredients else "—"
        table.add_row(s.name, s.cuisine, str(s.prep_time_minutes), ready, missing)

    console.print(table)

    color = decision_colors[plan.decision]
    label = decision_labels[plan.decision]
    rec_name = plan.recommended_meal.name if plan.recommended_meal else "—"

    console.print(
        Panel(
            f"[bold]Recommended:[/bold] {rec_name}\n"
            f"[bold]Decision:[/bold] [{color}]{label}[/{color}]\n\n"
            f"[italic]{plan.reasoning}[/italic]",
            title="Action",
            border_style=color,
        )
    )


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plan meals from fridge ingredients.")
    p.add_argument(
        "--ingredients",
        required=True,
        help="Comma-separated ingredient list, e.g. 'eggs,butter,cheese'",
    )
    p.add_argument("--model", default="gemini-2.5-flash")
    p.add_argument("--target-dish", default=None, help="Specific dish you want to cook")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    names = [n.strip() for n in args.ingredients.split(",") if n.strip()]
    fridge = FridgeContents(ingredients=[Ingredient(name=n) for n in names])

    if args.target_dish:
        console.print(f"[bold]Evaluating target dish:[/bold] {args.target_dish}")
    else:
        console.print(f"[bold]Planning meals for:[/bold] {', '.join(names)}")
        
    plan = plan_meals(fridge, target_dish=args.target_dish, model=args.model)

    if args.json:
        import json as _json
        data = {
            "decision": plan.decision.value,
            "recommended_meal": plan.recommended_meal.name if plan.recommended_meal else None,
            "reasoning": plan.reasoning,
            "suggestions": [
                {
                    "name": s.name,
                    "cuisine": s.cuisine,
                    "can_cook_now": s.can_cook_now,
                    "missing_ingredients": s.missing_ingredients,
                    "prep_time_minutes": s.prep_time_minutes,
                }
                for s in plan.suggestions
            ],
        }
        print(_json.dumps(data, indent=2))
    else:
        display_meal_plan(plan)


if __name__ == "__main__":
    main()
