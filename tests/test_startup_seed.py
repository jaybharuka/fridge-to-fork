"""
Phase D — self-healing canonical-ingredient seed on app startup (app.py's
_lifespan). Uses TestClient as a context manager (`with TestClient(app) as
client:`) deliberately — that's what actually triggers FastAPI/Starlette
lifespan startup/shutdown events; a bare `TestClient(app)` (the pattern
every other test file in this suite uses) does not, which is exactly why
those tests never accidentally exercise this and don't need to.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork import db


class TestStartupSeed(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(path)  # start from a genuinely absent file, not just an empty one
        self.db_path = path
        self._db_path_patch = patch.object(db, "DEFAULT_DB_PATH", path)
        self._db_path_patch.start()

    def tearDown(self):
        self._db_path_patch.stop()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_startup_seeds_a_fresh_missing_db(self):
        self.assertFalse(os.path.exists(self.db_path))
        with TestClient(a.app):
            pass  # entering the context is what runs the lifespan startup

        import asyncio

        async def _check():
            async with db.get_connection(self.db_path) as conn:
                return await db.list_canonical_ingredients(conn)

        rows = asyncio.run(_check())
        self.assertGreater(len(rows), 0)
        names = {r["canonical_name"] for r in rows}
        self.assertIn("onion", names)

    def test_startup_seed_is_safe_to_run_twice(self):
        """A restart re-running the (idempotent) seed on an already-seeded
        DB must not duplicate rows or error."""
        with TestClient(a.app):
            pass
        with TestClient(a.app):
            pass

        import asyncio

        async def _check():
            async with db.get_connection(self.db_path) as conn:
                return await db.list_canonical_ingredients(conn)

        rows = asyncio.run(_check())
        names = [r["canonical_name"] for r in rows]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
