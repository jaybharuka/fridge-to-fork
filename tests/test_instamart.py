"""
Staged Instamart flow (fridge_to_fork/instamart.py + instamart_routes.py).

Fixtures mirror the shapes in Swiggy's reference docs
(https://mcp.swiggy.com/builders/docs/reference/instamart/): `{success, data}` /
`{success:false, error:{message}}` envelopes, camelCase params, search results as
data.products[].variations[].spinId, InstamartCart for get_cart. The fake session
records every tool call so the tests can assert the exact argument names sent.

Run: python -m unittest tests.test_instamart
"""

import asyncio
import inspect
import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

import app as a
from fridge_to_fork import instamart
from fridge_to_fork.instamart import InstamartError
from fridge_to_fork.models import Decision, MealPlan, MealSuggestion
from fridge_to_fork.swiggy_agent import run_swiggy_agent

# --------------------------------------------------------------------------- fixtures


def envelope(data=None, *, success=True, message=None, error=None) -> SimpleNamespace:
    body = {"success": success}
    if data is not None:
        body["data"] = data
    if error is not None:
        body["error"] = {"message": error}
    if message:
        body["message"] = message
    return SimpleNamespace(
        structuredContent=None, isError=False, content=[SimpleNamespace(text=json.dumps(body))]
    )


def transport_error(text: str) -> SimpleNamespace:
    return SimpleNamespace(structuredContent=None, isError=True, content=[SimpleNamespace(text=text)])


ADDRESSES = {
    "addresses": [
        {"id": "addr-work", "addressLine": "Tower B, Whitefield", "phoneNumber": "9000000001", "addressCategory": "Work"},
        {"id": "addr-home", "addressLine": "12 MG Road, Bengaluru", "phoneNumber": "9876543210", "addressTag": "Home"},
    ],
    "pagination": {"page": 1, "pageSize": 10, "total": 2, "totalPages": 1, "hasMore": False},
}

TOMATO_SEARCH = {
    "nextOffset": "1",
    "products": [
        {
            "displayName": "Fresh Tomato (Hybrid)",
            "brand": "Fresh",
            "inStock": True,
            "isAvail": True,
            "productId": "p-tomato",
            "parentProductId": "pp-tomato",
            "variations": [
                {
                    "spinId": "spin-t500",
                    "skuId": "sku-t500",
                    "quantityDescription": "500 g",
                    "displayName": "Tomato Hybrid 500 g",
                    "price": {"mrp": 40, "offerPrice": 32},
                    "isInStockAndAvailable": True,
                    "imageUrl": "https://img.example/t500.png",
                    "maxQuantity": 5,
                },
                {
                    "spinId": "spin-t1k",
                    "skuId": "sku-t1k",
                    "quantityDescription": "1 kg",
                    "displayName": "Tomato Hybrid 1 kg",
                    "price": {"mrp": 80, "offerPrice": 60},
                    "isInStockAndAvailable": False,
                },
            ],
        },
        {
            "displayName": "Tomato Puree",
            "brand": "Kissan",
            "inStock": False,
            "isAvail": True,
            "productId": "p-puree",
            "variations": [
                {"spinId": "spin-puree", "skuId": "sku-puree", "quantityDescription": "200 g", "price": {"mrp": 60, "offerPrice": 55}, "isInStockAndAvailable": True}
            ],
        },
    ],
}


def cart(*, total="₹136", item_total="₹120", address_id="addr-home", **overrides) -> dict:
    data = {
        "selectedAddress": "12 MG Road, Bengaluru",
        "selectedAddressDetails": {"id": address_id, "address": "12 MG Road", "area": "Indiranagar", "name": "Home", "mobile": "9876543210"},
        "cartTotalAmount": item_total,
        "items": [
            {"spinId": "spin-t500", "skuId": "sku-t500", "productId": "p-tomato", "itemName": "Tomato Hybrid", "itemVariant": "500 g",
             "quantity": 2, "isInStockAndAvailable": True, "mrp": 40, "discountedFinalPrice": 32, "imageUrl": "https://img.example/t500.png"},
        ],
        "billBreakdown": {
            "lineItems": [{"label": "Item total", "value": item_total}, {"label": "Delivery fee", "value": "₹16"}],
            "toPay": {"label": "To pay", "value": total},
        },
        "availablePaymentMethods": ["Cash", "UPI"],
    }
    return {**data, **overrides}


GPAY = {"id": "gpay://upi/", "displayName": "Google Pay", "kind": "intent", "enabled": True}
PHONEPE = {"id": "phonepe://upi/", "displayName": "PhonePe", "kind": "intent", "enabled": False}
QR = {"id": "upi-qr", "displayName": "Scan QR", "kind": "qr", "enabled": True}

# get_payment_options `data` (PaymentOptionsView): cod {available,id,displayName}, allMethods[], platforms.*.methods[]
PAYMENT_VIEW = {
    "platforms": {
        "mobile": {"groupName": "UPI apps", "methods": [GPAY, PHONEPE]},
        "desktop": {"groupName": "Scan QR", "methods": [QR]},
    },
    "cod": {"available": True, "id": "Cash", "displayName": "Cash on delivery"},
    "allMethods": [GPAY, PHONEPE, QR],
    "paymentAmount": "₹136",
    "addressId": "addr-home",
    "placeOrderToolName": "checkout",
}

