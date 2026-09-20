"""
Deterministic Food flow, phase 1 (fridge_to_fork/food.py, food_routes.py): search -> cart -> review -> COD checkout.
Fixtures follow Swiggy's Food reference pages (search_restaurants, search_menu, update_food_cart, get_food_cart,
place_food_order, get_food_orders). Run: python -m unittest tests.test_food
"""

import copy
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork import features, food
from fridge_to_fork.swiggy_common import SwiggyError
from tests.test_instamart import ADDRESSES, FakeSession, envelope, signed_bearer

# ---------------------------------------------------------------------------- fixtures (documented shapes)

SAVED = {"addresses": [{"id": "addr-home", "addressLine": "12 MG Road, Bengaluru", "phoneNumber": "9876543210", "addressTag": "Home"}],
         "pagination": {"page": 1, "pageSize": 10, "total": 1, "totalPages": 1, "hasMore": False}}

RESTAURANTS = {
    "restaurants": [
        {"id": "r1", "name": "Punjabi Tadka", "cuisines": ["North Indian"], "avgRating": 4.4, "areaName": "Indiranagar", "distanceKm": 1.2,
         "deliveryTimeMinutes": 28, "deliveryTimeRange": "25-30 mins", "costForTwo": "₹400 for two", "offer": "20% off", "availabilityStatus": "OPEN"},
        {"id": "r2", "name": "Biryani House", "cuisines": ["Biryani"], "avgRating": 4.1, "deliveryTimeMinutes": 35, "availabilityStatus": "OPEN"},
        {"id": "r3", "name": "Late Night Bites", "cuisines": ["Fast food"], "availabilityStatus": "CLOSED", "nextOpenTime": "6 PM"},
    ],
    "dishes": [],
    "query": "butter chicken",
    "hasMore": False,
}

PLAIN = {"name": "Butter Chicken", "price": 320, "isVeg": False, "menu_item_id": "m-plain", "inStock": 1, "restaurant_id": "r1",
         "restaurant_name": "Punjabi Tadka", "imageUrl": "https://img.example/bc.png", "rating": "4.5", "totalRatings": "1K+", "isBestseller": True,
         "hasVariants": False, "hasAddons": False}

V2 = {"name": "Butter Chicken Bowl", "price": 250, "isVeg": False, "menu_item_id": "m-v2", "inStock": 1, "restaurant_id": "r2",
      "restaurant_name": "Biryani House", "hasVariants": True, "hasAddons": True,
      "variantsV2": [{"groupId": "g-size", "name": "Size", "variations": [
          {"id": "v-half", "name": "Half", "price": 250, "inStock": 1, "default": 1}, {"id": "v-full", "name": "Full", "price": 420, "inStock": 1}]}],
      "addons": [{"groupId": "g-extra", "groupName": "Extras", "minAddons": 0, "maxAddons": 2, "maxFreeAddons": 0,
                  "choices": [{"id": "a-raita", "name": "Raita", "price": 30}, {"id": "a-naan", "name": "Butter Naan", "price": 40}]}]}

LEGACY = {"name": "Butter Chicken Combo", "price": 300, "menu_item_id": "m-legacy", "inStock": 1, "restaurant_id": "r2", "hasVariants": True,
          "variations": [{"id": "l1", "groupId": "lg", "name": "Regular", "price": 300, "default": 1}, {"id": "l2", "groupId": "lg", "name": "Large", "price": 380}]}

CLOSED = {"name": "Butter Chicken Roll", "price": 150, "menu_item_id": "m-closed", "inStock": 1, "restaurant_id": "r3", "restaurant_name": "Late Night Bites"}
UNKNOWN_REST = {"name": "Butter Chicken Thali", "price": 280, "menu_item_id": "m-unk", "inStock": 1, "restaurant_id": "r9", "restaurant_name": "Somewhere New"}
OUT_OF_STOCK = {**PLAIN, "menu_item_id": "m-oos", "name": "Butter Chicken Special", "inStock": 0}
BROKEN_VARIANTS = {"name": "Mystery Curry", "price": 200, "menu_item_id": "m-broken", "inStock": 1, "restaurant_id": "r1", "hasVariants": True}
NO_ID = {"name": "Butter Chicken (no id)", "price": 200, "restaurant_id": "r1"}

MENU = {"items": [UNKNOWN_REST, PLAIN, CLOSED, V2, LEGACY, OUT_OF_STOCK, BROKEN_VARIANTS, NO_ID], "query": "butter chicken", "totalItems": 8, "hasMore": False}


