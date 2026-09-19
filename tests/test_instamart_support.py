"""
"Report a problem" (fridge_to_fork/instamart_support.py) against Swiggy's documented report_error:
required tool + errorMessage, optional domain/flowDescription/toolContext/userNotes, response
data.mailto + data.summary{subject, body}. Run: python -m unittest tests.test_instamart_support
"""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

import app as a
from fridge_to_fork import instamart, instamart_support
from fridge_to_fork.instamart import InstamartError
from tests.test_instamart import FakeSession, envelope, signed_bearer, using

REPORT = {
    "mailto": "mailto:mcp-support@swiggy.example?subject=Instamart%20checkout%20failed&body=Details",
    "summary": {"subject": "Instamart checkout failed", "body": "Tool: checkout\nError: Payment method not available"},
}


class ReportProblemTests(unittest.IsolatedAsyncioTestCase):
    async def report(self, s, **over):
        args = {"tool": "checkout", "error_message": "Payment method not available", "flow": None, "context": {}, "notes": None, **over}
        with using(s):
            return await instamart_support.report_problem("tok", args["tool"], args["error_message"], args["flow"], args["context"], args["notes"])

    async def test_required_fields_only_uses_swiggys_argument_names_and_the_im_domain(self):
        s = FakeSession({"report_error": envelope(REPORT)})
        await self.report(s)
        self.assertEqual(s.args("report_error"), {"tool": "checkout", "errorMessage": "Payment method not available", "domain": "im"})

    async def test_flow_identifiers_and_notes_are_passed_as_documented(self):
        s = FakeSession({"report_error": envelope(REPORT)})
        await self.report(s, flow="reviewed cart -> chose cash -> checkout failed", context={"orderId": "IM-1", "addressId": "addr-home", "paymentMethod": "Cash"}, notes="It charged me twice")
        self.assertEqual(s.args("report_error"), {
            "tool": "checkout", "errorMessage": "Payment method not available", "domain": "im",
            "flowDescription": "reviewed cart -> chose cash -> checkout failed",
            "toolContext": {"orderId": "IM-1", "addressId": "addr-home", "paymentMethod": "Cash"},
            "userNotes": "It charged me twice",
        })

    async def test_the_prefilled_email_and_summary_are_returned(self):
        out = await self.report(FakeSession({"report_error": envelope(REPORT)}))
        self.assertEqual(out["report"], {"mailto": REPORT["mailto"], "subject": "Instamart checkout failed", "body": REPORT["summary"]["body"]})

    async def test_only_a_real_mailto_link_is_ever_returned(self):
        for bad in ("https://evil.example/x", "javascript:alert(1)", "", None):
            s = FakeSession({"report_error": envelope({"mailto": bad, "summary": REPORT["summary"]})})
            with self.subTest(bad):
                out = await self.report(s)
            self.assertIsNone(out["report"]["mailto"])
            self.assertTrue(out["report"]["body"])  # the summary text is still usable

    async def test_a_response_with_nothing_to_send_is_an_error(self):
        with self.assertRaises(InstamartError):
            await self.report(FakeSession({"report_error": envelope({})}))

    async def test_tool_not_rolled_out_surfaces_as_an_error_the_ui_can_fall_back_from(self):
        for failing in (McpError(ErrorData(code=-32601, message="Method not found")), envelope(success=False, error="unknown tool report_error")):
            with self.subTest(type(failing).__name__), self.assertRaises(InstamartError) as ctx:
                await self.report(FakeSession({"report_error": failing}))
            self.assertEqual(ctx.exception.code, "tool_error")

    async def test_auth_expiry_propagates(self):
        with self.assertRaises(InstamartError) as ctx:
            await self.report(FakeSession({"report_error": envelope(success=False, error="TOKEN_EXPIRED")}))
        self.assertEqual(ctx.exception.code, "auth_required")


class FailingToolIsRememberedTests(unittest.IsolatedAsyncioTestCase):
    async def test_errors_carry_the_swiggy_tool_that_refused(self):
        for failing in (envelope(success=False, error="Cart is empty"), McpError(ErrorData(code=-32601, message="nope"))):
            with self.subTest(type(failing).__name__), self.assertRaises(InstamartError) as ctx:
                await instamart._call(FakeSession({"get_cart": failing}), "get_cart")
            self.assertEqual(ctx.exception.tool, "get_cart")

    def test_the_route_envelope_names_the_tool_so_the_app_can_report_it(self):
        client = TestClient(a.app)
        boom = InstamartError("tool_error", "Cart is empty", tool="get_cart")
        with patch.object(instamart, "search_ingredients", AsyncMock(side_effect=boom)):
            r = client.post("/api/instamart/search", json={"items": ["x"]}, headers=signed_bearer())
        self.assertEqual(r.json()["error"], {"code": "tool_error", "message": "Cart is empty", "tool": "get_cart"})
        with patch.object(instamart, "search_ingredients", AsyncMock(side_effect=InstamartError("cart_changed", "changed"))):
            r = client.post("/api/instamart/search", json={"items": ["x"]}, headers=signed_bearer())
        self.assertNotIn("tool", r.json()["error"])


class ReportRouteTests(unittest.TestCase):
    BODY = {"tool": "checkout", "error_message": "Payment method not available", "flow": "checkout failed", "context": {"orderId": "IM-1"}, "notes": "help"}

    def setUp(self):
        self.client = TestClient(a.app)

    def test_requires_auth(self):
        r = self.client.post("/api/instamart/report", json=self.BODY)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "auth_required"))

    def test_passes_the_report_through(self):
        out = {"report": {"mailto": REPORT["mailto"], "subject": "s", "body": "b"}}
        with patch.object(instamart_support, "report_problem", AsyncMock(return_value=out)) as fn:
            r = self.client.post("/api/instamart/report", json=self.BODY, headers=signed_bearer())
        self.assertEqual(r.json(), {"ok": True, **out})
        self.assertEqual(fn.await_args.args, ("swiggy-tok", "checkout", "Payment method not available", "checkout failed", {"orderId": "IM-1"}, "help"))

    def test_validation_keeps_free_form_data_out(self):
        h = signed_bearer()
        bad = {
            "unknown tool": {**self.BODY, "tool": "drop_tables"},
            "the report tool itself": {**self.BODY, "tool": "report_error"},
            "empty message": {**self.BODY, "error_message": "  "},
            "message too long": {**self.BODY, "error_message": "x" * 501},
            "notes too long": {**self.BODY, "notes": "x" * 1001},
            "unknown context key (e.g. a phone number)": {**self.BODY, "context": {"userPhone": "9876543210"}},
            "context value too long": {**self.BODY, "context": {"orderId": "x" * 101}},
        }
        for label, body in bad.items():
            self.assertEqual(self.client.post("/api/instamart/report", json=body, headers=h).status_code, 422, label)

    def test_minimal_report_is_valid(self):
        out = {"report": {"mailto": None, "subject": None, "body": "b"}}
        with patch.object(instamart_support, "report_problem", AsyncMock(return_value=out)) as fn:
            r = self.client.post("/api/instamart/report", json={"tool": "get_orders", "error_message": "boom"}, headers=signed_bearer())
        self.assertTrue(r.json()["ok"])
        self.assertEqual(fn.await_args.args, ("swiggy-tok", "get_orders", "boom", None, {}, None))


if __name__ == "__main__":
    unittest.main()