# list_coupons `data`
COUPONS = {
    "availableCoupons": [
        {"couponCode": "SAVE20", "title": "₹20 off", "description": "On orders above ₹99", "isApplicable": True,
         "applicabilityStatus": "APPLICABLE", "tnc": {"title": "T&C", "bulletTexts": ["Valid once per user"]}, "offerId": "o-1"},
        {"couponCode": "BIG100", "title": "₹100 off", "isApplicable": False,
         "applicabilityStatus": "MIN_CART_NOT_MET", "applicabilityMessage": "Add ₹200 more to use this"},
    ]
}


def discounted_cart(**overrides) -> dict:
    """The cart after SAVE20: same items, toPay ₹116, a coupon line in the bill."""
    c = cart(total="₹116", **overrides)
    c["billBreakdown"]["lineItems"] = [*c["billBreakdown"]["lineItems"], {"label": "Coupon SAVE20", "value": "-₹20"}]
    return c


DEFAULT_RESPONSES = {"get_payment_options": envelope(PAYMENT_VIEW), "list_coupons": envelope(COUPONS)}


class FakeSession:
    """Replays Swiggy-shaped results by tool name and records (name, arguments)."""

    def __init__(self, responses: dict):
        merged = {**DEFAULT_RESPONSES, **responses}
        self.responses = {k: (list(v) if isinstance(v, list) else v) for k, v in merged.items()}
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        response = self.responses[name]
        if isinstance(response, list):
            response = response.pop(0)
        if callable(response):
            response = response(arguments)
        if inspect.isawaitable(response):
            response = await response
        if isinstance(response, Exception):
            raise response
        return response

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def args(self, name: str) -> dict:
        return next(args for n, args in self.calls if n == name)


def using(session: FakeSession):
    @asynccontextmanager
    async def fake(_token):
        yield session

    return patch.object(instamart, "_session", fake)


class InstamartCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        instamart._attempts.clear()
        instamart._inflight.clear()


# --------------------------------------------------------------------------- envelope


class EnvelopeTests(InstamartCase):
    async def test_success_false_at_http_200_raises_with_swiggy_message(self):
        s = FakeSession({"get_cart": envelope(success=False, error="MIN_ORDER_NOT_MET: add ₹19 more")})
        with self.assertRaises(InstamartError) as ctx:
            await instamart._call(s, "get_cart")
        self.assertEqual(ctx.exception.code, "min_order_not_met")
        self.assertIn("₹19", ctx.exception.message)

    async def test_transport_level_error_raises(self):
        s = FakeSession({"get_cart": transport_error("boom")})
        with self.assertRaises(InstamartError) as ctx:
            await instamart._call(s, "get_cart")
        self.assertEqual(ctx.exception.code, "tool_error")

    async def test_auth_failures_map_to_auth_required(self):
        for text in ("HTTP 401 Unauthorized", "TOKEN_EXPIRED: token expired", "JSON-RPC -32001"):
            s = FakeSession({"get_cart": envelope(success=False, error=text)})
            with self.assertRaises(InstamartError) as ctx:
                await instamart._call(s, "get_cart")
            self.assertEqual((ctx.exception.code, ctx.exception.status), ("auth_required", 401), text)

    async def test_structured_content_wrapped_in_result_is_unwrapped(self):
        wrapped = SimpleNamespace(structuredContent={"result": {"success": True, "data": {"x": 1}}}, isError=False, content=[])
        self.assertEqual(await instamart._call(FakeSession({"t": wrapped}), "t"), {"x": 1})


# --------------------------------------------------------------------------- stage 1


class SearchTests(InstamartCase):
    def session(self, **extra) -> FakeSession:
        return FakeSession({"get_addresses": envelope(ADDRESSES), "search_products": envelope(TOMATO_SEARCH), **extra})

    async def test_search_uses_camelcase_address_id_and_prefers_home(self):
        s = self.session()
        with using(s):
            out = await instamart.search_ingredients("tok", ["tomato"])
        self.assertEqual(s.args("search_products"), {"addressId": "addr-home", "query": "tomato"})
        self.assertEqual(s.args("get_addresses"), {"page": 1, "pageSize": 10})
        self.assertEqual(out["address"], {"id": "addr-home", "label": "Home", "addressLine": "12 MG Road, Bengaluru", "category": None})
        self.assertNotIn("phone", json.dumps(out).lower())

    async def test_options_are_sku_level_variations_in_stock_first(self):
        with using(self.session()):
            out = await instamart.search_ingredients("tok", ["tomato"])
        options = out["results"][0]["options"]
        self.assertEqual([o["spinId"] for o in options], ["spin-t500", "spin-t1k", "spin-puree"])
        first = options[0]
        self.assertEqual((first["skuId"], first["price"], first["mrp"], first["size"], first["brand"]), ("sku-t500", 32.0, 40.0, "500 g", "Fresh"))
        self.assertEqual(first["imageUrl"], "https://img.example/t500.png")
        self.assertEqual([o["available"] for o in options], [True, False, False])  # variation OOS, product OOS

    async def test_no_match_and_all_out_of_stock_get_notes(self):
        oos = {"products": [{"displayName": "X", "inStock": False, "variations": [{"spinId": "s", "skuId": "k", "price": {}, "isInStockAndAvailable": False}]}]}
        s = self.session(search_products=[envelope({"products": []}), envelope(oos)])
        with using(s):
            out = await instamart.search_ingredients("tok", ["unobtainium", "saffron"])
        self.assertEqual([r["note"] for r in out["results"]], ["No match on Instamart", "Out of stock nearby"])

    async def test_no_saved_address_is_a_clear_error(self):
        s = FakeSession({"get_addresses": envelope({"addresses": []})})
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.search_ingredients("tok", ["tomato"])
        self.assertEqual(ctx.exception.code, "no_address")
        self.assertNotIn("search_products", s.names())

    async def test_one_failed_item_does_not_sink_the_rest(self):
        s = self.session(search_products=[envelope(TOMATO_SEARCH), envelope(success=False, error="Invalid query")])
        with using(s):
            out = await instamart.search_ingredients("tok", ["tomato", "??"])
        self.assertTrue(out["results"][0]["options"])
        self.assertEqual(out["results"][1], {"ingredient": "??", "options": [], "note": "Invalid query"})

    async def test_auth_failure_mid_search_propagates(self):
        s = self.session(search_products=envelope(success=False, error="401 Unauthorized"))
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.search_ingredients("tok", ["tomato"])
        self.assertEqual(ctx.exception.code, "auth_required")

    async def test_search_never_touches_the_cart(self):
        s = self.session()
        with using(s):
            await instamart.search_ingredients("tok", ["tomato"])
        self.assertFalse({"update_cart", "clear_cart", "checkout"} & set(s.names()))


