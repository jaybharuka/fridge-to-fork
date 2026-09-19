"""
Payment-option diagnostics (instamart._log_payment_view): what Swiggy's get_payment_options listed BEFORE our
filtering, why each method was offered or dropped, and the cart's value beside it. Behaviour must not change.
Run: python -m unittest tests.test_instamart_payment_diag
"""

import unittest

from fridge_to_fork import instamart
from tests.test_instamart import (
    ADDRESSES, GPAY, PAYMENT_VIEW, PHONEPE, QR, FakeSession, cart, checkout_session, discounted_cart, envelope, place, using,
)

SELECTION = [{"spin_id": "spin-t500", "sku_id": "sku-t500", "quantity": 2}]


def session(**over) -> FakeSession:
    return FakeSession({"clear_cart": envelope({"verified": True}), "update_cart": envelope(cart()), "get_cart": envelope(cart()), **over})


class PaymentDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        instamart._attempts.clear()
        instamart._inflight.clear()

    async def build(self, s):
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            out = await instamart.build_cart("tok", "addr-home", SELECTION)
        return out, "\n".join(r for r in logs.output if "payment options" in r)

    async def test_the_raw_view_and_the_offered_keys_are_logged_with_a_reason_per_method(self):
        _, text = await self.build(session())
        self.assertIn("payment options (cart): source=get_payment_options", text)
        self.assertIn("cod={'available': True, 'id': 'Cash', 'displayName': 'Cash on delivery'}", text)
        self.assertIn("offered=['cod', 'upi_intent:gpay://upi/', 'upi_qr']", text)
        self.assertIn("'gpay://upi/' kind='intent' enabled=True", text)
        self.assertIn("-> offered", text)
        self.assertIn("'phonepe://upi/' kind='intent' enabled=False", text)
        self.assertIn("dropped: enabled=false", text)
        self.assertIn("platform_methods={'mobile': 2, 'desktop': 1}", text)
        self.assertIn("paymentAmount='₹136'", text)

    async def test_a_method_without_a_kind_is_logged_as_dropped_and_why(self):
        # Swiggy's types declare `kind` optional, but the filter only offers "qr"/"intent": this is the suspect
        # if the real response lists UPI methods that never reach the screen.
        no_kind = {**PAYMENT_VIEW, "allMethods": [{"id": "gpay://upi/", "displayName": "Google Pay", "enabled": True}], "platforms": None}
        out, text = await self.build(session(get_payment_options=envelope(no_kind)))
        self.assertIn("'gpay://upi/' kind=None enabled=True", text)
        self.assertIn("dropped: kind=None is not qr/intent", text)
        self.assertEqual([o["key"] for o in out["review"]["payment"]["options"]], ["cod"])  # behaviour unchanged: still cash only

    async def test_cod_only_is_visible_as_cod_only(self):
        cod_only = {"cod": {"available": True, "id": "Cash", "displayName": "Cash"}, "allMethods": [], "paymentAmount": "₹136"}
        out, text = await self.build(session(get_payment_options=envelope(cod_only)))
        self.assertIn("allMethods=0", text)
        self.assertIn("methods=[]", text)
        self.assertIn("offered=['cod']", text)

    async def test_the_carts_value_is_logged_beside_the_options(self):
        _, text = await self.build(session())
        self.assertIn("itemTotal='₹120'", text)
        self.assertIn("toPay='₹136'", text)
        self.assertIn("availablePaymentMethods=['Cash', 'UPI']", text)

    async def test_a_failed_tool_call_and_the_cart_fallback_are_visible(self):
        s = session(get_payment_options=envelope(success=False, error="not available"), get_cart=envelope(cart(paymentOptions=PAYMENT_VIEW)))
        out, text = await self.build(s)
        self.assertIn("source=cart.paymentOptions (fallback)", text)
        self.assertIn("tool_error='not available'", text)
        self.assertEqual(out["review"]["payment"]["options"][0]["key"], "cod")

    async def test_every_stage_logs_under_its_own_tag(self):
        from tests.test_instamart import COUPONS

        s = FakeSession({"get_cart": [envelope(cart()), envelope(discounted_cart())], "apply_coupon": envelope(discounted_cart()), "list_coupons": envelope(COUPONS)})
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            await instamart.apply_coupon("tok", "addr-home", "SAVE20")
        text = "\n".join(logs.output)
        self.assertIn("payment options (coupon-before)", text)
        self.assertIn("payment options (coupon-after)", text)

        with using(checkout_session()), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            await place()
        self.assertIn("payment options (checkout)", "\n".join(logs.output))

    async def test_nothing_personal_reaches_the_log(self):
        _, text = await self.build(session())
        for private in ("9876543210", "9000000001", "12 MG Road", "Indiranagar", "Bengaluru", "Tower B"):
            self.assertNotIn(private, text)

    async def test_the_filter_itself_is_unchanged(self):
        cases = {
            "cash + intent + qr": (PAYMENT_VIEW, ["cod", "upi_intent:gpay://upi/", "upi_qr"]),
            "disabled dropped": ({"allMethods": [PHONEPE]}, []),
            "second qr dropped": ({"allMethods": [QR, {**QR, "id": "qr2"}]}, ["upi_qr"]),
            "unknown kind dropped": ({"allMethods": [{"id": "x", "kind": "wallet"}]}, []),
            "no id dropped": ({"allMethods": [{"kind": "qr"}]}, []),
            "cod unavailable": ({"cod": {"available": False, "id": "Cash"}}, []),
        }
        for label, (view, expected) in cases.items():
            self.assertEqual([o["key"] for o in instamart._payment_options(view)], expected, label)


if __name__ == "__main__":
    unittest.main()
