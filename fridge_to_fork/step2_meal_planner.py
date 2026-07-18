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
import re
import time
from typing import Optional

from dotenv import load_dotenv
from google import genai
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import Decision, FridgeContents, Ingredient, MealPlan, MealSuggestion, RecipeIngredient

load_dotenv()

console = Console()


# ---------------------------------------------------------------------------
# Fridge / staple matching — deterministic, Python-side (not left to the LLM
# to self-report, since that proved unreliable in practice)
# ---------------------------------------------------------------------------

# Assumed available regardless of what's in the fridge photo (or when
# there's no photo at all) — a normal Indian kitchen has these.
_STAPLES = [
    "salt", "oil", "ghee", "butter", "water", "flour", "sugar",
    "cumin seeds", "mustard seeds", "turmeric", "red chilli powder",
    "coriander powder", "garam masala", "onions", "garlic", "ginger",
    "green chillies", "potatoes", "tomatoes", "lemon",
]

_DESCRIPTIVE_WORDS = {
    "fresh", "chopped", "whole", "medium", "large", "small", "grated",
    "sliced", "minced", "dried", "ripe", "raw", "boiled", "cooked",
    "or", "and", "of", "the", "a",
}

# Spelling variants that the naive pluralization heuristic below turns
# into different strings (e.g. "chili"/"chilies"/"chilly"/"chily" from
# "chilli"/"chillies") — canonicalize them to one token so they still match.
_SPELLING_VARIANTS = {
    "chili": "chilli", "chilies": "chilli", "chily": "chilli", "chilly": "chilli",
    "yogurt": "yoghurt", "curd": "yoghurt",
}


def _normalize_ingredient_words(name: str) -> set[str]:
    """Lowercase, strip descriptive words, and naively singularize each
    word so "Fresh Tomatoes" and "tomato" both reduce to {"tomato"}."""
    words = re.findall(r"[a-z]+", name.lower())
    result = set()
    for word in words:
        if word in _DESCRIPTIVE_WORDS:
            continue
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("es") and len(word) > 3:
            word = word[:-2]
        elif word.endswith("s") and len(word) > 3:
            word = word[:-1]
        word = _SPELLING_VARIANTS.get(word, word)
        result.add(word)
    return result


def _fuzzy_ingredient_match(recipe_name: str, candidate_names: list[str]) -> bool:
    """True if `recipe_name` fuzzy-matches any of `candidate_names` —
    case/plural/descriptive-word insensitive. Uses subset containment
    (not "any shared word") so e.g. "ginger-garlic paste" still matches
    a plain "ginger", but "coriander leaves" does NOT falsely match a
    "coriander powder" staple just because both mention coriander."""
    recipe_words = _normalize_ingredient_words(recipe_name)
    if not recipe_words:
        return False
    for candidate in candidate_names:
        candidate_words = _normalize_ingredient_words(candidate)
        if not candidate_words:
            continue
        if candidate_words <= recipe_words or recipe_words <= candidate_words:
            return True
    return False


def _is_pantry_staple(recipe_name: str) -> bool:
    return _fuzzy_ingredient_match(recipe_name, _STAPLES)


def _enrich_recipe_ingredients(plan: MealPlan, fridge: FridgeContents) -> MealPlan:
    """
    Deterministically (not via LLM self-report) fill in is_staple and
    found_in_fridge on every recipe ingredient, then derive the
    recommended meal's missing_ingredients (name + total price) from
    whatever's left unchecked — neither a staple nor detected in the
    fridge photo. No cook/order_groceries/order_dish decision is made
    here; the user picks for themselves between ordering the missing
    items or ordering the finished dish.
    """
    fridge_names = [ing.name for ing in fridge.ingredients]

    for suggestion in plan.suggestions:
        if not suggestion.recipe_ingredients:
            continue
        for ri in suggestion.recipe_ingredients:
            ri.is_staple = _is_pantry_staple(ri.name)
            ri.found_in_fridge = _fuzzy_ingredient_match(ri.name, fridge_names)

    if plan.recommended_meal and plan.recommended_meal.recipe_ingredients:
        missing = [
            ri for ri in plan.recommended_meal.recipe_ingredients
            if not (ri.is_staple or ri.found_in_fridge)
        ]
        plan.recommended_meal.missing_ingredients = [ri.name for ri in missing]
        plan.recommended_meal.total_order_price_inr = sum(ri.estimated_price_inr for ri in missing)

    return plan