def food_cart(*, to_pay=386, items=None, restaurant_id="r1", discount=0, coupon=None, **overrides) -> dict:
    """get_food_cart `data`: the live cart is nested under data.data, next to addressId and the payment view."""
    inner = {
        "cart_id": "cart-1", "result": "success", "restaurant": {"id": restaurant_id, "name": "Punjabi Tadka", "area": "Indiranagar", "deliverySubtitle": "28 mins"},
        "items": items if items is not None else [{
            "menu_item_id": "m-plain", "name": "Butter Chicken", "quantity": 1, "subtotal": 320, "total": 320, "final_price": 320, "in_stock": True, "is_veg": 0,
            "imageUrl": "https://img.example/bc.png"}],
        "item_count": 1,
        "pricing": {"item_total": 320, "delivery_charge": 40, "delivery_charge_strikeoff": 60, "taxes_and_charges": 26, "to_pay": to_pay},
        "offers": {"coupon_applied": coupon, "coupon_discount": discount, "free_delivery_applied": False},
    }
    return {"data": inner, "addressId": "addr-home", "availablePaymentMethods": ["Cash", "UPI"], **overrides}


COD = {"available": True, "id": "Cash", "displayName": "Cash on delivery"}
UPI_ONLY_VIEW = {"allMethods": [{"id": "gpay://upi/", "groupName": "UPI", "enabled": True}], "placeOrderToolName": "place_food_order"}
PAYMENT = {"cod": COD, "allMethods": [{"id": "gpay://upi/", "groupName": "UPI", "enabled": True}, {"id": "PayWithQR", "groupName": "UPI", "enabled": True}],
           "paymentAmount": "386", "addressId": "addr-home", "placeOrderToolName": "place_food_order"}

PLACED = {"orderId": "F-1001", "status": "CONFIRMED", "normalizedStatus": "success", "items": [{"name": "Butter Chicken", "quantity": 1, "total": 320}],
          "restaurantName": "Punjabi Tadka", "restaurantAddress": "Indiranagar", "totalAmount": 386, "estimatedDelivery": "35 mins", "deliveryAddress": "12 MG Road"}
ACTIVE = {"orders": [{"orderId": "F-1001", "restaurantId": "r1", "restaurantName": "Punjabi Tadka", "orderTotal": "₹386", "orderStatus": "PLACED",
                      "orderType": "FOOD", "orderedItems": "Butter Chicken x1", "orderedTime": "now", "isActiveOrder": True, "actions": []}]}
NONE_ACTIVE = {"orders": []}


def using(session: FakeSession):
    @asynccontextmanager
    async def fake(_token):
        yield session

    return patch.object(food, "_session", fake)


def selection(**over) -> dict:
    return {"restaurant_id": "r1", "restaurant_name": "Punjabi Tadka", "menu_item_id": "m-plain", "quantity": 1, "format": None, "variants": [], "addons": [], **over}


def cart_session(cart=None, **over) -> FakeSession:
    return FakeSession({
        "get_addresses": envelope(SAVED), "flush_food_cart": envelope({"success": True}), "update_food_cart": envelope(cart or food_cart()),
        "get_food_cart": envelope(cart or food_cart()), "get_payment_options": envelope(PAYMENT), **over,
    })


class FoodCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        food._attempts.clear()
        food._inflight.clear()


# ---------------------------------------------------------------------------- stage 1+2: search


