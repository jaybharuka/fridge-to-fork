"""
"Report a problem" for Food (fridge_to_fork/food_support.py), mirroring Instamart's (tests/test_instamart_support.py)
against Swiggy's documented report_error: required tool + errorMessage, optional domain/flowDescription/toolContext/
userNotes, response data.mailto + data.summary{subject, body}. Run: python -m unittest tests.test_food_support
"""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

import app as a
from fridge_to_fork import features, food, food_support, instamart_support
from fridge_to_fork.swiggy_common import SwiggyError
from tests.test_food import using
from tests.test_instamart import FakeSession, envelope, signed_bearer

REPORT = {
    "mailto": "mailto:mcp-support@swiggy.example?subject=Food%20place_food_order%20failed&body=Details",
    "summary": {"subject": "Food place_food_order failed", "body": "Tool: place_food_order\nError: Payment method not available"},
}


class ReportProblemTests(unittest.IsolatedAsyncioTestCase):
    async def report(self, s, **over):
        args = {"tool": "place_food_order", "error_message": "Payment method not available", "flow": None, "context": {}, "notes": None, **over}
        with using(s):
            return await food_support.report_problem("tok", args["tool"], args["error_message"], args["flow"], args["context"], args["notes"])

    async def test_required_fields_only_uses_swiggys_argument_names_and_the_food_domain(self):
        s = FakeSession({"report_error": envelope(REPORT)})
        await self.report(s)
        self.assertEqual(s.args("report_error"), {"tool": "place_food_order", "errorMessage": "Payment method not available", "domain": "food"})

    async def test_flow_identifiers_and_notes_are_passed_as_documented(self):
        s = FakeSession({"report_error": envelope(REPORT)})
        ctx = {"orderId": "F-1", "restaurantId": "r1", "addressId": "addr-home", "menu_item_id": "m-1", "cartId": "cart-1", "paymentMethod": "UPI", "couponCode": "SAVE50", "query": "butter chicken"}
        await self.report(s, flow="reviewed cart -> chose UPI -> place order failed", context=ctx, notes="It charged me twice")
        self.assertEqual(s.args("report_error"), {
            "tool": "place_food_order", "errorMessage": "Payment method not available", "domain": "food",
            "flowDescription": "reviewed cart -> chose UPI -> place order failed", "toolContext": ctx, "userNotes": "It charged me twice",
        })

    async def test_the_prefilled_email_and_summary_are_returned(self):
        out = await self.report(FakeSession({"report_error": envelope(REPORT)}))
        self.assertEqual(out["report"], {"mailto": REPORT["mailto"], "subject": "Food place_food_order failed", "body": REPORT["summary"]["body"]})

    async def test_only_a_real_mailto_link_is_ever_returned(self):
        for bad in ("https://evil.example/x", "javascript:alert(1)", "", None):
            s = FakeSession({"report_error": envelope({"mailto": bad, "summary": REPORT["summary"]})})
            with self.subTest(bad):
                out = await self.report(s)
            self.assertIsNone(out["report"]["mailto"])
            self.assertTrue(out["report"]["body"])

    async def test_a_response_with_nothing_to_send_is_an_error(self):
        with self.assertRaises(SwiggyError):
            await self.report(FakeSession({"report_error": envelope({})}))

    async def test_tool_not_rolled_out_surfaces_as_an_error_the_ui_can_fall_back_from(self):
        for failing in (McpError(ErrorData(code=-32601, message="Method not found")), envelope(success=False, error="unknown tool report_error")):
            with self.subTest(type(failing).__name__), self.assertRaises(SwiggyError) as ctx:
                await self.report(FakeSession({"report_error": failing}))
            self.assertEqual(ctx.exception.code, "tool_error")

    async def test_auth_expiry_propagates(self):
        with self.assertRaises(SwiggyError) as ctx:
            await self.report(FakeSession({"report_error": envelope(success=False, error="TOKEN_EXPIRED")}))
        self.assertEqual(ctx.exception.code, "auth_required")


class SharedWithInstamartTests(unittest.TestCase):
    def test_both_products_use_the_same_report_builder_and_only_differ_in_domain_and_identifiers(self):
        self.assertEqual(instamart_support.CONTEXT_KEYS, ("orderId", "addressId", "spinId", "couponCode", "query", "cartId", "paymentMethod"))
        self.assertEqual(food_support.CONTEXT_KEYS, ("orderId", "restaurantId", "addressId", "menu_item_id", "couponCode", "query", "cartId", "paymentMethod"))
        # nothing personal is an allowed identifier for either product
        for keys in (instamart_support.CONTEXT_KEYS, food_support.CONTEXT_KEYS):
            self.assertFalse({"userName", "userPhone", "phone", "name", "address", "addressLine", "email", "lat", "lng"} & set(keys))


