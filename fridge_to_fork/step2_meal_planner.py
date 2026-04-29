"""
Step 2 — Meal Planner
=====================
Takes identified fridge contents and uses Claude to:
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
from typing import Optional

import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import Decision, FridgeContents, Ingredient, MealPlan, MealSuggestion

load_dotenv()

console = Console()

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert chef and nutritionist helping a busy person decide what to eat.
Given a list of available ingredients, suggest meals and determine the best action.
Respond ONLY with valid JSON — no prose, no markdown fences.
"""

_USER_PROMPT_TEMPLATE = """\
Available ingredients:
{ingredient_list}

Suggest 3 to 5 meals. For each meal state:
- Whether it can be cooked right now with the listed ingredients
- Which ingredients are missing (if any)

Also recommend ONE best action:
- "cook"             → cook the best available meal
- "order_dish"       → order the finished dish from a food-delivery service
- "order_groceries"  → order the 1-2 missing ingredients from a quick-commerce service and then cook

Prefer cooking when ≥70 % of ingredients are present and missing items are few.
Prefer ordering the dish when the user would need to buy 5+ ingredients.
Prefer ordering groceries when the user needs just 1-3 ingredients.

Return ONLY this JSON:
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


# ---------------------------------------------------------------------------
# Core planner function
# ---------------------------------------------------------------------------

def plan_meals(
    fridge: FridgeContents,
    *,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 1500,
    client: Optional[anthropic.Anthropic] = None,
) -> MealPlan:
    """
    Suggest meals and decide cook-vs-order given fridge contents.

    Parameters
    ----------
    fridge:
        Output of step1 identify_ingredients().
    model:
        Claude model. Sonnet is a good balance of speed/quality here.
    max_tokens:
        Response cap.
    client:
        Optional pre-built Anthropic client.

    Returns
    -------
    MealPlan with suggestions, a Decision, and the recommended meal.
    """
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Build ingredient list for the prompt
    ingredient_list = "\n".join(
        f"- {ing.name}" + (f" ({ing.quantity})" if ing.quantity else "")
        for ing in fridge.ingredients
    )
    if not ingredient_list:
        ingredient_list = "(no ingredients detected)"

    prompt = _USER_PROMPT_TEMPLATE.format(ingredient_list=ingredient_list)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()
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
    p.add_argument("--model", default="claude-sonnet-4-6")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    names = [n.strip() for n in args.ingredients.split(",") if n.strip()]
    fridge = FridgeContents(ingredients=[Ingredient(name=n) for n in names])

    console.print(f"[bold]Planning meals for:[/bold] {', '.join(names)}")
    plan = plan_meals(fridge, model=args.model)

    if args.json:
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
        import json as _json
        print(_json.dumps(data, indent=2))
    else:
        display_meal_plan(plan)


if __name__ == "__main__":
    main()
