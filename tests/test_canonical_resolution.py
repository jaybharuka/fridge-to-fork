"""
Phase D — canonical-ingredient resolution in _fuzzy_ingredient_match.
Seeds a real temp SQLite file via the existing seed_canonical_ingredients
script (same one Phase A's own tests already exercise), points
step2_meal_planner's cache loader at it, and confirms: (a) a genuinely new
capability (Hindi-transliteration matches the word-overlap heuristic alone
can't make), (b) every pre-existing matcher behavior is unaffected, and
(c) the "never a hard dependency" fallback actually degrades gracefully.
"""

import asyncio
import os
import tempfile

import pytest

from fridge_to_fork import db, step2_meal_planner as step2
from fridge_to_fork.seed_canonical_ingredients import seed


@pytest.fixture
def seeded_db(monkeypatch):
    """A real temp DB, seeded, with step2's in-memory cache reset before
    and after so tests don't leak state into each other or into the wider
    suite (module-level caches are exactly the kind of thing that does)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", path)
    monkeypatch.setattr(step2, "_canonical_cache", None)

    async def _seed():
        async with db.get_connection(path) as conn:
            await seed(conn)

    asyncio.run(_seed())
    yield path
    step2._canonical_cache = None
    os.unlink(path)


def test_canonical_resolution_bridges_hindi_transliteration(seeded_db):
    """A real, pre-existing gap: 'onion' and 'pyaz' share zero letters, so
    the word-overlap heuristic alone can never match them - only the
    canonical table (which the seed script grouped them under) can."""
    assert step2._fuzzy_ingredient_match("onion", ["pyaz"]) is True
    assert step2._fuzzy_ingredient_match("garlic", ["lahsun"]) is True
    assert step2._fuzzy_ingredient_match("ginger", ["adrak"]) is True


def test_canonical_resolution_does_not_cross_link_unrelated_items(seeded_db):
    """pyaz (onion) must not suddenly match lahsun (garlic) just because
    both resolve to *some* canonical entry - they must resolve to the
    SAME one."""
    assert step2._fuzzy_ingredient_match("pyaz", ["lahsun"]) is False


def test_existing_word_overlap_matching_still_works(seeded_db):
    """Word-overlap matching (phrase synonyms, pluralization) must be
    unaffected by canonical resolution existing alongside it — but the
    fallback itself is no longer plain subset containment (ingredient_
    matching.py port, 2026-09-30): see test_fuzzy_match_paste_needs_every_part
    below for the one deliberately-changed case."""
    assert step2._fuzzy_ingredient_match("capsicum", ["bell pepper"]) is True
    assert step2._fuzzy_ingredient_match("capsicum", ["black pepper"]) is False
    assert step2._fuzzy_ingredient_match("grapes", ["grape"]) is True
    assert step2._fuzzy_ingredient_match("coriander leaves", ["coriander powder"]) is False


def test_fuzzy_match_paste_needs_every_part(seeded_db):
    """Deliberate behavior change from tonight's ingredient_matching.py port
    (FRIDGE_SCAN_FIX_REPORT.md F3): "ginger-garlic paste" used to count as
    present with just ONE of its two parts in the fridge (plain subset
    containment) — only half true, and one of the named bugs. The strict
    fallback's paste exception now requires every part to be present."""
    assert step2._fuzzy_ingredient_match("ginger-garlic paste", ["ginger"]) is False
    assert step2._fuzzy_ingredient_match("ginger-garlic paste", ["ginger", "garlic"]) is True


def test_no_match_when_neither_side_has_a_canonical_entry(seeded_db):
    assert step2._fuzzy_ingredient_match("saffron", ["quinoa"]) is False


def test_cache_is_loaded_once_and_reused(seeded_db):
    assert step2._canonical_cache is None
    step2._fuzzy_ingredient_match("onion", ["pyaz"])
    assert step2._canonical_cache is not None
    cache_identity = id(step2._canonical_cache)
    step2._fuzzy_ingredient_match("garlic", ["lahsun"])
    assert id(step2._canonical_cache) == cache_identity  # not rebuilt on every call


def test_missing_db_falls_back_to_string_matching_only(monkeypatch):
    """The core 'never a hard dependency' guarantee: a completely absent DB
    file must not raise, and must not break matching that doesn't need the
    canonical table at all."""
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", "/nonexistent/path/does-not-exist.db")
    monkeypatch.setattr(step2, "_canonical_cache", None)
    try:
        assert step2._fuzzy_ingredient_match("onion", ["pyaz"]) is False  # no DB -> no canonical bridge
        assert step2._fuzzy_ingredient_match("grapes", ["grape"]) is True  # string matching still works
    finally:
        step2._canonical_cache = None
