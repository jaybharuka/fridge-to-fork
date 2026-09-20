"""
The four layers around Food ordering after the deterministic flow replaced the Gemini agent
(fridge_to_fork/features.py):

  1. frontend card    - disabled while FOOD_ORDERING_ENABLED is False (mirrored in frontend/lib/features.ts)
  2. frontend hook    - useScanStream.placeOrder never sends order_dish (checked in the browser run)
  3. backend routes   - /api/food/* refuse (before auth) while FOOD_ORDERING_ENABLED is False: the kill switch
  4. agent            - deleted: swiggy_agent only simulates (--dry-run) or refuses, and POST /api/order order_dish
                        only tells a stale page to reload

Run: python -m unittest tests.test_food_disabled
"""

import ast
import inspect
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork import features, food, instamart, swiggy_agent, step3_order_router
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


class SwitchTests(unittest.TestCase):
    def test_the_flow_is_switched_off_and_the_old_agent_switch_no_longer_exists(self):
        # Pinned on purpose: switching the flow on or off is a deliberate step (a real order), so it must be a visible
        # change to this test, never something that rides along with another deploy. It is OFF until it is established
        # that place_food_order places a real, charged order against the connected account.
        self.assertFalse(features.FOOD_ORDERING_ENABLED)
        self.assertFalse(hasattr(features, "FOOD_AGENT_ENABLED"))

    def test_the_kill_switch_refuses_every_food_route_before_auth_and_before_touching_swiggy(self):
        calls = {
            "search": {"dish": "x"},
            "cart": {"address_id": "a", "selection": {"restaurant_id": "r", "menu_item_id": "m", "quantity": 1}},
            "coupon": {"address_id": "a", "coupon_code": "X"},
            "checkout": {"address_id": "a", "expected_total": 10, "payment_key": "cod", "idempotency_key": "idem-key-0001"},
            "payment-status": {"order_id": "o", "paas_id": "p", "address_id": "a"},
            "orders": {},
            "order-status": {"order_id": "o"},
            "order-details": {"order_id": "o"},
            "report": {"tool": "place_food_order", "error_message": "boom"},
        }
        with patch.object(features, "FOOD_ORDERING_ENABLED", False), patch.object(food, "_session", side_effect=AssertionError("Swiggy must not be contacted")):
            for path, body in calls.items():
                for label, headers in (("no session", {}), ("valid session", bearer())):
                    r = client.post(f"/api/food/{path}", json=body, headers=headers)
                    self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "food_disabled"), (path, label))
        self.assertIn("Order the ingredients instead", features.FOOD_UNAVAILABLE_MESSAGE)


class OrderRouteTests(unittest.TestCase):
    def test_order_dish_no_longer_orders_anything_it_tells_a_stale_page_to_reload(self):
        for label, headers in (("with a valid session", bearer()), ("with no session at all", None)):
            r = order_dish(headers)
            self.assertIn(features.FOOD_MOVED_MESSAGE, r.text, label)
            self.assertIn('"type": "error"', r.text, label)
            self.assertNotIn("Routing your order", r.text, label)  # the progress event that used to precede a real order
            self.assertNotIn("auth_required", r.text, label)
            self.assertNotIn('"placed"', r.text, label)

    def test_the_route_cannot_reach_an_agent_because_none_is_imported(self):
        self.assertFalse(hasattr(a, "order_dish_from_swiggy"))
        self.assertFalse(hasattr(step3_order_router, "order_dish_from_swiggy"))

    def test_cook_still_works(self):
        r = client.post("/api/order", data={"action": "cook", "meal_name": "Butter Chicken"})
        self.assertIn("cook_confirmed", r.text)

    def test_unknown_actions_are_still_rejected_as_before(self):
        r = client.post("/api/order", data={"action": "order_groceries", "meal_name": "T"}, headers=bearer())
        self.assertIn("Unknown action: order_groceries", r.text)


class AgentDeletedTests(unittest.IsolatedAsyncioTestCase):
    def test_the_llm_agent_code_is_gone(self):
        tree = ast.parse(inspect.getsource(swiggy_agent))
        imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertFalse([m for m in imported if m.startswith(("google", "mcp", "httpx"))], imported)  # no LLM, no MCP, no network client
        for attr in ("Agent", "MCPToolset", "Runner", "FOOD_MCP_URL", "DINEOUT_MCP_URL"):
            self.assertFalse(hasattr(swiggy_agent, attr), attr)

    async def test_a_real_dish_order_is_refused_and_points_at_the_staged_flow(self):
        result = await swiggy_agent.run_swiggy_agent(plan(Decision.ORDER_DISH), "addr", "tok")
        self.assertFalse(result.success)
        self.assertIsNone(result.order_id)
        self.assertIn("fridge_to_fork.food", result.error)

    async def test_it_never_contacts_swiggy(self):
        with patch.object(food, "_session", side_effect=AssertionError("no Swiggy")), patch.object(instamart, "_session", side_effect=AssertionError("no Swiggy")):
            for decision in (Decision.ORDER_DISH, Decision.ORDER_GROCERIES):
                result = await swiggy_agent.run_swiggy_agent(plan(decision), "addr", "tok")
                self.assertFalse(result.success)

    async def test_dry_run_simulation_is_untouched(self):
        result = await swiggy_agent.run_swiggy_agent(plan(Decision.ORDER_DISH), "addr", None, dry_run=True)
        self.assertTrue(result.success)
        self.assertEqual((result.platform, result.items), ("swiggy_food", ["Butter Chicken"]))
        result = await swiggy_agent.run_swiggy_agent(plan(Decision.ORDER_GROCERIES), "addr", None, dry_run=True)
        self.assertEqual((result.platform, result.items), ("swiggy_instamart", ["tomato"]))

    async def test_cook_needs_no_order(self):
        self.assertIsNone(await swiggy_agent.run_swiggy_agent(plan(Decision.COOK), "addr", "tok"))


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

    def test_the_kill_switch_does_not_touch_instamart(self):
        out = {"address": {"id": "a", "label": "Home", "addressLine": "x", "category": None}, "results": []}
        with patch.object(features, "FOOD_ORDERING_ENABLED", False), patch.object(instamart, "search_ingredients", AsyncMock(return_value=out)):
            r = client.post("/api/instamart/search", json={"items": ["tomato"]}, headers=bearer())
        self.assertTrue(r.json()["ok"])


if __name__ == "__main__":
    unittest.main()