class SearchTests(FoodCase):
    async def search(self, **over):
        s = FakeSession({"get_addresses": envelope(SAVED), "search_restaurants": envelope(RESTAURANTS), "search_menu": envelope(MENU), **over})
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            out = await food.search_dish("tok", "butter chicken", "addr-home")
        return out, s, "\n".join(logs.output)

    async def test_it_searches_both_tools_near_the_chosen_address(self):
        _, s, _ = await self.search()
        self.assertEqual(s.args("search_restaurants"), {"addressId": "addr-home", "query": "butter chicken"})
        self.assertEqual(s.args("search_menu"), {"addressId": "addr-home", "query": "butter chicken"})
        self.assertNotIn("update_food_cart", s.names())  # docs: never touch the cart before the user decides

    async def test_a_result_carries_what_the_user_needs_to_choose(self):
        out, _, _ = await self.search()
        plain = next(r for r in out["results"] if r["menuItemId"] == "m-plain")
        self.assertEqual((plain["name"], plain["price"], plain["isVeg"], plain["bestseller"], plain["available"]), ("Butter Chicken", 320.0, False, True, True))
        self.assertEqual(plain["restaurant"], {
            "id": "r1", "name": "Punjabi Tadka", "area": "Indiranagar", "etaMinutes": 28, "etaRange": "25-30 mins", "distanceKm": 1.2,
            "rating": 4.4, "costForTwo": "₹400 for two", "offer": "20% off", "open": True})
        self.assertEqual(plain["imageUrl"], "https://img.example/bc.png")

    async def test_restaurants_that_are_not_open_are_never_offered(self):
        out, _, _ = await self.search()
        self.assertNotIn("m-closed", [r["menuItemId"] for r in out["results"]])

    async def test_a_restaurant_search_didnt_list_is_kept_but_after_the_confirmed_open_ones(self):
        out, _, _ = await self.search()
        ids = [r["menuItemId"] for r in out["results"]]
        self.assertIsNone(next(r for r in out["results"] if r["menuItemId"] == "m-unk")["restaurant"]["open"])
        self.assertLess(ids.index("m-plain"), ids.index("m-unk"))

    async def test_out_of_stock_items_sort_last_and_are_marked_unavailable(self):
        out, _, _ = await self.search()
        oos = next(r for r in out["results"] if r["menuItemId"] == "m-oos")
        self.assertFalse(oos["available"])
        self.assertEqual(out["results"][-1]["menuItemId"], "m-oos")  # or the unsupported one, but never ahead of in-stock items
        first_unavailable = min(i for i, r in enumerate(out["results"]) if not r["available"])
        self.assertTrue(all(not r["available"] for r in out["results"][first_unavailable:]))

    async def test_items_without_the_ids_a_cart_needs_are_dropped(self):
        out, _, _ = await self.search()
        self.assertNotIn("Butter Chicken (no id)", [r["name"] for r in out["results"]])

    async def test_variants_v2_and_addons_are_surfaced_with_their_group_ids(self):
        out, _, _ = await self.search()
        c = next(r for r in out["results"] if r["menuItemId"] == "m-v2")["customization"]
        self.assertEqual(c["format"], "variantsV2")
        self.assertTrue(c["supported"])
        self.assertEqual(c["variantGroups"], [{"groupId": "g-size", "name": "Size", "options": [
            {"id": "v-half", "name": "Half", "price": 250.0, "default": True, "available": True},
            {"id": "v-full", "name": "Full", "price": 420.0, "default": False, "available": True}]}])
        self.assertEqual(c["addonGroups"], [{"groupId": "g-extra", "name": "Extras", "min": 0, "max": 2, "choices": [
            {"id": "a-raita", "name": "Raita", "price": 30.0}, {"id": "a-naan", "name": "Butter Naan", "price": 40.0}]}])

    async def test_legacy_variations_are_grouped_by_group_id_and_keep_their_own_format(self):
        out, _, _ = await self.search()
        c = next(r for r in out["results"] if r["menuItemId"] == "m-legacy")["customization"]
        self.assertEqual(c["format"], "variations")
        self.assertEqual([(g["groupId"], [o["id"] for o in g["options"]]) for g in c["variantGroups"]], [("lg", ["l1", "l2"])])

    async def test_an_item_that_claims_variants_but_gives_none_is_unsupported_not_guessed(self):
        out, _, _ = await self.search()
        self.assertFalse(next(r for r in out["results"] if r["menuItemId"] == "m-broken")["customization"]["supported"])
        self.assertTrue(next(r for r in out["results"] if r["menuItemId"] == "m-plain")["customization"]["supported"])

    async def test_a_failing_restaurant_search_still_returns_the_dishes(self):
        out, _, _ = await self.search(search_restaurants=envelope(success=False, error="down"))
        self.assertIn("m-plain", [r["menuItemId"] for r in out["results"]])
        self.assertTrue(all(r["restaurant"]["open"] is None for r in out["results"]))

    async def test_a_failing_menu_search_is_an_error(self):
        s = FakeSession({"get_addresses": envelope(SAVED), "search_restaurants": envelope(RESTAURANTS), "search_menu": envelope(success=False, error="nope")})
        with using(s), self.assertRaises(SwiggyError) as ctx:
            await food.search_dish("tok", "x", "addr-home")
        self.assertEqual(ctx.exception.tool, "search_menu")

    async def test_auth_expiry_propagates_from_either_search(self):
        for tool in ("search_restaurants", "search_menu"):
            s = FakeSession({"get_addresses": envelope(SAVED), "search_restaurants": envelope(RESTAURANTS), "search_menu": envelope(MENU), tool: envelope(success=False, error="401 Unauthorized")})
            with using(s), self.assertRaises(SwiggyError) as ctx:
                await food.search_dish("tok", "x", "addr-home")
            self.assertEqual(ctx.exception.code, "auth_required", tool)

    async def test_results_are_capped(self):
        many = {**MENU, "items": [{**PLAIN, "menu_item_id": f"m{i}"} for i in range(30)]}
        out, _, _ = await self.search(search_menu=envelope(many))
        self.assertEqual(len(out["results"]), food.MAX_RESULTS)

    async def test_the_diagnostic_line_shows_structure_and_no_personal_text(self):
        _, _, text = await self.search()
        self.assertIn("[FOOD][diag] search: menu_items=8", text)
        self.assertIn("status=['CLOSED', 'OPEN']", text)
        self.assertIn("closed_dropped=1", text)
        self.assertIn("'menu_item_id': 'str'", text)
        for private in ("9876543210", "12 MG Road", "Bengaluru", "Punjabi Tadka", "Butter"):
            self.assertNotIn(private, text)


