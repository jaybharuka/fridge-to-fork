"""
Deterministic Food flow, phase 1 (fridge_to_fork/food.py, food_routes.py): search -> cart -> review -> COD checkout.
Fixtures follow Swiggy's Food reference pages (search_restaurants, search_menu, update_food_cart, get_food_cart,
place_food_order, get_food_orders). Run: python -m unittest tests.test_food

Phase 2 adds fetch_food_coupons/apply_food_coupon, and UPI (place_food_order PENDING_PAYMENT -> check_payment_status ->
confirm_order, which for Food echoes addressId/cartId/lat/lng and never uses paasId), on top of the shared classifier.
"""

import copy
import json
import logging
import unittest
from types import SimpleNamespace
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
NOTHING_OFFERABLE = {"allMethods": [{"id": "SwiggyPay", "groupName": "SWIGGYPAY", "enabled": True}, {"id": "gpay://upi/", "groupName": "UPI", "enabled": False}],
                     "placeOrderToolName": "place_food_order"}
FOOD_COUPONS = {
    "coupon_sections": [{"title": "For you", "type": "offers", "coupons": [
        {"id": "SAVE50", "applicable": True, "applicabilityStatus": "APPLICABLE", "title": "₹50 off", "subtitle": "On orders above ₹200",
         "description": "Flat ₹50 off", "terms_and_conditions": {"title": "T&C", "bullet_texts": ["Valid once per user"]}},
        {"id": "BIG150", "applicable": False, "applicabilityStatus": "NOT_APPLICABLE", "title": "₹150 off", "subtitle": "Add ₹200 more to use this"},
        {"applicabilityStatus": "APPLICABLE", "title": "a coupon with no id"},
        {"id": "save50", "applicable": True, "title": "duplicate of SAVE50"},
    ]}],
    "summary": {"total_coupons": 4, "applicable_coupons": 2, "sections_count": 1, "filter_applied": "COD-compatible offers"},
}
PENDING = {"orderId": "F-1001", "paasId": "paas-77", "transactionId": "t-1", "upiIntentUrl": "upi://pay?x=1", "bridgeUrl": "https://pay.example/bridge/abc",
           "isQrFlow": False, "pollingIntervalInMs": 3000, "maxTimeToPollForInMs": 120000, "paymentMethod": "UPI", "status": "PENDING_PAYMENT",
           "normalizedStatus": "pending", "totalAmount": 386, "addressId": "addr-home", "cartId": "cart-1", "lat": 12.97, "lng": 77.59}
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
        "get_food_cart": envelope(cart or food_cart()), "get_payment_options": envelope(PAYMENT), "fetch_food_coupons": envelope(FOOD_COUPONS), "apply_food_coupon": envelope({"statusCode": 0}), **over,
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

    async def test_cash_and_every_listed_upi_option_are_offered_by_the_shared_classifier(self):
        out, s, text = await self.build()
        self.assertEqual([o["key"] for o in out["review"]["payment"]["options"]], ["cod", "upi_intent:gpay://upi/", "upi_qr"])
        self.assertEqual(s.args("get_payment_options"), {"addressId": "addr-home"})  # Food: same addressId as get_food_cart
        self.assertIn("[FOOD][diag] payment options (cart)", text)
        self.assertIn("'gpay://upi/' kind=None enabled=True group='UPI' as='intent' -> offered", text)  # the real all-kind=None shape
        self.assertIn("'PayWithQR' kind=None enabled=True group='UPI' as='qr' -> offered", text)

    async def test_the_parts_of_the_payment_view_nothing_reads_are_logged_so_missing_cash_can_be_explained(self):
        # Food's view has allGroups (snake_case group_name), upiMethods and markdown, which the classifier never looks at.
        view = {**PAYMENT, "cod": None, "allGroups": [
            {"group_name": "UPI", "display_name": "Pay via UPI", "methods": [{"id": "gpay://upi/"}, {"id": "PayWithQR"}]},
            {"group_name": "CASH", "display_name": "Pay on Delivery", "methods": [{"id": "Cash"}]}],
            "upiMethods": [{"id": "gpay://upi/"}], "markdown": "long text with a name"}
        out, _, text = await self.build(get_payment_options=envelope(view))
        self.assertIn("extras: allGroups=[{'group': 'UPI', 'display': 'Pay via UPI', 'ids': ['gpay://upi/', 'PayWithQR']}, {'group': 'CASH', 'display': 'Pay on Delivery', 'ids': ['Cash']}]", text)
        self.assertIn("upiMethods=['gpay://upi/']", text)
        self.assertIn("'markdown': 'str'", text)  # the type, never the text
        self.assertNotIn("long text with a name", text)
        self.assertIn("cod=None", text)
        self.assertNotIn("cod", [o["type"] for o in out["review"]["payment"]["options"]])  # diagnostics only: nothing about what is offered changed

    async def test_only_what_swiggy_lists_and_enables_is_offered(self):
        out, _, _ = await self.build(get_payment_options=envelope({**PAYMENT, "cod": {"available": False, "id": "Cash"}, "allMethods": [
            {"id": "gpay://upi/", "groupName": "UPI", "enabled": True}, {"id": "phonepe://", "groupName": "UPI", "enabled": False}, {"id": "SwiggyPay", "groupName": "SWIGGYPAY", "enabled": True}]}))
        self.assertEqual([o["key"] for o in out["review"]["payment"]["options"]], ["upi_intent:gpay://upi/"])

    async def test_a_cart_without_any_offered_payment_method_blocks_checkout(self):
        out, _, _ = await self.build(get_payment_options=envelope(NOTHING_OFFERABLE))
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

    async def test_the_request_sent_and_the_raw_first_cart_item_are_logged_for_the_first_real_attempt(self):
        _, _, text = await self.build()
        self.assertIn('[FOOD][diag] update_food_cart sent: restaurantId=\'r1\' addressId=\'addr-home\' cartItems=[{"menu_item_id": "m-plain", "quantity": 1}]', text)
        self.assertIn('first_item_raw={"menu_item_id": "m-plain", "name": "Butter Chicken", "quantity": 1', text)
        self.assertNotIn("imageUrl", text.split("first_item_raw=")[1])  # a URL is noise, and everything else here is ids and prices
        for private in ("9876543210", "12 MG Road", "Bengaluru", "Punjabi Tadka"):
            self.assertNotIn(private, text)  # not even the restaurant name is sent to the log

    async def test_a_refusal_from_any_cart_tool_is_logged_with_swiggys_message(self):
        for tool in ("flush_food_cart", "update_food_cart", "get_food_cart"):
            s = cart_session(**{tool: envelope(success=False, error=f"{tool} says: Restaurant is closed")})
            with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs, self.assertRaises(SwiggyError):
                await food.build_cart("tok", "addr-home", selection())
            self.assertIn(f"[FOOD][diag] {tool} refused: code=tool_error message='{tool} says: Restaurant is closed'", "\n".join(logs.output), tool)

    async def test_auth_expiry_is_not_logged_as_a_refusal(self):
        s = cart_session(update_food_cart=envelope(success=False, error="401 Unauthorized"))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs, self.assertRaises(SwiggyError):
            await food.build_cart("tok", "addr-home", selection())
        self.assertNotIn("refused", "\n".join(logs.output))

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

    async def test_a_payment_key_swiggy_does_not_list_is_refused(self):
        for key in ("nonsense", "upi_intent:phonepe://", "upi_intent:", "COD", "upi_qr2"):  # none of these is a listed, enabled option
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

    async def test_the_exact_payment_method_sent_to_place_food_order_is_logged(self):
        s = checkout_session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            await place()
        self.assertIn('[FOOD][diag] place_food_order sent: {"addressId": "addr-home", "paymentMethod": "Cash"}', "\n".join(logs.output))

    async def test_a_place_food_order_refusal_is_logged_with_swiggys_message(self):
        s = checkout_session(place_food_order=envelope(success=False, error="Invalid paymentMethod COD"), get_food_orders=[envelope(NONE_ACTIVE), envelope(NONE_ACTIVE)])
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            out = await place()
        self.assertEqual(out["status"], "failed")
        self.assertIn("[FOOD][diag] place_food_order refused: code=tool_error message='Invalid paymentMethod COD'", "\n".join(logs.output))

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

    async def test_a_pending_payment_with_no_usable_payment_page_is_unknown_never_an_order(self):
        for label, pending in (("no bridge", {**PENDING, "bridgeUrl": None}), ("http bridge", {**PENDING, "bridgeUrl": "http://pay.example/x"}), ("no paasId", {**PENDING, "paasId": None})):
            s = checkout_session(place_food_order=envelope(pending), get_food_orders=[envelope(NONE_ACTIVE), envelope(NONE_ACTIVE)])
            food._attempts.clear()
            with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
                out = await place(payment="upi_qr")
            self.assertEqual(out["status"], "unknown", label)
            self.assertEqual(out["orderIds"], ["F-1001"], label)

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