def _ascii_safe(value) -> str:
    """
    ASCII-only string repr for logging arbitrary LLM output (emoji, etc.)
    to stdout. Both plain print() and rich's Console() have proven
    unreliable with wide/multi-codepoint Unicode when stdout is a
    redirected (non-TTY) stream rather than a real console.
    """
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


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
                cooking_steps=[
                    "Gather and prep all the ingredients listed above.",
                    f"Follow your usual method for {target_dish}, adjusting seasoning to taste.",
                    "Cook until done, then serve hot.",
                ],
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
        reasoning = "Based on what's in your fridge right now."
    
    recommended = suggestions[0] if suggestions else None
    return MealPlan(suggestions=suggestions, decision=decision, recommended_meal=recommended, reasoning=reasoning)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_RECIPE_RULES = """\
RECIPE INGREDIENTS — for the suggested dish, return every single
ingredient needed to cook it — do not classify ingredients as staples,
garnishes, "have", or "missing", and do not compare against the fridge
contents. Just list everything the recipe requires; a separate process
(not you) will determine what the user already has.

QUANTITIES — scale every ingredient's quantity to the requested number
of servings (see below), and include the unit in the same field, e.g.
"200g", "2 medium", "1 tsp".

PRICES — every ingredient must include a realistic estimated_price_inr
as a plain integer in Indian Rupees, for the quantity listed. Never
null, never "--", never omit this field.
"""

_PROMPT_TEMPLATE = _RECIPE_RULES + """
You are an expert chef and nutritionist helping a busy person decide what to eat.

Ingredients detected in their fridge (for inspiration only):
{ingredient_list}

Suggest 3 to 5 meals inspired by what's available. For each meal, give a
complete recipe per the RECIPE INGREDIENTS rules above.

Also return a complete ingredient list for cooking each suggested dish for {servings} people
with exact quantities, SCALED to {servings} servings — do not use a fixed base-recipe amount
regardless of the number of people. Work out the per-serving amount and multiply it by
{servings}. Example: if a base recipe for 2 people needs "1 cup rice", for {servings} people
that becomes roughly "{servings_half} cups rice" (i.e. 0.5 cup per person x {servings}). Apply
that same scaling logic to every quantity. Be specific: "2 medium onions", "200ml fresh cream",
"3 cloves garlic", "1 tsp cumin seeds".

Also return clear step-by-step cooking instructions as a numbered "cooking_steps" array — one
imperative sentence per step (e.g. "Heat oil in a pan over medium heat", "Add chopped onions
and saute until golden"), enough steps to actually cook the dish start to finish. This is the
recipe itself, so it must be complete and followable, not a summary. prep_time_minutes must be
a realistic estimate for this specific dish, not a generic default like 30 for everything.

Return ONLY valid JSON (no markdown, no prose):
{{
  "suggestions": [
    {{
      "name": "<meal name>",
      "description": "<one sentence>",
      "cuisine": "<e.g. Indian, Italian, Mexican>",
      "prep_time_minutes": <integer>,
      "recipe_ingredients": [
        {{
          "name": "<ingredient name>",
          "quantity": "<exact amount with unit, e.g. '200ml', '2 medium'>",
          "estimated_price_inr": <integer>
        }}
      ],
      "cooking_steps": ["<step 1>", "<step 2>", ...]
    }}
  ],
  "recommended_meal": "<meal name from the list above>",
  "reasoning": "<one or two sentences about the recommended dish>"
}}
"""