# --------------------------------------------------------------------------- stage 2+3


SELECTION = [{"spin_id": "spin-t500", "sku_id": "sku-t500", "quantity": 2}]


class CartTests(InstamartCase):
    async def test_cart_is_cleared_then_updated_with_sku_ids_then_reviewed(self):
        s = FakeSession({"clear_cart": envelope({"verified": True}), "update_cart": envelope(cart()), "get_cart": envelope(cart())})
        with using(s):
            out = await instamart.build_cart("tok", "addr-home", SELECTION)
        self.assertEqual(s.names(), ["clear_cart", "update_cart", "get_cart", "get_payment_options", "list_coupons"])
        self.assertEqual(
            s.args("update_cart"),
            {"selectedAddressId": "addr-home", "items": [{"spinId": "spin-t500", "skuId": "sku-t500", "quantity": 2}]},
        )
        review = out["review"]
        self.assertEqual((review["total"], review["totalLabel"], review["canCheckout"], review["blockers"]), ("₹136", "To pay", True, []))
        self.assertEqual(review["items"][0]["name"], "Tomato Hybrid")
        self.assertEqual(review["lineItems"][1], {"label": "Delivery fee", "value": "₹16"})
        self.assertEqual(review["address"]["id"], "addr-home")

    async def test_swiggy_adjustments_are_surfaced(self):
        updated = cart(
            removedOutOfStockItems=[{"itemName": "Tomato Puree"}],
            reducedQuantityItems=[{"spinId": "x", "itemName": "Tomato Hybrid", "requestedQuantity": 9, "cappedQuantity": 5}],
        )
        s = FakeSession({"clear_cart": envelope({"verified": True}), "update_cart": envelope(updated), "get_cart": envelope(cart())})
        with using(s):
            out = await instamart.build_cart("tok", "addr-home", SELECTION)
        self.assertEqual(len(out["adjustments"]), 2)
        self.assertIn("quantity reduced from 9 to 5", out["adjustments"][1])

    async def test_blockers_minimum_unserviceable_out_of_stock_and_no_payment_method(self):
        bad = cart(item_total="₹60", unserviceableItems=[{"itemName": "Tomato Hybrid"}])
        bad["items"][0]["isInStockAndAvailable"] = False
        s = FakeSession({
            "clear_cart": envelope({"verified": True}), "update_cart": envelope(cart()), "get_cart": envelope(bad),
            "get_payment_options": envelope({"allMethods": []}),
        })
        with using(s):
            review = (await instamart.build_cart("tok", "addr-home", SELECTION))["review"]
        self.assertFalse(review["canCheckout"])
        joined = " ".join(review["blockers"])
        for expected in ("minimum order is ₹99", "Not deliverable", "out of stock", "No payment method"):
            self.assertIn(expected, joined)

    async def test_empty_cart_and_cart_warning(self):
        s = FakeSession({"clear_cart": envelope({"verified": True}), "update_cart": envelope(cart()),
                         "get_cart": envelope(cart(items=[], cartAbsent=True, cartWarning={"statusCode": 3, "message": "Add ₹30 more for free delivery"}))})
        with using(s):
            review = (await instamart.build_cart("tok", "addr-home", SELECTION))["review"]
        self.assertFalse(review["canCheckout"])
        self.assertEqual(review["warning"], "Add ₹30 more for free delivery")

    async def test_cart_for_a_different_address_is_rejected(self):
        s = FakeSession({"clear_cart": envelope({"verified": True}), "update_cart": envelope(cart()), "get_cart": envelope(cart(address_id="addr-work"))})
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.build_cart("tok", "addr-home", SELECTION)
        self.assertEqual(ctx.exception.code, "address_mismatch")

    async def test_update_cart_domain_failure_is_reported_not_swallowed(self):
        s = FakeSession({"clear_cart": envelope({"verified": True}), "update_cart": envelope(success=False, error="ADDRESS_NOT_SERVICEABLE")})
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.build_cart("tok", "addr-home", SELECTION)
        self.assertEqual(ctx.exception.code, "unserviceable")
        self.assertNotIn("get_cart", s.names())


# --------------------------------------------------------------------------- stage 4


ORDER_PLACED = {"orderId": "IM-1001", "status": "PLACED", "paymentMethod": "COD", "cartTotal": "₹136", "addressId": "addr-home"}


