"""
Tests for swiggy_agent._build_instruction() / _agent_system_instruction() —
no network, pure string-building logic.

Security-fix regression coverage: Decision.ADD_TO_CART must never produce
an instruction (per-decision or system-level) that could be read by the
agent as license to check out, place an order, or pay. See app.py
cart_fill() and the "Add to cart never checks out" fix.
"""

import pytest

from fridge_to_fork.models import Decision, MealPlan, MealSuggestion
from fridge_to_fork.swiggy_agent import (
    _CHECKOUT_CAPABLE_DECISIONS,
    _agent_system_instruction,
    _build_instruction,
)


def _make_plan(decision: Decision, missing: list[str] | None = None) -> MealPlan:
    meal = MealSuggestion(
        name="Masala Omelette",
        description="",
        can_cook_now=False,
        missing_ingredients=missing or [],
    )
    return MealPlan(
        suggestions=[meal], decision=decision, recommended_meal=meal, reasoning="test",
    )


# ---------------------------------------------------------------------------
# _build_instruction() — ADD_TO_CART must be unambiguously cart-only
# ---------------------------------------------------------------------------

def test_add_to_cart_instruction_forbids_checkout():
    plan = _make_plan(Decision.ADD_TO_CART, missing=["Paneer", "Yogurt", "Besan"])
    instruction = _build_instruction(plan, "Mumbai, India")
    lower = instruction.lower()

    # The instruction must explicitly forbid checkout/ordering, not just omit it.
    assert "do not check out" in lower or "do not checkout" in lower
    assert "do not place an order" in lower or "do not place any order" in lower
    assert "cod" not in lower
    assert "cash on delivery" not in lower
    # "checkout" itself may appear when NAMING the forbidden tool
    # ("do not call checkout") — the exact bug phrase from the original
    # instruction ("and checkout for delivery") must never appear here.
    assert "confirm_order" in lower or "payment" in lower  # names the forbidden tools/concept
    assert "and checkout for delivery" not in lower


def test_add_to_cart_instruction_contains_all_items():
    items = ["Paneer", "Yogurt", "Besan"]
    plan = _make_plan(Decision.ADD_TO_CART, missing=items)
    instruction = _build_instruction(plan, "Mumbai, India")
    for item in items:
        assert item in instruction


def test_add_to_cart_instruction_mentions_add_to_cart():
    plan = _make_plan(Decision.ADD_TO_CART, missing=["Paneer"])
    instruction = _build_instruction(plan, "Mumbai, India").lower()
    assert "add" in instruction and "cart" in instruction


def test_order_groceries_instruction_still_says_checkout():
    """Unchanged existing behaviour — ORDER_GROCERIES is still checkout-capable."""
    plan = _make_plan(Decision.ORDER_GROCERIES, missing=["Paneer"])
    instruction = _build_instruction(plan, "Mumbai, India").lower()
    assert "checkout" in instruction


def test_order_dish_instruction_unchanged():
    plan = _make_plan(Decision.ORDER_DISH)
    instruction = _build_instruction(plan, "Mumbai, India").lower()
    assert "swiggy food" in instruction


def test_cook_decision_falls_through_to_default():
    plan = _make_plan(Decision.COOK)
    instruction = _build_instruction(plan, "Mumbai, India")
    assert "has all ingredients" in instruction


# ---------------------------------------------------------------------------
# _agent_system_instruction() — COD line must be scoped to checkout-capable
# decisions only, never bleeding into ADD_TO_CART
# ---------------------------------------------------------------------------

def test_add_to_cart_not_in_checkout_capable_set():
    assert Decision.ADD_TO_CART not in _CHECKOUT_CAPABLE_DECISIONS
    assert Decision.ORDER_GROCERIES in _CHECKOUT_CAPABLE_DECISIONS
    assert Decision.ORDER_DISH in _CHECKOUT_CAPABLE_DECISIONS


def test_system_instruction_add_to_cart_has_no_cod_line():
    instruction = _agent_system_instruction(Decision.ADD_TO_CART).lower()
    assert "cod" not in instruction
    assert "cash on delivery" not in instruction
    assert "not authorized to check out" in instruction


def test_system_instruction_order_groceries_keeps_cod_line():
    instruction = _agent_system_instruction(Decision.ORDER_GROCERIES).lower()
    assert "cod" in instruction


def test_system_instruction_order_dish_keeps_cod_line():
    instruction = _agent_system_instruction(Decision.ORDER_DISH).lower()
    assert "cod" in instruction


# ---------------------------------------------------------------------------
# run_swiggy_agent() dry_run — ADD_TO_CART never fabricates an order_id/ETA
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_to_cart_dry_run_has_no_order_id_or_eta():
    from fridge_to_fork.swiggy_agent import run_swiggy_agent

    plan = _make_plan(Decision.ADD_TO_CART, missing=["Paneer", "Yogurt"])
    result = await run_swiggy_agent(plan, "Mumbai, India", dry_run=True)

    assert result.success is True
    assert result.order_id is None
    assert result.estimated_minutes is None
    assert result.platform == "swiggy_instamart"
    assert result.items == ["Paneer", "Yogurt"]


@pytest.mark.asyncio
async def test_order_groceries_dry_run_still_has_order_id():
    """Unchanged existing behaviour."""
    from fridge_to_fork.swiggy_agent import run_swiggy_agent

    plan = _make_plan(Decision.ORDER_GROCERIES, missing=["Paneer"])
    result = await run_swiggy_agent(plan, "Mumbai, India", dry_run=True)

    assert result.success is True
    assert result.order_id is not None
    assert result.estimated_minutes == 15
