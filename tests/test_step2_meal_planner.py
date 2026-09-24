"""
Tests for step2_meal_planner — all Claude API calls are mocked.
"""

import json
from unittest.mock import MagicMock

import pytest

from fridge_to_fork.models import Decision, FridgeContents, Ingredient, MealPlan
from fridge_to_fork.step2_meal_planner import (
    _fuzzy_ingredient_match,
    _normalize_ingredient_words,
    plan_meals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FULL_FRIDGE_RESPONSE = {
    "suggestions": [
        {
            "name": "Scrambled Eggs",
            "description": "Quick and easy scrambled eggs with butter.",
            "can_cook_now": True,
            "missing_ingredients": [],
            "cuisine": "Western",
            "prep_time_minutes": 10,
        },
        {
            "name": "Cheese Omelette",
            "description": "Fluffy omelette with cheddar.",
            "can_cook_now": True,
            "missing_ingredients": [],
            "cuisine": "Western",
            "prep_time_minutes": 12,
        },
        {
            "name": "Pasta Carbonara",
            "description": "Classic carbonara with eggs and cheese.",
            "can_cook_now": False,
            "missing_ingredients": ["pancetta", "black pepper"],
            "cuisine": "Italian",
            "prep_time_minutes": 25,
        },
    ],
    "decision": "cook",
    "recommended_meal": "Scrambled Eggs",
    "reasoning": "Most ingredients are present. Scrambled eggs is fast and uses what's available.",
}

SPARSE_FRIDGE_RESPONSE = {
    "suggestions": [
        {
            "name": "Biryani",
            "description": "Fragrant rice dish.",
            "can_cook_now": False,
            "missing_ingredients": ["basmati rice", "chicken", "spices", "onion", "yogurt"],
            "cuisine": "Indian",
            "prep_time_minutes": 60,
        }
    ],
    "decision": "order_dish",
    "recommended_meal": "Biryani",
    "reasoning": "Too many missing ingredients. Ordering the dish is more practical.",
}

ALMOST_THERE_RESPONSE = {
    "suggestions": [
        {
            "name": "Tomato Omelette",
            "description": "Eggs with fresh tomato.",
            "can_cook_now": False,
            "missing_ingredients": ["tomato"],
            "cuisine": "Western",
            "prep_time_minutes": 15,
        }
    ],
    "decision": "order_groceries",
    "recommended_meal": "Tomato Omelette",
    "reasoning": "Only one ingredient missing. Quick-commerce can deliver it in 15 min.",
}


def _make_fridge(*names: str) -> FridgeContents:
    return FridgeContents(ingredients=[Ingredient(name=n) for n in names])


def _mock_client(response_json: dict) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.text = json.dumps(response_json)
    client.models.generate_content.return_value = response
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plan_meals_cook_decision():
    fridge = _make_fridge("eggs", "butter", "cheddar cheese", "milk")
    client = _mock_client(FULL_FRIDGE_RESPONSE)

    plan = plan_meals(fridge, client=client)

    assert isinstance(plan, MealPlan)
    assert plan.decision == Decision.COOK
    assert plan.recommended_meal is not None
    assert plan.recommended_meal.name == "Scrambled Eggs"
    assert len(plan.suggestions) == 3


def test_plan_meals_order_dish_decision():
    fridge = _make_fridge("salt")
    client = _mock_client(SPARSE_FRIDGE_RESPONSE)

    plan = plan_meals(fridge, client=client)

    assert plan.decision == Decision.ORDER_DISH
    assert plan.recommended_meal.name == "Biryani"
    assert "basmati rice" in plan.recommended_meal.missing_ingredients


def test_plan_meals_order_groceries_decision():
    fridge = _make_fridge("eggs", "butter", "oil")
    client = _mock_client(ALMOST_THERE_RESPONSE)

    plan = plan_meals(fridge, client=client)

    assert plan.decision == Decision.ORDER_GROCERIES
    assert plan.recommended_meal.missing_ingredients == ["tomato"]


def test_plan_meals_empty_fridge():
    fridge = FridgeContents(ingredients=[])
    client = _mock_client(SPARSE_FRIDGE_RESPONSE)

    plan = plan_meals(fridge, client=client)

    # With empty fridge the prompt still fires; result depends on model response
    assert plan.decision in Decision.__members__.values()


def test_plan_meals_strips_markdown_fence():
    wrapped = "```json\n" + json.dumps(FULL_FRIDGE_RESPONSE) + "\n```"
    client = MagicMock()
    response = MagicMock()
    response.text = wrapped
    client.models.generate_content.return_value = response

    plan = plan_meals(_make_fridge("eggs"), client=client)
    assert len(plan.suggestions) == 3


def test_plan_meals_fallback_recommended_meal():
    """If recommended_meal name doesn't match any suggestion, fall back to first."""
    response = dict(FULL_FRIDGE_RESPONSE)
    response["recommended_meal"] = "NonExistentDish"
    client = _mock_client(response)

    plan = plan_meals(_make_fridge("eggs"), client=client)

    assert plan.recommended_meal == plan.suggestions[0]


def test_plan_meals_uses_correct_model():
    client = _mock_client(FULL_FRIDGE_RESPONSE)
    plan_meals(_make_fridge("eggs"), model="gemini-2.0-flash", client=client)
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-2.0-flash"


def test_plan_meals_includes_ingredient_names_in_prompt():
    client = _mock_client(FULL_FRIDGE_RESPONSE)
    fridge = _make_fridge("spinach", "paneer", "cream")
    plan_meals(fridge, client=client)

    kwargs = client.models.generate_content.call_args.kwargs
    prompt_text = kwargs["contents"]
    assert "spinach" in prompt_text
    assert "paneer" in prompt_text
    assert "cream" in prompt_text


def test_plan_meals_with_target_dish():
    client = _mock_client(FULL_FRIDGE_RESPONSE)
    fridge = _make_fridge("eggs", "butter")
    plan_meals(fridge, target_dish="Mushroom Risotto", client=client)

    kwargs = client.models.generate_content.call_args.kwargs
    prompt_text = kwargs["contents"]
    assert "Mushroom Risotto" in prompt_text
    assert "eggs" in prompt_text


# ---------------------------------------------------------------------------
# _fuzzy_ingredient_match / _normalize_ingredient_words
# Vision-accuracy audit (2026-09) found two real bugs here: "capsicum"
# (a plausible Gemini vision output) never matched "bell pepper" (a
# plausible recipe ingredient name) despite naming the same vegetable —
# a genuinely-detected item silently reported as "missing" — and the
# plural-stripping heuristic mangled "grapes" into "grap" instead of
# "grape", breaking that match too. Both fixed together since they're the
# same bug family (matching logic, not vision accuracy).
# ---------------------------------------------------------------------------

def test_capsicum_matches_bell_pepper():
    assert _fuzzy_ingredient_match("capsicum", ["bell pepper"])
    assert _fuzzy_ingredient_match("bell pepper", ["capsicum"])
    assert _fuzzy_ingredient_match("red bell pepper", ["capsicum"])


def test_capsicum_does_not_match_unrelated_pepper_items():
    """Guards against the coarser fix (mapping the single word "capsicum" -> "pepper")
    that would have falsely matched the spice, not just the vegetable."""
    assert not _fuzzy_ingredient_match("capsicum", ["black pepper"])
    assert not _fuzzy_ingredient_match("capsicum", ["pepper powder"])


@pytest.mark.parametrize("singular,plural", [
    ("grape", "grapes"),
    ("apple", "apples"),
    ("olive", "olives"),
    ("lime", "limes"),
])
def test_plural_of_word_ending_in_e_matches_singular(singular, plural):
    assert _fuzzy_ingredient_match(singular, [plural])
    assert _fuzzy_ingredient_match(plural, [singular])


@pytest.mark.parametrize("singular,plural", [
    ("tomato", "tomatoes"),
    ("potato", "potatoes"),
    ("mango", "mangoes"),
])
def test_oes_plural_still_matches_singular(singular, plural):
    """The -oes case (tomato/potato/mango) must keep working after narrowing the old
    blanket "any -es" stripping rule down to just this pattern."""
    assert _fuzzy_ingredient_match(singular, [plural])


def test_grapes_normalizes_to_grape_not_grap():
    assert _normalize_ingredient_words("grapes") == {"grape"}


def test_coriander_leaves_still_does_not_match_coriander_powder():
    """Pre-existing behavior this fix must not regress."""
    assert not _fuzzy_ingredient_match("coriander leaves", ["coriander powder"])


def test_subset_match_still_works():
    """Pre-existing behavior this fix must not regress."""
    assert _fuzzy_ingredient_match("ginger-garlic paste", ["ginger"])