def checkout_session(**overrides) -> FakeSession:
    responses = {
        "get_cart": envelope(cart()),
        "get_orders": [envelope({"orders": [], "hasMore": False}), envelope({"orders": [{"orderId": "IM-1001", "status": "PLACED"}], "hasMore": False})],
        "checkout": envelope(ORDER_PLACED),
    }
    return FakeSession({**responses, **overrides})


async def place(key="key-00000001", total="₹136", address="addr-home", payment="cod"):
    return await instamart.checkout("tok", address, total, key, payment)


class CheckoutTests(InstamartCase):
    async def test_happy_path_sends_the_listed_cod_id_and_address_and_verifies_against_get_orders(self):
        s = checkout_session()
        with using(s):
            out = await place()
        self.assertEqual(s.args("checkout"), {"addressId": "addr-home", "paymentMethod": "Cash"})  # cod.id echoed from get_payment_options
        self.assertEqual(s.args("get_orders"), {"orderType": "INSTAMART", "activeOnly": True, "count": 10})
        self.assertEqual((out["status"], out["orderIds"], out["verified"]), ("placed", ["IM-1001"], True))
        self.assertEqual(s.names().count("checkout"), 1)

    async def test_changed_total_blocks_checkout(self):
        s = checkout_session(get_cart=envelope(cart(total="₹151")))
        with using(s), self.assertRaises(InstamartError) as ctx:
            await place(total="₹136")
        self.assertEqual(ctx.exception.code, "cart_changed")
        self.assertNotIn("checkout", s.names())

    async def test_blocked_or_mismatched_cart_never_reaches_checkout(self):
        for label, response, address in (
            ("below minimum", envelope(cart(item_total="₹50")), "addr-home"),
            ("wrong address", envelope(cart()), "addr-work"),
        ):
            s = checkout_session(get_cart=response)
            with self.subTest(label), using(s), self.assertRaises(InstamartError):
                await place(key=f"key-{label[:4]}-0001", address=address)
            self.assertNotIn("checkout", s.names(), label)

    async def test_same_idempotency_key_replays_without_a_second_checkout(self):
        s = checkout_session()
        with using(s):
            first = await place()
            second = await place()
        self.assertEqual(first, second)
        self.assertEqual(s.names().count("checkout"), 1)

    async def test_concurrent_checkout_for_one_account_is_refused(self):
        gate = asyncio.Event()

        async def slow(_args):
            await gate.wait()
            return envelope(ORDER_PLACED)

        s = checkout_session(checkout=slow)
        with using(s):
            first = asyncio.create_task(place(key="key-first-0001"))
            await asyncio.sleep(0.05)
            with self.assertRaises(InstamartError) as ctx:
                await place(key="key-second-0001")
            gate.set()
            await first
        self.assertEqual(ctx.exception.code, "checkout_in_progress")
        self.assertEqual(s.names().count("checkout"), 1)

    async def test_swiggy_domain_failure_is_failed_not_retried(self):
        s = checkout_session(
            checkout=envelope(success=False, error="Payment method not available"),
            get_orders=[envelope({"orders": []}), envelope({"orders": []})],
        )
        with using(s):
            out = await place()
        self.assertEqual((out["status"], out["message"], out["orderIds"]), ("failed", "Payment method not available", []))
        self.assertEqual(s.names().count("checkout"), 1)

    async def test_transport_drop_but_order_exists_is_rescued_as_placed(self):
        s = checkout_session(checkout=ConnectionError("reset by peer"))
        with using(s):
            out = await place()
        self.assertEqual((out["status"], out["orderIds"], out["verified"]), ("placed", ["IM-1001"], True))

    async def test_transport_drop_with_no_order_is_unknown_never_failed(self):
        s = checkout_session(checkout=ConnectionError("reset by peer"), get_orders=[envelope({"orders": []}), envelope({"orders": []})])
        with using(s):
            out = await place()
        self.assertEqual(out["status"], "unknown")
        self.assertIn("Check the Swiggy app", out["message"])

    async def test_unknown_when_orders_cannot_be_checked(self):
        s = checkout_session(checkout=ConnectionError("reset"), get_orders=envelope(success=False, error="down"))
        with using(s):
            out = await place()
        self.assertEqual(out["status"], "unknown")

    async def test_claimed_success_without_order_id_is_not_placed(self):
        s = checkout_session(checkout=envelope({"status": "PLACED"}), get_orders=[envelope({"orders": []}), envelope({"orders": []})])
        with using(s):
            out = await place()
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["orderIds"], [])

    async def test_auth_expiry_during_checkout_propagates(self):
        s = checkout_session(checkout=envelope(success=False, error="TOKEN_EXPIRED"))
        with using(s), self.assertRaises(InstamartError) as ctx:
            await place()
        self.assertEqual(ctx.exception.code, "auth_required")

    async def test_multi_store_partial_success_is_flagged(self):
        partial = {"orders": [{"orderId": "IM-1"}, {"error": "x"}], "orderCount": 2, "successCount": 1, "failureCount": 1, "allSucceeded": False}
        s = checkout_session(checkout=envelope(partial), get_orders=[envelope({"orders": []}), envelope({"orders": [{"orderId": "IM-1"}]})])
        with using(s):
            out = await place()
        self.assertEqual((out["status"], out["orderIds"]), ("partial", ["IM-1"]))


# --------------------------------------------------------------------------- phase 1: payment options