class CouponTests(FoodCase):
    def session(self, **over):
        before, after = food_cart(), food_cart(to_pay=336, coupon="SAVE50", discount=50)
        applied = {"statusCode": 0, "data": {"offers": {"coupon_applied": "SAVE50", "coupon_discount": 50}, "pricing": {"coupon_discount": 50, "to_pay": 336}}}
        return cart_session(**{"get_food_cart": [envelope(before), envelope(after)], "apply_food_coupon": envelope(applied), **over})

    async def apply(self, s, code="SAVE50"):
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            return await food.apply_coupon("tok", "addr-home", code)

    async def refuse(self, s, code="SAVE50"):
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await food.apply_coupon("tok", "addr-home", code)
        return ctx.exception

    async def test_the_cart_lists_coupons_by_id_for_this_restaurant_and_address(self):
        s = cart_session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.build_cart("tok", "addr-home", selection())
        self.assertEqual(s.args("fetch_food_coupons"), {"restaurantId": "r1", "addressId": "addr-home"})
        c = out["coupons"]
        self.assertTrue(c["available"])
        self.assertEqual(c["filter"], "COD-compatible offers")
        self.assertEqual([x["code"] for x in c["items"]], ["SAVE50", "BIG150"])  # the id-less one and the duplicate are dropped
        self.assertEqual(c["items"][0], {"code": "SAVE50", "title": "₹50 off", "description": "Flat ₹50 off", "applicable": True, "applied": False, "message": None, "terms": ["Valid once per user"]})
        self.assertEqual((c["items"][1]["applicable"], c["items"][1]["message"]), (False, "Add ₹200 more to use this"))
        self.assertIsNone(c["items"][1]["description"])  # the reason is not repeated as a description

    async def test_coupons_that_cannot_be_listed_never_fail_the_cart(self):
        s = cart_session(fetch_food_coupons=envelope(success=False, error="not rolled out"))
        with using(s), self.assertLogs("uvicorn.error", level="INFO"):
            out = await food.build_cart("tok", "addr-home", selection())
        self.assertEqual(out["coupons"], {"available": False, "items": [], "filter": None})
        self.assertTrue(out["review"]["canCheckout"])

    async def test_a_listing_auth_failure_still_propagates(self):
        s = cart_session(fetch_food_coupons=envelope(success=False, error="401 Unauthorized"))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await food.build_cart("tok", "addr-home", selection())
        self.assertEqual(ctx.exception.code, "auth_required")

    async def test_a_coupon_is_applied_and_the_discount_is_read_back_from_the_cart(self):
        s = self.session()
        out = await self.apply(s)
        self.assertEqual(s.args("apply_food_coupon"), {"couponCode": "SAVE50", "addressId": "addr-home"})
        self.assertEqual(s.names().count("get_food_cart"), 2)  # before and after
        self.assertLess(s.names().index("apply_food_coupon"), len(s.names()) - s.names()[::-1].index("get_food_cart") - 1)
        self.assertEqual(out["review"]["total"], 336.0)
        self.assertEqual(out["review"]["lineItems"][-1], {"label": "Coupon SAVE50", "value": -50.0})
        self.assertEqual(out["coupon"], {"code": "SAVE50", "title": "₹50 off", "savings": 50.0})
        self.assertTrue(out["coupons"]["available"])

    async def test_the_code_matches_case_insensitively_but_is_sent_as_listed(self):
        s = self.session()
        await self.apply(s, code="  save50 ")
        self.assertEqual(s.args("apply_food_coupon")["couponCode"], "SAVE50")

    async def test_a_coupon_swiggy_no_longer_lists_is_refused_without_applying(self):
        s = self.session()
        exc = await self.refuse(s, code="MADEUP")
        self.assertEqual(exc.code, "coupon_not_found")
        self.assertNotIn("apply_food_coupon", s.names())

    async def test_a_coupon_that_is_not_applicable_is_refused_with_swiggys_reason(self):
        s = self.session()
        exc = await self.refuse(s, code="BIG150")
        self.assertEqual((exc.code, exc.message), ("coupon_not_applicable", "Add ₹200 more to use this"))
        self.assertNotIn("apply_food_coupon", s.names())

    def silent(self, cart):
        """The same cart with no `restaurant` block at all: the docs type it as optional."""
        cart = copy.deepcopy(cart)
        cart["data"].pop("restaurant", None)
        return cart

    def session_without_restaurant(self, **over):
        before = self.silent(food_cart())
        after = self.silent(food_cart(to_pay=336, coupon="SAVE50", discount=50))
        applied = {"statusCode": 0, "data": {"offers": {"coupon_applied": "SAVE50", "coupon_discount": 50}}}
        return cart_session(**{"get_food_cart": [envelope(before), envelope(after)], "apply_food_coupon": envelope(applied), **over})

    async def test_a_cart_that_does_not_name_its_restaurant_still_gets_coupons_via_the_restaurant_the_review_carried(self):
        # Real account: "Swiggy didn't say which restaurant this cart is for". The coupon call was never even made.
        s = self.session_without_restaurant()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            out = await food.apply_coupon("tok", "addr-home", "SAVE50", "1404575", "Punjabi Tadka")
        self.assertEqual(s.args("fetch_food_coupons"), {"restaurantId": "1404575", "addressId": "addr-home"})
        self.assertEqual(s.args("get_food_cart"), {"addressId": "addr-home", "restaurantName": "Punjabi Tadka"})  # the name is passed like build_cart does
        self.assertEqual(s.args("apply_food_coupon"), {"couponCode": "SAVE50", "addressId": "addr-home"})
        self.assertEqual((out["review"]["total"], out["review"]["restaurant"]["id"], out["review"]["restaurant"]["name"]), (336.0, "1404575", "Punjabi Tadka"))
        self.assertIn("cart restaurant fields=[] cart_restaurant_id=None supplied_restaurant_id='1404575' name_sent=True", "\n".join(logs.output))

    async def test_an_id_less_restaurant_block_counts_as_silent(self):
        cart = food_cart(restaurant_id=None)
        s = cart_session(get_food_cart=[envelope(cart), envelope(food_cart(to_pay=336, coupon="SAVE50", discount=50, restaurant_id=None))],
                         apply_food_coupon=envelope({"statusCode": 0}))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.apply_coupon("tok", "addr-home", "SAVE50", "r1", None)
        self.assertEqual((s.args("fetch_food_coupons")["restaurantId"], out["review"]["restaurant"]["id"]), ("r1", "r1"))

    async def test_when_nothing_names_the_restaurant_it_is_refused_before_any_coupon_call_and_the_log_says_why(self):
        s = self.session_without_restaurant()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs, self.assertRaises(SwiggyError) as ctx:
            await food.apply_coupon("tok", "addr-home", "SAVE50")
        self.assertEqual(ctx.exception.code, "cart_blocked")
        self.assertNotIn("fetch_food_coupons", s.names())
        self.assertNotIn("apply_food_coupon", s.names())
        self.assertIn("cart_restaurant_id=None supplied_restaurant_id=None", "\n".join(logs.output))

    async def test_a_restaurant_the_review_names_that_disagrees_with_the_cart_is_refused_untouched(self):
        s = self.session()  # the cart says r1
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await food.apply_coupon("tok", "addr-home", "SAVE50", "r9", "Somewhere Else")
        self.assertEqual(ctx.exception.code, "cart_changed")
        for tool in ("fetch_food_coupons", "apply_food_coupon"):
            self.assertNotIn(tool, s.names())

    async def test_when_the_cart_names_its_restaurant_that_wins_and_agreement_is_fine(self):
        s = self.session()
        await self.apply(s)  # nothing supplied: the cart's r1 is used, as before
        self.assertEqual(s.args("fetch_food_coupons")["restaurantId"], "r1")
        s = self.session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            await food.apply_coupon("tok", "addr-home", "SAVE50", "r1", None)  # supplied and equal: fine
        self.assertEqual(s.args("fetch_food_coupons")["restaurantId"], "r1")

    async def test_the_review_carries_the_restaurant_it_was_built_for_even_if_the_cart_does_not_name_it(self):
        cart = self.silent(food_cart())
        s = cart_session(update_food_cart=envelope(cart), get_food_cart=envelope(cart))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.build_cart("tok", "addr-home", selection(restaurant_id="1404575", restaurant_name="Punjabi Tadka"))
        self.assertEqual((out["review"]["restaurant"]["id"], out["review"]["restaurant"]["name"]), ("1404575", "Punjabi Tadka"))
        self.assertEqual(s.args("fetch_food_coupons")["restaurantId"], "1404575")

    async def test_a_cart_naming_a_different_restaurant_than_the_dish_is_still_refused_at_build(self):
        s = cart_session(update_food_cart=envelope(food_cart(restaurant_id="r7")), get_food_cart=envelope(food_cart(restaurant_id="r7")))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await food.build_cart("tok", "addr-home", selection())
        self.assertEqual(ctx.exception.code, "cart_mismatch")

    async def test_a_refusal_of_the_coupon_listing_or_apply_is_logged_with_swiggys_message(self):
        for tool in ("fetch_food_coupons", "apply_food_coupon"):
            s = self.session(**{tool: envelope(success=False, error=f"{tool}: nope")})
            with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs, self.assertRaises(SwiggyError):
                await food.apply_coupon("tok", "addr-home", "SAVE50")
            self.assertIn(f"[FOOD][diag] {tool} refused: code=tool_error message='{tool}: nope'", "\n".join(logs.output), tool)

    # ---- a coupon the cart already carries (real account: coupon_applied 'SWIGGYIT' before the attempt)

    def with_coupons(self, entries):
        return {**FOOD_COUPONS, "coupon_sections": [{"title": "For you", "type": "offers", "coupons": entries}]}

    ENTRIES = [{"id": "SWIGGYIT", "applicabilityStatus": "APPLIED", "title": "Swiggy IT", "subtitle": "Auto applied"},
               {"id": "SAVE50", "applicable": True, "applicabilityStatus": "APPLICABLE", "title": "₹50 off"}]

    def carrying(self, code="SWIGGYIT", discount=30):
        return cart_session(
            get_food_cart=[envelope(food_cart(to_pay=356, coupon=code, discount=discount))],
            fetch_food_coupons=envelope(self.with_coupons(self.ENTRIES)),
        )

    async def test_an_applied_status_means_applied_not_applicable(self):
        s = self.carrying()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.build_cart("tok", "addr-home", selection())
        by_code = {c["code"]: c for c in out["coupons"]["items"]}
        self.assertEqual((by_code["SWIGGYIT"]["applied"], by_code["SWIGGYIT"]["applicable"]), (True, False))
        self.assertEqual((by_code["SAVE50"]["applied"], by_code["SAVE50"]["applicable"]), (False, True))

    async def test_a_coupon_the_cart_already_carries_is_reported_in_the_review(self):
        s = self.carrying()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.build_cart("tok", "addr-home", selection())
        self.assertEqual(out["review"]["coupon"], {"code": "SWIGGYIT", "discount": 30.0})

    async def test_asking_for_an_already_applied_coupon_is_a_no_op_success_never_a_call_to_swiggy(self):
        for asked in ("SWIGGYIT", "swiggyit"):
            s = self.carrying()
            with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
                out = await food.apply_coupon("tok", "addr-home", asked, "r1", None)
            self.assertNotIn("apply_food_coupon", s.names(), asked)
            self.assertTrue(out["alreadyApplied"])
            self.assertEqual(out["coupon"], {"code": "SWIGGYIT", "title": "Swiggy IT", "savings": 30.0})
            self.assertEqual(out["review"]["total"], 356.0)  # the cart, unchanged
            self.assertEqual(out["review"]["coupon"], {"code": "SWIGGYIT", "discount": 30.0})

    async def test_a_second_coupon_is_refused_up_front_because_there_is_no_remove_tool(self):
        s = self.carrying()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await food.apply_coupon("tok", "addr-home", "SAVE50", "r1", None)
        self.assertEqual(ctx.exception.code, "coupon_already_applied")
        self.assertIn("SWIGGYIT is already applied", ctx.exception.message)
        self.assertIn("Edit dish", ctx.exception.message)
        self.assertNotIn("apply_food_coupon", s.names())

    async def test_a_suggested_coupon_with_no_discount_is_not_an_applied_one(self):
        # Swiggy: coupon_applied with coupon_discount 0 is only auto-suggested. Applying another coupon must still go through.
        before = food_cart(coupon="SWIGGYIT", discount=0)
        after = food_cart(to_pay=336, coupon="SAVE50", discount=50)
        s = cart_session(get_food_cart=[envelope(before), envelope(after)],
                         fetch_food_coupons=envelope(self.with_coupons([{"id": "SAVE50", "applicable": True, "title": "₹50 off"}])),
                         apply_food_coupon=envelope({"statusCode": 0}))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await food.apply_coupon("tok", "addr-home", "SAVE50", "r1", None)
        self.assertEqual(s.args("apply_food_coupon"), {"couponCode": "SAVE50", "addressId": "addr-home"})
        self.assertNotIn("alreadyApplied", out)
        self.assertEqual(out["review"]["total"], 336.0)

    async def test_the_coupon_that_was_sent_and_what_the_cart_already_carried_are_logged(self):
        s = self.session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            await food.apply_coupon("tok", "addr-home", "SAVE50")
        text = "\n".join(logs.output)
        self.assertIn("[FOOD][diag] apply_food_coupon requested: couponCode='SAVE50' listed=[('SAVE50', 'applicable'), ('BIG150', 'not_applicable')]", text)
        self.assertIn("offers_before={coupon_applied: None, coupon_discount: 0}", text)

    async def test_a_blocked_cart_is_never_offered_a_coupon(self):
        s = cart_session(get_food_cart=envelope(food_cart(items=[])))
        exc = await self.refuse(s)
        self.assertEqual(exc.code, "cart_blocked")
        self.assertNotIn("fetch_food_coupons", s.names())

    async def test_a_discount_of_zero_is_a_suggestion_not_an_applied_coupon(self):
        s = cart_session(get_food_cart=[envelope(food_cart()), envelope(food_cart(coupon="SAVE50", discount=0))])
        self.assertEqual((await self.refuse(s)).code, "coupon_not_reflected")

    async def test_a_discount_with_no_lower_total_is_not_counted(self):
        s = cart_session(get_food_cart=[envelope(food_cart()), envelope(food_cart(coupon="SAVE50", discount=50))])  # to_pay unchanged
        self.assertEqual((await self.refuse(s)).code, "coupon_not_reflected")

    async def test_a_different_coupon_reflected_on_the_cart_is_not_counted(self):
        s = cart_session(get_food_cart=[envelope(food_cart()), envelope(food_cart(to_pay=336, coupon="OTHER", discount=50))])
        self.assertEqual((await self.refuse(s)).code, "coupon_not_reflected")

    async def test_a_cart_whose_items_changed_meanwhile_is_refused(self):
        changed = food_cart(to_pay=336, coupon="SAVE50", discount=50, items=[{"menu_item_id": "m-other", "name": "Other", "quantity": 1, "subtotal": 1, "total": 1, "final_price": 1}])
        s = cart_session(get_food_cart=[envelope(food_cart()), envelope(changed)])
        self.assertEqual((await self.refuse(s)).code, "cart_changed")

    async def test_an_address_that_is_not_the_users_is_refused(self):
        s = self.session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await food.apply_coupon("tok", "somebody-elses", "SAVE50")
        self.assertEqual(ctx.exception.code, "address_not_found")
        self.assertNotIn("apply_food_coupon", s.names())

    async def test_the_coupon_diagnostic_holds_codes_and_amounts_only(self):
        s = self.session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            await food.apply_coupon("tok", "addr-home", "SAVE50")
        text = "\n".join(logs.output)
        self.assertIn("[FOOD][diag] coupon: code_listed=SAVE50 applied='SAVE50' discount=50.0 total_before=386.0 total_after=336.0", text)
        self.assertIn("payment options (coupon-before)", text)
        self.assertIn("payment options (coupon-after)", text)
        for private in ("9876543210", "12 MG Road", "Bengaluru"):
            self.assertNotIn(private, text)

    async def test_a_discounted_cart_is_ordered_at_the_discounted_total_only(self):
        s = checkout_session(get_food_cart=envelope(food_cart(to_pay=336, coupon="SAVE50", discount=50)))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place(total=336.0)
        self.assertEqual(out["status"], "placed")
        food._attempts.clear()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await place(total=386.0, key="idem-key-0002")  # the pre-discount total the user no longer sees
        self.assertEqual(ctx.exception.code, "cart_changed")


