"""
Order history / live status / details (fridge_to_fork/instamart_orders.py).
Fixtures follow Swiggy's reference docs for get_orders, get_delivery_status, track_order and
get_order_details. Run: python -m unittest tests.test_instamart_orders
"""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

import app as a
from fridge_to_fork import instamart_orders
from fridge_to_fork.instamart import InstamartError
from tests.test_instamart import ADDRESSES, FakeSession, envelope, signed_bearer, using

ORDERS = {
    "orders": [
        {"orderId": "IM-1001", "status": "OUT_FOR_DELIVERY", "currentStatus": "Out for delivery", "createdAt": "2026-09-19T10:00:00Z",
         "updatedAt": "2026-09-19T10:05:00Z", "estimatedDeliveryTime": "10:20", "itemCount": 2, "totalAmount": 136, "paymentMethod": "Cash",
         "items": [{"name": "Tomato Hybrid", "quantity": 2}], "deliveryAddress": {"addressLine": "12 MG Road, Bengaluru"}},
        {"orderId": "IM-0900", "status": "DELIVERED", "createdAt": "2026-09-10T09:00:00Z", "itemCount": 1, "totalAmount": "₹64",
         "items": [], "deliveryAddress": {"addressLine": "Somewhere unsaved"}},
    ],
    "hasMore": False,
}

NOW = 1_789_800_000_000
DELIVERY = {"orderId": "IM-1001", "deliveryBy": NOW + 9 * 60_000, "serverNow": NOW, "etaText": "9 mins", "statusText": "Rider is on the way", "pollIntervalSec": 20}

TRACKING = {
    "orderId": "IM-1001", "orderTitle": "Your groceries", "orderSubtitle": "2 items",
    "status": {"statusMessage": "Out for delivery", "subStatusMessage": "Arriving soon", "etaMinutes": 9, "etaText": "9 mins"},
    "storeInfo": {"name": "Instamart Store", "address": "HSR"}, "deliveryInfo": {"fullAddress": "12 MG Road"},
    "items": [{"name": "Tomato Hybrid", "quantity": 2, "price": "₹64"}], "itemCount": 2,
    "paymentInfo": {"message": "Pay ₹136 on delivery"},
    "mapInfo": {"storeLocation": {"latitude": 12.9, "longitude": 77.6}, "riderLocation": {"latitude": 12.95, "longitude": 77.59}},
    "pollingIntervalSeconds": 15,
}

DETAILS = {
    "orderId": "IM-1001", "status": "Delivered", "totalBill": 136, "hasRefunds": True,
    "items": [{"name": "Tomato Hybrid", "quantity": 2, "finalPrice": 64, "removed": False},
              {"name": "Tomato Puree", "quantity": 1, "finalPrice": 55, "removed": True}],
    "bill": {"lineItems": [{"name": "Item total", "amount": "₹120"}, {"name": "Delivery fee", "amount": "₹16"}], "grandTotal": "₹136"},
}


def session(**over) -> FakeSession:
    return FakeSession({"get_orders": envelope(ORDERS), "get_addresses": envelope(ADDRESSES), **over})


