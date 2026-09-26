"""
Phase C — HTTP tests for the new /api/fridge-scans routes (scan_routes.py).
Each request opens its own DB connection (db.get_connection()), so tests
point db.DEFAULT_DB_PATH at a shared temp FILE, not ":memory:" — an
in-memory sqlite DB is fresh per connection and would lose all data
between requests within a single test.

Also confirms the isolation claim directly: existing routes (e.g. /health)
still work unaffected by this router's addition.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork import db

client = TestClient(a.app)


class TestScanRoutes(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._db_path_patch = patch.object(db, "DEFAULT_DB_PATH", path)
        self._db_path_patch.start()
        self.db_path = path

    def tearDown(self):
        self._db_path_patch.stop()
        os.unlink(self.db_path)

    def _create_scan(self, ingredients=None):
        body = {
            "ingredients": ingredients if ingredients is not None else [
                {"name": "tomato", "confidence": 0.9, "category": "produce", "tier": "confirmed"},
                {
                    "name": "dal", "confidence": 0.6, "category": "grain_legume", "tier": "uncertain",
                    "needs_confirmation": True, "possible_matches": ["moong dal", "toor dal"],
                    "estimated_quantity": {"type": "count", "value": 1, "unit": "packet"},
                },
            ],
        }
        return client.post("/api/fridge-scans", json=body)

    def test_create_scan_returns_scan_and_items(self):
        r = self._create_scan()
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["scan"]["status"], "pending_review")
        self.assertEqual(len(data["items"]), 2)
        names = {i["name"] for i in data["items"]}
        self.assertEqual(names, {"tomato", "dal"})

    def test_uncertain_item_round_trips_possible_matches_and_quantity(self):
        data = self._create_scan().json()
        dal = next(i for i in data["items"] if i["name"] == "dal")
        self.assertTrue(dal["needs_confirmation"])
        self.assertEqual(dal["possible_matches"], ["moong dal", "toor dal"])
        self.assertEqual(dal["quantity_type"], "count")
        self.assertEqual(dal["quantity_value"], "1")

    def test_get_scan_returns_what_was_created(self):
        scan_id = self._create_scan().json()["scan"]["id"]
        r = client.get(f"/api/fridge-scans/{scan_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["items"]), 2)

    def test_get_nonexistent_scan_is_404(self):
        r = client.get("/api/fridge-scans/999999")
        self.assertEqual(r.status_code, 404)

    def test_patch_item_updates_name_and_quantity(self):
        data = self._create_scan().json()
        item_id = data["items"][0]["id"]
        scan_id = data["scan"]["id"]
        r = client.patch(f"/api/fridge-scans/{scan_id}/items/{item_id}", json={"name": "roma tomato", "quantity_value": "3"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["item"]["name"], "roma tomato")
        self.assertEqual(r.json()["item"]["quantity_value"], "3")

    def test_patch_item_removed_excludes_it_from_get(self):
        data = self._create_scan().json()
        item_id = data["items"][0]["id"]
        scan_id = data["scan"]["id"]
        client.patch(f"/api/fridge-scans/{scan_id}/items/{item_id}", json={"removed": True})
        remaining = client.get(f"/api/fridge-scans/{scan_id}").json()["items"]
        self.assertEqual(len(remaining), 1)

    def test_patch_item_on_wrong_scan_is_404(self):
        data = self._create_scan().json()
        item_id = data["items"][0]["id"]
        other_scan_id = self._create_scan(ingredients=[]).json()["scan"]["id"]
        r = client.patch(f"/api/fridge-scans/{other_scan_id}/items/{item_id}", json={"name": "x"})
        self.assertEqual(r.status_code, 404)

    def test_confirm_scan_sets_status(self):
        scan_id = self._create_scan().json()["scan"]["id"]
        r = client.post(f"/api/fridge-scans/{scan_id}/confirm")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["scan"]["status"], "confirmed")

    def test_confirm_nonexistent_scan_is_404(self):
        r = client.post("/api/fridge-scans/999999/confirm")
        self.assertEqual(r.status_code, 404)

    def test_existing_routes_unaffected(self):
        """Direct check of the isolation claim: adding this router doesn't
        break or shadow anything that already existed."""
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(client.get("/auth/status").json(), {"authenticated": False, "expires_at": None})


if __name__ == "__main__":
    unittest.main()
