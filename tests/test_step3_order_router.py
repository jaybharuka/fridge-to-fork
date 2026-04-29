"""
Tests for step3_order_router — MCP HTTP calls are mocked with pytest-httpx,
and dry_run mode is tested without any network.
"""

import pytest

from fridge_to_fork.models import Decision, MealPlan, MealSuggestion
from fridge_to_fork.step3_order_router import (
    order_dish_from_swiggy,
    order_groceries_from_instamart,
    route_order,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(
    decision: Decision,
    meal_name: str = "Scrambled Eggs",
    missing: list[str] | None = None,
) -> MealPlan:
    meal = MealSuggestion(
        name=meal_name,
        description="",
        can_cook_now=(decision == Decision.COOK),
        missing_ingredients=missing or [],
    )
    return MealPlan(
        suggestions=[meal],
        decision=decision,
        recommended_meal=meal,
        reasoning="test",
    )


# ---------------------------------------------------------------------------
# dry_run tests (no network required)
# ---------------------------------------------------------------------------

def test_order_dish_dry_run():
    result = order_dish_from_swiggy("Butter Chicken", "Mumbai", dry_run=True)
    assert result.success is True
    assert result.platform == "swiggy_food"
    assert result.order_id is not None
    assert result.estimated_minutes == 35
    assert "Butter Chicken" in result.items


def test_order_groceries_dry_run():
    items = ["onion", "tomato", "garlic"]
    result = order_groceries_from_instamart(items, "Mumbai", dry_run=True)
    assert result.success is True
    assert result.platform == "swiggy_instamart"
    assert result.order_id is not None
    assert result.estimated_minutes == 15
    assert result.items == items


def test_order_groceries_dry_run_single_item():
    result = order_groceries_from_instamart(["milk"], "Delhi", dry_run=True)
    assert result.success is True
    assert result.items == ["milk"]


# ---------------------------------------------------------------------------
# route_order dispatch tests
# ---------------------------------------------------------------------------

def test_route_order_cook_returns_none():
    plan = _make_plan(Decision.COOK)
    result = route_order(plan, "Mumbai", dry_run=True)
    assert result is None


def test_route_order_order_dish():
    plan = _make_plan(Decision.ORDER_DISH, meal_name="Biryani")
    result = route_order(plan, "Mumbai", dry_run=True)
    assert result is not None
    assert result.platform == "swiggy_food"
    assert result.success is True


def test_route_order_order_groceries():
    plan = _make_plan(Decision.ORDER_GROCERIES, missing=["tomato", "onion"])
    result = route_order(plan, "Mumbai", dry_run=True)
    assert result is not None
    assert result.platform == "swiggy_instamart"
    assert "tomato" in result.items


def test_route_order_groceries_no_missing_returns_none():
    """If decision is order_groceries but no missing items, return None."""
    plan = _make_plan(Decision.ORDER_GROCERIES, missing=[])
    result = route_order(plan, "Mumbai", dry_run=True)
    assert result is None


def test_route_order_uses_recommended_meal_name():
    plan = _make_plan(Decision.ORDER_DISH, meal_name="Dal Makhani")
    result = route_order(plan, "Bengaluru", dry_run=True)
    assert "Dal Makhani" in result.items


# ---------------------------------------------------------------------------
# OrderResult structure tests
# ---------------------------------------------------------------------------

def test_order_result_fields():
    result = order_dish_from_swiggy("Pizza", "Hyderabad", dry_run=True)
    assert hasattr(result, "success")
    assert hasattr(result, "order_id")
    assert hasattr(result, "platform")
    assert hasattr(result, "items")
    assert hasattr(result, "estimated_minutes")
    assert hasattr(result, "error")
    assert result.error is None  # no error in dry_run


def test_order_id_is_unique():
    r1 = order_dish_from_swiggy("Pizza", "A", dry_run=True)
    r2 = order_dish_from_swiggy("Pizza", "A", dry_run=True)
    assert r1.order_id != r2.order_id