class FoodAddressTests(FoodCase):
    async def resolve(self, saved_id, asked):
        saved = {**SAVED, "addresses": [{**SAVED["addresses"][0], "id": saved_id}]}
        s = FakeSession({"get_addresses": envelope(saved)})
        with using(s):
            async with food._session("tok") as session:
                return await food._resolve_address(session, asked)

    async def test_the_canonical_food_id_is_returned_even_if_the_caller_used_another_form(self):
        full = "d60pf1o28cib6t3jveug__AMOOxgTFUakDAsJFL27MqT"
        for asked in (full, "d60pf1o28cib6t3jveug"):
            self.assertEqual((await self.resolve(full, asked))["id"], full, asked)  # the compound-id quirk found on Instamart

    async def test_an_unknown_address_is_refused_and_logged_by_id_only(self):
        with self.assertLogs("uvicorn.error", level="WARNING") as logs, self.assertRaises(SwiggyError) as ctx:
            await self.resolve("addr-home", "somebody-elses")
        self.assertEqual(ctx.exception.code, "address_not_found")
        self.assertNotIn("MG Road", "\n".join(logs.output))

    async def test_no_saved_address_is_a_clear_error(self):
        s = FakeSession({"get_addresses": envelope({"addresses": [], "pagination": {"hasMore": False}})})
        with using(s), self.assertRaises(SwiggyError) as ctx:
            await food.search_dish("tok", "x", None)
        self.assertEqual(ctx.exception.code, "no_address")


# ---------------------------------------------------------------------------- stage 3+4: cart and review


