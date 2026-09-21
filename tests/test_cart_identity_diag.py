"""Cart-sync diagnostic: both cart builds log the cart's id and whether the restaurant block came back (ids/flags only)."""
import unittest

from fridge_to_fork import food, instamart
from tests import test_food as tf
from tests import test_instamart as ti


class InstamartIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def build(self, get_cart):
        s = ti.cart_session(get_cart=ti.envelope(get_cart))
        with ti.using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            await instamart.build_cart("tok", "addr-home", ti.SELECTION)
        return [line for line in logs.output if "[INSTAMART][diag] cart identity" in line]

    async def test_the_cart_id_and_address_binding_are_logged(self):
        (line,) = await self.build(ti.cart(cartId="c-123"))
        self.assertIn("cartId='c-123'", line)
        self.assertIn("cartAbsent=None", line)
        self.assertIn("items=1", line)
        self.assertIn("requested_address='addr-home'", line)

    async def test_an_absent_cart_is_visible(self):
        (line,) = await self.build(ti.cart(cartAbsent=True, cartAbsentReason="EXPIRED"))
        self.assertIn("cartId=None", line)
        self.assertIn("cartAbsent=True cartAbsentReason='EXPIRED'", line)

    async def test_no_names_or_amounts_are_logged(self):
        (line,) = await self.build(ti.cart(cartId="c-1"))
        for private in ("Tomato", "MG Road", "9876543210", "₹"):
            self.assertNotIn(private, line)


class FoodIdentityTests(tf.FoodCase):
    async def build(self, cart):
        s = tf.cart_session(cart=cart)
        with tf.using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            await food.build_cart("tok", "addr-home", tf.selection())
        return [line for line in logs.output if "[FOOD][diag] cart identity" in line]

    async def test_cart_id_and_restaurant_presence_are_logged(self):
        base = tf.food_cart()
        inner = base["data"] if isinstance(base.get("data"), dict) else base
        inner["cart_id"] = "fc-9"
        (line,) = await self.build(base)
        self.assertIn("cart_id='fc-9'", line)
        self.assertIn("restaurant_block_present=", line)
        self.assertIn("id_like_keys=", line)
        self.assertIn("addressId='addr-home'", line)

    async def test_a_missing_restaurant_block_is_reported_as_absent(self):
        base = tf.food_cart()
        inner = base["data"] if isinstance(base.get("data"), dict) else base
        inner.pop("restaurant", None)
        (line,) = await self.build(base)
        self.assertIn("restaurant_block_present=False restaurant_id_present=False", line)


if __name__ == "__main__":
    unittest.main()
