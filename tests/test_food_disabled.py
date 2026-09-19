"""
The Swiggy Food "order the finished dish" path is switched off (fridge_to_fork/features.py): the route
refuses before auth or the agent, and the agent refuses if anything else calls it. The Instamart flow and
the harmless "cook" action must be unaffected. Run: python -m unittest tests.test_food_disabled
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork import features, instamart, swiggy_agent
from fridge_to_fork.models import Decision, MealPlan, MealSuggestion

client = TestClient(a.app)


def bearer() -> dict:
    exp = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    return {"Authorization": f"Bearer {a._issue_bearer('swiggy-tok', exp)}"}


def order_dish(headers=None):
    return client.post("/api/order", data={"action": "order_dish", "meal_name": "Butter Chicken"}, headers=headers or {})


def plan(decision: Decision) -> MealPlan:
    meal = MealSuggestion(name="Butter Chicken", description="", can_cook_now=False, missing_ingredients=["tomato"])
    return MealPlan(suggestions=[meal], decision=decision, recommended_meal=meal, reasoning="")


class RouteRefusalTests(unittest.TestCase):
    def test_the_switch_is_off(self):
        self.assertFalse(features.FOOD_ORDERING_ENABLED)

    def test_order_dish_is_refused_with_a_clear_message_and_never_reaches_the_agent(self):
        for label, headers in (("with a valid session", bearer()), ("with no session at all", None)):
            with self.subTest(label), patch.object(a, "order_dish_from_swiggy", AsyncMock()) as agent:
                r = order_dish(headers)
            self.assertIn(features.FOOD_UNAVAILABLE_MESSAGE, r.text)
            self.assertIn('"type": "error"', r.text)
            self.assertNotIn("Routing your order", r.text)  # the progress event that precedes a real order
            self.assertNotIn("auth_required", r.text)  # refused before auth: no misleading "connect Swiggy"
            agent.assert_not_awaited()

    def test_the_refusal_names_the_alternative(self):
        self.assertIn("Order the ingredients instead", features.FOOD_UNAVAILABLE_MESSAGE)

    def test_cook_still_works(self):
        r = client.post("/api/order", data={"action": "cook", "meal_name": "Butter Chicken"})
        self.assertIn("cook_confirmed", r.text)

    def test_unknown_actions_are_still_rejected_as_before(self):
        r = client.post("/api/order", data={"action": "order_groceries", "meal_name": "T"}, headers=bearer())
        self.assertIn("Unknown action: order_groceries", r.text)


class AgentRefusalTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_agent_refuses_a_real_dish_order_without_building_anything(self):
        with patch.object(swiggy_agent, "Agent", side_effect=AssertionError("agent must not be built")), \
             patch.object(swiggy_agent, "MCPToolset", side_effect=AssertionError("no MCP connections")):
            result = await swiggy_agent.run_swiggy_agent(plan(Decision.ORDER_DISH), "addr", "tok")
        self.assertFalse(result.success)
        self.assertIsNone(result.order_id)
        self.assertIn("temporarily unavailable", result.error)

    async def test_dry_run_simulation_is_untouched(self):
        result = await swiggy_agent.run_swiggy_agent(plan(Decision.ORDER_DISH), "addr", None, dry_run=True)
        self.assertTrue(result.success)


class InstamartUnaffectedTests(unittest.TestCase):
    def test_instamart_routes_are_still_served_and_guarded(self):
        r = client.post("/api/instamart/search", json={"items": ["tomato"]})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "auth_required"))

    def test_instamart_search_still_runs_for_a_connected_user(self):
        out = {"address": {"id": "a", "label": "Home", "addressLine": "x", "category": None}, "results": []}
        with patch.object(instamart, "search_ingredients", AsyncMock(return_value=out)) as fn:
            r = client.post("/api/instamart/search", json={"items": ["tomato"]}, headers=bearer())
        self.assertTrue(r.json()["ok"])
        fn.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
