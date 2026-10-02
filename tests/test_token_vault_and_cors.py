"""
The Swiggy token is never stored or sent in readable form, and CORS fails closed.
Run: python -m unittest tests.test_token_vault_and_cors
"""

import base64
import json
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

import app as a
from fridge_to_fork import instamart_orders, token_vault

SECRET = "unit-test-secret"
TOKEN = "swiggy-secret-token-0123456789"


def _exp(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


class TokenVaultTests(unittest.TestCase):
    def test_roundtrip(self):
        exp = _exp(timedelta(days=1))
        blob = token_vault.seal(TOKEN, exp, SECRET)
        self.assertEqual(token_vault.unseal(blob, SECRET, 3600), (TOKEN, exp))

    def test_the_blob_does_not_contain_the_token_in_any_decodable_form(self):
        blob = token_vault.seal(TOKEN, _exp(timedelta(days=1)), SECRET)
        self.assertNotIn(TOKEN, blob)
        padded = blob + "=" * (-len(blob) % 4)
        self.assertNotIn(TOKEN.encode(), base64.urlsafe_b64decode(padded))  # Fernet is base64 of ciphertext

    def test_a_different_secret_cannot_open_it(self):
        blob = token_vault.seal(TOKEN, _exp(timedelta(days=1)), SECRET)
        self.assertIsNone(token_vault.unseal(blob, "another-secret", 3600))

    def test_tampered_garbage_and_empty_are_rejected_without_raising(self):
        blob = token_vault.seal(TOKEN, _exp(timedelta(days=1)), SECRET)
        for bad in (blob[:-3] + "AAA", "garbage", "", None, 123):
            self.assertIsNone(token_vault.unseal(bad, SECRET, 3600), repr(bad))

    def test_expired_token_and_too_old_blob_are_rejected(self):
        self.assertIsNone(token_vault.unseal(token_vault.seal(TOKEN, _exp(timedelta(seconds=-5)), SECRET), SECRET, 3600))
        self.assertIsNone(token_vault.unseal(token_vault.seal(TOKEN, _exp(timedelta(days=1)), SECRET), SECRET, -1))

    def test_a_bearer_that_is_merely_signed_the_old_way_is_not_accepted(self):
        from itsdangerous import URLSafeTimedSerializer
        old = URLSafeTimedSerializer(SECRET, salt="f2f-bearer").dumps({"t": TOKEN, "exp": _exp(timedelta(days=1))})
        self.assertIsNone(token_vault.unseal(old, SECRET, 3600))


class CorsTests(unittest.TestCase):
    def test_unset_or_blank_origin_means_localhost_only_never_a_wildcard(self):
        for unset in (None, "", "   "):
            origins = a._allowed_origins(unset)
            self.assertNotIn("*", origins)
            self.assertEqual(origins, ["http://localhost:3000", "http://127.0.0.1:3000"])

    def test_a_configured_origin_is_the_only_one_and_a_trailing_slash_is_tolerated(self):
        self.assertEqual(a._allowed_origins("https://app.example.com"), ["https://app.example.com"])
        self.assertEqual(a._allowed_origins(" https://app.example.com/ "), ["https://app.example.com"])

    def test_the_running_app_refuses_a_foreign_origin(self):
        c = TestClient(a.app)
        r = c.options("/api/scan", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("access-control-allow-origin", r.headers)

    def test_methods_and_headers_are_listed_not_wildcards(self):
        c = TestClient(a.app)
        origin = a._allowed_origins(a._frontend_origin)[0]
        ok = c.options("/api/scan", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization, content-type"})
        self.assertEqual(ok.status_code, 200)
        self.assertNotEqual(ok.headers["access-control-allow-headers"].strip(), "*")
        denied = c.options("/api/scan", headers={"Origin": origin, "Access-Control-Request-Method": "DELETE"})
        self.assertEqual(denied.status_code, 400)


class LoginFlowEndToEndTests(unittest.TestCase):
    """login -> callback -> status -> session-token -> an authenticated call with ONLY the bearer -> logout, with Swiggy's
    own token endpoint stubbed. The cookie is Secure, so the client must speak https for the cookie jar to send it."""

    def setUp(self):
        self.client = TestClient(a.app, base_url="https://testserver", follow_redirects=False)

    def _token_response(self, *_a, **_k):
        return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 3600}, request=httpx.Request("POST", "https://mcp.swiggy.com/auth/token"))

    def _log_in(self):
        with patch.object(a, "_get_swiggy_client_id", AsyncMock(return_value="cid")), patch.object(httpx.AsyncClient, "post", AsyncMock(side_effect=self._token_response)):
            login = self.client.get("/auth/login?next=/")
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(login.headers["location"]).query)["state"][0]
            return self.client.get(f"/auth/callback?code=abc&state={state}")

    def test_the_whole_flow(self):
        callback = self._log_in()
        self.assertEqual(callback.status_code, 307)  # back to the app

        status = self.client.get("/auth/status").json()
        self.assertTrue(status["authenticated"])

        st = self.client.get("/auth/session-token")
        body = st.json()
        self.assertTrue(body["authenticated"])
        self.assertEqual(st.headers["cache-control"], "no-store")

        # Nothing the browser can see contains the Swiggy token: not the response, not the cookie's decoded payload.
        self.assertNotIn(TOKEN, json.dumps(body))
        cookie = self.client.cookies.get("session")
        payload = base64.b64decode(cookie.split(".")[0] + "=" * (-len(cookie.split(".")[0]) % 4))
        self.assertNotIn(TOKEN.encode(), payload)
        self.assertIn(b"swiggy", payload)
        # What the page holds is genuinely encrypted (only the server key opens it), not just re-encoded.
        self.assertEqual(token_vault.unseal(body["token"], a._SECRET_KEY, 3600)[0], TOKEN)
        self.assertIsNone(token_vault.unseal(body["token"], "some-other-key", 3600))

        # An authenticated call with no cookie at all, only the bearer, reaches the route with the REAL Swiggy token.
        bare = TestClient(a.app)
        with patch.object(instamart_orders, "list_orders", AsyncMock(return_value={"orders": [], "hasMore": False})) as fn:
            r = bare.post("/api/instamart/orders", json={}, headers={"Authorization": f"Bearer {body['token']}"})
        self.assertTrue(r.json()["ok"])
        self.assertEqual(fn.await_args.args[0], TOKEN)

        # Logout clears the cookie session.
        self.assertEqual(self.client.get("/auth/logout").status_code, 307)
        self.assertFalse(self.client.get("/auth/status").json()["authenticated"])
        self.assertEqual(self.client.get("/auth/session-token").json(), {"authenticated": False})

    def test_a_callback_with_the_wrong_state_stores_nothing(self):
        with patch.object(a, "_get_swiggy_client_id", AsyncMock(return_value="cid")):
            self.client.get("/auth/login")
            r = self.client.get("/auth/callback?code=abc&state=not-the-state")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.client.get("/auth/status").json()["authenticated"])


if __name__ == "__main__":
    unittest.main()
