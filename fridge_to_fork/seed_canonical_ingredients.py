"""
Seeds canonical_ingredients from the vocabulary step2_meal_planner.py
already maintains by hand (_PHRASE_SYNONYMS, _STAPLES, _FRIDGE_STAPLES,
_PANTRY_ONLY_STAPLES) — read-only import, does not modify that module.
Phase A only: nothing here is called by app.py yet.

Those source sets are flat (no English/Hindi or singular/plural grouping),
so the groupings below are a one-time hand-curation of that existing
vocabulary into (canonical_name, aliases, category) rows — not new
ingredient knowledge, just structuring what the matcher already implied.

Idempotent: re-running (locally, or in CI) only upserts, never duplicates
(see db.upsert_canonical_ingredient's ON CONFLICT).

Run standalone:
    python -m fridge_to_fork.seed_canonical_ingredients
"""

from __future__ import annotations

import asyncio

from . import db
from .step2_meal_planner import _FRIDGE_STAPLES, _PANTRY_ONLY_STAPLES, _PHRASE_SYNONYMS, _STAPLES

# (canonical_name, aliases, category) — hand-grouped from the flat source
# sets above. _STAPLES entries not already covered by the more specific
# _FRIDGE_STAPLES/_PANTRY_ONLY_STAPLES groupings below are appended as
# their own single-alias-free rows at the end, so nothing from any source
# set is silently dropped.
_FRIDGE_STAPLE_GROUPS: list[tuple[str, list[str], str]] = [
    ("tomato", ["tomatoes"], "staple"),
    ("onion", ["onions", "pyaz"], "staple"),
    ("garlic", ["lahsun"], "staple"),
    ("ginger", ["adrak"], "staple"),
    ("green chilli", ["green chillies", "hari mirch"], "staple"),
    ("lemon", ["nimbu"], "staple"),
    ("lime", [], "staple"),
    ("coriander leaves", ["fresh coriander", "cilantro", "dhania"], "staple"),
    ("mint leaves", ["pudina"], "staple"),
    ("curry leaves", [], "staple"),
]

_PANTRY_STAPLE_GROUPS: list[tuple[str, list[str], str]] = [
    ("salt", [], "staple"),
    ("water", [], "staple"),
    ("oil", [], "staple"),
    ("sugar", [], "staple"),
    ("atta", ["maida", "flour"], "staple"),
    ("turmeric", ["turmeric powder", "haldi"], "staple"),
    ("cumin powder", ["jeera powder"], "staple"),
    ("coriander powder", ["dhania powder"], "staple"),
    ("red chilli powder", ["lal mirch powder"], "staple"),
    ("garam masala", [], "staple"),
    ("black pepper", ["pepper powder"], "staple"),
    ("mustard seeds", ["rai"], "staple"),
    ("asafoetida", ["hing"], "staple"),
    ("carom seeds", ["ajwain"], "staple"),
    ("fennel seeds", ["saunf"], "staple"),
    ("bay leaf", ["tej patta"], "staple"),
    ("cardamom", ["elaichi"], "staple"),
    ("cloves", ["laung"], "staple"),
    ("cinnamon", ["dalchini"], "staple"),
    ("star anise", ["chakra phool"], "staple"),
    ("dry red chilli", ["dried red chilli"], "staple"),
    ("ghee", [], "staple"),
    ("butter", [], "staple"),
    ("vinegar", [], "staple"),
    ("baking soda", [], "staple"),
    ("baking powder", [], "staple"),
]

# capsicum/bell-pepper and any future _PHRASE_SYNONYMS entries — the
# replacement is the canonical name, the key is the one known alias so far.
_PHRASE_SYNONYM_GROUPS: list[tuple[str, list[str], str]] = [
    (replacement, [phrase], "specialty") for phrase, replacement in _PHRASE_SYNONYMS.items()
]


def _build_seed_rows() -> list[tuple[str, list[str], str]]:
    rows = [*_FRIDGE_STAPLE_GROUPS, *_PANTRY_STAPLE_GROUPS, *_PHRASE_SYNONYM_GROUPS]
    covered_names = {name for name, _, _ in rows} | {
        alias for _, aliases, _ in rows for alias in aliases
    }
    # _STAPLES entries not already represented above (by name or alias) —
    # appended with no aliases rather than dropped, so every source set is
    # fully accounted for in the seeded table.
    for name in _STAPLES:
        if name not in covered_names:
            rows.append((name, [], "staple"))
            covered_names.add(name)
    return rows


async def seed(conn) -> int:
    """Returns the number of canonical_ingredients rows upserted."""
    await db.init_db(conn)
    rows = _build_seed_rows()
    for canonical_name, aliases, category in rows:
        await db.upsert_canonical_ingredient(conn, canonical_name, aliases, category)
    return len(rows)


async def main() -> None:
    async with db.get_connection() as conn:
        count = await seed(conn)
        print(f"Seeded {count} canonical ingredients into {db.DEFAULT_DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