class RefusalMessageTests(FoodCase):
    """`Swiggy rejected the request.` is OUR fallback for a failure with no readable message. Read every documented place
    a message can live first, and keep the raw body in the log when there is none."""

    @staticmethod
    def raw(body: dict):
        """A tool result whose text is exactly `body` (envelope() only builds the standard shapes)."""
        return SimpleNamespace(structuredContent=None, isError=False, content=[SimpleNamespace(text=json.dumps(body))])

    async def refuse(self, payload):
        payload = self.raw(payload) if isinstance(payload, dict) else payload
        s = cart_session(apply_food_coupon=payload)
        with using(s), self.assertLogs("uvicorn.error", level="INFO") as logs:
            logging.getLogger("uvicorn.error").info("-")  # assertLogs needs at least one record, even when nothing is logged
            async with food._session("tok") as session:
                with self.assertRaises(SwiggyError) as ctx:
                    await food._call(session, "apply_food_coupon", couponCode="X", addressId="a")
        return ctx.exception, "\n".join(logs.output)

    async def test_the_documented_error_envelope_is_read_as_before(self):
        exc, _ = await self.refuse(envelope(success=False, error="Coupon expired"))
        self.assertEqual(exc.message, "Coupon expired")

    async def test_a_message_in_data_status_message_is_found(self):
        exc, text = await self.refuse({"success": False, "data": {"statusCode": 400, "statusMessage": "Coupon already applied"}})
        self.assertEqual((exc.code, exc.message, exc.tool), ("tool_error", "Coupon already applied", "apply_food_coupon"))
        self.assertNotIn("no readable message", text)

    async def test_the_other_places_a_message_can_live(self):
        for payload, expected in (
            ({"success": False, "message": "Top-level message"}, "Top-level message"),
            ({"success": False, "error": {"description": "In description"}}, "In description"),
            ({"success": False, "data": {"message": "In data.message"}}, "In data.message"),
            ({"success": False, "error": {"message": "  "}, "message": "Falls through blanks"}, "Falls through blanks"),
        ):
            exc, _ = await self.refuse(payload)
            self.assertEqual(exc.message, expected, payload)

    async def test_with_no_message_anywhere_the_raw_body_is_logged_and_the_browser_gets_only_the_generic_sentence(self):
        exc, text = await self.refuse({"success": False, "error": {"code": "COUPON_NOT_APPLICABLE", "details": {"reason": 7}}})
        self.assertEqual(exc.message, "Swiggy rejected the request.")
        self.assertIn("[SWIGGY][diag] apply_food_coupon refused with no readable message: payload=", text)
        self.assertIn("COUPON_NOT_APPLICABLE", text)  # the code Swiggy sent is now visible

    async def test_an_auth_failure_is_still_an_auth_failure(self):
        exc, _ = await self.refuse(envelope(success=False, error="401 Unauthorized"))
        self.assertEqual(exc.code, "auth_required")

    async def test_domain_codes_are_still_mapped(self):
        exc, _ = await self.refuse(envelope(success=False, error="ITEM_OUT_OF_STOCK: sold out"))
        self.assertEqual(exc.code, "out_of_stock")


