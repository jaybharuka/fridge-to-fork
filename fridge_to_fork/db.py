"""
Database foundation — Phase A of the fridge-scan accuracy overhaul.

Not wired into app.py, step1_fridge_vision.py, step2_meal_planner.py, or
instamart.py yet (that's Phase C, "Persistence wiring") — this module is
additive-only and importing it has zero effect on anything currently live.

Connection layer: aiosqlite (already a declared dependency, unused until
now) against a local file, NOT Turso yet. Turso is libSQL, which is
SQLite-wire-compatible, so the schema/DDL below and the CRUD helpers are
expected to carry over unchanged when Phase C swaps the connection layer to
a Turso client — only get_connection() below should need to change then.
Deliberately not guessing a Turso Python package name now: a quick check
turned up conflicting current package names for it (the ecosystem has
churned), so that pick is deferred to Phase C, where it can be verified by
actually installing and testing it rather than assumed here.

Schema — the minimum viable tables from the accuracy-overhaul plan, Phase 9:
  CanonicalIngredient — one row per canonical ingredient concept (e.g.
    "bell pepper"), with its known aliases (e.g. "capsicum") and category.
    Seeded from step2_meal_planner.py's existing _PHRASE_SYNONYMS/_STAPLES/
    _FRIDGE_STAPLES/_PANTRY_ONLY_STAPLES sets — see seed_canonical_ingredients.py.
  FridgeScan — one row per fridge-photo scan (or manual/recipe-only entry).
  FridgeItem — one row per detected/added ingredient within a scan, with the
    tier (confirmed/probable/uncertain) and quantity fields the vision-schema
    extension (Phase B) will populate.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

import aiosqlite

# Local file by default (dev/test). Phase C points this at Turso instead —
# until then, matches Render's ephemeral disk fine for local dev since
# nothing writes here from the live app yet.
DEFAULT_DB_PATH = os.environ.get("FRIDGE_DB_PATH", "fridge_to_fork.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_ingredients (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE,
    aliases       TEXT NOT NULL DEFAULT '[]',  -- JSON array of strings
    category      TEXT NOT NULL DEFAULT 'specialty'
        CHECK (category IN ('staple', 'specialty', 'perishable'))
);

CREATE TABLE IF NOT EXISTS fridge_scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_session_id TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    status          TEXT NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'confirmed'))
);

CREATE TABLE IF NOT EXISTS fridge_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id           INTEGER NOT NULL REFERENCES fridge_scans(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    canonical_id      INTEGER REFERENCES canonical_ingredients(id),
    category          TEXT NOT NULL DEFAULT 'specialty',
    quantity_type     TEXT CHECK (quantity_type IN ('count', 'level')),
    quantity_value    TEXT,
    quantity_unit     TEXT,
    state             TEXT,
    confidence        REAL NOT NULL DEFAULT 0,
    tier              TEXT NOT NULL DEFAULT 'uncertain'
        CHECK (tier IN ('confirmed', 'probable', 'uncertain')),
    needs_confirmation INTEGER NOT NULL DEFAULT 0,
    possible_matches  TEXT NOT NULL DEFAULT '[]',  -- JSON array of strings
    user_edited       INTEGER NOT NULL DEFAULT 0,
    removed           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_fridge_items_scan_id ON fridge_items(scan_id);
"""


