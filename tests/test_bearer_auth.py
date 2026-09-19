"""
Header-based auth for the direct-to-Render /api calls (the session cookie is
host-only on the Vercel domain and never reaches them).
Run: python -m unittest tests.test_bearer_auth
"""

import unittest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app as a

client = TestClient(a.app)
ORDER = {"action": "order_groceries", "meal_name": "Test", "missing_ingredients": ""}


def _exp(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


class TestBearerAuth(unittest.TestCase):
    def test_status_unauthenticated_without_credentials(self):
        self.assertEqual(client.get("/auth/status").json(), {"authenticated": False, "expires_at": None})

    def test_valid_bearer_authenticates(self):
        exp = _exp(timedelta(days=1))
        r = client.get("/auth/status", headers={"Authorization": f"Bearer {a._issue_bearer('tok', exp)}"})
        self.assertEqual(r.json(), {"authenticated": True, "expires_at": exp})

    def test_expired_bearer_rejected(self):
        tok = a._issue_bearer("tok", _exp(timedelta(seconds=-5)))
        self.assertFalse(client.get("/auth/status", headers={"Authorization": f"Bearer {tok}"}).json()["authenticated"])

    def test_garbage_and_tampered_bearer_rejected(self):
        good = a._issue_bearer("tok", _exp(timedelta(days=1)))
        for bad in ("garbage", good[:-2] + "xx", ""):
            r = client.get("/auth/status", headers={"Authorization": f"Bearer {bad}"})
            self.assertFalse(r.json()["authenticated"], bad)

    def test_order_without_credentials_is_auth_required(self):
        self.assertIn('"auth_required"', client.post("/api/order", data=ORDER).text)

    def test_order_with_bad_bearer_is_auth_required(self):
        r = client.post("/api/order", data=ORDER, headers={"Authorization": "Bearer nope"})
        self.assertIn('"auth_required"', r.text)

    def test_order_with_valid_bearer_passes_the_auth_gate(self):
        tok = a._issue_bearer("swiggy-tok", _exp(timedelta(days=1)))
        with patch.object(a, "order_groceries_from_instamart", AsyncMock(return_value=None)) as order:
            r = client.post("/api/order", data=ORDER, headers={"Authorization": f"Bearer {tok}"})
        self.assertNotIn("auth_required", r.text)
        self.assertEqual(order.await_args.args[-1], "swiggy-tok")  # the Swiggy token, not our signed wrapper

    def test_session_token_endpoint_requires_the_cookie_session(self):
        r = client.get("/auth/session-token", headers={"Authorization": "Bearer x"})
        self.assertEqual(r.json(), {"authenticated": False})
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_session_token_roundtrip_through_cookie(self):
        # Cookie session is only ever created by the callback; forge one the same way it would be signed.
        from itsdangerous import TimestampSigner
        import base64, json
        exp = _exp(timedelta(days=1))
        raw = base64.b64encode(json.dumps({"access_token": "tok", "expires_at": exp}).encode())
        cookie = TimestampSigner(a._SECRET_KEY).sign(raw).decode()
        c = TestClient(a.app, cookies={"session": cookie})
        body = c.get("/auth/session-token").json()
        self.assertTrue(body["authenticated"])
        self.assertEqual(body["expires_at"], exp)
        # ...and the issued token really works as a bearer with no cookie at all
        r = client.get("/auth/status", headers={"Authorization": f"Bearer {body['token']}"})
        self.assertTrue(r.json()["authenticated"])

    def test_cors_preflight_allows_authorization_header(self):
        r = client.options(
            "/api/order",
            headers={
                "Origin": "https://fridge-to-fork-cyan.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("authorization", r.headers["access-control-allow-headers"].lower())


if __name__ == "__main__":
    unittest.main()
