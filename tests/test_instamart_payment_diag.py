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


REAL_VIEW = {
    "cod": {"available": True, "id": "COD", "displayName": "Cash on delivery"},
    "allMethods": [
        {"id": "gpay://upi/", "groupName": "UPI", "enabled": True},
        {"id": "phonepe://", "groupName": "UPI", "enabled": True},
        {"id": "paytmmp://", "groupName": "UPI", "enabled": True},
        {"id": "PayWithQR", "groupName": "UPI", "enabled": True},
        {"id": "COD", "groupName": "COD", "enabled": True},
        {"id": "SwiggyPay", "groupName": "SWIGGYPAY", "enabled": True},
    ],
    "paymentAmount": "₹136",
}


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

    async def test_a_method_with_neither_kind_nor_a_upi_group_is_logged_as_dropped_and_why(self):
        no_kind = {**PAYMENT_VIEW, "allMethods": [{"id": "gpay://upi/", "displayName": "Google Pay", "enabled": True}], "platforms": None}
        out, text = await self.build(session(get_payment_options=envelope(no_kind)))
        self.assertIn("'gpay://upi/' kind=None enabled=True group=None as=None", text)
        self.assertIn("dropped: not a UPI qr/app method (group=None)", text)
        self.assertEqual([o["key"] for o in out["review"]["payment"]["options"]], ["cod"])

    async def test_the_real_production_response_now_offers_the_upi_apps(self):
        # Exactly what production returned: every method kind=None, only groupName populated.
        view = {**REAL_VIEW}
        out, text = await self.build(session(get_payment_options=envelope(view)))
        keys = [o["key"] for o in out["review"]["payment"]["options"]]
        self.assertEqual(keys, ["cod", "upi_intent:gpay://upi/", "upi_intent:phonepe://", "upi_intent:paytmmp://", "upi_qr"])  # Swiggy's order
        self.assertIn("'gpay://upi/' kind=None enabled=True group='UPI' as='intent' -> offered", text)
        self.assertIn("'PayWithQR' kind=None enabled=True group='UPI' as='qr' -> offered", text)
        self.assertIn("'SwiggyPay' kind=None enabled=True group='SWIGGYPAY' as=None -> dropped", text)

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

    def test_classifying_without_a_kind(self):
        def keys(*methods):
            return [o["key"] for o in instamart._payment_options({"allMethods": list(methods)})]

        def m(id, group="UPI", **kw):
            return {"id": id, "groupName": group, "enabled": True, **kw}

        cases = {
            "group casing/whitespace is ignored": (keys(m("gpay://upi/", group=" upi ")), ["upi_intent:gpay://upi/"]),
            "every real URI scheme is an app": (
                keys(*(m(s) for s in ("gpay://upi/", "phonepe://", "paytmmp://", "bhim://upi/", "credpay://upi/", "super://", "fpupi://"))),
                [f"upi_intent:{s}" for s in ("gpay://upi/", "phonepe://", "paytmmp://", "bhim://upi/", "credpay://upi/", "super://", "fpupi://")],
            ),
            "PayWithQR is the qr, only one kept": (keys(m("PayWithQR"), m("PayWithQR2")), ["upi_qr"]),
            "valid kind wins over the group": (keys(m("x", group="SWIGGYPAY", kind="intent")), ["upi_intent:x"]),
            "valid kind wins over the id": (keys(m("gpay://upi/", kind="qr")), ["upi_qr"]),
            "true negative: unrecognised group": (keys(m("gpay://upi/", group="WALLET")), []),
            "true negative: swiggypay is not offered": (keys(m("SwiggyPay", group="SWIGGYPAY")), []),
            "true negative: cod group is served by the cod object": (keys(m("COD", group="COD")), []),
            "true negative: disabled upi app": (keys(m("gpay://upi/", enabled=False)), []),
            "true negative: upi group but unrecognisable id": (keys(m("SomethingElse")), []),
            "true negative: no id": (keys({"groupName": "UPI", "enabled": True}), []),
            "true negative: no group at all": (keys({"id": "gpay://upi/", "enabled": True}), []),
        }
        for label, (got, expected) in cases.items():
            self.assertEqual(got, expected, label)

    def test_labels_fall_back_to_the_app_name(self):
        opts = instamart._payment_options({"allMethods": [
            {"id": "gpay://upi/", "groupName": "UPI"}, {"id": "newapp://x", "groupName": "UPI"}, {"id": "phonepe://", "groupName": "UPI", "displayName": "PhonePe UPI"},
        ]})
        self.assertEqual([o["label"] for o in opts], ["Google Pay", "UPI app (newapp)", "PhonePe UPI"])

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
