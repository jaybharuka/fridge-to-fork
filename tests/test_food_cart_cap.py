"""Swiggy's ₹1000 Food cart cap ("hard ₹1000 cap on Builders Club orders"). The docs' pseudo-code checks `cart.data.total`, which
is not a cart-level field; the cart schema says to use the payable total (`to_pay`) for checkout decisions, so that is what the
cap is checked against. Over the cap: a blocker at review (the button is disabled by canCheckout) and a refusal at checkout."""
from fridge_to_fork import food
from fridge_to_fork.swiggy_common import SwiggyError
from tests import test_food as tf


def over(to_pay, **kw):
    return tf.food_cart(to_pay=to_pay, **kw)


class CapReviewTests(tf.FoodCase):
    async def review(self, cart):
        s = tf.cart_session(cart=cart)
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            return (await food.build_cart("tok", "addr-home", tf.selection()))["review"]

    async def test_a_cart_at_the_cap_is_fine(self):
        r = await self.review(over(1000))
        self.assertEqual((r["blockers"], r["canCheckout"]), ([], True))

    async def test_a_cart_over_the_cap_is_blocked_with_the_amount_and_the_way_out(self):
        r = await self.review(over(1180))
        self.assertFalse(r["canCheckout"])
        (msg,) = r["blockers"]
        self.assertIn("₹1,000", msg)
        self.assertIn("₹1,180", msg)
        self.assertIn("Edit dish", msg)
        self.assertEqual(r["total"], 1180.0)  # the review still shows the real bill

    async def test_a_fractional_total_over_the_cap_is_still_blocked(self):
        r = await self.review(over(1000.5))
        self.assertFalse(r["canCheckout"])
        self.assertIn("₹1,000.50", r["blockers"][0])

    async def test_the_cap_is_on_the_payable_amount_not_the_item_total(self):
        # item total above the cap but a coupon brings the payable amount under it: allowed, and the reading is logged
        cart = over(950, coupon="SWIGGYIT", discount=150)
        cart_inner = cart["data"] if isinstance(cart.get("data"), dict) else cart
        cart_inner["pricing"]["item_total"] = 1100
        s = tf.cart_session(cart=cart)
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            r = (await food.build_cart("tok", "addr-home", tf.selection()))["review"]
        self.assertTrue(r["canCheckout"])
        self.assertTrue(any("item_total is over the cap but to_pay is not" in l for l in logs.output))


class CapCouponTests(tf.FoodCase):
    async def test_a_coupon_can_still_be_applied_to_an_over_cap_cart_so_it_can_come_back_under(self):
        before, after = over(1050), over(950, coupon="FLAVORFUL", discount=100)
        listing = {**tf.FOOD_COUPONS, "coupon_sections": [{"coupons": [{"id": "b202c339-80da-4c2e-a561-c84a1f4cf755", "title": "FLAVORFUL", "applicable": True}]}]}
        s = tf.cart_session(get_food_cart=[tf.envelope(before), tf.envelope(after)], fetch_food_coupons=tf.envelope(listing),
                            apply_food_coupon=tf.envelope({"statusCode": 0}))
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.apply_coupon("tok", "addr-home", "FLAVORFUL", "r1", None)
        self.assertTrue(out["review"]["canCheckout"])
        self.assertEqual(out["review"]["total"], 950.0)

    async def test_other_blockers_still_stop_a_coupon(self):
        empty = tf.food_cart(items=[])
        s = tf.cart_session(get_food_cart=[tf.envelope(empty)])
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await food.apply_coupon("tok", "addr-home", "X", "r1", None)
        self.assertEqual(ctx.exception.code, "cart_blocked")


class CapCheckoutTests(tf.FoodCase):
    async def test_checkout_refuses_an_over_cap_cart_and_never_places_an_order(self):
        s = tf.checkout_session(get_food_cart=[tf.envelope(over(1180))])
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await tf.place(total=1180.0)
        self.assertEqual(ctx.exception.code, "cart_blocked")
        self.assertIn("₹1,000", ctx.exception.message)
        self.assertNotIn("place_food_order", s.names())
