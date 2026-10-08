"""
A network failure during the checkout request is "unknown", never "Order not placed, try again" (2026-10 checkout investigation).

Before: a 502 or a dropped connection on the checkout call surfaced when the MCP session closed, outside the inner try in
instamart._checkout_locked, so the "unknown" outcome and the order re-check never ran and the client was told the order
had failed. These tests drive the app's real session code (swiggy_common.open_session, the real MCP client) against a fake
MCP server on 127.0.0.1. Nothing here talks to Swiggy. Run: pytest tests/test_checkout_network_failure.py
"""

import asyncio
import json
import logging
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from fridge_to_fork import instamart, swiggy_common
from fridge_to_fork.instamart import InstamartError
from tests.test_instamart import COUPONS, ORDER_PLACED, PAYMENT_VIEW, FakeSession, cart, envelope, using

UNKNOWN = "Check the Swiggy app before trying again"


class FakeMcpState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.calls: list[str] = []
        self.fail: dict[str, str] = {}        # tool -> "502" | "reset" | "401"
        self.orders: list[dict] = []          # what get_orders lists right now
        self.place_creates_order = False      # a checkout (even a failed response) leaves a real order behind
        self.checkout_data = dict(ORDER_PLACED)


STATE = FakeMcpState()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_DELETE(self):
        self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()

    def do_GET(self):
        self.send_response(405); self.send_header("Content-Length", "0"); self.end_headers()

    def _json(self, body: dict):
        raw = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        method = msg.get("method")
        if "id" not in msg:  # a notification
            self.send_response(202); self.send_header("Content-Length", "0"); self.end_headers()
        elif method == "initialize":
            self._json({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "fake", "version": "1"}}})
        elif method == "tools/list":
            self._json({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": []}})
        elif method == "tools/call":
            name = msg["params"]["name"]
            STATE.calls.append(name)
            if name == "checkout" and STATE.place_creates_order:
                STATE.orders.append({"orderId": "IM-7777", "status": "PLACED"})
            mode = STATE.fail.get(name)
            if mode == "reset":
                self.connection.close()
                return
            if mode in ("502", "401"):
                self.send_response(int(mode)); self.send_header("Content-Length", "0"); self.end_headers()
                return
            data = {
                "get_cart": cart(), "get_payment_options": PAYMENT_VIEW, "list_coupons": COUPONS,
                "get_orders": {"orders": list(STATE.orders), "hasMore": False},
                "checkout": STATE.checkout_data,
            }[name]
            text = json.dumps({"success": True, "data": data})
            self._json({"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": text}], "isError": False}})
        else:
            self.send_response(202); self.send_header("Content-Length", "0"); self.end_headers()


class FakeServerCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/mcp"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        STATE.reset()
        instamart._attempts.clear()
        instamart._inflight.clear()
        patcher = patch.object(instamart, "_session", lambda token: swiggy_common.open_session(self.url, token))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def place(self, key="key-00000001"):
        return await instamart.checkout("tok", "addr-home", "₹136", key, "cod")


class NetworkFailureDuringCheckoutTests(FakeServerCase):
    async def test_a_502_on_the_checkout_request_is_unknown_not_failed(self):
        STATE.fail["checkout"] = "502"
        out = await self.place()
        self.assertEqual(out["status"], "unknown")
        self.assertIn(UNKNOWN, out["message"])
        self.assertNotIn("Please try again", out["message"])

    async def test_a_dropped_connection_on_the_checkout_request_is_unknown_not_failed(self):
        STATE.fail["checkout"] = "reset"
        out = await self.place()
        self.assertEqual(out["status"], "unknown")
        self.assertIn(UNKNOWN, out["message"])

    async def test_the_order_recheck_runs_and_rescues_an_order_that_was_placed_anyway(self):
        STATE.fail["checkout"] = "502"
        STATE.place_creates_order = True  # Swiggy processed it, then the response never made it back
        out = await self.place()
        self.assertEqual((out["status"], out["orderIds"], out["verified"]), ("placed", ["IM-7777"], True))
        self.assertEqual(STATE.calls.count("get_orders"), 2)  # before the request, and again after the failure

    async def test_the_unknown_outcome_is_remembered_so_the_same_key_never_checks_out_twice(self):
        STATE.fail["checkout"] = "502"
        first = await self.place()
        STATE.fail.clear()  # the network is back; a blind resend must still not place another order
        second = await self.place()
        self.assertEqual(second, first)
        self.assertEqual(STATE.calls.count("checkout"), 1)

    async def test_a_new_key_after_an_unknown_is_a_new_attempt(self):
        STATE.fail["checkout"] = "502"
        await self.place("key-00000001")
        STATE.fail.clear()
        out = await self.place("key-00000002")
        self.assertEqual(out["status"], "placed")  # the guard is per key; telling the user not to reorder is the UI's job
        self.assertEqual(STATE.calls.count("checkout"), 2)