def cart_session(**overrides) -> FakeSession:
    return FakeSession({"clear_cart": envelope({"verified": True}), "update_cart": envelope(cart()), "get_cart": envelope(cart()), **overrides})


class PaymentOptionTests(InstamartCase):
    async def build(self, s: FakeSession) -> dict:
        with using(s):
            return (await instamart.build_cart("tok", "addr-home", SELECTION))["review"]

    async def test_options_come_from_get_payment_options_and_skip_disabled_methods(self):
        s = cart_session()
        review = await self.build(s)
        options = review["payment"]["options"]
        self.assertEqual([o["key"] for o in options], ["cod", "upi_intent:gpay://upi/", "upi_qr"])  # PhonePe is enabled:false
        self.assertEqual((options[0]["methodId"], options[0]["label"]), ("Cash", "Cash on delivery"))
        self.assertEqual(options[1]["methodId"], "gpay://upi/")
        self.assertEqual(review["payment"]["amount"], "₹136")
        self.assertIn("get_payment_options", s.names())

    async def test_cod_is_not_offered_when_swiggy_says_it_is_unavailable(self):
        view = {**PAYMENT_VIEW, "cod": {"available": False, "id": "Cash", "displayName": "Cash"}}
        review = await self.build(cart_session(get_payment_options=envelope(view)))
        self.assertNotIn("cod", [o["key"] for o in review["payment"]["options"]])
        self.assertTrue(review["canCheckout"])  # UPI is still a way to pay

    async def test_falls_back_to_the_view_embedded_in_get_cart_when_the_tool_fails(self):
        s = cart_session(get_payment_options=envelope(success=False, error="not available"), get_cart=envelope(cart(paymentOptions=PAYMENT_VIEW)))
        review = await self.build(s)
        self.assertEqual(review["payment"]["options"][0]["key"], "cod")

    async def test_no_payment_options_at_all_blocks_checkout(self):
        review = await self.build(cart_session(get_payment_options=envelope({"allMethods": []})))
        self.assertEqual(review["payment"]["options"], [])
        self.assertFalse(review["canCheckout"])
        self.assertIn("No payment method", review["blockers"][0])


# --------------------------------------------------------------------------- phase 1: coupons


class CouponTests(InstamartCase):
    def apply_session(self, **overrides) -> FakeSession:
        return FakeSession({
            "get_cart": [envelope(cart()), envelope(discounted_cart())],
            "apply_coupon": envelope(discounted_cart()),
            **overrides,
        })

    async def test_real_coupons_are_listed_with_the_cart(self):
        s = cart_session()
        with using(s):
            out = await instamart.build_cart("tok", "addr-home", SELECTION)
        self.assertEqual(s.args("list_coupons"), {"addressId": "addr-home"})
        self.assertTrue(out["coupons"]["available"])
        save, big = out["coupons"]["items"]
        self.assertEqual((save["code"], save["title"], save["applicable"], save["terms"]), ("SAVE20", "₹20 off", True, ["Valid once per user"]))
        self.assertEqual((big["applicable"], big["message"]), (False, "Add ₹200 more to use this"))

    async def test_coupons_unavailable_never_break_the_cart(self):
        for failing in (envelope(success=False, error="unknown tool list_coupons"), McpError(ErrorData(code=-32601, message="Method not found"))):
            with self.subTest(str(type(failing).__name__)), using(cart_session(list_coupons=failing)):
                out = await instamart.build_cart("tok", "addr-home", SELECTION)
            self.assertEqual(out["coupons"], {"available": False, "items": []})
            self.assertTrue(out["review"]["canCheckout"])

    async def test_apply_relists_applies_the_listed_code_and_reflects_the_discount(self):
        s = self.apply_session()
        with using(s):
            out = await instamart.apply_coupon("tok", "addr-home", "save20")  # user-typed casing
        self.assertEqual(s.names()[:6], ["get_cart", "get_payment_options", "list_coupons", "apply_coupon", "get_cart", "get_payment_options"])
        self.assertEqual(s.args("apply_coupon"), {"couponCode": "SAVE20"})  # Swiggy's own code, exactly as listed
        self.assertEqual(out["review"]["total"], "₹116")
        self.assertEqual(out["coupon"], {"code": "SAVE20", "title": "₹20 off", "savings": 20.0})
        self.assertTrue(out["review"]["canCheckout"])

    async def test_a_coupon_that_stopped_being_applicable_is_not_applied(self):
        gone = {"availableCoupons": [{**COUPONS["availableCoupons"][0], "isApplicable": False, "applicabilityMessage": "Cart changed — coupon no longer valid"}]}
        s = self.apply_session(list_coupons=envelope(gone))
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.apply_coupon("tok", "addr-home", "SAVE20")
        self.assertEqual((ctx.exception.code, ctx.exception.message), ("coupon_not_applicable", "Cart changed — coupon no longer valid"))
        self.assertNotIn("apply_coupon", s.names())

    async def test_a_code_swiggy_no_longer_lists_is_refused(self):
        s = self.apply_session(list_coupons=envelope({"availableCoupons": []}))
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.apply_coupon("tok", "addr-home", "EXPIRED10")
        self.assertEqual(ctx.exception.code, "coupon_not_found")
        self.assertNotIn("apply_coupon", s.names())

    async def test_swiggy_rejecting_the_apply_surfaces_its_message(self):
        s = self.apply_session(apply_coupon=envelope(success=False, error="Coupon has expired"))
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.apply_coupon("tok", "addr-home", "SAVE20")
        self.assertEqual(ctx.exception.message, "Coupon has expired")

    async def test_accepted_but_total_unchanged_is_not_counted_as_applied(self):
        s = self.apply_session(get_cart=[envelope(cart()), envelope(cart())])
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.apply_coupon("tok", "addr-home", "SAVE20")
        self.assertEqual(ctx.exception.code, "coupon_not_reflected")

    async def test_a_cart_for_another_address_is_refused_before_anything_is_listed(self):
        s = self.apply_session(get_cart=[envelope(cart(address_id="addr-work"))])
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.apply_coupon("tok", "addr-home", "SAVE20")
        self.assertEqual(ctx.exception.code, "address_mismatch")
        self.assertNotIn("list_coupons", s.names())

    async def test_a_blocked_cart_does_not_get_a_coupon(self):
        s = self.apply_session(get_cart=[envelope(cart(item_total="₹40"))])
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.apply_coupon("tok", "addr-home", "SAVE20")
        self.assertEqual(ctx.exception.code, "cart_blocked")

    async def test_the_coupon_tool_missing_at_apply_time_is_an_error_not_a_silent_success(self):
        s = self.apply_session(list_coupons=McpError(ErrorData(code=-32601, message="Method not found")))
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.apply_coupon("tok", "addr-home", "SAVE20")
        self.assertEqual(ctx.exception.code, "tool_error")
        self.assertNotIn("apply_coupon", s.names())


