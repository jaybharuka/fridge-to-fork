"""
fridge_to_fork/ingredient_matching.py

One shared, strict "is this the same ingredient?" rule, used by:
  * step1 dedupe          (replaces _deduplicate_items' "any shared 4+ letter word")
  * step1 blacklist       (replaces word-subset matching in _is_blacklisted)
  * step2 fridge matching (replaces two-way subset in _fuzzy_ingredient_match)
  * step2 pantry checks   (replaces raw word-subset in _classify_ingredient_status
                           and the one-way subset in _is_vision_blocked)

Rule: two names are the same ingredient only if
  1. they have the same head noun (last meaningful word), and
  2. one name's words are a subset of the other's, and
  3. every extra word is a harmless variety modifier (colour, "baby", "cherry"...).

So "red bell pepper" == "bell pepper", but "coconut milk" != "milk",
"green peas" != "green chilli", "coriander powder" != "fresh coriander".
"""

import re

_DESCRIPTIVE_WORDS = {
    "fresh", "chopped", "whole", "medium", "large", "small", "grated",
    "sliced", "minced", "dried", "ripe", "raw", "boiled", "cooked",
    "or", "and", "of", "the", "a",
}

_SPELLING_VARIANTS = {
    "chili": "chilli", "chilies": "chilli", "chily": "chilli", "chilly": "chilli",
    "yogurt": "yoghurt", "curd": "yoghurt",
}

_IRREGULAR_PLURALS = {"leaves": "leaf", "loaves": "loaf", "halves": "half"}

_PHRASE_SYNONYMS = {
    "capsicum": "bell pepper",
    "methi": "fenugreek",
    "dhania": "coriander",
    "cilantro": "coriander",
    "pudina": "mint",
    "lauki": "bottle gourd",
}

# Words describing the *form* an ingredient comes in, dropped from the end of
# a name before comparing ("garlic cloves" -> "garlic", "mint leaves" -> "mint")
_FORM_WORDS = {"leaf", "sprig", "bunch", "piece", "clove", "stick", "block", "pod"}
# ...except where dropping them names a different thing ("curry leaf" is not "curry")
_KEEP_FORM_AFTER = {"curry", "bay", "banana"}

# Extra words allowed between two names that still mean the same ingredient.
_SAFE_MODIFIERS = {
    "red", "green", "yellow", "orange", "white", "purple",
    "baby", "cherry", "button", "english",
}


def normalize(name: str) -> list[str]:
    """Lowercase, apply synonyms, drop descriptive words, singularize.
    Returns an ordered word list (order matters: last word = head noun)."""
    s = name.lower()
    for phrase, replacement in _PHRASE_SYNONYMS.items():
        s = re.sub(rf"\b{re.escape(phrase)}\b", replacement, s)
    words = []
    for w in re.findall(r"[a-z]+", s):
        if w in _DESCRIPTIVE_WORDS:
            continue
        if w in _IRREGULAR_PLURALS:
            w = _IRREGULAR_PLURALS[w]
        elif w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("oes") and len(w) > 4:
            w = w[:-2]
        elif w.endswith("s") and len(w) > 3 and not w.endswith("ss"):
            w = w[:-1]
        words.append(_SPELLING_VARIANTS.get(w, w))
    return words


def core_words(name: str) -> list[str]:
    words = normalize(name)
    while len(words) > 1 and words[-1] in _FORM_WORDS and words[-2] not in _KEEP_FORM_AFTER:
        words = words[:-1]
    return words


def same_ingredient(a: str, b: str) -> bool:
    wa, wb = core_words(a), core_words(b)
    if not wa or not wb or wa[-1] != wb[-1]:
        return False
    sa, sb = set(wa), set(wb)
    if sa <= sb:
        extra = sb - sa
    elif sb <= sa:
        extra = sa - sb
    else:
        return False
    return extra <= _SAFE_MODIFIERS


def matches_any(name: str, candidates: list[str]) -> bool:
    return any(same_ingredient(name, c) for c in candidates)


def recipe_item_in_fridge(recipe_name: str, fridge_names: list[str]) -> bool:
    """Like matches_any, plus one deliberate exception: an "X-Y paste" the
    user can make themselves counts as present when every part was seen
    ("ginger-garlic paste" needs both ginger AND garlic, not just one)."""
    if matches_any(recipe_name, fridge_names):
        return True
    words = core_words(recipe_name)
    if len(words) >= 2 and words[-1] == "paste":
        return all(matches_any(part, fridge_names) for part in words[:-1])
    return False


