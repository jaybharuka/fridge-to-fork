"""
Phase A tests — db.py schema round-trip + seed_canonical_ingredients.py
seed-data integrity. In-memory sqlite only; never touches a real file, the
live app, or any other test's state.
"""

from fridge_to_fork import db
from fridge_to_fork.seed_canonical_ingredients import _build_seed_rows, seed
from fridge_to_fork.step2_meal_planner import _FRIDGE_STAPLES, _PANTRY_ONLY_STAPLES, _PHRASE_SYNONYMS, _STAPLES


async def _fresh_conn():
    ctx = db.get_connection(":memory:")
    conn = await ctx.__aenter__()
    await db.init_db(conn)
    return ctx, conn


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------

async def test_create_scan_and_fetch():
    ctx, conn = await _fresh_conn()
    try:
        scan_id = await db.create_scan(conn, user_session_id="sess-123")
        scan = await db.get_scan(conn, scan_id)
        assert scan is not None
        assert scan["user_session_id"] == "sess-123"
        assert scan["status"] == "pending_review"
    finally:
        await ctx.__aexit__(None, None, None)


async def test_add_item_and_list_items_round_trip():
    ctx, conn = await _fresh_conn()
    try:
        scan_id = await db.create_scan(conn)
        item_id = await db.add_item(
            conn, scan_id,
            name="bell pepper", category="specialty",
            quantity_type="count", quantity_value="2", quantity_unit="piece",
            confidence=82.0, tier="confirmed", needs_confirmation=0,
            possible_matches=[],
        )
        assert item_id > 0

        items = await db.list_items(conn, scan_id)
        assert len(items) == 1
        item = items[0]
        assert item["name"] == "bell pepper"
        assert item["quantity_value"] == "2"
        assert item["tier"] == "confirmed"
        assert item["possible_matches"] == []  # JSON round-trips to a real list, not a string
    finally:
        await ctx.__aexit__(None, None, None)


async def test_uncertain_item_carries_possible_matches():
    ctx, conn = await _fresh_conn()
    try:
        scan_id = await db.create_scan(conn)
        await db.add_item(
            conn, scan_id,
            name="dal (unreadable packet)", category="specialty",
            confidence=55.0, tier="uncertain", needs_confirmation=1,
            possible_matches=["moong dal", "toor dal", "masoor dal"],
        )
        items = await db.list_items(conn, scan_id)
        assert items[0]["needs_confirmation"] == 1
        assert items[0]["possible_matches"] == ["moong dal", "toor dal", "masoor dal"]
    finally:
        await ctx.__aexit__(None, None, None)


async def test_removed_items_excluded_by_default():
    ctx, conn = await _fresh_conn()
    try:
        scan_id = await db.create_scan(conn)
        await db.add_item(conn, scan_id, name="milk", removed=1)
        await db.add_item(conn, scan_id, name="eggs", removed=0)

        assert [i["name"] for i in await db.list_items(conn, scan_id)] == ["eggs"]
        assert {i["name"] for i in await db.list_items(conn, scan_id, include_removed=True)} == {"milk", "eggs"}
    finally:
        await ctx.__aexit__(None, None, None)


async def test_deleting_scan_cascades_to_items():
    ctx, conn = await _fresh_conn()
    try:
        scan_id = await db.create_scan(conn)
        await db.add_item(conn, scan_id, name="cheese")
        await conn.execute("DELETE FROM fridge_scans WHERE id = ?", (scan_id,))
        await conn.commit()

        cursor = await conn.execute("SELECT COUNT(*) AS n FROM fridge_items WHERE scan_id = ?", (scan_id,))
        row = await cursor.fetchone()
        assert row["n"] == 0
    finally:
        await ctx.__aexit__(None, None, None)


async def test_upsert_canonical_ingredient_is_idempotent_and_updates():
    ctx, conn = await _fresh_conn()
    try:
        id1 = await db.upsert_canonical_ingredient(conn, "bell pepper", ["capsicum"], "specialty")
        id2 = await db.upsert_canonical_ingredient(conn, "bell pepper", ["capsicum", "shimla mirch"], "specialty")
        assert id1 == id2  # same row, not a duplicate

        rows = await db.list_canonical_ingredients(conn)
        assert len(rows) == 1
        assert rows[0]["aliases"] == ["capsicum", "shimla mirch"]  # the update took
    finally:
        await ctx.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Seed-data integrity
# ---------------------------------------------------------------------------

async def test_seed_produces_no_duplicate_canonical_names():
    ctx, conn = await _fresh_conn()
    try:
        await seed(conn)
        rows = await db.list_canonical_ingredients(conn)
        names = [r["canonical_name"] for r in rows]
        assert len(names) == len(set(names))
    finally:
        await ctx.__aexit__(None, None, None)


async def test_seed_is_idempotent():
    """Running seed() twice must not duplicate or error (matches a real
    redeploy re-running it, or a manual re-run)."""
    ctx, conn = await _fresh_conn()
    try:
        first_count = await seed(conn)
        rows_after_first = await db.list_canonical_ingredients(conn)
        await seed(conn)
        rows_after_second = await db.list_canonical_ingredients(conn)
        assert len(rows_after_first) == len(rows_after_second) == first_count
    finally:
        await ctx.__aexit__(None, None, None)


async def test_seed_covers_every_source_name():
    """Every name step2_meal_planner.py's own vocabulary sets know about
    must appear in the seed as either a canonical_name or an alias — the
    seed script's job is to structure that existing vocabulary, not narrow
    it, so nothing from the source sets should be silently dropped."""
    rows = _build_seed_rows()
    covered = {name for name, _, _ in rows} | {a for _, aliases, _ in rows for a in aliases}

    source_names = set(_STAPLES) | _FRIDGE_STAPLES | _PANTRY_ONLY_STAPLES | set(_PHRASE_SYNONYMS.keys())
    missing = source_names - covered
    assert not missing, f"names present in step2_meal_planner.py's vocabulary but missing from the seed: {missing}"


async def test_seed_categories_are_valid():
    ctx, conn = await _fresh_conn()
    try:
        await seed(conn)
        rows = await db.list_canonical_ingredients(conn)
        assert all(r["category"] in {"staple", "specialty", "perishable"} for r in rows)
    finally:
        await ctx.__aexit__(None, None, None)