class FailingToolIsRememberedTests(unittest.IsolatedAsyncioTestCase):
    def test_the_route_envelope_names_the_tool_so_the_app_can_report_it(self):
        client = TestClient(a.app)
        boom = SwiggyError("tool_error", "Restaurant is closed", tool="update_food_cart")
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food, "build_cart", AsyncMock(side_effect=boom)):
            r = client.post("/api/food/cart", json={"address_id": "a", "selection": {"restaurant_id": "r", "menu_item_id": "m", "quantity": 1}}, headers=signed_bearer())
        self.assertEqual(r.json()["error"], {"code": "tool_error", "message": "Restaurant is closed", "tool": "update_food_cart"})


class ReportRouteTests(unittest.TestCase):
    BODY = {"tool": "place_food_order", "error_message": "Payment method not available", "flow": "place order failed", "context": {"orderId": "F-1"}, "notes": "help"}

    def setUp(self):
        self.client = TestClient(a.app)
        # The routes are shipped switched off (tests/test_food_disabled.py pins that); these tests are about the report itself.
        flag = patch.object(features, "FOOD_ORDERING_ENABLED", True)
        flag.start()
        self.addCleanup(flag.stop)

    def test_requires_auth(self):
        r = self.client.post("/api/food/report", json=self.BODY)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "auth_required"))

    def test_passes_the_report_through(self):
        out = {"report": {"mailto": REPORT["mailto"], "subject": "s", "body": "b"}}
        with patch.object(food_support, "report_problem", AsyncMock(return_value=out)) as fn:
            r = self.client.post("/api/food/report", json=self.BODY, headers=signed_bearer())
        self.assertEqual(r.json(), {"ok": True, **out})
        self.assertEqual(fn.await_args.args, ("swiggy-tok", "place_food_order", "Payment method not available", "place order failed", {"orderId": "F-1"}, "help"))

    def test_every_food_tool_the_app_calls_can_be_reported(self):
        tools = ["get_addresses", "search_restaurants", "search_menu", "update_food_cart", "get_food_cart", "flush_food_cart", "fetch_food_coupons",
                 "apply_food_coupon", "get_payment_options", "place_food_order", "check_payment_status", "confirm_order", "get_food_orders",
                 "get_food_delivery_status", "get_food_order_details", "track_food_order"]
        out = {"report": {"mailto": None, "subject": None, "body": "b"}}
        with patch.object(food_support, "report_problem", AsyncMock(return_value=out)):
            for tool in tools:
                r = self.client.post("/api/food/report", json={"tool": tool, "error_message": "boom"}, headers=signed_bearer())
                self.assertTrue(r.json()["ok"], tool)

    def test_validation_keeps_free_form_data_out(self):
        h = signed_bearer()
        bad = {
            "unknown tool": {**self.BODY, "tool": "drop_tables"},
            "the report tool itself": {**self.BODY, "tool": "report_error"},
            "an Instamart tool": {**self.BODY, "tool": "checkout"},
            "empty message": {**self.BODY, "error_message": "  "},
            "message too long": {**self.BODY, "error_message": "x" * 501},
            "notes too long": {**self.BODY, "notes": "x" * 1001},
            "flow too long": {**self.BODY, "flow": "x" * 301},
            "unknown context key (a phone number)": {**self.BODY, "context": {"userPhone": "9876543210"}},
            "unknown context key (an address)": {**self.BODY, "context": {"address": "12 MG Road"}},
            "another server's key": {**self.BODY, "context": {"spinId": "s"}},
            "context value too long": {**self.BODY, "context": {"orderId": "x" * 101}},
        }
        with patch.object(food_support, "report_problem", AsyncMock()) as fn:
            for label, body in bad.items():
                self.assertEqual(self.client.post("/api/food/report", json=body, headers=h).status_code, 422, label)
        fn.assert_not_awaited()

    def test_every_documented_identifier_this_app_has_is_accepted(self):
        ctx = {k: "id-1" for k in food_support.CONTEXT_KEYS}
        out = {"report": {"mailto": None, "subject": None, "body": "b"}}
        with patch.object(food_support, "report_problem", AsyncMock(return_value=out)) as fn:
            r = self.client.post("/api/food/report", json={**self.BODY, "context": ctx}, headers=signed_bearer())
        self.assertTrue(r.json()["ok"])
        self.assertEqual(fn.await_args.args[4], ctx)

    def test_minimal_report_is_valid(self):
        out = {"report": {"mailto": None, "subject": None, "body": "b"}}
        with patch.object(food_support, "report_problem", AsyncMock(return_value=out)) as fn:
            r = self.client.post("/api/food/report", json={"tool": "get_food_orders", "error_message": "boom"}, headers=signed_bearer())
        self.assertTrue(r.json()["ok"])
        self.assertEqual(fn.await_args.args, ("swiggy-tok", "get_food_orders", "boom", None, {}, None))


if __name__ == "__main__":
    unittest.main()