def dedupe_detections(items: list[dict]) -> list[dict]:
    """Drop-in replacement for step1's _deduplicate_items(): keeps the
    highest-confidence report of each ingredient, merging only true variants."""
    kept: list[dict] = []
    for item in sorted(items, key=lambda x: x.get("confidence", 0), reverse=True):
        if not any(same_ingredient(item["name"], k["name"]) for k in kept):
            kept.append(item)
    return kept


# ---------------------------------------------------------------------------
# Vision blacklist (replaces step1's VISION_BLACKLIST + _is_blacklisted)
# ---------------------------------------------------------------------------

# Blocked only when this is the WHOLE name ("sauce" is blocked, "soy sauce"
# is not; "bottle" is blocked, "bottle gourd" is not).
GENERIC_NAMES = {
    "food", "vegetable", "fruit", "produce", "beverage", "drink", "dairy",
    "herb", "spice", "spices", "masala", "condiment", "condiments", "sauce",
    "ingredient", "snack", "groceries", "water", "water bottle",
    "container", "steel container", "plastic container", "glass container",
    "jar", "bottle", "packet", "package", "wrapper", "box", "carton", "bag",
    "plastic bag", "pouch", "dabba", "tiffin", "utensil", "vessel", "pot",
    "pan", "bowl", "plate", "tray",
}

# Dry pantry goods a fridge photo can't really show. Matched with the strict
# same_ingredient() rule, so "fenugreek leaves" and "bell pepper" survive.
PANTRY_ONLY = [
    "sugar", "flour", "atta", "maida", "salt", "oil",
    "cardamom", "cinnamon", "cloves", "star anise", "mace", "nutmeg",
    "black pepper", "white pepper", "cumin", "cumin seeds", "coriander powder",
    "turmeric", "chilli powder", "red chilli powder", "garam masala", "bay leaf",
    "mustard seeds", "fenugreek seeds", "asafoetida", "hing",
]

# Not blocked. Accepted from vision only at very high confidence, because
# wrapped packets are easy to misread as meat.
HIGH_BAR_ITEMS = ["chicken", "fish", "meat", "mutton", "lamb", "prawn", "shrimp"]
HIGH_BAR_CONFIDENCE = 90

# Also not blocked (a container of leftover rice or dal is a real, common
# fridge item — the old blacklist wrongly blocked these outright, see
# FRIDGE_SCAN_FIX_REPORT.md F2). But a bag/container of pale dry goods is
# about as easy to misidentify at a glance as a wrapped meat packet, so
# it gets the same high-confidence bar rather than a free pass — kept as
# its own list/constant (not folded into HIGH_BAR_ITEMS) so the two can be
# tuned independently later.
DRY_GOODS_HIGH_BAR = ["rice", "dal", "lentil", "lentils"]
DRY_GOODS_HIGH_BAR_CONFIDENCE = 90

# Pantry items that ALSO exist as a real fresh/root form Gemini can
# genuinely see in a fridge — unlike sugar/flour/salt, which never do.
# normalize() strips "fresh"/"dried"/"raw" etc. as no-op descriptive
# words for MATCHING purposes (so "fresh turmeric" and "dried turmeric"
# both reduce to the same {"turmeric"} core), which is exactly why
# is_blocked_detection() below checks the raw name for "fresh"/"root"
# instead of relying on core_words() to tell them apart.
_HAS_FRESH_FORM = {"turmeric"}

_HIGH_BAR_WORDS = {w for m in HIGH_BAR_ITEMS for w in core_words(m)}
_DRY_GOODS_WORDS = {w for m in DRY_GOODS_HIGH_BAR for w in core_words(m)}
_GENERIC_KEYS = {" ".join(core_words(g)) for g in GENERIC_NAMES}


def is_blocked_detection(name: str) -> bool:
    if " ".join(core_words(name)) in _GENERIC_KEYS:
        return True
    if not matches_any(name, PANTRY_ONLY):
        return False
    if set(core_words(name)) & _HAS_FRESH_FORM:
        lower = name.lower()
        if "fresh" in lower or "root" in lower:
            return False  # e.g. "fresh turmeric" — the rhizome, not the spice jar
    return True


def passes_confidence(name: str, confidence: int, floor: int = 60) -> bool:
    words = set(core_words(name))
    if words & _HIGH_BAR_WORDS:
        return confidence >= HIGH_BAR_CONFIDENCE
    if words & _DRY_GOODS_WORDS:
        return confidence >= DRY_GOODS_HIGH_BAR_CONFIDENCE
    return confidence >= floor
