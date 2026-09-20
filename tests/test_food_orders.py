"""
Food tracking, phase 3 (fridge_to_fork/food_orders.py): order history, live delivery status, order details.
Fixtures follow Swiggy's Food reference pages (get_food_orders, get_food_delivery_status, track_food_order,
get_food_order_details). Run: python -m unittest tests.test_food_orders
"""

import logging
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork import features, food_orders
from fridge_to_fork.swiggy_common import SwiggyError
from tests.test_food import SAVED, using
from tests.test_instamart import FakeSession, envelope, signed_bearer

ORDERS = {
    "orders": [
        {"orderId": "F-2002", "restaurantId": "r1", "restaurantName": "Punjabi Tadka", "restaurantAreaName": "Indiranagar", "orderTotal": "₹386",
         "orderStatus": "OUT_FOR_DELIVERY", "orderDeliveryStatus": "On the way", "orderType": "FOOD", "orderedItems": "Butter Chicken x1",
         "orderedTime": "Today, 1:10 PM", "isActiveOrder": True,
         "actions": [{"type": "REORDER", "priority": 1, "title": "Reorder", "isEnabled": True, "reorderMeta": {"orderItems": []}}]},
        {"orderId": "F-1001", "restaurantId": "r2", "restaurantName": "Biryani House", "orderTotal": "₹698", "orderStatus": "DELIVERED",
         "orderType": "FOOD", "orderedItems": "Chicken Biryani x2", "orderedTime": "Yesterday, 8:02 PM", "isActiveOrder": False, "actions": []},
    ],
    "statusMessage": "ok",
}
NOW = 1_789_800_000_000
DELIVERY = {"orderId": "F-2002", "deliveryBy": NOW + 9 * 60_000, "serverNow": NOW, "etaText": "9 mins", "statusText": "Rider is on the way", "pollIntervalSec": 20}
TRACK = {"orders": [{"orderId": "F-2002", "title": "Your order is on the way", "subtitle": "Arriving soon", "etaText": "9 mins", "orderStatus": "OUT_FOR_DELIVERY",
                     "progressPercentage": "75", "pollingDuration": "10"}]}
DETAILS = {"order": {
    "order_id": 2002, "delivery_address": {"address": "12 MG Road, Bengaluru", "phone": "9876543210", "lat": 12.9, "lng": 77.6},
    "order_items": [{"name": "Butter Chicken", "quantity": 1, "final_price": 320, "variants": [{"name": "Full"}], "addons": [{"name": "Raita"}]},
                    {"item_name": "Naan", "quantity": 2, "total": "₹60"}],
    "charges": {"Delivery fee": "₹40", "Taxes": "₹26"}, "is_coupon_applied": True, "coupon_applied": "SAVE50", "order_time": "2026-09-20 13:10",
    "confirmed_time": "2026-09-20 13:11", "customer_id": "c-1", "order_status": "Delivered", "post_status": "delivered", "order_type": "FOOD",
    "restaurant_id": "r1", "restaurant_name": "Punjabi Tadka", "restaurant_address": "x", "restaurant_locality": "Indiranagar", "restaurant_cuisine": ["North Indian"],
    "payment_method": "Cash", "order_total": 336, "item_total": 380, "order_tax": 26, "order_discount": 0, "coupon_discount": 50, "order_delivery_charge": 40,
    "is_cancellable": True, "is_reorderable_order": True}}


def session(**over) -> FakeSession:
    return FakeSession({"get_addresses": envelope(SAVED), "get_food_orders": envelope(ORDERS), "get_food_delivery_status": envelope(DELIVERY),
                        "track_food_order": envelope(TRACK), "get_food_order_details": envelope(DETAILS), **over})


