"""
Regression test for the /api/cart-fill financial-risk fix.

Original bug: cart_fill() in app.py looped over items and called
run_swiggy_agent() once PER ITEM with Decision.ORDER_GROCERIES (whose
instruction told the agent to search, add to cart, AND checkout, COD by
default) — dry_run hardcoded to False, no confirmation step. Tapping
"Add" for N items could place up to N separate real COD orders.

Fix: one MealPlan covering every item, one run_swiggy_agent() call, using
Decision.ADD_TO_CART (whose instruction explicitly forbids checkout).
This test proves the call count and decision, with run_swiggy_agent
mocked — no real Swiggy account, token, or network involved.
"""

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

import app as app_module
from fridge_to_fork.models import Decision, OrderResult

ITEMS = [
    {"id": "d1", "name": "Paneer", "qty_needed": 1, "unit": "pack"},
    {"id": "d2", "name": "Yogurt", "qty_needed": 1, "unit": "pack"},
    {"id": "d3", "name": "Besan", "qty_needed": 1, "unit": "pack"},
]


def _client() -> TestClient:
    """Plain TestClient — auth is patched per-test via _token_valid()
    rather than a real OAuth round-trip, since auth correctness itself is
    covered elsewhere (test_auth_next_redirect.py). These tests isolate
    cart_fill()'s own call-batching logic, which is what the fix is about."""
    return TestClient(app_module.app)


@pytest.mark.asyncio
async def test_cart_fill_calls_agent_exactly_once_for_multiple_items():
    mock_result = OrderResult(success=True, platform="swiggy_instamart", items=[i["name"] for i in ITEMS])
    mock_agent = AsyncMock(return_value=mock_result)

    client = _client()
    with patch.object(app_module, "_token_valid", return_value=True), \
         patch("fridge_to_fork.swiggy_agent.run_swiggy_agent", mock_agent):
        response = client.post("/api/cart-fill", json={"items": ITEMS, "dry_run": True})

    assert response.status_code == 200
    body = response.text

    # Exactly one agent call for a 3-item batch, not three.
    assert mock_agent.call_count == 1

    call_kwargs = mock_agent.call_args.kwargs
    plan = call_kwargs["plan"]
    assert plan.decision == Decision.ADD_TO_CART
    assert plan.recommended_meal.missing_ingredients == ["Paneer", "Yogurt", "Besan"]
    assert call_kwargs["dry_run"] is True  # real parameter, propagated from the request body

    # SSE stream still reports per-item feedback for the UI.
    assert body.count('"type": "item_searching"') == 3
    assert body.count('"type": "item_added"') == 3
    assert '"type": "cart_complete"' in body


@pytest.mark.asyncio
async def test_cart_fill_dry_run_defaults_false_but_is_respected_when_true():
    """dry_run must be a real, request-controlled parameter, not a dead
    hardcoded literal — this is what makes it safely testable at all."""
    mock_result = OrderResult(success=True, platform="swiggy_instamart", items=["Paneer"])
    mock_agent = AsyncMock(return_value=mock_result)

    client = _client()
    with patch.object(app_module, "_token_valid", return_value=True), \
         patch("fridge_to_fork.swiggy_agent.run_swiggy_agent", mock_agent):
        client.post("/api/cart-fill", json={"items": [ITEMS[0]]})  # no dry_run key

    assert mock_agent.call_args.kwargs["dry_run"] is False  # default, but a real param


@pytest.mark.asyncio
async def test_cart_fill_requires_auth():
    client = _client()
    mock_agent = AsyncMock()
    with patch.object(app_module, "_token_valid", return_value=False), \
         patch("fridge_to_fork.swiggy_agent.run_swiggy_agent", mock_agent):
        response = client.post("/api/cart-fill", json={"items": ITEMS})

    assert '"type": "auth_required"' in response.text
    mock_agent.assert_not_called()


@pytest.mark.asyncio
async def test_cart_fill_agent_failure_reports_all_items_failed():
    mock_result = OrderResult(success=False, platform="swiggy_instamart", error="no products matched")
    mock_agent = AsyncMock(return_value=mock_result)

    client = _client()
    with patch.object(app_module, "_token_valid", return_value=True), \
         patch("fridge_to_fork.swiggy_agent.run_swiggy_agent", mock_agent):
        response = client.post("/api/cart-fill", json={"items": ITEMS, "dry_run": True})

    assert mock_agent.call_count == 1
    assert response.text.count('"type": "item_failed"') == 3