class CartTests(FoodCase):
    async def build(self, sel=None, **over):
        s = cart_session(**over)
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            out = await food.build_cart("tok", "addr-home", sel or selection())
        return out, s, "\n".join(logs.output)

    async def test_the_cart_is_flushed_before_anything_is_added(self):
        _, s, _ = await self.build()
        self.assertEqual(s.names()[s.names().index("flush_food_cart"):][:4], ["flush_food_cart", "update_food_cart", "get_food_cart", "get_payment_options"])

    async def test_a_plain_item_is_sent_with_the_ids_and_the_address(self):
        _, s, _ = await self.build()
        self.assertEqual(s.args("update_food_cart"), {
            "restaurantId": "r1", "cartItems": [{"menu_item_id": "m-plain", "quantity": 1}], "addressId": "addr-home", "restaurantName": "Punjabi Tadka"})
        self.assertEqual(s.args("get_food_cart"), {"addressId": "addr-home", "restaurantName": "Punjabi Tadka"})

    async def test_variants_v2_and_addons_use_their_own_fields(self):
        sel = selection(menu_item_id="m-v2", restaurant_id="r2", format="variantsV2", variants=[{"group_id": "g-size", "variation_id": "v-full"}],
                        addons=[{"group_id": "g-extra", "addon_id": "a-raita", "quantity": 1}])
        cart = food_cart(restaurant_id="r2", items=[{"menu_item_id": "m-v2", "name": "Bowl", "quantity": 1, "subtotal": 1, "total": 450, "final_price": 450,
                                                    "variants": [{"group_id": "g-size", "variation_id": "v-full", "name": "Full"}], "addons": [{"group_id": "g-extra", "id": "a-raita", "name": "Raita"}]}])
        _, s, _ = await self.build(sel, update_food_cart=envelope(cart), get_food_cart=envelope(cart))
        item = s.args("update_food_cart")["cartItems"][0]
        self.assertEqual(item, {"menu_item_id": "m-v2", "quantity": 1, "variantsV2": [{"group_id": "g-size", "variation_id": "v-full"}],
                                "addons": [{"group_id": "g-extra", "addon_id": "a-raita", "quantity": 1}]})
        self.assertNotIn("variants", item)  # docs: one format or the other, never both

    async def test_legacy_variations_are_sent_as_variants(self):
        sel = selection(menu_item_id="m-legacy", restaurant_id="r2", format="variations", variants=[{"group_id": "lg", "variation_id": "l2"}])
        cart = food_cart(restaurant_id="r2", items=[{"menu_item_id": "m-legacy", "name": "Combo", "quantity": 1, "subtotal": 1, "total": 380, "final_price": 380,
                                                    "variants": [{"group_id": "lg", "variation_id": "l2"}]}])
        _, s, _ = await self.build(sel, update_food_cart=envelope(cart), get_food_cart=envelope(cart))
        self.assertEqual(list(s.args("update_food_cart")["cartItems"][0]), ["menu_item_id", "quantity", "variants"])

    async def test_the_review_is_the_real_cart_with_the_real_bill(self):
        out, _, _ = await self.build()
        r = out["review"]
        self.assertEqual(r["total"], 386.0)
        self.assertEqual([(li["label"], li["value"]) for li in r["lineItems"]], [("Item total", 320.0), ("Delivery fee", 40.0), ("Taxes and charges", 26.0)])
        self.assertEqual(r["lineItems"][1]["strikeoff"], 60.0)
        self.assertEqual((r["items"][0]["name"], r["items"][0]["quantity"], r["items"][0]["lineTotal"]), ("Butter Chicken", 1, 320.0))
        self.assertEqual((r["restaurant"]["name"], r["address"]["id"], r["address"]["label"]), ("Punjabi Tadka", "addr-home", "Home"))
        self.assertTrue(r["canCheckout"])
        self.assertIsNone(r["coupon"])

    async def test_only_cash_is_offered_in_this_phase_even_though_swiggy_lists_upi(self):
        out, _, text = await self.build()
        self.assertEqual([o["key"] for o in out["review"]["payment"]["options"]], ["cod"])
        self.assertIn("[FOOD][diag] payment options (cart)", text)
        self.assertIn("'gpay://upi/' kind=None enabled=True group='UPI' as='intent' -> offered", text)  # the shared classifier, real shape

    async def test_a_cart_without_any_offered_payment_method_blocks_checkout(self):
        out, _, _ = await self.build(get_payment_options=envelope(UPI_ONLY_VIEW))
        self.assertFalse(out["review"]["canCheckout"])
        self.assertIn("No payment method is available for this cart.", out["review"]["blockers"])

    async def test_an_auto_suggested_coupon_with_no_discount_is_not_shown_as_applied(self):
        cart = food_cart(coupon="SAVE50", discount=0)
        out, _, _ = await self.build(update_food_cart=envelope(cart), get_food_cart=envelope(cart))
        self.assertIsNone(out["review"]["coupon"])
        self.assertNotIn("Coupon", [li["label"] for li in out["review"]["lineItems"]])

    async def test_a_real_discount_is_shown(self):
        cart = food_cart(to_pay=336, coupon="SAVE50", discount=50)
        out, _, _ = await self.build(update_food_cart=envelope(cart), get_food_cart=envelope(cart))
        self.assertEqual(out["review"]["coupon"], {"code": "SAVE50", "discount": 50.0})
        self.assertEqual(out["review"]["lineItems"][-1], {"label": "Coupon SAVE50", "value": -50.0})

    async def test_an_out_of_stock_cart_item_blocks_checkout(self):
        cart = food_cart(items=[{"menu_item_id": "m-plain", "name": "Butter Chicken", "quantity": 1, "subtotal": 1, "total": 320, "final_price": 320, "in_stock": False}])
        out, _, _ = await self.build(update_food_cart=envelope(cart), get_food_cart=envelope(cart))
        self.assertFalse(out["review"]["canCheckout"])

    async def test_a_cart_shape_without_the_nesting_is_still_read(self):
        flat = food_cart()["data"]
        out, _, _ = await self.build(update_food_cart=envelope(flat), get_food_cart=envelope(flat))
        self.assertEqual(out["review"]["total"], 386.0)

    async def test_the_cart_diagnostic_shows_structure_and_no_personal_text(self):
        _, _, text = await self.build()
        self.assertIn("[FOOD][diag] cart: update_keys=", text)
        self.assertIn("inner_keys=", text)
        self.assertIn("first_item_fields=", text)
        for private in ("9876543210", "12 MG Road", "Bengaluru"):
            self.assertNotIn(private, text)

    async def test_a_swiggy_refusal_of_the_cart_update_is_surfaced_with_its_tool(self):
        s = cart_session(update_food_cart=envelope(success=False, error="Restaurant is closed"))
        with using(s), self.assertRaises(SwiggyError) as ctx:
            await food.build_cart("tok", "addr-home", selection())
        self.assertEqual((ctx.exception.code, ctx.exception.tool), ("tool_error", "update_food_cart"))
        self.assertNotIn("get_food_cart", s.names())


