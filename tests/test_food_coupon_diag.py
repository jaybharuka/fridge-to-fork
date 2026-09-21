"""Log-only diagnostic: what a listed coupon entry actually carries (id vs title vs ribbon), to tell codes from internal ids."""
from fridge_to_fork import food
from tests import test_food as tf


class CouponListingDiagTests(tf.FoodCase):
    async def test_id_title_ribbon_and_status_are_logged_per_entry(self):
        uuid = "b202c339-80da-4c2e-a561-c84a1f4cf755"
        listing = {**tf.FOOD_COUPONS, "summary": {"filter_applied": "COD-compatible offers"}, "coupon_sections": [
            {"title": "For you", "coupons": [{"id": uuid, "title": "TRYNEW", "ribbon_text": "NEW", "applicabilityStatus": "APPLICABLE"}]}]}
        s = tf.cart_session(fetch_food_coupons=tf.envelope(listing))
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            await food.build_cart("tok", "addr-home", tf.selection())
        (line,) = [l for l in logs.output if "[FOOD][diag] coupons listed" in l]
        self.assertIn(f"'id': '{uuid}'", line)
        self.assertIn("'title': 'TRYNEW'", line)
        self.assertIn("filter_applied='COD-compatible offers'", line)
        self.assertIn("'keys': ['applicabilityStatus', 'id', 'ribbon_text', 'title']", line)

    async def test_the_listing_is_unchanged_by_the_diagnostic(self):
        s = tf.cart_session()
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.build_cart("tok", "addr-home", tf.selection())
        self.assertTrue(out["coupons"]["available"])


class CouponCodeFieldTests(tf.FoodCase):
    """Real listing (Behrouz cart): every `id` is a UUID and the coupon code is the `title`. Sending the UUID as
    couponCode was refused with an empty body."""

    UUID = "b202c339-80da-4c2e-a561-c84a1f4cf755"

    def listing(self, *entries):
        return {**tf.FOOD_COUPONS, "summary": {"filter_applied": "COD only"},
                "coupon_sections": [{"title": "For you", "coupons": list(entries)}]}

    def entry(self, id_, title, **extra):
        return {"id": id_, "title": title, "ribbon_text": "₹125 OFF", "applicable": True, **extra}

    async def build(self, *entries):
        s = tf.cart_session(fetch_food_coupons=tf.envelope(self.listing(*entries)))
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.build_cart("tok", "addr-home", tf.selection())
        return s, out["coupons"]

    async def test_a_uuid_id_means_the_title_is_the_code(self):
        _, coupons = await self.build(self.entry(self.UUID, "FLAVORFUL"))
        (c,) = coupons["items"]
        self.assertEqual((c["code"], c["title"], c["ribbon"]), ("FLAVORFUL", "FLAVORFUL", "₹125 OFF"))

    async def test_a_real_code_in_id_is_still_used(self):
        _, coupons = await self.build(self.entry("SAVE50", "₹50 off"))
        self.assertEqual(coupons["items"][0]["code"], "SAVE50")

    async def test_a_uuid_id_with_no_code_shaped_title_is_not_offered(self):
        _, coupons = await self.build(self.entry(self.UUID, "Flat ₹50 off on orders above ₹199"), self.entry("SAVE50", "ok"))
        self.assertEqual([c["code"] for c in coupons["items"]], ["SAVE50"])

    async def test_applying_sends_the_title_code_never_the_uuid(self):
        before = tf.food_cart()
        after = tf.food_cart(to_pay=336, coupon="FLAVORFUL", discount=50)
        s = tf.cart_session(get_food_cart=[tf.envelope(before), tf.envelope(after)],
                            fetch_food_coupons=tf.envelope(self.listing(self.entry(self.UUID, "FLAVORFUL"))),
                            apply_food_coupon=tf.envelope({"statusCode": 0}))
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.apply_coupon("tok", "addr-home", "FLAVORFUL", "r1", None)
        self.assertEqual(s.args("apply_food_coupon"), {"couponCode": "FLAVORFUL", "addressId": "addr-home"})
        self.assertEqual(out["review"]["total"], 336.0)

    async def test_a_coupon_the_cart_already_carries_matches_its_title_code(self):
        # coupon_applied on the cart is the code ('SWIGGYIT'), which used to never match the UUID id
        s = tf.cart_session(get_food_cart=[tf.envelope(tf.food_cart(to_pay=356, coupon="SWIGGYIT", discount=30))],
                            fetch_food_coupons=tf.envelope(self.listing(self.entry(self.UUID, "SWIGGYIT"))))
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.apply_coupon("tok", "addr-home", "SWIGGYIT", "r1", None)
        self.assertTrue(out["alreadyApplied"])
        self.assertNotIn("apply_food_coupon", s.names())
