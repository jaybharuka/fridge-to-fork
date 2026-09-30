"""
Self-check for the deterministic Instamart flow (swiggy_agent.py).
No real MCP connection — stdlib unittest with a fake ClientSession so this
runs without pytest/pytest-asyncio installed: `python -m unittest
tests.test_swiggy_agent_instamart`.
"""

import unittest

from fridge_to_fork.swiggy_agent import (
    _finalize_checkout,
    _resolve_products,
    order_from_instamart_mcp,
)


class FakeResult:
    def __init__(self, data, is_error=False):
        self.structuredContent = data
        self.content = []
        self.isError = is_error


class FakeSession:
    """Replays canned responses for call_tool(name, args) by tool name."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls = []

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        queue = self.responses.get(name, [])
        data = queue.pop(0) if queue else {}
        return FakeResult(data)


class ResolveProductsTests(unittest.IsolatedAsyncioTestCase):
    async def test_top_match_wins_and_misses_recorded(self):
        session = FakeSession({
            "search_products": [
                {"products": [{"id": "p1", "name": "Onion 1kg"}]},
                {"products": []},
            ]
        })
        resolved, not_found = await _resolve_products(session, ["onion", "unobtanium"], "addr1")
        self.assertEqual(resolved, [{"product_id": "p1", "name": "Onion 1kg"}])
        self.assertEqual(not_found, ["unobtanium"])


class FinalizeCheckoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_success_skips_polling(self):
        session = FakeSession({})
        order = await _finalize_checkout(session, {"status": "CONFIRMED", "order_id": "o1"})
        self.assertEqual(order["status"], "CONFIRMED")
        self.assertEqual(session.calls, [])

    async def test_pending_payment_polls_then_confirms(self):
        session = FakeSession({
            "check_payment_status": [{"status": "SUCCESS"}],
            "confirm_order": [{"status": "CONFIRMED", "order_id": "o1"}],
        })
        import fridge_to_fork.swiggy_agent as sa
        sa.PAYMENT_POLL_INTERVAL_SECONDS = 0
        order = await _finalize_checkout(session, {"status": "PENDING_PAYMENT", "order_id": "o1"})
        self.assertEqual(order["status"], "CONFIRMED")


class DryRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_no_network(self):
        result = await order_from_instamart_mcp(["milk"], access_token=None, dry_run=True)
        self.assertTrue(result.success)
        self.assertEqual(result.items, ["milk"])

    async def test_no_token_returns_auth_required(self):
        result = await order_from_instamart_mcp(["milk"], access_token=None)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "auth_required")

    async def test_empty_missing_ingredients_is_noop_success(self):
        result = await order_from_instamart_mcp([], access_token="tok")
        self.assertTrue(result.success)
        self.assertEqual(result.items, [])


if __name__ == "__main__":
    unittest.main()