class CartVerificationTests(FoodCase):
    """The cart is only offered for ordering if Swiggy's own cart is exactly what the user picked."""

    async def refuse(self, cart, sel=None):
        s = cart_session(update_food_cart=envelope(cart), get_food_cart=envelope(cart))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await food.build_cart("tok", "addr-home", sel or selection())
        self.assertEqual(ctx.exception.code, "cart_mismatch")
        self.assertNotIn("get_payment_options", s.names())  # never reaches the payment step
        return ctx.exception

    def item(self, **over):
        return {"menu_item_id": "m-plain", "name": "Butter Chicken", "quantity": 1, "subtotal": 1, "total": 320, "final_price": 320, **over}

    async def test_a_leftover_item_from_before_is_refused(self):
        await self.refuse(food_cart(items=[self.item(), self.item(menu_item_id="stale", name="Old dish")]))

    async def test_a_different_dish_is_refused(self):
        await self.refuse(food_cart(items=[self.item(menu_item_id="other")]))

    async def test_an_empty_cart_is_refused(self):
        await self.refuse(food_cart(items=[]))

    async def test_a_different_restaurant_is_refused(self):
        await self.refuse(food_cart(restaurant_id="r7"))

    async def test_a_different_quantity_is_refused(self):
        await self.refuse(food_cart(items=[self.item(quantity=3)]))

    async def test_a_chosen_variant_swiggys_cart_does_not_echo_is_refused(self):
        sel = selection(format="variantsV2", variants=[{"group_id": "g-size", "variation_id": "v-full"}])
        await self.refuse(food_cart(items=[self.item()]), sel)  # cart has no variants at all: a wrong request shape looks exactly like this
        await self.refuse(food_cart(items=[self.item(variants=[{"group_id": "g-size", "variation_id": "v-half"}])]), sel)  # the wrong size

    async def test_a_chosen_addon_swiggys_cart_does_not_echo_is_refused(self):
        sel = selection(addons=[{"group_id": "g-extra", "addon_id": "a-raita", "quantity": 1}])
        exc = await self.refuse(food_cart(items=[self.item()]), sel)
        self.assertIn("add-ons", exc.message)

    async def test_the_refusal_says_nothing_was_ordered(self):
        exc = await self.refuse(food_cart(items=[]))
        self.assertIn("Nothing was ordered", exc.message)


# ---------------------------------------------------------------------------- stage 5: checkout


def checkout_session(**over) -> FakeSession:
    return FakeSession({
        "get_addresses": envelope(SAVED), "get_food_cart": envelope(food_cart()), "get_payment_options": envelope(PAYMENT),
        "get_food_orders": [envelope(NONE_ACTIVE), envelope(ACTIVE)], "place_food_order": envelope(PLACED), **over,
    })


async def place(*, total=386.0, key="idem-key-0001", payment="cod", address="addr-home", token="tok"):
    return await food.checkout(token, address, total, key, payment)


