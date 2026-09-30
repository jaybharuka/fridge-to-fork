"""
Tests for step3_order_router.py's CLI checkout safety guard.

Bug: `fridge-to-fork --decision order_groceries --items ...` (without
--dry-run) placed one real, unconfirmed COD order via the old checkout-
capable Decision.ORDER_GROCERIES path — no confirmation step, same class
of issue as the Smart Cart /api/cart-fill fix, just without the per-item
multiplication (this was always a single batched call).

Fix: order_dish/order_groceries (both checkout-capable, see swiggy_agent.
_CHECKOUT_CAPABLE_DECISIONS) now refuse to run unless --dry-run or the
explicit --confirm-checkout flag is passed. --decision add_to_cart (new)
never checks out and never needs either flag.

No network: run_swiggy_agent is always mocked. Separate file from the
pre-existing tests/test_step3_order_router.py, which has unrelated,
pre-existing failures (a stale access_token signature mismatch) that
predate this fix — kept apart so this file's results aren't muddied by
that.
"""

from unittest.mock import AsyncMock, patch

import pytest

from fridge_to_fork import step3_order_router as router
from fridge_to_fork.models import Decision, OrderResult


def _argv(*args):
    return patch("sys.argv", ["fridge-to-fork", *args])


@pytest.mark.asyncio
async def test_order_groceries_without_dry_run_or_confirm_refuses():
    mock_agent = AsyncMock()
    with _argv("--decision", "order_groceries", "--items", "onion,tomato"), \
         patch("fridge_to_fork.swiggy_agent.run_swiggy_agent", mock_agent):
        with pytest.raises(SystemExit) as exc_info:
            await router.main_async()
        assert exc_info.value.code == 1
    mock_agent.assert_not_called()


@pytest.mark.asyncio
async def test_order_dish_without_dry_run_or_confirm_refuses():
    """order_dish (Swiggy Food) is equally checkout-capable/COD — same guard."""
    mock_agent = AsyncMock()
    with _argv("--decision", "order_dish", "--items", "Butter Chicken"), \
         patch("fridge_to_fork.swiggy_agent.run_swiggy_agent", mock_agent):
        with pytest.raises(SystemExit) as exc_info:
            await router.main_async()
        assert exc_info.value.code == 1
    mock_agent.assert_not_called()


@pytest.mark.asyncio
async def test_order_groceries_with_dry_run_proceeds_without_confirm():
    mock_agent = AsyncMock(return_value=OrderResult(success=True, platform="swiggy_instamart"))
    with _argv("--decision", "order_groceries", "--items", "onion", "--dry-run"), \
         patch("fridge_to_fork.swiggy_agent.run_swiggy_agent", mock_agent):
        await router.main_async()
    mock_agent.assert_called_once()


@pytest.mark.asyncio
async def test_order_groceries_with_confirm_checkout_proceeds():
    mock_agent = AsyncMock(return_value=OrderResult(success=True, platform="swiggy_instamart"))
    with _argv("--decision", "order_groceries", "--items", "onion", "--confirm-checkout"), \
         patch("fridge_to_fork.swiggy_agent.run_swiggy_agent", mock_agent):
        await router.main_async()
    mock_agent.assert_called_once()
    plan = mock_agent.call_args.args[0]
    assert plan.decision == Decision.ORDER_GROCERIES


@pytest.mark.asyncio
async def test_add_to_cart_never_needs_confirm_checkout_or_dry_run():
    mock_agent = AsyncMock(return_value=OrderResult(success=True, platform="swiggy_instamart"))
    with _argv("--decision", "add_to_cart", "--items", "onion,tomato"), \
         patch("fridge_to_fork.swiggy_agent.run_swiggy_agent", mock_agent):
        await router.main_async()  # neither flag passed — must NOT refuse
    mock_agent.assert_called_once()
    plan = mock_agent.call_args.args[0]
    assert plan.decision == Decision.ADD_TO_CART
    assert plan.recommended_meal.missing_ingredients == ["onion", "tomato"]


@pytest.mark.asyncio
async def test_add_to_cart_with_no_items_does_nothing():
    mock_agent = AsyncMock()
    with _argv("--decision", "add_to_cart", "--items", " , "), \
         patch("fridge_to_fork.swiggy_agent.run_swiggy_agent", mock_agent):
        await router.main_async()
    mock_agent.assert_not_called()


def test_decision_choices_include_add_to_cart():
    assert set(router._CLI_DECISIONS) == {"order_dish", "order_groceries", "add_to_cart"}
    assert router._CLI_DECISIONS["add_to_cart"] == Decision.ADD_TO_CART
