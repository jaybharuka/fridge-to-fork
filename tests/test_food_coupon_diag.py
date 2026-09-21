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