class CheckoutTests(FoodCase):
    async def test_a_cash_order_is_placed_and_cross_checked(self):
        s = checkout_session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place()
        self.assertEqual((out["status"], out["orderIds"], out["verified"], out["total"]), ("placed", ["F-1001"], True, 386))
        self.assertEqual(out["detail"], {"restaurant": "Punjabi Tadka", "eta": "35 mins", "items": ["Butter Chicken"]})
        self.assertEqual(s.args("place_food_order"), {"addressId": "addr-home", "paymentMethod": "Cash"})  # cod.id echoed exactly
        names = s.names()
        self.assertEqual(names.count("get_food_orders"), 2)  # before and after, like Instamart's get_orders check
        self.assertLess(names.index("get_food_orders"), names.index("place_food_order"))
        self.assertEqual(s.args("get_food_orders"), {"addressId": "addr-home", "activeOnly": True})

    async def test_the_total_is_re_verified_against_the_live_cart(self):
        s = checkout_session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await place(total=350.0)
        self.assertEqual(ctx.exception.code, "cart_changed")
        self.assertNotIn("place_food_order", s.names())

    async def test_a_lapsed_coupon_changes_the_total_and_is_refused(self):
        # the user reviewed 336 (coupon applied); the live cart now bills 386
        s = checkout_session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await place(total=336.0)
        self.assertEqual(ctx.exception.code, "cart_changed")
        self.assertNotIn("place_food_order", s.names())

    async def test_a_blocked_cart_is_never_ordered(self):
        s = checkout_session(get_food_cart=envelope(food_cart(items=[])))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await place()
        self.assertEqual(ctx.exception.code, "cart_blocked")
        self.assertNotIn("place_food_order", s.names())

    async def test_an_unknown_or_unoffered_payment_key_is_refused(self):
        for key in ("upi_qr", "upi_intent:gpay://upi/", "nonsense"):  # UPI is listed by Swiggy but not offered in this phase
            s = checkout_session()
            with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
                await place(key=f"k-{key}-xx", payment=key)
            self.assertEqual(ctx.exception.code, "payment_unavailable", key)
            self.assertNotIn("place_food_order", s.names())

    async def test_an_address_that_is_not_the_users_is_refused_before_anything_is_placed(self):
        s = checkout_session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await place(address="somebody-elses")
        self.assertEqual(ctx.exception.code, "address_not_found")
        self.assertNotIn("place_food_order", s.names())

    async def test_a_replayed_key_returns_the_stored_result_and_never_places_twice(self):
        s = checkout_session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            first = await place()
            second = await place()
        self.assertEqual(first, second)
        self.assertEqual(s.names().count("place_food_order"), 1)

    async def test_only_one_order_runs_per_account(self):
        food._inflight.add(food._account("tok"))
        with using(checkout_session()), self.assertRaises(SwiggyError) as ctx:
            await place()
        self.assertEqual(ctx.exception.code, "checkout_in_progress")

    async def test_the_lock_is_shared_with_instamart_and_released_afterwards(self):
        from fridge_to_fork import instamart

        self.assertIs(food._inflight, instamart._inflight)
        self.assertIs(food._attempts, instamart._attempts)
        with using(checkout_session()), self.assertLogs("uvicorn.error", level="WARNING"):
            await place()
        self.assertNotIn(food._account("tok"), food._inflight)

    async def test_a_dropped_connection_is_unknown_not_a_retry(self):
        s = checkout_session(place_food_order=ConnectionError("reset"), get_food_orders=[envelope(NONE_ACTIVE), envelope(NONE_ACTIVE)])
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place()
        self.assertEqual(out["status"], "unknown")
        self.assertIn("Check the Swiggy app", out["message"])
        self.assertEqual(s.names().count("place_food_order"), 1)  # never retried

    async def test_a_dropped_connection_where_the_order_actually_went_through_is_rescued(self):
        s = checkout_session(place_food_order=ConnectionError("reset"))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place()
        self.assertEqual((out["status"], out["orderIds"], out["verified"]), ("placed", ["F-1001"], True))
        self.assertEqual(s.names().count("place_food_order"), 1)

    async def test_swiggys_refusal_is_a_failure_with_its_message(self):
        s = checkout_session(place_food_order=envelope(success=False, error="Cash on delivery not available above 1000"), get_food_orders=[envelope(NONE_ACTIVE), envelope(NONE_ACTIVE)])
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place()
        self.assertEqual(out["status"], "failed")
        self.assertIn("not available", out["message"])

    async def test_a_claimed_order_that_swiggy_does_not_list_is_placed_but_unverified(self):
        s = checkout_session(get_food_orders=[envelope(NONE_ACTIVE), envelope(NONE_ACTIVE)])
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place()
        self.assertEqual((out["status"], out["verified"]), ("placed", False))

    async def test_when_the_orders_check_is_unavailable_the_outcome_is_still_reported(self):
        s = checkout_session(get_food_orders=envelope(success=False, error="down"))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place()
        self.assertEqual((out["status"], out["verified"]), ("placed", False))

    async def test_pending_payment_is_never_reported_as_an_order(self):
        pending = {"orderId": "F-2", "paasId": "p", "status": "PENDING_PAYMENT", "normalizedStatus": "pending", "bridgeUrl": "https://pay.example/x"}
        s = checkout_session(place_food_order=envelope(pending), get_food_orders=[envelope(NONE_ACTIVE), envelope(NONE_ACTIVE)])
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place()
        self.assertEqual(out["status"], "unknown")

    async def test_a_reply_with_no_order_id_is_a_failure_not_a_success(self):
        s = checkout_session(place_food_order=envelope({"status": "CONFIRMED", "orderId": None}), get_food_orders=[envelope(NONE_ACTIVE), envelope(NONE_ACTIVE)])
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place()
        self.assertEqual(out["status"], "failed")

    async def test_auth_expiry_propagates_and_releases_the_lock(self):
        s = checkout_session(place_food_order=envelope(success=False, error="401 Unauthorized"))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await place()
        self.assertEqual(ctx.exception.code, "auth_required")
        self.assertNotIn(food._account("tok"), food._inflight)

    async def test_the_log_holds_ids_and_amounts_only(self):
        s = checkout_session()
        with using(s), self.assertLogs("uvicorn.error", level="INFO") as logs:
            await place()
        text = "\n".join(logs.output)
        self.assertIn("placing cod order, total=386", text)
        for private in ("9876543210", "12 MG Road", "Bengaluru"):
            self.assertNotIn(private, text)