class FailuresBeforeTheRequestIsSentTests(FakeServerCase):
    async def test_a_network_failure_before_the_checkout_request_is_a_plain_failure(self):
        STATE.fail["get_cart"] = "502"
        with self.assertRaises(InstamartError) as caught:
            await self.place()
        self.assertEqual(caught.exception.code, "checkout_not_sent")
        self.assertIn("nothing was ordered", caught.exception.message)
        self.assertNotIn("checkout", STATE.calls)  # the checkout request was never sent

    async def test_a_pre_send_failure_does_not_lock_the_key(self):
        STATE.fail["get_cart"] = "502"
        with self.assertRaises(InstamartError):
            await self.place()
        STATE.fail.clear()
        out = await self.place()  # same key: the user fixed the problem (the network came back)
        self.assertEqual(out["status"], "placed")
        self.assertEqual(STATE.calls.count("checkout"), 1)

    async def test_a_cart_problem_is_still_a_plain_failure_and_does_not_lock_the_key(self):
        with patch.object(instamart, "_session", lambda token: swiggy_common.open_session(self.url, token)):
            with self.assertRaises(InstamartError) as caught:
                await instamart.checkout("tok", "addr-home", "₹999", "key-00000001", "cod")  # the total moved
        self.assertEqual(caught.exception.code, "cart_changed")
        self.assertNotIn("key-00000001", instamart._attempts)

    async def test_an_expired_session_is_a_plain_auth_failure_even_on_the_checkout_request(self):
        STATE.fail["checkout"] = "401"
        with self.assertRaises(InstamartError) as caught:
            await self.place()
        self.assertEqual(caught.exception.code, "auth_required")
        self.assertNotIn("key-00000001", instamart._attempts)


class CancelledMidCheckoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        instamart._attempts.clear()
        instamart._inflight.clear()

    async def test_a_cancelled_request_after_the_send_is_remembered_as_unknown(self):
        started = asyncio.Event()

        async def hang(_args):
            started.set()
            await asyncio.sleep(30)

        session = FakeSession({"get_cart": envelope(cart()), "get_orders": envelope({"orders": []}), "checkout": hang})
        with using(session):
            task = asyncio.create_task(instamart.checkout("tok", "addr-home", "₹136", "key-00000001", "cod"))
            await asyncio.wait_for(started.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(instamart._attempts["key-00000001"][1]["status"], "unknown")
            replay = await instamart.checkout("tok", "addr-home", "₹136", "key-00000001", "cod")
        self.assertEqual(replay["status"], "unknown")
        self.assertEqual(session.names().count("checkout"), 1)
        self.assertEqual(instamart._inflight, set())


class CheckoutLogLineTests(unittest.IsolatedAsyncioTestCase):
    """One structured line per checkout outcome, with the raw status string and no personal data."""

    def setUp(self):
        instamart._attempts.clear()
        instamart._inflight.clear()

    async def lines(self, session, key="key-00000001", total="₹136"):
        with using(session), self.assertLogs("uvicorn.error", level="INFO") as logs:
            try:
                await instamart.checkout("tok", "addr-home", total, key, "cod")
            except InstamartError:
                pass
        return [r.getMessage() for r in logs.records if r.getMessage().startswith("[CHECKOUT]")]

    def session(self, **over):
        base = {"get_cart": envelope(cart()), "get_orders": [envelope({"orders": []}), envelope({"orders": [{"orderId": "IM-1001"}]})], "checkout": envelope(ORDER_PLACED)}
        return FakeSession({**base, **over})

    async def test_a_verified_order(self):
        (line,) = await self.lines(self.session())
        for part in ("kind=instamart", "payment=cod", "sent=yes", "status_raw='PLACED'", "error_code=-", "order_ids=IM-1001", "verified=yes", "outcome=placed"):
            self.assertIn(part, line)
        self.assertRegex(line, r"elapsed=\d+\.\d\ds$")

    async def test_an_unverified_order(self):
        (line,) = await self.lines(self.session(get_orders=envelope({"orders": []})))
        self.assertIn("verified=no", line)
        self.assertIn("outcome=unverified", line)

    async def test_the_raw_status_string_is_logged_as_swiggy_sent_it(self):
        (line,) = await self.lines(self.session(checkout=envelope({"orderId": "IM-1", "status": "AWAITING_RESTAURANT_ACK"})))
        self.assertIn("status_raw='AWAITING_RESTAURANT_ACK'", line)

    async def test_a_swiggy_refusal(self):
        (line,) = await self.lines(self.session(checkout=envelope(success=False, error="Cash on delivery is not available"), get_orders=envelope({"orders": []})))
        self.assertIn("sent=yes", line)
        self.assertIn("error_code=tool_error", line)
        self.assertIn("outcome=failed", line)

    async def test_a_transport_failure_after_the_send(self):
        (line,) = await self.lines(self.session(checkout=ConnectionError("reset by peer"), get_orders=envelope({"orders": []})))
        self.assertIn("sent=yes", line)
        self.assertIn("outcome=unknown", line)

    async def test_a_failure_before_the_send(self):
        (line,) = await self.lines(self.session(), total="₹999")
        for part in ("sent=no", "error_code=cart_changed", "outcome=failed", "order_ids=-"):
            self.assertIn(part, line)

    async def test_a_replayed_key_is_logged_as_a_replay(self):
        await self.lines(self.session())
        (line,) = await self.lines(self.session())
        self.assertIn("replayed=yes", line)
        self.assertIn("outcome=placed", line)

    async def test_no_personal_data_in_the_line(self):
        lines = await self.lines(self.session())
        text = " ".join(lines)
        for private in ("9876543210", "12 MG Road", "Bengaluru", "Indiranagar", "Tomato"):
            self.assertNotIn(private, text)


if __name__ == "__main__":
    unittest.main()