# --------------------------------------------------------------------------- phase 1: checkout x payment x coupon


class CheckoutPaymentTests(InstamartCase):
    async def test_upi_qr_uses_generate_qr_and_returns_the_payment_page_without_calling_it_placed(self):
        pending = {"orderId": "IM-2002", "paasId": "paas-9", "status": "PENDING_PAYMENT", "bridgeUrl": "https://pay.swiggy.com/bridge/abc",
                   "upiIntentUrl": "upi://pay?x=1", "isQrFlow": True, "pollingIntervalInMs": 2000, "maxTimeToPollForInMs": 90000}
        s = checkout_session(checkout=envelope(pending))
        with using(s):
            out = await place(payment="upi_qr")
        self.assertEqual(s.args("checkout"), {"addressId": "addr-home", "paymentMethod": "UPI", "generateUPIQR": True})
        self.assertEqual(out["status"], "pending_payment")
        self.assertEqual(out["payment"], {"orderId": "IM-2002", "paasId": "paas-9", "bridgeUrl": "https://pay.swiggy.com/bridge/abc", "pollIntervalMs": 2000, "maxPollMs": 90000})
        self.assertEqual(s.names().count("get_orders"), 1)  # only the pre-checkout duplicate check; no premature "verified"

    async def test_upi_app_choice_echoes_the_intent_id_exactly(self):
        s = checkout_session(checkout=envelope({"orderId": "IM-3", "paasId": "p", "status": "PENDING_PAYMENT", "bridgeUrl": "https://pay.swiggy.com/b"}))
        with using(s):
            await place(payment="upi_intent:gpay://upi/")
        self.assertEqual(s.args("checkout"), {"addressId": "addr-home", "paymentMethod": "UPI", "intentApp": "gpay://upi/"})

    async def test_unknown_or_disabled_payment_choice_never_reaches_checkout(self):
        for key in ("bitcoin", "upi_intent:phonepe://upi/", ""):
            s = checkout_session()
            with self.subTest(key), using(s), self.assertRaises(InstamartError) as ctx:
                await place(key=f"key-{abs(hash(key)) % 10**8:08d}", payment=key)
            self.assertEqual(ctx.exception.code, "payment_unavailable")
            self.assertNotIn("checkout", s.names())

    async def test_a_method_that_disappeared_since_review_is_refused(self):
        view = {**PAYMENT_VIEW, "cod": {"available": False, "id": "Cash", "displayName": "Cash"}}
        s = checkout_session(get_payment_options=envelope(view))
        with using(s), self.assertRaises(InstamartError) as ctx:
            await place(payment="cod")
        self.assertEqual(ctx.exception.code, "payment_unavailable")
        self.assertNotIn("checkout", s.names())

    async def test_checkout_with_a_coupon_verifies_the_discounted_total(self):
        s = checkout_session(get_cart=envelope(discounted_cart()), checkout=envelope({**ORDER_PLACED, "cartTotal": 116}))
        with using(s):
            out = await place(total="₹116")
        self.assertEqual(out["status"], "placed")
        self.assertEqual(s.names().count("checkout"), 1)

    async def test_the_pre_coupon_total_is_refused_once_a_coupon_is_applied(self):
        s = checkout_session(get_cart=envelope(discounted_cart()))
        with using(s), self.assertRaises(InstamartError) as ctx:
            await place(total="₹136")  # stale: user never saw the discount
        self.assertEqual(ctx.exception.code, "cart_changed")
        self.assertNotIn("checkout", s.names())

    async def test_a_coupon_that_lapsed_between_review_and_checkout_is_refused(self):
        s = checkout_session(get_cart=envelope(cart()))  # Swiggy now bills ₹136 again
        with using(s), self.assertRaises(InstamartError) as ctx:
            await place(total="₹116")  # what the user confirmed, with the coupon
        self.assertEqual(ctx.exception.code, "cart_changed")
        self.assertNotIn("checkout", s.names())

    async def test_pending_payment_without_a_safe_payment_page_is_unknown_not_placed(self):
        for label, data in (
            ("http bridge", {"orderId": "IM-4", "paasId": "p", "status": "PENDING_PAYMENT", "bridgeUrl": "http://evil.example/x"}),
            ("javascript bridge", {"orderId": "IM-4", "paasId": "p", "status": "PENDING_PAYMENT", "bridgeUrl": "javascript:alert(1)"}),
            ("no paasId", {"orderId": "IM-4", "status": "PENDING_PAYMENT", "bridgeUrl": "https://pay.swiggy.com/b"}),
        ):
            s = checkout_session(checkout=envelope(data))
            with self.subTest(label), using(s):
                out = await place(key=f"key-{label[:4]}-0001", payment="upi_qr")
            self.assertEqual((out["status"], out["payment"]), ("unknown", None))
            self.assertIn("Check the Swiggy app", out["message"])

    async def test_a_replayed_pending_checkout_does_not_start_a_second_payment(self):
        pending = {"orderId": "IM-5", "paasId": "p", "status": "PENDING_PAYMENT", "bridgeUrl": "https://pay.swiggy.com/b"}
        s = checkout_session(checkout=envelope(pending))
        with using(s):
            first = await place(payment="upi_qr")
            second = await place(payment="upi_qr")
        self.assertEqual(first, second)
        self.assertEqual(s.names().count("checkout"), 1)