class OrderListTests(unittest.IsolatedAsyncioTestCase):
    async def test_orders_are_normalized_and_asked_for_by_type(self):
        s = session()
        with using(s):
            out = await instamart_orders.list_orders("tok", active_only=False)
        self.assertEqual(s.args("get_orders"), {"orderType": "INSTAMART", "activeOnly": False, "count": 10})
        first, second = out["orders"]
        self.assertEqual((first["orderId"], first["status"], first["totalAmount"], first["paymentMethod"]), ("IM-1001", "Out for delivery", 136.0, "Cash"))
        self.assertEqual(first["items"], [{"name": "Tomato Hybrid", "quantity": 2}])
        self.assertEqual((second["status"], second["totalAmount"]), ("DELIVERED", 64.0))  # "₹64" string tolerated

    async def test_active_only_is_passed_through(self):
        s = session()
        with using(s):
            await instamart_orders.list_orders("tok", active_only=True)
        self.assertTrue(s.args("get_orders")["activeOnly"])

    async def test_address_text_is_matched_to_a_saved_address_id(self):
        with using(session()):
            first, second = (await instamart_orders.list_orders("tok"))["orders"]
        self.assertEqual(first["addressId"], "addr-home")
        self.assertIsNone(second["addressId"])  # not one of the saved addresses: never guessed

    async def test_a_failing_address_lookup_does_not_lose_the_orders(self):
        with using(session(get_addresses=envelope(success=False, error="down"))):
            out = await instamart_orders.list_orders("tok")
        self.assertEqual(len(out["orders"]), 2)
        self.assertIsNone(out["orders"][0]["addressId"])

    async def test_auth_failure_propagates(self):
        with using(session(get_orders=envelope(success=False, error="401 Unauthorized"))), self.assertRaises(InstamartError) as ctx:
            await instamart_orders.list_orders("tok")
        self.assertEqual(ctx.exception.code, "auth_required")


class OrderStatusTests(unittest.IsolatedAsyncioTestCase):
    async def status(self, s, address_id="addr-home", lat=None, lng=None):
        with using(s):
            return await instamart_orders.order_status("tok", "IM-1001", address_id, lat, lng)

    async def test_delivery_status_uses_order_and_address_and_swiggys_own_clock(self):
        s = FakeSession({"get_delivery_status": envelope(DELIVERY)})
        out = await self.status(s)
        self.assertEqual(s.args("get_delivery_status"), {"orderId": "IM-1001", "addressId": "addr-home"})
        d = out["delivery"]
        self.assertEqual((d["statusText"], d["etaText"], d["minutesLeft"], d["terminal"], d["pollIntervalSec"]), ("Rider is on the way", "9 mins", 9, False, 20))
        self.assertNotIn("track_order", s.names())

    async def test_track_order_is_never_called_without_real_coordinates(self):
        s = FakeSession({"get_delivery_status": envelope(DELIVERY)})
        out = await self.status(s)
        self.assertIsNone(out["tracking"])
        self.assertNotIn("track_order", s.names())

    async def test_track_order_with_supplied_coordinates(self):
        s = FakeSession({"get_delivery_status": envelope(DELIVERY), "track_order": envelope(TRACKING)})
        out = await self.status(s, lat=12.9716, lng=77.5946)
        self.assertEqual(s.args("track_order"), {"orderId": "IM-1001", "lat": 12.9716, "lng": 77.5946})
        t = out["tracking"]
        self.assertEqual(
            (t["statusMessage"], t["etaMinutes"], t["store"], t["riderLocation"], t["pollIntervalSec"]),
            ("Out for delivery", 9, "Instamart Store", {"lat": 12.95, "lng": 77.59}, 15),
        )

    async def test_delivered_and_cancelled_are_terminal(self):
        for flag in ("delivered", "cancelled"):
            s = FakeSession({"get_delivery_status": envelope({**DELIVERY, flag: True, "deliveryBy": None})})
            with self.subTest(flag):
                d = (await self.status(s))["delivery"]
                self.assertTrue(d["terminal"])
                self.assertIsNone(d["minutesLeft"])  # deliveryBy can be null

    async def test_poll_interval_is_clamped_to_the_documented_floor(self):
        for raw, expected in ((1, 10), (500, 60), (None, 30), (25, 25)):
            s = FakeSession({"get_delivery_status": envelope({**DELIVERY, "pollIntervalSec": raw})})
            with self.subTest(raw):
                self.assertEqual((await self.status(s))["delivery"]["pollIntervalSec"], expected)

    async def test_no_address_means_no_delivery_call_and_a_note(self):
        s = FakeSession({})
        out = await self.status(s, address_id=None)
        self.assertEqual(s.names(), [])
        self.assertIsNone(out["delivery"])
        self.assertIn("delivery address", out["notes"][0])

    async def test_a_failing_status_tool_degrades_with_a_note_instead_of_erroring(self):
        s = FakeSession({"get_delivery_status": McpError(ErrorData(code=-32601, message="Method not found"))})
        out = await self.status(s)
        self.assertIsNone(out["delivery"])
        self.assertIn("isn't available", out["notes"][0])

    async def test_auth_expiry_still_propagates(self):
        s = FakeSession({"get_delivery_status": envelope(success=False, error="TOKEN_EXPIRED")})
        with self.assertRaises(InstamartError) as ctx:
            await self.status(s)
        self.assertEqual(ctx.exception.code, "auth_required")


