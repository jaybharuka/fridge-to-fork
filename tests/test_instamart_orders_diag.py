"""
get_orders diagnostics (instamart_orders.list_orders): what Swiggy returned before we parse it, and, when it is empty,
what the same call returns without orderType. Behaviour of the list itself must not change.
Run: python -m unittest tests.test_instamart_orders_diag
"""

import unittest

from fridge_to_fork import instamart_orders
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
        self.assertIn("orderType=INSTAMART activeOnly=False count=10", text)
        self.assertIn("returned=2 hasMore=False without_orderId=0", text)
        self.assertIn("status=['DELIVERED', 'OUT_FOR_DELIVERY']", text)
        self.assertIn("createdAt=['2026-09-19T10:00:00Z', '2026-09-10T09:00:00Z']", text)
        self.assertIn("'orderId': 'str'", text)
        self.assertIn("first_deliveryAddress_fields=['addressLine']", text)
        self.assertIn("orderIds=['IM-1001', 'IM-0900']", text)
        self.assertIn("parsed: kept=2 with_address_id=1", text)
        self.assertNotIn("get_orders returned nothing", text)  # no probe when there are orders
        for private in ("MG Road", "Bengaluru", "Tomato", "Somewhere unsaved", "9876543210"):
            self.assertNotIn(private, text)

    async def test_orders_without_an_id_are_counted_and_still_dropped(self):
        data = {"orders": [{"order_id": "X-1", "status": "DELIVERED"}, {"orderId": "IM-2", "status": "DELIVERED"}], "hasMore": True}
        out, text = await run(FakeSession({"get_orders": envelope(data), "get_addresses": envelope(ADDRESSES)}))
        self.assertEqual([o["orderId"] for o in out["orders"]], ["IM-2"])
        self.assertIn("without_orderId=1", text)
        self.assertIn("'order_id': 'str'", text)  # the field that was actually there is visible

    async def test_an_empty_answer_probes_without_ordertype_and_logs_both(self):
        s = FakeSession({"get_orders": [envelope(EMPTY), envelope(ORDERS)], "get_addresses": envelope(ADDRESSES)})
        out, text = await run(s)
        self.assertEqual(out, {"orders": [], "hasMore": False})  # the probe is diagnostic only
        self.assertIn("get_orders returned nothing", text)
        self.assertIn("same call with no orderType: data_keys=['hasMore', 'orders'] orders_is=list returned=2", text)
        self.assertNotIn("orderType", s.calls[1][1])

    async def test_a_failing_probe_is_logged_not_raised(self):
        s = FakeSession({"get_orders": [envelope(EMPTY), envelope(success=False, error="nope")], "get_addresses": envelope(ADDRESSES)})
        out, text = await run(s)
        self.assertEqual(out["orders"], [])
        self.assertIn("probe failed", text)


if __name__ == "__main__":
    unittest.main()
