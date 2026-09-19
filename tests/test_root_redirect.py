"""
GET / on the backend redirects to the frontend (the vanilla page is retired).
Run: python -m unittest tests.test_root_redirect
"""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as a

client = TestClient(a.app)
FRONTEND = "https://frontend.example.app"


class TestRootRedirect(unittest.TestCase):
    def get_root(self):
        return client.get("/", follow_redirects=False)

    def test_redirects_to_frontend_origin(self):
        with patch.object(a, "_frontend_origin", FRONTEND):
            r = self.get_root()
        self.assertEqual((r.status_code, r.headers["location"]), (307, FRONTEND + "/"))

    def test_trailing_slash_in_config_does_not_double_up(self):
        with patch.object(a, "_frontend_origin", FRONTEND + "/"):
            self.assertEqual(self.get_root().headers["location"], FRONTEND + "/")

    def test_falls_back_to_app_base_url(self):
        with patch.object(a, "_frontend_origin", ""), patch.dict(os.environ, {"APP_BASE_URL": FRONTEND}):
            self.assertEqual(self.get_root().headers["location"], FRONTEND + "/")

    def test_never_redirects_to_itself(self):
        with patch.object(a, "_frontend_origin", "http://testserver"):
            r = self.get_root()
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("location", r.headers)

    def test_old_page_is_not_served_anywhere(self):
        with patch.object(a, "_frontend_origin", FRONTEND):
            self.assertNotIn("<html", self.get_root().text.lower())

    def test_other_routes_are_unaffected(self):
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(client.get("/auth/status").json(), {"authenticated": False, "expires_at": None})


if __name__ == "__main__":
    unittest.main()