class UpiCheckoutTests(FoodCase):
    async def place_upi(self, payment, pending=None, **over):
        s = checkout_session(place_food_order=envelope(pending or PENDING), **over)
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            out = await place(payment=payment)
        return out, s, "\n".join(logs.output)

    async def test_an_upi_app_is_ordered_with_its_id_echoed_exactly(self):
        out, s, _ = await self.place_upi("upi_intent:gpay://upi/")
        self.assertEqual(s.args("place_food_order"), {"addressId": "addr-home", "paymentMethod": "UPI", "intentApp": "gpay://upi/"})
        self.assertEqual(out["status"], "pending_payment")

    async def test_the_qr_option_asks_for_a_qr(self):
        _, s, _ = await self.place_upi("upi_qr")
        self.assertEqual(s.args("place_food_order"), {"addressId": "addr-home", "paymentMethod": "UPI", "generateUPIQR": True})

    async def test_a_pending_payment_is_not_an_order_and_carries_what_confirming_needs(self):
        out, s, text = await self.place_upi("upi_qr")
        self.assertEqual((out["status"], out["orderIds"], out["verified"], out["total"]), ("pending_payment", ["F-1001"], False, 386))
        self.assertEqual(out["payment"], {
            "orderId": "F-1001", "paasId": "paas-77", "bridgeUrl": "https://pay.example/bridge/abc", "pollIntervalMs": 3000, "maxPollMs": 120000,
            "addressId": "addr-home", "cartId": "cart-1", "lat": 12.97, "lng": 77.59})
        self.assertEqual(s.names().count("get_food_orders"), 1)  # only the "before" read: nothing is placed yet, so no "after" verification
        self.assertIn("[FOOD][diag] place_food_order pending: keys=", text)
        self.assertIn("has_lat_lng=True", text)
        for private in ("9876543210", "12 MG Road", "pay.example"):
            self.assertNotIn(private, text)

    async def test_polling_hints_are_clamped(self):
        out, _, _ = await self.place_upi("upi_qr", pending={**PENDING, "pollingIntervalInMs": 100, "maxTimeToPollForInMs": 10**9})
        self.assertEqual((out["payment"]["pollIntervalMs"], out["payment"]["maxPollMs"]), (1000, 300_000))

    async def test_missing_coordinates_are_passed_on_as_missing_never_invented(self):
        out, _, _ = await self.place_upi("upi_qr", pending={k: v for k, v in PENDING.items() if k not in ("lat", "lng", "cartId")})
        self.assertEqual((out["payment"]["lat"], out["payment"]["lng"], out["payment"]["cartId"]), (None, None, None))

    async def test_a_replayed_key_returns_the_same_pending_payment_and_never_orders_twice(self):
        s = checkout_session(place_food_order=envelope(PENDING))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            first = await place(payment="upi_qr")
            second = await place(payment="upi_qr")
        self.assertEqual(first, second)
        self.assertEqual(s.names().count("place_food_order"), 1)

    async def test_the_lock_is_released_while_the_user_pays(self):
        await self.place_upi("upi_qr")
        self.assertNotIn(food._account("tok"), food._inflight)

    async def test_a_dropped_connection_placing_a_upi_order_is_unknown_not_a_retry(self):
        s = checkout_session(place_food_order=ConnectionError("reset"), get_food_orders=[envelope(NONE_ACTIVE), envelope(NONE_ACTIVE)])
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place(payment="upi_qr")
        self.assertEqual(out["status"], "unknown")
        self.assertEqual(s.names().count("place_food_order"), 1)