# --------------------------------------------------------------------------- phase 1: UPI payment polling


class PaymentStatusTests(InstamartCase):
    def session(self, status: dict, **overrides) -> FakeSession:
        return FakeSession({
            "check_payment_status": envelope({"paasId": "paas-9", **status}),
            "get_orders": envelope({"orders": [{"orderId": "IM-2002"}]}),
            **overrides,
        })

    async def poll(self, s: FakeSession, final=False) -> dict:
        with using(s):
            return await instamart.payment_status("tok", "IM-2002", "paas-9", final)

    async def test_pending_keeps_waiting_and_confirms_nothing(self):
        s = self.session({"status": "pending", "terminal": False})
        out = await self.poll(s)
        self.assertEqual(out["status"], "pending_payment")
        self.assertEqual(s.args("check_payment_status"), {"paasId": "paas-9", "orderId": "IM-2002"})
        self.assertNotIn("confirm_order", s.names())

    async def test_terminal_success_not_yet_confirmed_calls_confirm_order_with_order_and_paas_id(self):
        s = self.session({"status": "success", "terminal": True, "isTerminalSuccess": True, "confirmed": False},
                         confirm_order=envelope({"orderId": "IM-2002", "result": "success"}))
        out = await self.poll(s)
        self.assertEqual(s.args("confirm_order"), {"orderId": "IM-2002", "paasId": "paas-9"})
        self.assertEqual((out["status"], out["orderIds"], out["verified"]), ("placed", ["IM-2002"], True))

    async def test_already_confirmed_skips_confirm_order(self):
        s = self.session({"status": "success", "terminal": True, "isTerminalSuccess": True, "confirmed": True})
        out = await self.poll(s)
        self.assertNotIn("confirm_order", s.names())
        self.assertEqual(out["status"], "placed")

    async def test_failures_and_refunds_never_confirm(self):
        cases = {
            "failed": "didn't go through",
            "cancelled": "cancelled",
            "refund-initiated": "refund has started",
            "cart_changed": "Prices or stock changed",
        }
        for state, fragment in cases.items():
            s = self.session({"status": state, "terminal": True, "isTerminalFailure": state != "cart_changed"})
            with self.subTest(state):
                out = await self.poll(s)
                self.assertEqual(out["status"], "failed")
                self.assertIn(fragment, out["message"])
                self.assertNotIn("confirm_order", s.names())

    async def test_at_the_deadline_it_confirms_once_and_lets_swiggy_reconcile_a_late_payment(self):
        s = self.session({"status": "pending", "terminal": False}, confirm_order=envelope({"orderId": "IM-2002", "result": "success"}))
        out = await self.poll(s, final=True)
        self.assertEqual(s.names().count("confirm_order"), 1)
        self.assertEqual(out["status"], "placed")

    async def test_deadline_with_swiggy_still_pending_is_unknown_never_failed(self):
        s = self.session({"status": "pending", "terminal": False}, confirm_order=envelope({"orderId": "IM-2002", "result": "pending"}))
        out = await self.poll(s, final=True)
        self.assertEqual(out["status"], "unknown")
        self.assertIn("Check the Swiggy app", out["message"])

    async def test_confirm_reporting_failure_is_failed(self):
        s = self.session({"status": "success", "isTerminalSuccess": True, "confirmed": False}, confirm_order=envelope({"result": "failed"}))
        self.assertEqual((await self.poll(s))["status"], "failed")


# --------------------------------------------------------------------------- routes


