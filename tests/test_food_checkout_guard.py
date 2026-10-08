"""
Food checkout: a network failure once the request may have been sent is "unknown", never "not placed"; failures and unknowns are
remembered under their idempotency key; one structured log line per outcome. The same guard as Instamart's
(swiggy_common.guarded_checkout). Run: pytest tests/test_food_checkout_guard.py

The transport failure is simulated the way the real client produces it (proved for Instamart against a fake MCP server in
tests/test_checkout_network_failure.py): the call in flight is cancelled, and the error surfaces when the session closes, outside
the body of the checkout. Nothing here talks to Swiggy.
"""

import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from fridge_to_fork import food
from fridge_to_fork.swiggy_common import SwiggyError
from tests.test_food import ACTIVE, NONE_ACTIVE, PLACED, FoodCase, checkout_session, envelope, place, using

UNKNOWN = "Check the Swiggy app before trying again"


def cancelled(_args):
    raise asyncio.CancelledError()


def dies_on_exit(session):
    """A session whose transport fails while a call is in flight: the call is cancelled, and the translated error is raised when
    the session closes."""
    @asynccontextmanager
    async def fake(_token):
        try:
            yield session
        except BaseException as exc:  # noqa: BLE001 - the cancellation the transport's task group delivers
            raise SwiggyError("upstream_unavailable", "Couldn't reach Swiggy. Please try again.", 502) from exc

    return patch.object(food, "_session", fake)


class FoodNetworkFailureTests(FoodCase):
    async def test_a_network_failure_on_the_order_request_is_unknown_not_failed(self):
        s = checkout_session(place_food_order=cancelled, get_food_orders=[envelope(NONE_ACTIVE), envelope(NONE_ACTIVE)])
        with dies_on_exit(s):
            out = await place()
        self.assertEqual(out["status"], "unknown")
        self.assertIn(UNKNOWN, out["message"])
        self.assertEqual(s.names().count("get_food_orders"), 2)  # the snapshot before the request, and the re-check after the failure

    async def test_the_order_recheck_rescues_an_order_that_was_placed_anyway(self):
        s = checkout_session(place_food_order=cancelled)  # default order lists: none before, one active after
        recheck_session = checkout_session(get_food_orders=envelope(ACTIVE))

        @asynccontextmanager
        async def sessions(_token):
            # the first session carries the checkout and dies; the re-check opens a fresh one that sees the order
            if not getattr(sessions, "opened", False):
                sessions.opened = True
                try:
                    yield s
                except BaseException as exc:  # noqa: BLE001
                    raise SwiggyError("upstream_unavailable", "Couldn't reach Swiggy. Please try again.", 502) from exc
            else:
                yield recheck_session

        with patch.object(food, "_session", sessions):
            out = await place()
        self.assertEqual((out["status"], out["orderIds"], out["verified"]), ("placed", ["F-1001"], True))

    async def test_the_unknown_is_remembered_so_the_same_key_never_places_twice(self):
        s = checkout_session(place_food_order=cancelled, get_food_orders=[envelope(NONE_ACTIVE), envelope(NONE_ACTIVE)])
        with dies_on_exit(s):
            first = await place()
        healthy = checkout_session()
        with using(healthy):
            second = await place()  # same key, the network is back
        self.assertEqual(second, first)
        self.assertNotIn("place_food_order", healthy.names())

    async def test_a_network_failure_before_the_request_is_a_plain_failure_and_does_not_lock_the_key(self):
        s = checkout_session(get_food_cart=cancelled)
        with dies_on_exit(s), self.assertRaises(SwiggyError) as caught:
            await place()
        self.assertEqual(caught.exception.code, "checkout_not_sent")
        self.assertIn("nothing was ordered", caught.exception.message)
        self.assertNotIn("place_food_order", s.names())
        self.assertNotIn("idem-key-0001", food._attempts)
        healthy = checkout_session()
        with using(healthy):
            out = await place()  # same key: the user's problem went away
        self.assertEqual(out["status"], "placed")
        self.assertEqual(healthy.names().count("place_food_order"), 1)

    async def test_a_cart_problem_is_still_a_plain_failure(self):
        with using(checkout_session()), self.assertRaises(SwiggyError) as caught:
            await place(total=999.0)
        self.assertEqual(caught.exception.code, "cart_changed")
        self.assertNotIn("idem-key-0001", food._attempts)

    async def test_a_cancelled_request_after_the_send_is_remembered_as_unknown(self):
        started = asyncio.Event()

        async def hang(_args):
            started.set()
            await asyncio.sleep(30)

        s = checkout_session(place_food_order=hang, get_food_orders=envelope(NONE_ACTIVE))
        with using(s):
            task = asyncio.create_task(place())
            await asyncio.wait_for(started.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(food._attempts["idem-key-0001"][1]["status"], "unknown")
            replay = await place()
        self.assertEqual(replay["status"], "unknown")
        self.assertEqual(s.names().count("place_food_order"), 1)
        self.assertEqual(food._inflight, set())


class FoodCheckoutLogTests(FoodCase):
    async def lines(self, session, **kw):
        with using(session), self.assertLogs("uvicorn.error", level="INFO") as logs:
            try:
                await place(**kw)
            except SwiggyError:
                pass
        return [r.getMessage() for r in logs.records if r.getMessage().startswith("[CHECKOUT]")]

    async def test_a_verified_order_logs_swiggys_raw_status(self):
        (line,) = await self.lines(checkout_session())
        for part in ("kind=food", "payment=cod", "sent=yes", "status_raw='CONFIRMED / success'", "error_code=-", "order_ids=F-1001", "verified=yes", "outcome=placed"):
            self.assertIn(part, line)
        self.assertRegex(line, r"elapsed=\d+\.\d\ds$")

    async def test_a_refusal_logs_the_error_code(self):
        (line,) = await self.lines(checkout_session(place_food_order=envelope(success=False, error="Restaurant is closed"), get_food_orders=envelope(NONE_ACTIVE)))
        for part in ("kind=food", "sent=yes", "error_code=tool_error", "outcome=failed"):
            self.assertIn(part, line)

    async def test_a_failure_before_the_send_is_logged_as_not_sent(self):
        (line,) = await self.lines(checkout_session(), total=999.0)
        for part in ("sent=no", "error_code=cart_changed", "outcome=failed"):
            self.assertIn(part, line)

    async def test_no_personal_data_in_the_line(self):
        text = " ".join(await self.lines(checkout_session()))
        for private in ("9876543210", "12 MG Road", "Bengaluru", "Punjabi Tadka", "Butter Chicken"):
            self.assertNotIn(private, text)


if __name__ == "__main__":
    unittest.main()
