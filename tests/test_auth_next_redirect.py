"""
Self-check for _safe_next_path (app.py) — the open-redirect guard on the
Swiggy OAuth `next` param. Run: python -m unittest tests.test_auth_next_redirect
"""

import unittest

from app import _safe_next_path


class TestSafeNextPath(unittest.TestCase):
    def test_missing_or_empty_defaults_to_root(self):
        self.assertEqual(_safe_next_path(None), "/")
        self.assertEqual(_safe_next_path(""), "/")

    def test_relative_paths_pass_through(self):
        self.assertEqual(_safe_next_path("/"), "/")
        self.assertEqual(_safe_next_path("/order"), "/order")
        self.assertEqual(_safe_next_path("/order?resume=1"), "/order?resume=1")

    def test_absolute_urls_rejected(self):
        self.assertEqual(_safe_next_path("http://evil.com"), "/")
        self.assertEqual(_safe_next_path("https://evil.com/phish"), "/")

    def test_protocol_relative_rejected(self):
        self.assertEqual(_safe_next_path("//evil.com"), "/")

    def test_non_http_scheme_rejected(self):
        self.assertEqual(_safe_next_path("javascript:alert(1)"), "/")

    def test_schemeless_host_rejected(self):
        # Not a leading-slash path, so it's not a valid relative redirect
        # even though urlsplit sees no scheme/netloc for it.
        self.assertEqual(_safe_next_path("evil.com"), "/")


if __name__ == "__main__":
    unittest.main()
