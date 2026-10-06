"""
get_orders logging (instamart_orders.list_orders and the checkout check): what Swiggy returned before we parse it, and the
orderType it puts on each order. Swiggy files Instamart orders as "DASH", so neither call sends an orderType (sending
"INSTAMART" returned nothing; 2026-10-06 diagnostic).
Run: python -m unittest tests.test_instamart_orders_diag
"""

import unittest

from fridge_to_fork import instamart, instamart_orders
from tests.test_instamart import ADDRESSES, FakeSession, envelope, using
from tests.test_instamart_orders import ORDERS

EMPTY = {"orders": [], "hasMore": False}


async def run(s, **kw):
    with using(s), unittest.TestCase().assertLogs("uvicorn.error", level="WARNING") as logs:
        out = await instamart_orders.list_orders("tok", **kw)
    return out, "\n".join(r for r in logs.output if "get_orders" in r)


class OrdersDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_raw_shape_is_logged_without_any_personal_text(self):
        s = FakeSession({"get_orders": envelope(ORDERS), "get_addresses": envelope(ADDRESSES)})
        out, text = await run(s)
        self.assertEqual(len(out["orders"]), 2)
        self.assertIn("activeOnly=False count=10", text)
        self.assertIn("returned=2 hasMore=False without_orderId=0", text)
        self.assertIn("status=['DELIVERED', 'OUT_FOR_DELIVERY']", text)
        self.assertIn("createdAt=['2026-09-19T10:00:00Z', '2026-09-10T09:00:00Z']", text)
        self.assertIn("'orderId': 'str'", text)
        self.assertIn("first_deliveryAddress_fields=['addressLine']", text)
        self.assertIn("orderIds=['IM-1001', 'IM-0900']", text)
        self.assertIn("parsed: kept=2 with_address_id=1", text)
        self.assertIn("orderTypes=['None']", text)  # these fixtures carry no orderType: the field is logged either way
        for private in ("MG Road", "Bengaluru", "Tomato", "Somewhere unsaved", "9876543210"):
            self.assertNotIn(private, text)

    async def test_orders_without_an_id_are_counted_and_still_dropped(self):
        data = {"orders": [{"order_id": "X-1", "status": "DELIVERED"}, {"orderId": "IM-2", "status": "DELIVERED"}], "hasMore": True}
        out, text = await run(FakeSession({"get_orders": envelope(data), "get_addresses": envelope(ADDRESSES)}))
        self.assertEqual([o["orderId"] for o in out["orders"]], ["IM-2"])
        self.assertIn("without_orderId=1", text)
        self.assertIn("'order_id': 'str'", text)  # the field that was actually there is visible


TYPED = {"orders": [{"orderId": "A-1", "orderType": "DASH", "status": "DELIVERED", "isActive": False, "createdAt": "2026-09-29T05:16:30.000Z",
                     "deliveryAddress": {"addressLine": "MG Road, Bengaluru", "phoneNumber": "9876543210"}}], "hasMore": False}


class DashOrdersTests(unittest.IsolatedAsyncioTestCase):
    """Swiggy returns Instamart orders with orderType 'DASH'. They must be asked for without a type and kept."""

    async def test_history_asks_without_an_order_type_and_keeps_dash_orders(self):
        s = FakeSession({"get_orders": envelope(TYPED), "get_addresses": envelope(ADDRESSES)})
        out, text = await run(s)
        self.assertEqual([o["orderId"] for o in out["orders"]], ["A-1"])
        self.assertNotIn("orderType", s.args("get_orders"))
        self.assertEqual(s.args("get_orders"), {"activeOnly": False, "count": 10})
        self.assertEqual(s.names().count("get_orders"), 1)
        self.assertIn("orderTypes=['DASH']", text)  # still logged, so a regression stays visible
        self.assertIn("('DASH', 'DELIVERED', False, '2026-09-29T05:16:30.000Z')", text)
        for private in ("MG Road", "9876543210"):
            self.assertNotIn(private, text)

    async def test_the_checkout_check_sees_dash_orders(self):
        s = FakeSession({"get_orders": envelope(TYPED)})
        with self.assertLogs("uvicorn.error", level="WARNING") as logs:
            ids = await instamart._active_order_ids(s)
        self.assertEqual(ids, {"A-1"})
        self.assertEqual([c[1] for c in s.calls], [{"activeOnly": True, "count": 10}])  # one call, no orderType
        self.assertIn("orderTypes=['DASH']", "\n".join(logs.output))

    async def test_an_empty_history_makes_no_second_call(self):
        s = FakeSession({"get_orders": envelope(EMPTY), "get_addresses": envelope(ADDRESSES)})
        out, _ = await run(s)
        self.assertEqual(out, {"orders": [], "hasMore": False})
        self.assertEqual(s.names().count("get_orders"), 1)

    async def test_a_failing_checkout_check_still_returns_none(self):
        s = FakeSession({"get_orders": envelope(success=False, error="nope")})
        self.assertIsNone(await instamart._active_order_ids(s))


if __name__ == "__main__":
    unittest.main()