@asynccontextmanager
async def get_connection(db_path: str | None = None) -> AsyncIterator[aiosqlite.Connection]:
    """One connection, foreign keys on (off by default in sqlite), row access by column name."""
    conn = await aiosqlite.connect(db_path or DEFAULT_DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        await conn.close()


async def init_db(conn: aiosqlite.Connection) -> None:
    await conn.executescript(SCHEMA)
    await conn.commit()


# ---------------------------------------------------------------------------
# Minimal CRUD — enough for Phase A's round-trip tests and for Phase C to
# build on; app.py does not call any of this yet.
# ---------------------------------------------------------------------------

async def create_scan(conn: aiosqlite.Connection, user_session_id: str | None = None) -> int:
    cursor = await conn.execute(
        "INSERT INTO fridge_scans (user_session_id) VALUES (?)", (user_session_id,)
    )
    await conn.commit()
    return cursor.lastrowid


async def add_item(conn: aiosqlite.Connection, scan_id: int, **fields: Any) -> int:
    """fields: any subset of fridge_items' columns except id/scan_id. possible_matches,
    if given as a list, is JSON-encoded automatically."""
    if isinstance(fields.get("possible_matches"), list):
        fields["possible_matches"] = json.dumps(fields["possible_matches"])
    columns = ["scan_id", *fields.keys()]
    placeholders = ", ".join("?" for _ in columns)
    values = [scan_id, *fields.values()]
    cursor = await conn.execute(
        f"INSERT INTO fridge_items ({', '.join(columns)}) VALUES ({placeholders})", values
    )
    await conn.commit()
    return cursor.lastrowid


async def get_scan(conn: aiosqlite.Connection, scan_id: int) -> Optional[dict]:
    cursor = await conn.execute("SELECT * FROM fridge_scans WHERE id = ?", (scan_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_items(conn: aiosqlite.Connection, scan_id: int, *, include_removed: bool = False) -> list[dict]:
    query = "SELECT * FROM fridge_items WHERE scan_id = ?"
    if not include_removed:
        query += " AND removed = 0"
    cursor = await conn.execute(query, (scan_id,))
    rows = await cursor.fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["possible_matches"] = json.loads(item["possible_matches"] or "[]")
        items.append(item)
    return items


# Columns a caller (Phase C's PATCH route) may edit on an existing item —
# an explicit allowlist, not "whatever keys the request body happened to
# have," so a request can never touch id/scan_id/canonical_id/tier/
# confidence/needs_confirmation/possible_matches through this path (those
# are vision-assigned or system-assigned, not user-editable fields).
EDITABLE_ITEM_FIELDS = {"name", "category", "quantity_type", "quantity_value", "quantity_unit", "state", "removed"}


async def get_item(conn: aiosqlite.Connection, item_id: int) -> Optional[dict]:
    cursor = await conn.execute("SELECT * FROM fridge_items WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    item = dict(row)
    item["possible_matches"] = json.loads(item["possible_matches"] or "[]")
    return item


async def update_item(conn: aiosqlite.Connection, item_id: int, **fields: Any) -> Optional[dict]:
    """Returns the updated item, or None if item_id doesn't exist. Raises
    ValueError for any field not in EDITABLE_ITEM_FIELDS — fails fast on a
    caller mistake rather than silently ignoring it (or worse, silently
    accepting it if the allowlist is ever loosened carelessly later)."""
    unknown = set(fields) - EDITABLE_ITEM_FIELDS
    if unknown:
        raise ValueError(f"not editable: {unknown}")
    if not fields:
        return await get_item(conn, item_id)
    assignments = ", ".join(f"{col} = ?" for col in fields)
    await conn.execute(
        f"UPDATE fridge_items SET {assignments} WHERE id = ?", [*fields.values(), item_id]
    )
    await conn.commit()
    return await get_item(conn, item_id)


async def confirm_scan(conn: aiosqlite.Connection, scan_id: int) -> Optional[dict]:
    await conn.execute("UPDATE fridge_scans SET status = 'confirmed' WHERE id = ?", (scan_id,))
    await conn.commit()
    return await get_scan(conn, scan_id)


async def upsert_canonical_ingredient(
    conn: aiosqlite.Connection, canonical_name: str, aliases: list[str], category: str
) -> int:
    """Idempotent — re-running the seed script (or seeding twice) never duplicates a canonical name."""
    await conn.execute(
        """INSERT INTO canonical_ingredients (canonical_name, aliases, category)
           VALUES (?, ?, ?)
           ON CONFLICT(canonical_name) DO UPDATE SET aliases = excluded.aliases, category = excluded.category""",
        (canonical_name, json.dumps(aliases), category),
    )
    await conn.commit()
    cursor = await conn.execute(
        "SELECT id FROM canonical_ingredients WHERE canonical_name = ?", (canonical_name,)
    )
    row = await cursor.fetchone()
    return row["id"]


async def list_canonical_ingredients(conn: aiosqlite.Connection) -> list[dict]:
    cursor = await conn.execute("SELECT * FROM canonical_ingredients ORDER BY canonical_name")
    rows = await cursor.fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["aliases"] = json.loads(item["aliases"] or "[]")
        items.append(item)
    return items