def signed_bearer() -> dict:
    from datetime import datetime, timedelta, timezone

    exp = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    return {"Authorization": f"Bearer {a._issue_bearer('swiggy-tok', exp)}"}


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(a.app)

    def test_every_stage_requires_auth_with_the_error_envelope(self):
        bodies = {
            "search": {"items": ["tomato"]},
            "cart": {"address_id": "a", "selections": [{"spin_id": "s", "sku_id": "k", "quantity": 1}]},
            "coupon": {"address_id": "a", "coupon_code": "SAVE20"},
            "checkout": {"address_id": "a", "expected_total": "₹1", "idempotency_key": "key-00000001", "payment_key": "cod"},
            "payment-status": {"order_id": "o", "paas_id": "p"},
        }
        for stage, body in bodies.items():
            r = self.client.post(f"/api/instamart/{stage}", json=body)
            self.assertEqual(r.status_code, 401, stage)
            self.assertEqual(r.json(), {"ok": False, "error": {"code": "auth_required", "message": "Connect your Swiggy account to continue."}})

    def test_search_route_dedupes_and_wraps_result(self):
        with patch.object(instamart, "search_ingredients", AsyncMock(return_value={"address": {}, "results": []})) as fn:
            r = self.client.post("/api/instamart/search", json={"items": ["Tomato", "tomato ", "Onion"]}, headers=signed_bearer())
        self.assertEqual(r.json(), {"ok": True, "address": {}, "results": []})
        self.assertEqual(fn.await_args.args, ("swiggy-tok", ["Tomato", "Onion"], None))

    def test_instamart_errors_map_to_status_and_envelope(self):
        cases = ((InstamartError("upstream_unavailable", "down", 502), 502), (InstamartError("cart_changed", "changed"), 200))
        for exc, status in cases:
            with patch.object(instamart, "search_ingredients", AsyncMock(side_effect=exc)):
                r = self.client.post("/api/instamart/search", json={"items": ["x"]}, headers=signed_bearer())
            self.assertEqual((r.status_code, r.json()["ok"], r.json()["error"]["code"]), (status, False, exc.code))

    def test_request_validation(self):
        h = signed_bearer()
        self.assertEqual(self.client.post("/api/instamart/search", json={"items": []}, headers=h).status_code, 422)
        self.assertEqual(self.client.post("/api/instamart/search", json={"items": ["x"] * 26}, headers=h).status_code, 422)
        bad_qty = {"address_id": "a", "selections": [{"spin_id": "s", "sku_id": "k", "quantity": 0}]}
        self.assertEqual(self.client.post("/api/instamart/cart", json=bad_qty, headers=h).status_code, 422)
        weak_key = {"address_id": "a", "expected_total": "₹1", "idempotency_key": "short", "payment_key": "cod"}
        self.assertEqual(self.client.post("/api/instamart/checkout", json=weak_key, headers=h).status_code, 422)

    def test_checkout_route_passes_the_reviewed_total_and_key(self):
        order = {"status": "placed", "orderIds": ["IM-1"], "message": "Order placed.", "verified": True, "total": "₹136"}
        with patch.object(instamart, "checkout", AsyncMock(return_value=order)) as fn:
            r = self.client.post(
                "/api/instamart/checkout",
                json={"address_id": "addr-home", "expected_total": "₹136", "idempotency_key": "key-abcdef12", "payment_key": "upi_qr"},
                headers=signed_bearer(),
            )
        self.assertEqual(r.json(), {"ok": True, "order": order})
        self.assertEqual(fn.await_args.args, ("swiggy-tok", "addr-home", "₹136", "key-abcdef12", "upi_qr"))

    def test_checkout_requires_a_payment_choice(self):
        body = {"address_id": "a", "expected_total": "₹1", "idempotency_key": "key-abcdef12"}
        self.assertEqual(self.client.post("/api/instamart/checkout", json=body, headers=signed_bearer()).status_code, 422)

    def test_coupon_and_payment_status_routes_pass_through(self):
        h = signed_bearer()
        with patch.object(instamart, "apply_coupon", AsyncMock(return_value={"review": {}, "coupon": {"code": "SAVE20"}, "coupons": {}})) as fn:
            r = self.client.post("/api/instamart/coupon", json={"address_id": "addr-home", "coupon_code": "SAVE20"}, headers=h)
        self.assertEqual((r.json()["ok"], fn.await_args.args), (True, ("swiggy-tok", "addr-home", "SAVE20")))
        order = {"status": "pending_payment", "orderIds": ["o"], "message": "", "verified": False, "total": None, "payment": None}
        with patch.object(instamart, "payment_status", AsyncMock(return_value=order)) as fn:
            r = self.client.post("/api/instamart/payment-status", json={"order_id": "o", "paas_id": "p", "final": True}, headers=h)
        self.assertEqual((r.json(), fn.await_args.args), ({"ok": True, "order": order}, ("swiggy-tok", "o", "p", True)))
        bad = self.client.post("/api/instamart/coupon", json={"address_id": "a", "coupon_code": ""}, headers=h)
        self.assertEqual(bad.status_code, 422)


# --------------------------------------------------------------------------- the old agent path is closed for groceries


class AgentPathClosedTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_refuses_real_instamart_orders_without_touching_the_network(self):
        item = MealSuggestion(name="meal", description="", can_cook_now=False, missing_ingredients=["tomato"])
        plan = MealPlan(suggestions=[item], decision=Decision.ORDER_GROCERIES, recommended_meal=item, reasoning="")
        with patch("fridge_to_fork.swiggy_agent.Agent", side_effect=AssertionError("agent must not be built")):
            result = await run_swiggy_agent(plan, "addr", "tok")
        self.assertFalse(result.success)
        self.assertIsNone(result.order_id)
        self.assertIn("fridge_to_fork.instamart", result.error)

    def test_order_endpoint_no_longer_accepts_grocery_orders(self):
        r = TestClient(a.app).post("/api/order", data={"action": "order_groceries", "meal_name": "T"}, headers=signed_bearer())
        self.assertIn("Unknown action: order_groceries", r.text)
        self.assertNotIn("Routing your order", r.text)

    def test_cart_fill_agent_endpoint_is_gone(self):
        self.assertEqual(TestClient(a.app).post("/api/cart-fill", json={"items": []}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