_TARGET_DISH_PROMPT = _RECIPE_RULES + """
You are an expert chef and nutritionist helping a busy person.

The user explicitly wants to eat: "{target_dish}"

Ingredients detected in their fridge (for inspiration only):
{ingredient_list}

Give a complete recipe for "{target_dish}" per the RECIPE INGREDIENTS
rules above.

Also return a complete ingredient list for cooking "{target_dish}" for {servings} people
with exact quantities, SCALED to {servings} servings — do not use a fixed base-recipe amount
regardless of the number of people. Work out the per-serving amount and multiply it by
{servings}. Example: if a base recipe for 2 people needs "1 cup rice", for {servings} people
that becomes roughly "{servings_half} cups rice" (i.e. 0.5 cup per person x {servings}). Apply
that same scaling logic to every quantity. Be specific: "2 medium onions", "200ml fresh cream",
"3 cloves garlic", "1 tsp cumin seeds".

Also return clear step-by-step cooking instructions as a numbered "cooking_steps" array — one
imperative sentence per step (e.g. "Heat oil in a pan over medium heat", "Add chopped onions
and saute until golden"), enough steps to actually cook "{target_dish}" start to finish. This
is the recipe itself, so it must be complete and followable, not a summary. prep_time_minutes
must be a realistic estimate for "{target_dish}" specifically, not a generic default like 30
for everything.

Return ONLY valid JSON (no markdown, no prose) with a single suggestion representing the target dish:
{{
  "suggestions": [
    {{
      "name": "<name of the target dish>",
      "description": "<one sentence describing the dish>",
      "cuisine": "<cuisine type>",
      "prep_time_minutes": <integer>,
      "recipe_ingredients": [
        {{
          "name": "<ingredient name>",
          "quantity": "<exact amount with unit, e.g. '200ml', '2 medium'>",
          "estimated_price_inr": <integer>
        }}
      ],
      "cooking_steps": ["<step 1>", "<step 2>", ...]
    }}
  ],
  "recommended_meal": "<name of the target dish>",
  "reasoning": "<one or two sentences about the dish>"
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
                    # No more have/missing classification, so this no longer
                    # reflects fridge contents — it's unused by the UI.
                    can_cook_now=True,
                    cuisine=s.get("cuisine", ""),
                    prep_time_minutes=int(s.get("prep_time_minutes", 0)),
                    # is_staple / found_in_fridge are filled in afterwards by
                    # _enrich_recipe_ingredients() — deterministic Python
                    # matching, not left to the LLM to self-report.
                    recipe_ingredients=[
                        RecipeIngredient(
                            name=ri.get("name", ""),
                            quantity=ri.get("quantity", ""),
                            estimated_price_inr=int(ri.get("estimated_price_inr", 0) or 0),
                        )
                        for ri in s.get("recipe_ingredients", [])
                    ] or None,
                    cooking_steps=[step for step in s.get("cooking_steps", []) if step],
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
    servings: int = 2,
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
    servings:
        How many people the recipe_ingredients quantities should be
        scaled for. Defaults to 2.

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

    servings_half = round(servings * 0.5, 1)
    if servings_half == int(servings_half):
        servings_half = int(servings_half)

    if target_dish:
        prompt = _TARGET_DISH_PROMPT.format(
            ingredient_list=ingredient_list, target_dish=target_dish,
            servings=servings, servings_half=servings_half,
        )
    else:
        prompt = _PROMPT_TEMPLATE.format(
            ingredient_list=ingredient_list, servings=servings, servings_half=servings_half
        )

    chain = _dedupe([model, *TEXT_MODEL_FALLBACK_CHAIN]) if model else TEXT_MODEL_FALLBACK_CHAIN

    for chain_model in chain:
        try:
            result = _call_text_model_with_retry(client, chain_model, prompt)
            console.print(f"[green][OK] Meal planning succeeded with model: {chain_model}[/green]")
            return _enrich_recipe_ingredients(result, fridge)
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                console.print(f"[yellow][WARNING] {chain_model} quota exhausted, trying next model...[/yellow]")
            else:
                console.print(f"[yellow][WARNING] {chain_model} failed with: {e}, trying next...[/yellow]")

    console.print("[yellow][WARNING] All Gemini text models quota exhausted, using fallback[/yellow]")
    return _enrich_recipe_ingredients(_fallback_meal_plan(fridge, target_dish), fridge)


# ---------------------------------------------------------------------------
# Top-up suggestions — small upsell items shown alongside the meal plan
# ---------------------------------------------------------------------------

_TOP_UP_PROMPT = """\
You are a smart shopping assistant for Swiggy, India's leading food
delivery platform.

The user is planning to make: {meal_name}
Their fridge contains: {ingredient_list}
Ingredients already missing for this dish (being ordered separately —
never suggest these here): {missing_ingredients}
AI decision: {decision}

Suggest at most 3 smart "upgrade" items that would genuinely improve
this specific meal. These should be small, affordable, impulse purchases.

RULES:
- If decision is "cook" or "order_groceries": suggest items from
  Swiggy Instamart (fresh ingredients, condiments, toppings that
  elevate the dish)