class PaymentStatusTests(FoodCase):
    ARGS = dict(order_id="F-1001", paas_id="paas-77", address_id="addr-home", cart_id="cart-1", lat=12.97, lng=77.59)

    async def poll(self, status, confirm=None, final=False, orders=None, **args):
        s = FakeSession({"check_payment_status": envelope(status), "confirm_order": envelope(confirm or {"orderId": "F-1001", "result": "success"}),
                         "get_food_orders": envelope(orders or ACTIVE)})
        with using(s):
            out = await food.payment_status("tok", **{**self.ARGS, **args}, final=final)
        return out, s

    async def test_a_pending_payment_keeps_waiting_and_confirms_nothing(self):
        out, s = await self.poll({"paasId": "paas-77", "status": "pending", "terminal": False})
        self.assertEqual(out["status"], "pending_payment")
        self.assertEqual(s.args("check_payment_status"), {"paasId": "paas-77", "orderId": "F-1001", "addressId": "addr-home", "cartId": "cart-1", "lat": 12.97, "lng": 77.59})
        self.assertNotIn("confirm_order", s.names())

    async def test_terminal_success_confirms_with_the_echoed_food_context_and_never_paasid(self):
        out, s = await self.poll({"paasId": "paas-77", "status": "success", "terminal": True, "isTerminalSuccess": True, "confirmed": False})
        self.assertEqual(s.args("confirm_order"), {"orderId": "F-1001", "addressId": "addr-home", "cartId": "cart-1", "lat": 12.97, "lng": 77.59})
        self.assertNotIn("paasId", s.args("confirm_order"))
        self.assertEqual((out["status"], out["orderIds"], out["verified"]), ("placed", ["F-1001"], True))  # cross-checked with get_food_orders

    async def test_an_already_confirmed_payment_is_not_confirmed_again(self):
        out, s = await self.poll({"paasId": "paas-77", "status": "success", "terminal": True, "isTerminalSuccess": True, "confirmed": True})
        self.assertEqual(out["status"], "placed")
        self.assertNotIn("confirm_order", s.names())

    async def test_a_placed_order_swiggy_does_not_list_is_unverified(self):
        out, _ = await self.poll({"paasId": "p", "status": "success", "terminal": True, "isTerminalSuccess": True, "confirmed": True}, orders=NONE_ACTIVE)
        self.assertEqual((out["status"], out["verified"]), ("placed", False))

    async def test_a_failed_or_cancelled_payment_never_confirms(self):
        for status, expected in (({"status": "failed", "isTerminalFailure": True}, "didn't go through"), ({"status": "cancelled", "terminal": True}, "cancelled"),
                                 ({"status": "cart_changed", "terminal": True}, "Prices or stock changed"), ({"status": "refund-initiated", "terminal": True}, "refund")):
            out, s = await self.poll(status)
            self.assertEqual(out["status"], "failed", status)
            self.assertIn(expected, out["message"], status)
            self.assertEqual(out["orderIds"], ["F-1001"], status)  # a failed payment still names its order (a report needs it)
            self.assertNotIn("confirm_order", s.names(), status)

    async def test_confirm_reporting_pending_keeps_waiting(self):
        out, _ = await self.poll({"status": "success", "isTerminalSuccess": True}, confirm={"orderId": "F-1001", "result": "pending"})
        self.assertEqual((out["status"], out["message"]), ("pending_payment", "Confirming your payment…"))

    async def test_confirm_reporting_failure_is_a_failure(self):
        out, _ = await self.poll({"status": "success", "isTerminalSuccess": True}, confirm={"orderId": "F-1001", "result": "failed"})
        self.assertEqual((out["status"], out["orderIds"]), ("failed", ["F-1001"]))

    async def test_at_the_deadline_it_asks_swiggy_to_reconcile_once_then_gives_up_as_unknown(self):
        out, s = await self.poll({"status": "pending", "terminal": False}, confirm={"orderId": "F-1001", "result": "pending"}, final=True)
        self.assertEqual(s.names().count("confirm_order"), 1)
        self.assertEqual(out["status"], "unknown")
        self.assertIn("Check the Swiggy app", out["message"])

    async def test_a_late_payment_found_at_the_deadline_is_placed(self):
        out, _ = await self.poll({"status": "pending", "terminal": False}, final=True)
        self.assertEqual(out["status"], "placed")

    async def test_coordinates_that_were_never_given_are_not_sent(self):
        _, s = await self.poll({"status": "pending"}, cart_id=None, lat=None, lng=None)
        self.assertEqual(s.args("check_payment_status"), {"paasId": "paas-77", "orderId": "F-1001", "addressId": "addr-home"})

    async def test_auth_expiry_propagates(self):
        s = FakeSession({"check_payment_status": envelope(success=False, error="401 Unauthorized")})
        with using(s), self.assertRaises(SwiggyError) as ctx:
            await food.payment_status("tok", **self.ARGS)
        self.assertEqual(ctx.exception.code, "auth_required")


