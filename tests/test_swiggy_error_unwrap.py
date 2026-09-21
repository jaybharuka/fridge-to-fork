"""A SwiggyError raised inside `async with open_session(...)` reaches the caller wrapped in an ExceptionGroup (the MCP transport's
task group wraps whatever the body raises; verified against a real local MCP server). It used to be treated as a network failure
and replaced by "Couldn't reach Swiggy", so a real answer such as "address not serviceable" was hidden behind a 502."""
import logging
import unittest

import httpx

from fridge_to_fork import swiggy_common as sc


class TranslateTests(unittest.TestCase):
    def test_a_swiggy_error_inside_an_exception_group_is_returned_as_is(self):
        real = sc.SwiggyError("address_unserviceable", "The selected address is not serviceable at the moment.", 409)
        with self.assertNoLogs("uvicorn.error", level=logging.ERROR):
            out = sc._translate(ExceptionGroup("unhandled errors in a TaskGroup", [real]))
        self.assertIs(out, real)

    def test_it_is_found_when_nested_and_next_to_transport_noise(self):
        real = sc.SwiggyError("cart_changed", "Your cart total changed.", 409)
        noise = httpx.ReadTimeout("stream closed")
        out = sc._translate(ExceptionGroup("outer", [ExceptionGroup("inner", [noise, real])]))
        self.assertIs(out, real)

    def test_a_real_transport_failure_is_still_upstream_unavailable_and_logged(self):
        with self.assertLogs("uvicorn.error", level=logging.ERROR):
            out = sc._translate(ExceptionGroup("g", [httpx.ConnectError("refused")]))
        self.assertEqual((out.code, out.status), ("upstream_unavailable", 502))

    def test_an_unauthorized_response_is_still_auth_required(self):
        req = httpx.Request("POST", "https://mcp.swiggy.com/food")
        err = httpx.HTTPStatusError("401", request=req, response=httpx.Response(401, request=req))
        self.assertEqual(sc._translate(ExceptionGroup("g", [err])).code, "auth_required")


if __name__ == "__main__":
    unittest.main()