class OrderListTests(unittest.IsolatedAsyncioTestCase):
    async def list(self, s, address="addr-home", active_only=False):
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            out = await food_orders.list_orders("tok", address, active_only)
        return out, "\n".join(logs.output)

    async def test_orders_are_asked_for_by_address_and_normalized(self):
        s = session()
        out, _ = await self.list(s)
        self.assertEqual(s.args("get_food_orders"), {"addressId": "addr-home", "activeOnly": False})
        first, second = out["orders"]
        self.assertEqual(first, {"orderId": "F-2002", "restaurant": "Punjabi Tadka", "area": "Indiranagar", "status": "OUT_FOR_DELIVERY", "deliveryStatus": "On the way",
                                 "total": "₹386", "items": "Butter Chicken x1", "orderedTime": "Today, 1:10 PM", "active": True})
        self.assertEqual((second["orderId"], second["active"], second["total"]), ("F-1001", False, "₹698"))

    async def test_active_comes_from_swiggys_flag_never_from_the_status_text(self):
        odd = {"orders": [{"orderId": "A", "orderStatus": "DELIVERED", "isActiveOrder": True}, {"orderId": "B", "orderStatus": "PREPARING", "isActiveOrder": False},
                          {"orderId": "C", "orderStatus": "WHATEVER_NEW_STATUS"}]}
        out, _ = await self.list(session(get_food_orders=envelope(odd)))
        self.assertEqual([(o["orderId"], o["active"]) for o in out["orders"]], [("A", True), ("B", False), ("C", False)])

    async def test_active_only_is_passed_through(self):
        s = session()
        await self.list(s, active_only=True)
        self.assertTrue(s.args("get_food_orders")["activeOnly"])

    async def test_the_address_used_is_returned_in_its_canonical_form(self):
        full = "d60pf1o28cib6t3jveug__AMOOxgTFUakDAsJFL27MqT"
        saved = {**SAVED, "addresses": [{**SAVED["addresses"][0], "id": full}]}
        s = session(get_addresses=envelope(saved))
        out, _ = await self.list(s, address="d60pf1o28cib6t3jveug")
        self.assertEqual((out["address"]["id"], s.args("get_food_orders")["addressId"]), (full, full))
        self.assertNotIn("phoneNumber", str(out["address"]))

    async def test_no_address_given_uses_home_or_first(self):
        s = session()
        out, _ = await self.list(s, address=None)
        self.assertEqual(out["address"]["id"], "addr-home")

    async def test_an_address_that_is_not_the_users_is_refused(self):
        s = session()
        with using(s), self.assertLogs("uvicorn.error", level="WARNING"), self.assertRaises(SwiggyError) as ctx:
            await food_orders.list_orders("tok", "somebody-elses")
        self.assertEqual(ctx.exception.code, "address_not_found")
        self.assertNotIn("get_food_orders", s.names())

    async def test_entries_without_an_order_id_are_dropped_and_counted(self):
        data = {"orders": [{"order_id": "X", "orderStatus": "DELIVERED"}, {"orderId": "OK-1", "orderStatus": "DELIVERED"}]}
        out, text = await self.list(session(get_food_orders=envelope(data)))
        self.assertEqual([o["orderId"] for o in out["orders"]], ["OK-1"])
        self.assertIn("without_orderId=1", text)
        self.assertIn("'order_id': 'str'", text)  # the field that was actually there stays visible

    async def test_an_empty_answer_is_an_empty_list_and_is_visible_in_the_log(self):
        out, text = await self.list(session(get_food_orders=envelope({"orders": []})))
        self.assertEqual(out["orders"], [])
        self.assertIn("returned=0", text)
        self.assertIn("addressId='addr-home'", text)

    async def test_the_diagnostic_shows_structure_and_no_personal_text(self):
        _, text = await self.list(session())
        self.assertIn("[FOOD][diag] get_food_orders: addressId='addr-home' activeOnly=False", text)
        self.assertIn("returned=2", text)
        self.assertIn("isActiveOrder=['False', 'True']", text)
        self.assertIn("action_types=['REORDER']", text)
        self.assertIn("orderedTime=['Today, 1:10 PM', 'Yesterday, 8:02 PM']", text)
        self.assertIn("parsed: kept=2 active=1", text)
        for private in ("9876543210", "MG Road", "Bengaluru", "Punjabi Tadka", "Butter Chicken", "Biryani"):
            self.assertNotIn(private, text)

    async def test_auth_failure_propagates(self):
        with using(session(get_food_orders=envelope(success=False, error="401 Unauthorized"))), self.assertRaises(SwiggyError) as ctx:
            await food_orders.list_orders("tok", "addr-home")
        self.assertEqual(ctx.exception.code, "auth_required")


