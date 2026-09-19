"""
The cart/address re-verification (instamart._verify_cart_address): it must catch a real address change,
must not fire on a mere id type difference, and must leave enough in the logs to diagnose a real-account
failure without leaking address text, names or phone numbers.
Run: python -m unittest tests.test_instamart_address_check
"""

import json
import unittest

from fridge_to_fork import instamart
from fridge_to_fork.instamart import InstamartError
from tests.test_instamart import ADDRESSES, FakeSession, cart, checkout_session, envelope, place, using

SELECTION = [{"spin_id": "spin-t500", "sku_id": "sku-t500", "quantity": 2}]


def build_session(cart_data: dict, **over) -> FakeSession:
    return FakeSession({
        "clear_cart": envelope({"verified": True}), "update_cart": envelope(cart_data), "get_cart": envelope(cart_data),
        "get_addresses": envelope(ADDRESSES), **over,
    })


class IdComparisonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        instamart._attempts.clear()  # checkout replays a stored result per idempotency key
        instamart._inflight.clear()

    async def test_a_numeric_cart_id_for_the_same_address_is_not_a_change(self):
        s = build_session(cart(address_id=123))
        with using(s):
            out = await instamart.build_cart("tok", "123", SELECTION)  # get_addresses said "123", get_cart says 123
        self.assertTrue(out["review"]["canCheckout"])
        self.assertNotIn("get_addresses", s.names())  # no diagnostics when nothing is wrong

    async def test_surrounding_whitespace_is_not_a_change(self):
        with using(build_session(cart(address_id=" addr-home "))):
            await instamart.build_cart("tok", "addr-home", SELECTION)

    async def test_a_genuinely_different_address_is_still_refused(self):
        with using(build_session(cart(address_id="addr-work"))), self.assertRaises(InstamartError) as ctx:
            await instamart.build_cart("tok", "addr-home", SELECTION)
        self.assertEqual(ctx.exception.code, "address_mismatch")

    async def test_cart_build_still_tolerates_a_cart_that_reports_no_address_id(self):
        with using(build_session(cart(address_id=None))):
            out = await instamart.build_cart("tok", "addr-home", SELECTION)
        self.assertIsNone(out["review"]["address"]["id"])

    async def test_checkout_does_not_tolerate_an_unverifiable_address(self):
        s = checkout_session(get_cart=envelope(cart(address_id=None)))
        with using(s), self.assertRaises(InstamartError) as ctx:
            await place()
        self.assertEqual(ctx.exception.code, "address_mismatch")
        self.assertNotIn("checkout", s.names())

    async def test_checkout_accepts_the_same_address_under_a_different_type(self):
        s = checkout_session(get_cart=envelope(cart(address_id=" addr-home")))
        with using(s):
            out = await place()
        self.assertEqual(out["status"], "placed")


class MismatchDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def mismatch(self, cart_data, **over) -> str:
        s = build_session(cart_data, **over)
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs, self.assertRaises(InstamartError):
            await instamart.build_cart("tok", "addr-home", SELECTION)
        return "\n".join(logs.output)

    async def test_the_log_names_both_ids_and_whether_each_is_a_saved_address(self):
        text = await self.mismatch(cart(address_id="addr-work"))
        self.assertIn("address mismatch at cart", text)
        self.assertIn("requested='addr-home'", text)
        self.assertIn("cart='addr-work'", text)
        self.assertIn("requested_is_saved=True", text)
        self.assertIn("cart_id_is_saved=True", text)  # Swiggy's cart is on a *different saved address*: a real change

    async def test_a_cart_id_that_is_not_a_saved_address_at_all_is_visible_in_the_log(self):
        text = await self.mismatch(cart(address_id="9f3a-unknown-format"))
        self.assertIn("cart_id_is_saved=False", text)  # suggests an id-format difference, not a different address

    async def test_same_address_under_another_id_format_is_told_apart_from_a_real_change(self):
        same_place = cart(address_id="9f3a-other-format", selectedAddressDetails={"id": "9f3a-other-format", "address": "12 MG Road, Bengaluru", "area": "", "name": "Home", "mobile": "x"})
        text = await self.mismatch(same_place)
        self.assertIn("cart_id_is_saved=False", text)
        self.assertIn("cart_text_matches_requested=True", text)  # -> id-format difference, a false positive

    async def test_a_cart_on_a_different_place_says_so(self):
        text = await self.mismatch(cart(address_id="addr-work", selectedAddressDetails={"id": "addr-work", "address": "Tower B, Whitefield", "area": "", "name": "Work", "mobile": "x"}))
        self.assertIn("cart_id_is_saved=True", text)
        self.assertIn("cart_text_matches_requested=False", text)  # -> Swiggy's cart really is on another address

    async def test_the_type_of_each_id_is_logged(self):
        text = await self.mismatch(cart(address_id=456))
        self.assertIn("cart=456 (int)", text)
        self.assertIn("(str)", text)

    async def test_no_address_text_name_or_phone_reaches_the_log(self):
        text = await self.mismatch(cart(address_id="addr-work"))
        for private in ("12 MG Road", "Bengaluru", "Tower B", "Whitefield", "9876543210", "9000000001", "Indiranagar"):
            self.assertNotIn(private, text)

    async def test_a_failing_diagnostic_lookup_never_masks_the_refusal(self):
        s = build_session(cart(address_id="addr-work"), get_addresses=envelope(success=False, error="down"))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs, self.assertRaises(InstamartError) as ctx:
            await instamart.build_cart("tok", "addr-home", SELECTION)
        self.assertEqual(ctx.exception.code, "address_mismatch")
        self.assertIn("cart_id_is_saved=None", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