class OrderDetailsTests(unittest.IsolatedAsyncioTestCase):
    async def test_details_are_itemized_with_removed_items_and_bill(self):
        s = FakeSession({"get_order_details": envelope(DETAILS)})
        with using(s):
            d = (await instamart_orders.order_details("tok", "IM-1001"))["details"]
        self.assertEqual(s.args("get_order_details"), {"orderId": "IM-1001"})
        self.assertTrue(d["available"] and d["hasRefunds"])
        self.assertEqual((d["totalBill"], d["bill"]["grandTotal"]), (136.0, "₹136"))
        self.assertEqual([(i["name"], i["finalPrice"], i["removed"]) for i in d["items"]], [("Tomato Hybrid", 64.0, False), ("Tomato Puree", 55.0, True)])
        self.assertEqual(d["bill"]["lineItems"][1], {"name": "Delivery fee", "amount": "₹16"})

    async def test_tool_not_rolled_out_is_unavailable_not_an_error(self):
        for failing in (McpError(ErrorData(code=-32601, message="Method not found")), envelope(success=False, error="unknown tool")):
            with self.subTest(type(failing).__name__), using(FakeSession({"get_order_details": failing})):
                d = (await instamart_orders.order_details("tok", "IM-1001"))["details"]
            self.assertEqual(d["available"], False)

    async def test_auth_failure_propagates(self):
        with using(FakeSession({"get_order_details": envelope(success=False, error="401")})), self.assertRaises(InstamartError):
            await instamart_orders.order_details("tok", "IM-1001")


class OrderRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(a.app)

    def test_all_three_routes_require_auth(self):
        for path, body in (("orders", {}), ("order-status", {"order_id": "o"}), ("order-details", {"order_id": "o"})):
            r = self.client.post(f"/api/instamart/{path}", json=body)
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "auth_required"), path)

    def test_routes_pass_arguments_through(self):
        h = signed_bearer()
        with patch.object(instamart_orders, "list_orders", AsyncMock(return_value={"orders": [], "hasMore": False})) as fn:
            r = self.client.post("/api/instamart/orders", json={"active_only": True}, headers=h)
        self.assertEqual((r.json()["ok"], fn.await_args.args), (True, ("swiggy-tok", True)))
        with patch.object(instamart_orders, "order_status", AsyncMock(return_value={"delivery": None, "tracking": None, "notes": []})) as fn:
            self.client.post("/api/instamart/order-status", json={"order_id": "IM-1", "address_id": "a", "lat": 12.9, "lng": 77.5}, headers=h)
        self.assertEqual(fn.await_args.args, ("swiggy-tok", "IM-1", "a", 12.9, 77.5))
        with patch.object(instamart_orders, "order_details", AsyncMock(return_value={"details": {"available": False}})) as fn:
            self.client.post("/api/instamart/order-details", json={"order_id": "IM-1"}, headers=h)
        self.assertEqual(fn.await_args.args, ("swiggy-tok", "IM-1"))

    def test_coordinates_must_come_as_a_valid_pair(self):
        h = signed_bearer()
        for body in ({"order_id": "o", "lat": 12.9}, {"order_id": "o", "lng": 77.5}, {"order_id": "o", "lat": 999, "lng": 1}, {"order_id": "o", "lat": 1, "lng": 999}):
            self.assertEqual(self.client.post("/api/instamart/order-status", json=body, headers=h).status_code, 422, body)


if __name__ == "__main__":
    unittest.main()