class OrderStatusTests(unittest.IsolatedAsyncioTestCase):
    async def status(self, s, order_id="F-2002"):
        with using(s), self.assertLogs("uvicorn.error", level="INFO") as logs:
            logging.getLogger("uvicorn.error").info("-")
            out = await food_orders.order_status("tok", order_id)
        return out, "\n".join(logs.output)

    async def test_both_tools_are_asked_by_order_id_only_and_never_with_coordinates(self):
        s = session()
        out, _ = await self.status(s)
        self.assertEqual(s.args("get_food_delivery_status"), {"orderId": "F-2002"})
        self.assertEqual(s.args("track_food_order"), {"orderId": "F-2002"})
        self.assertEqual(out["notes"], [])

    async def test_delivery_uses_swiggys_own_clock_and_flags(self):
        out, _ = await self.status(session())
        d = out["delivery"]
        self.assertEqual((d["statusText"], d["minutesLeft"], d["delivered"], d["cancelled"], d["terminal"], d["pollIntervalSec"]), ("Rider is on the way", 9, False, False, False, 20))

    async def test_delivered_and_cancelled_are_terminal(self):
        for flag in ("delivered", "cancelled"):
            out, _ = await self.status(session(get_food_delivery_status=envelope({**DELIVERY, flag: True})))
            self.assertTrue(out["delivery"]["terminal"], flag)

    async def test_the_poll_interval_is_clamped_to_a_sane_floor(self):
        out, _ = await self.status(session(get_food_delivery_status=envelope({**DELIVERY, "pollIntervalSec": 1})))
        self.assertEqual(out["delivery"]["pollIntervalSec"], 10)

    async def test_tracking_is_the_entry_for_this_order(self):
        out, _ = await self.status(session())
        self.assertEqual(out["tracking"], {"title": "Your order is on the way", "subtitle": "Arriving soon", "etaText": "9 mins", "status": "OUT_FOR_DELIVERY", "progress": 75.0})

    async def test_another_active_orders_tracking_is_never_shown_as_this_ones(self):
        others = {"orders": [{**TRACK["orders"][0], "orderId": "F-9999", "title": "SOMEONE ELSE"}, {**TRACK["orders"][0], "orderId": "F-2002", "title": "Mine"}]}
        out, _ = await self.status(session(track_food_order=envelope(others)))
        self.assertEqual(out["tracking"]["title"], "Mine")
        out, _ = await self.status(session(track_food_order=envelope({"orders": [others["orders"][0]]})))
        self.assertIsNone(out["tracking"])

    async def test_delivery_status_for_a_different_order_is_discarded(self):
        out, text = await self.status(session(get_food_delivery_status=envelope({**DELIVERY, "orderId": "F-9999"})))
        self.assertIsNone(out["delivery"])
        self.assertIn("answered for another order", text)

    async def test_progress_is_clamped_and_junk_is_ignored(self):
        for raw, expected in (("150", 100.0), ("-5", 0.0), ("abc", None), (None, None), ("42.5%", 42.5)):
            data = {"orders": [{**TRACK["orders"][0], "progressPercentage": raw}]}
            out, _ = await self.status(session(track_food_order=envelope(data)))
            self.assertEqual(out["tracking"]["progress"], expected, raw)

    async def test_each_source_degrades_on_its_own(self):
        out, _ = await self.status(session(get_food_delivery_status=envelope(success=False, error="not rolled out")))
        self.assertIsNone(out["delivery"])
        self.assertIsNotNone(out["tracking"])
        self.assertIn("isn't available", out["notes"][0])
        out, _ = await self.status(session(track_food_order=envelope(success=False, error="down")))
        self.assertIsNotNone(out["delivery"])
        self.assertIsNone(out["tracking"])

    async def test_auth_expiry_still_propagates_from_either_tool(self):
        for tool in ("get_food_delivery_status", "track_food_order"):
            with using(session(**{tool: envelope(success=False, error="401 Unauthorized")})), self.assertRaises(SwiggyError) as ctx:
                await food_orders.order_status("tok", "F-2002")
            self.assertEqual(ctx.exception.code, "auth_required", tool)

    async def test_the_tracking_diagnostic_holds_ids_and_statuses_only(self):
        _, text = await self.status(session())
        self.assertIn("[FOOD][diag] track_food_order: keys=['orders'] orders=1 matched=True statuses=['OUT_FOR_DELIVERY']", text)
        self.assertNotIn("SOMEONE", text)


