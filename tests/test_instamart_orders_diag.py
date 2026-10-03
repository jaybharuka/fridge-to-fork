"""
get_orders diagnostics (instamart_orders.list_orders): what Swiggy returned before we parse it, and, when it is empty,
what the same call returns without orderType. Behaviour of the list itself must not change.
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
        self.assertIn("orderType=INSTAMART activeOnly=False count=10", text)
        self.assertIn("returned=2 hasMore=False without_orderId=0", text)
        self.assertIn("status=['DELIVERED', 'OUT_FOR_DELIVERY']", text)
        self.assertIn("createdAt=['2026-09-19T10:00:00Z', '2026-09-10T09:00:00Z']", text)
        self.assertIn("'orderId': 'str'", text)
        self.assertIn("first_deliveryAddress_fields=['addressLine']", text)
        self.assertIn("orderIds=['IM-1001', 'IM-0900']", text)
        self.assertIn("parsed: kept=2 with_address_id=1", text)
        self.assertIn("orderTypes=['None']", text)  # these fixtures carry no orderType: the field is logged either way
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


TYPED = {"orders": [{"orderId": "A-1", "orderType": "DASH", "status": "DELIVERED", "isActive": False, "createdAt": "2026-09-29T05:16:30.000Z",
                     "deliveryAddress": {"addressLine": "MG Road, Bengaluru", "phoneNumber": "9876543210"}}], "hasMore": False}


class OrderTypeDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    """Temporary log-only diagnostics: the real orderType Swiggy puts on orders, with no effect on what the app does."""

    async def test_the_history_probe_logs_each_orders_type(self):
        s = FakeSession({"get_orders": [envelope(EMPTY), envelope(TYPED)], "get_addresses": envelope(ADDRESSES)})
        out, text = await run(s)
        self.assertEqual(out["orders"], [])  # still the filtered answer: behaviour unchanged
        self.assertIn("orderTypes=['DASH']", text)
        self.assertIn("('DASH', 'DELIVERED', False, '2026-09-29T05:16:30.000Z')", text)
        for private in ("MG Road", "9876543210"):
            self.assertNotIn(private, text)

    async def test_the_checkout_check_logs_an_unfiltered_probe_when_the_filtered_call_is_empty(self):
        s = FakeSession({"get_orders": [envelope(EMPTY), envelope(TYPED)]})
        with using(s), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            ids = await instamart._active_order_ids(s)
        text = "\n".join(logs.output)
        self.assertEqual(ids, set())  # the verification result is unchanged
        self.assertEqual([c[1] for c in s.calls], [{"orderType": "INSTAMART", "activeOnly": True, "count": 10}, {"activeOnly": True, "count": 10}])
        self.assertIn("checkout check, no orderType, activeOnly=True: orderTypes=['DASH']", text)

    async def test_no_probe_when_the_filtered_call_already_sees_orders(self):
        s = FakeSession({"get_orders": [envelope(TYPED)]})
        with self.assertLogs("uvicorn.error", level="WARNING"):
            ids = await instamart._active_order_ids(s)
        self.assertEqual(ids, {"A-1"})
        self.assertEqual(len(s.calls), 1)

    async def test_a_failing_checkout_probe_never_breaks_the_check(self):
        s = FakeSession({"get_orders": [envelope(EMPTY), envelope(success=False, error="nope")]})
        with self.assertLogs("uvicorn.error", level="WARNING") as logs:
            ids = await instamart._active_order_ids(s)
        self.assertEqual(ids, set())
        self.assertIn("checkout check probe failed", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