class PlacedTotalTests(FoodCase):
    async def test_a_cash_order_placed_at_another_total_is_flagged(self):
        s = checkout_session(place_food_order=envelope({**PLACED, "totalAmount": 436}))
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            out = await place()
        self.assertEqual(out["status"], "placed")
        self.assertIn("₹436", out["notice"])
        self.assertIn("₹386", out["notice"])
        self.assertIn("placed total differs", "\n".join(logs.output))

    async def test_a_matching_total_has_no_notice(self):
        with using(checkout_session()), self.assertLogs("uvicorn.error", level="WARNING"):
            out = await place()
        self.assertNotIn("notice", out)


# ---------------------------------------------------------------------------- routes


class FoodRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(a.app)

    def post(self, path, body, headers=None):
        return self.client.post(f"/api/food/{path}", json=body, headers=headers or {})

    def test_every_route_refuses_while_the_flow_is_off_even_without_auth(self):
        for path, body in (("search", {"dish": "x"}), ("cart", {"address_id": "a", "selection": selection()}),
                           ("checkout", {"address_id": "a", "expected_total": 100, "payment_key": "cod", "idempotency_key": "idem-key-0001"})):
            with patch.object(features, "FOOD_ORDERING_ENABLED", False), patch.object(food, "search_dish", AsyncMock()) as fn:
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

    def test_coupon_and_payment_status_routes_pass_their_arguments_through(self):
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food, "apply_coupon", AsyncMock(return_value={"review": {}, "coupon": {}, "coupons": {}})) as c, \
             patch.object(food, "payment_status", AsyncMock(return_value={"status": "pending_payment"})) as p:
            r1 = self.post("coupon", {"address_id": "addr-home", "coupon_code": "SAVE50"}, signed_bearer())
            r2 = self.post("payment-status", {"order_id": "F-1", "paas_id": "pp", "address_id": "addr-home", "cart_id": "cart-1", "lat": 12.9, "lng": 77.5, "final": True}, signed_bearer())
        self.assertTrue(r1.json()["ok"] and r2.json() == {"ok": True, "order": {"status": "pending_payment"}})
        c.assert_awaited_once_with("swiggy-tok", "addr-home", "SAVE50", None, None)
        p.assert_awaited_once_with("swiggy-tok", "F-1", "pp", "addr-home", "cart-1", 12.9, 77.5, True)

    def test_the_coupon_route_forwards_the_restaurant_the_review_carried(self):
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food, "apply_coupon", AsyncMock(return_value={"review": {}, "coupon": {}, "coupons": {}})) as c:
            r = self.post("coupon", {"address_id": "addr-home", "coupon_code": "SAVE50", "restaurant_id": "1404575", "restaurant_name": " Punjabi Tadka "}, signed_bearer())
        self.assertTrue(r.json()["ok"])
        c.assert_awaited_once_with("swiggy-tok", "addr-home", "SAVE50", "1404575", "Punjabi Tadka")
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food, "apply_coupon", AsyncMock()) as c:
            self.assertEqual(self.post("coupon", {"address_id": "a", "coupon_code": "X", "restaurant_id": ""}, signed_bearer()).status_code, 422)
            self.assertEqual(self.post("coupon", {"address_id": "a", "coupon_code": "X", "restaurant_name": "x" * 121}, signed_bearer()).status_code, 422)
        c.assert_not_awaited()

    def test_the_new_routes_refuse_while_the_flow_is_off_even_without_auth(self):
        for path, body in (("coupon", {"address_id": "a", "coupon_code": "X"}), ("payment-status", {"order_id": "o", "paas_id": "p", "address_id": "a"})):
            with patch.object(features, "FOOD_ORDERING_ENABLED", False):
                r = self.post(path, body)
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "food_disabled"), path)

    def test_bad_payment_status_input_is_rejected(self):
        base = {"order_id": "o", "paas_id": "p", "address_id": "a"}
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food, "payment_status", AsyncMock()) as p:
            for extra in ({"lat": 91}, {"lng": -181}, {"cart_id": ""}, {"order_id": ""}):
                self.assertEqual(self.post("payment-status", {**base, **extra}, signed_bearer()).status_code, 422, extra)
        p.assert_not_awaited()

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