class OrderDetailsTests(unittest.IsolatedAsyncioTestCase):
    async def details(self, s, order_id="2002"):
        with using(s), self.assertLogs("uvicorn.error", level="INFO") as logs:
            logging.getLogger("uvicorn.error").info("-")
            out = await food_orders.order_details("tok", order_id)
        return out["details"], "\n".join(logs.output)

    async def test_details_are_read_and_the_numeric_order_id_is_matched_as_text(self):
        s = session()
        d, _ = await self.details(s)
        self.assertEqual(s.args("get_food_order_details"), {"orderId": "2002"})
        self.assertTrue(d["available"])
        self.assertEqual((d["status"], d["total"], d["itemTotal"], d["delivery"], d["tax"], d["paymentMethod"]), ("Delivered", 336.0, 380.0, 40.0, 26.0, "Cash"))
        self.assertEqual(d["restaurant"], {"name": "Punjabi Tadka", "area": "Indiranagar"})
        self.assertEqual(d["charges"], [{"label": "Delivery fee", "value": "₹40"}, {"label": "Taxes", "value": "₹26"}])
        self.assertEqual(d["coupon"], {"code": "SAVE50", "discount": 50.0})

    async def test_items_are_read_tolerantly_since_the_docs_do_not_define_them(self):
        d, _ = await self.details(session())
        self.assertEqual(d["items"], [{"name": "Butter Chicken", "quantity": 1, "price": 320.0, "options": ["Full", "Raita"]},
                                      {"name": "Naan", "quantity": 2, "price": 60.0, "options": []}])
        d, _ = await self.details(session(get_food_order_details=envelope({"order": {**DETAILS["order"], "order_items": [{"weird": "shape"}, "not-a-dict"]}})))
        self.assertEqual(d["items"], [{"name": "", "quantity": None, "price": None, "options": []}])

    async def test_the_delivery_address_and_phone_never_leave_the_server(self):
        d, text = await self.details(session())
        for private in ("9876543210", "MG Road", "Bengaluru", "delivery_address", "customer_id", "c-1"):
            self.assertNotIn(private, str(d))  # nothing about the address or the customer is returned to the browser
        for private in ("9876543210", "MG Road", "Bengaluru", "c-1", "12.9", "77.6"):
            self.assertNotIn(private, text)  # and the log holds field NAMES only, never their values
        self.assertIn("delivery_address_fields=['address', 'lat', 'lng', 'phone']", text)

    async def test_cancellation_points_to_customer_care_because_there_is_no_tool(self):
        d, _ = await self.details(session())
        self.assertIn("080-67466729", d["cancelHelp"])
        d, _ = await self.details(session(get_food_order_details=envelope({"order": {**DETAILS["order"], "is_cancellable": False}})))
        self.assertIsNone(d["cancelHelp"])

    async def test_details_for_a_different_order_are_never_shown(self):
        d, _ = await self.details(session(), order_id="7777")
        self.assertFalse(d["available"])
        self.assertNotIn("Punjabi", str(d))

    async def test_an_empty_or_malformed_answer_is_unavailable(self):
        for data in ({}, {"order": None}, {"order": "x"}):
            d, _ = await self.details(session(get_food_order_details=envelope(data)))
            self.assertFalse(d["available"], data)

    async def test_a_refusal_is_unavailable_not_an_error(self):
        with using(session(get_food_order_details=envelope(success=False, error="not rolled out"))), self.assertLogs("uvicorn.error", level="INFO"):
            out = await food_orders.order_details("tok", "2002")
        self.assertFalse(out["details"]["available"])

    async def test_auth_failure_propagates(self):
        with using(session(get_food_order_details=envelope(success=False, error="401 Unauthorized"))), self.assertRaises(SwiggyError) as ctx:
            await food_orders.order_details("tok", "2002")
        self.assertEqual(ctx.exception.code, "auth_required")

    async def test_the_diagnostic_names_fields_not_values(self):
        _, text = await self.details(session())
        self.assertIn("[FOOD][diag] get_food_order_details: order_fields=", text)
        self.assertIn("charge_labels=['Delivery fee', 'Taxes']", text)


class OrderRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(a.app)

    def post(self, path, body, headers=None):
        return self.client.post(f"/api/food/{path}", json=body, headers=headers or {})

    def test_the_routes_refuse_while_the_flow_is_off_even_without_auth(self):
        for path, body in (("orders", {}), ("order-status", {"order_id": "o"}), ("order-details", {"order_id": "o"})):
            with patch.object(features, "FOOD_ORDERING_ENABLED", False), patch.object(food_orders, "list_orders", AsyncMock()) as fn:
                r = self.post(path, body)
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "food_disabled"), path)
            fn.assert_not_awaited()

    def test_with_the_flow_on_a_missing_token_is_401(self):
        with patch.object(features, "FOOD_ORDERING_ENABLED", True):
            self.assertEqual(self.post("orders", {}).status_code, 401)

    def test_routes_pass_their_arguments_through(self):
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), \
             patch.object(food_orders, "list_orders", AsyncMock(return_value={"address": {}, "orders": []})) as lo, \
             patch.object(food_orders, "order_status", AsyncMock(return_value={"delivery": None, "tracking": None, "notes": []})) as st, \
             patch.object(food_orders, "order_details", AsyncMock(return_value={"details": {"available": False}})) as dt:
            r1 = self.post("orders", {"address_id": "addr-home", "active_only": True}, signed_bearer())
            r2 = self.post("orders", {}, signed_bearer())
            r3 = self.post("order-status", {"order_id": "F-1"}, signed_bearer())
            r4 = self.post("order-details", {"order_id": "F-1"}, signed_bearer())
        self.assertTrue(all(r.json()["ok"] for r in (r1, r2, r3, r4)))
        self.assertEqual([c.args for c in lo.await_args_list], [("swiggy-tok", "addr-home", True), ("swiggy-tok", None, False)])
        st.assert_awaited_once_with("swiggy-tok", "F-1")
        dt.assert_awaited_once_with("swiggy-tok", "F-1")

    def test_bad_input_is_rejected_before_any_swiggy_call(self):
        with patch.object(features, "FOOD_ORDERING_ENABLED", True), patch.object(food_orders, "order_status", AsyncMock()) as st, patch.object(food_orders, "list_orders", AsyncMock()) as lo:
            for path, body in (("order-status", {}), ("order-status", {"order_id": ""}), ("order-status", {"order_id": "x" * 121}), ("orders", {"address_id": ""}), ("orders", {"active_only": "maybe"})):
                self.assertEqual(self.post(path, body, signed_bearer()).status_code, 422, (path, body))
        st.assert_not_awaited()
        lo.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