# ---------------------------------------------------------------------------- routes


class FoodRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(a.app)

    def post(self, path, body, headers=None):
        return self.client.post(f"/api/food/{path}", json=body, headers=headers or {})

    def test_every_route_refuses_while_the_flow_is_off_even_without_auth(self):
        self.assertFalse(features.FOOD_ORDERING_ENABLED)
        for path, body in (("search", {"dish": "x"}), ("cart", {"address_id": "a", "selection": selection()}),
                           ("checkout", {"address_id": "a", "expected_total": 100, "payment_key": "cod", "idempotency_key": "idem-key-0001"})):
            with patch.object(food, "search_dish", AsyncMock()) as fn:
                r = self.post(path, body)
            self.assertEqual(r.status_code, 403, path)
            self.assertEqual(r.json()["error"]["code"], "food_disabled", path)
            fn.assert_not_awaited()

    def test_with_the_flow_on_a_missing_token_is_401(self):
        with patch.object(features, "FOOD_ORDERING_ENABLED", True):
            r = self.post("search", {"dish": "butter chicken"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "auth_required"))

    def test_search_passes_the_dish_and_address_through(self):
        out = {"address": {}, "dish": "butter chicken", "results": [], "hasMore": False}
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food, "search_dish", AsyncMock(return_value=out)) as fn:
            r = self.post("search", {"dish": "  butter chicken ", "address_id": "addr-home"}, signed_bearer())
        self.assertEqual(r.json(), {"ok": True, **out})
        fn.assert_awaited_once_with("swiggy-tok", "butter chicken", "addr-home")

    def test_cart_passes_the_selection_through(self):
        sel = selection(menu_item_id="m-v2", format="variantsV2", variants=[{"group_id": "g", "variation_id": "v"}], addons=[{"group_id": "g2", "addon_id": "a"}])
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food, "build_cart", AsyncMock(return_value={"review": {}, "adjustments": []})) as fn:
            r = self.post("cart", {"address_id": "addr-home", "selection": sel}, signed_bearer())
        self.assertTrue(r.json()["ok"])
        passed = fn.await_args.args[2]
        self.assertEqual((passed["menu_item_id"], passed["format"], passed["variants"], passed["addons"]),
                         ("m-v2", "variantsV2", [{"group_id": "g", "variation_id": "v"}], [{"group_id": "g2", "addon_id": "a", "quantity": 1}]))

    def test_checkout_passes_the_key_and_total_through(self):
        order = {"status": "placed", "orderIds": ["F-1"], "message": "Order placed.", "verified": True, "total": 386, "payment": None}
        body = {"address_id": "addr-home", "expected_total": 386.5, "payment_key": "cod", "idempotency_key": "idem-key-0001"}
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food, "checkout", AsyncMock(return_value=order)) as fn:
            r = self.post("checkout", body, signed_bearer())
        self.assertEqual(r.json(), {"ok": True, "order": order})
        fn.assert_awaited_once_with("swiggy-tok", "addr-home", 386.5, "idem-key-0001", "cod")

    def test_bad_input_is_rejected_before_any_swiggy_call(self):
        bad = [
            ("search", {"dish": ""}), ("search", {"dish": "x" * 81}),
            ("cart", {"address_id": "a", "selection": selection(quantity=0)}), ("cart", {"address_id": "a", "selection": selection(quantity=21)}),
            ("cart", {"address_id": "a", "selection": selection(format="both")}),
            ("checkout", {"address_id": "a", "expected_total": 0, "payment_key": "cod", "idempotency_key": "idem-key-0001"}),
            ("checkout", {"address_id": "a", "expected_total": 10, "payment_key": "cod", "idempotency_key": "short"}),
            ("checkout", {"address_id": "a", "expected_total": 10, "payment_key": "cod", "idempotency_key": "has spaces in it!"}),
        ]
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food, "search_dish", AsyncMock()) as s, \
             patch.object(food, "build_cart", AsyncMock()) as c, patch.object(food, "checkout", AsyncMock()) as k:
            for path, body in bad:
                self.assertEqual(self.post(path, body, signed_bearer()).status_code, 422, (path, body))
        for fn in (s, c, k):
            fn.assert_not_awaited()

    def test_a_swiggy_domain_failure_is_a_200_with_the_code(self):
        exc = SwiggyError("cart_changed", "changed")
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food, "checkout", AsyncMock(side_effect=exc)):
            r = self.post("checkout", {"address_id": "a", "expected_total": 10, "payment_key": "cod", "idempotency_key": "idem-key-0001"}, signed_bearer())
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (200, "cart_changed"))


if __name__ == "__main__":
    unittest.main()