- If decision is "order_dish": suggest complementary items from
  Swiggy Food (side dishes, drinks, desserts that pair well)
- Never suggest anything already listed in the missing ingredients above
- Never suggest a pantry staple: salt, sugar, water, cooking oil, ghee,
  butter, cumin seeds, mustard seeds, turmeric powder, red chilli powder,
  coriander powder, cumin powder, garam masala, hing, bay leaves, cloves,
  cardamom, cinnamon, black pepper, dried red chillies, onions, garlic,
  ginger, green chillies, tomatoes, potatoes, lemon, lime, wheat flour,
  baking soda, vinegar
- Never suggest something the user already has in their fridge
- Every suggestion must be vegetarian
- Each suggestion must be a genuine upgrade specific to {meal_name}, not
  a generic add-on that would fit any dish
- Price should be realistic for Indian market (₹30-₹200 range)
- At least one suggestion should be under ₹60 (low friction)

Return ONLY a valid JSON array with at most 3 objects:
[
  {{
    "name": "Fresh Strawberries",
    "reason": "Makes your French Toast feel like a cafe breakfast",
    "estimated_price": 49,
    "source": "instamart",
    "emoji": "🍓"
  }},
  ...
]
source must be either "instamart" or "swiggy_food".
Do not include any text outside the JSON array.
"""


def _parse_top_up_response(raw_text: str) -> list[dict]:
    raw_text = (raw_text or "").strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    items = json.loads(raw_text)
    if not isinstance(items, list):
        return []

    valid_sources = {"instamart", "swiggy_food"}
    suggestions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        if source not in valid_sources:
            continue
        name = item.get("name", "")
        if not name:
            continue
        try:
            price = int(float(item.get("estimated_price", 0)))
        except (TypeError, ValueError):
            continue
        suggestions.append({
            "name": name,
            "reason": item.get("reason", ""),
            "estimated_price": price,
            "source": source,
            "emoji": item.get("emoji", "✨"),
        })
    return suggestions[:3]


def generate_top_up_suggestions(
    fridge: FridgeContents,
    meal: MealSuggestion,
    decision: Decision,
    model: str | None = None,
) -> list[dict]:
    """
    Suggest 3 small upsell items (Instamart or Swiggy Food) that would
    elevate the given meal. Best-effort only — any failure (API error,
    malformed JSON, exhausted quota on every model, etc.) returns an
    empty list rather than raising, since this is a nice-to-have upsell
    card and must never block the main flow.
    """
    try:
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
    except Exception as e:
        console.print(f"[yellow][WARNING] generate_top_up_suggestions failed to init client: {type(e).__name__}: {e}[/yellow]")
        return []

    ingredient_list = ", ".join(ing.name for ing in fridge.ingredients) or "(nothing detected)"
    missing_ingredients = ", ".join(meal.missing_ingredients) if meal and meal.missing_ingredients else "(none)"
    prompt = _TOP_UP_PROMPT.format(
        meal_name=meal.name if meal else "this meal",
        ingredient_list=ingredient_list,
        missing_ingredients=missing_ingredients,
        decision=decision.value,
    )

    chain = _dedupe([model, *TEXT_MODEL_FALLBACK_CHAIN]) if model else TEXT_MODEL_FALLBACK_CHAIN

    missing_names = meal.missing_ingredients if meal and meal.missing_ingredients else []

    for chain_model in chain:
        print(f"[TOP_UP] Attempting with model: {chain_model}")
        try:
            response = client.models.generate_content(model=chain_model, contents=prompt)
            suggestions = _parse_top_up_response(response.text)
            suggestions = [
                s for s in suggestions
                if not _fuzzy_ingredient_match(s["name"], missing_names)
            ]
            print(f"[TOP_UP] Result: {_ascii_safe(suggestions)}")
            if suggestions:
                console.print(f"[green][OK] Top-up suggestions succeeded with model: {chain_model}[/green]")
                return suggestions[:3]
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                console.print(f"[yellow][WARNING] {chain_model} quota exhausted, trying next model for top-up...[/yellow]")
            else:
                console.print(f"[yellow][WARNING] {chain_model} top-up failed with: {e}, trying next...[/yellow]")

    console.print("[yellow][WARNING] All Gemini models failed for top-up suggestions, skipping[/yellow]")
    return []


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
