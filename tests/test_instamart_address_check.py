"""
The cart/address re-verification (instamart._verify_cart_address): it must catch a real address change,
must not fire on a mere id type difference, and must leave enough in the logs to diagnose a real-account
failure without leaking address text, names or phone numbers.
Run: python -m unittest tests.test_instamart_address_check
"""

import json
import unittest

from fridge_to_fork import instamart, instamart_addresses
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


# --------------------------------------------------------------------------- the real Swiggy id quirk
# Confirmed from production logs: get_addresses returns "<base>__<token>", get_cart reports only "<base>".

FULL = "d60pf1o28cib6t3jveug__AMOOxgTFUakDAsJFL27MqT"
BASE = "d60pf1o28cib6t3jveug"


class CompoundIdRuleTests(unittest.TestCase):
    def test_the_cart_reporting_only_the_base_is_the_same_address(self):
        self.assertTrue(instamart._same_address_id(FULL, BASE))

    def test_identical_and_type_or_whitespace_variants_still_match(self):
        for a, b in ((FULL, FULL), ("addr-home", "addr-home"), (123, "123"), ("123", 123), (f" {FULL} ", BASE), (FULL, f" {BASE} ")):
            self.assertTrue(instamart._same_address_id(a, b), (a, b))

    def test_anything_that_is_not_exactly_the_part_before_the_first_separator_is_a_real_mismatch(self):
        cases = {
            "partial prefix, not at the boundary": (FULL, BASE[:-3]),
            "last character differs": (FULL, BASE[:-1] + "X"),
            "same base, different token (unknown semantics: refuse)": (FULL, BASE + "__SOMEOTHERTOKEN"),
            "reverse direction (requested is the short form)": (BASE, FULL),
            "prefix without the separator": ("abcdef", "abc"),
            "a different address's base": (FULL, "zzzzzzzzzzzzzzzzzzzz"),
            "beyond the first separator": ("a__b__c", "a__b"),
            "empty cart id": (FULL, ""),
            "missing cart id": (FULL, None),
            "missing requested id": (None, BASE),
            "leading separator, empty base": ("__token", ""),
        }
        for label, (full, other) in cases.items():
            self.assertFalse(instamart._same_address_id(full, other), label)

    def test_only_the_first_separator_defines_the_base(self):
        self.assertTrue(instamart._same_address_id("a__b__c", "a"))


class CompoundIdFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        instamart._attempts.clear()
        instamart._inflight.clear()

    def saved(self):
        return envelope({"addresses": [{"id": FULL, "addressLine": "12 MG Road, Bengaluru", "phoneNumber": "9876543210", "addressTag": "Home"}],
                         "pagination": {"page": 1, "pageSize": 10, "total": 1, "totalPages": 1, "hasMore": False}})

    async def test_cart_review_passes_with_the_real_values_and_carries_the_full_id_onward(self):
        s = build_session(cart(address_id=BASE), get_addresses=self.saved())
        with using(s):
            out = await instamart.build_cart("tok", FULL, SELECTION)
        self.assertEqual(s.args("update_cart")["selectedAddressId"], FULL)
        self.assertEqual(out["review"]["address"]["id"], FULL)  # the frontend echoes this into coupon/checkout calls
        self.assertTrue(out["review"]["canCheckout"])
        self.assertNotIn("get_addresses", s.names())  # nothing to diagnose

    async def test_a_cart_on_another_address_is_still_refused(self):
        other = "zzzzzzzzzzzzzzzzzzzz"
        with using(build_session(cart(address_id=other), get_addresses=self.saved())), self.assertLogs("uvicorn.error", level="WARNING"), \
             self.assertRaises(InstamartError) as ctx:
            await instamart.build_cart("tok", FULL, SELECTION)
        self.assertEqual(ctx.exception.code, "address_mismatch")

    async def test_a_truncation_that_is_not_at_the_separator_is_still_refused(self):
        with using(build_session(cart(address_id=BASE[:-4]), get_addresses=self.saved())), self.assertLogs("uvicorn.error", level="WARNING"), \
             self.assertRaises(InstamartError):
            await instamart.build_cart("tok", FULL, SELECTION)

    async def test_coupons_use_the_full_id_and_both_cart_reads_verify(self):
        from tests.test_instamart import COUPONS, discounted_cart

        s = FakeSession({
            "get_cart": [envelope(cart(address_id=BASE)), envelope(discounted_cart(address_id=BASE))],
            "apply_coupon": envelope(discounted_cart(address_id=BASE)),
            "list_coupons": envelope(COUPONS),
        })
        with using(s):
            out = await instamart.apply_coupon("tok", FULL, "SAVE20")
        self.assertEqual(s.args("list_coupons"), {"addressId": FULL})  # documented: the get_addresses id
        self.assertEqual(out["review"]["address"]["id"], FULL)
        self.assertEqual(out["review"]["total"], "₹116")

    async def test_a_coupon_on_a_cart_for_another_address_is_refused(self):
        s = FakeSession({"get_cart": [envelope(cart(address_id="zzzzzzzzzzzzzzzzzzzz"))], "get_addresses": self.saved()})
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(InstamartError) as ctx:
            await instamart.apply_coupon("tok", FULL, "SAVE20")
        self.assertEqual(ctx.exception.code, "address_mismatch")
        self.assertNotIn("apply_coupon", s.names())

    async def test_checkout_passes_with_the_real_values_and_sends_the_full_id(self):
        s = checkout_session(get_cart=envelope(cart(address_id=BASE)))
        with using(s):
            out = await place(address=FULL)
        self.assertEqual(out["status"], "placed")
        self.assertEqual(s.args("checkout")["addressId"], FULL)

    async def test_checkout_on_a_cart_for_another_address_never_reaches_checkout(self):
        s = checkout_session(get_cart=envelope(cart(address_id="zzzzzzzzzzzzzzzzzzzz")), get_addresses=self.saved())
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(InstamartError) as ctx:
            await place(address=FULL)
        self.assertEqual(ctx.exception.code, "address_mismatch")
        self.assertNotIn("checkout", s.names())


class CreatedAddressIdTests(unittest.IsolatedAsyncioTestCase):
    def saved(self, address_id):
        row = {"id": address_id, "addressLine": "5 Park Street", "phoneNumber": "9876543210", "addressCategory": "OTHER"}
        return envelope({"addresses": [row], "pagination": {"hasMore": False}})

    async def create(self, returned_id, listed_id):
        from tests.test_instamart_addresses import CREATE_FIELDS

        s = FakeSession({"create_address": envelope({"addressId": returned_id}), "get_addresses": self.saved(listed_id)})
        with using(s):
            return await instamart_addresses.create_address("tok", CREATE_FIELDS)

    async def test_a_base_only_id_from_create_address_is_returned_in_the_get_addresses_form(self):
        out = await self.create(BASE, FULL)
        self.assertEqual(out["addressId"], FULL)  # coordinates, orders and the picker are keyed by this form
        self.assertEqual(out["addresses"][0]["id"], FULL)

    async def test_an_id_that_already_matches_is_returned_unchanged(self):
        self.assertEqual((await self.create(FULL, FULL))["addressId"], FULL)

    async def test_an_id_not_found_in_the_list_is_returned_as_swiggy_gave_it(self):
        self.assertEqual((await self.create("brand-new", FULL))["addressId"], "brand-new")


if __name__ == "__main__":
    unittest.main()
