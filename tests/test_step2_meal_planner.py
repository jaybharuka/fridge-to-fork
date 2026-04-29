"""
Tests for step2_meal_planner — all Claude API calls are mocked.
"""

import json
from unittest.mock import MagicMock

import pytest

from fridge_to_fork.models import Decision, FridgeContents, Ingredient, MealPlan
from fridge_to_fork.step2_meal_planner import plan_meals


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
    content_block = MagicMock()
    content_block.text = json.dumps(response_json)
    message = MagicMock()
    message.content = [content_block]
    client = MagicMock()
    client.messages.create.return_value = message
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
    content_block = MagicMock()
    content_block.text = wrapped
    message = MagicMock()
    message.content = [content_block]
    client = MagicMock()
    client.messages.create.return_value = message

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
    plan_meals(_make_fridge("eggs"), model="claude-haiku-4-5-20251001", client=client)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5-20251001"


def test_plan_meals_includes_ingredient_names_in_prompt():
    client = _mock_client(FULL_FRIDGE_RESPONSE)
    fridge = _make_fridge("spinach", "paneer", "cream")
    plan_meals(fridge, client=client)

    kwargs = client.messages.create.call_args.kwargs
    prompt_text = kwargs["messages"][0]["content"]
    assert "spinach" in prompt_text
    assert "paneer" in prompt_text
    assert "cream" in prompt_text
