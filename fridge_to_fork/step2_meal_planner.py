"""
Step 2 — Meal Planner
=====================
Takes identified fridge contents and uses Google Gemini to:
  1. Suggest 3–5 meals
  2. Decide whether to cook (ingredients present) or order
     (either the finished dish from Swiggy Food, or missing
      ingredients from Swiggy Instamart)

Run standalone:
    python -m fridge_to_fork.step2_meal_planner --ingredients "eggs,butter,cheese,bread"
"""

import argparse
import json
import os
import re
import sqlite3
import time
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import db
from .gemini_keys import load_api_keys
from .ingredient_matching import matches_any, recipe_item_in_fridge
from .models import Decision, FridgeContents, Ingredient, MealPlan, MealSuggestion, RecipeIngredient

load_dotenv()

console = Console()

# Both raw Gemini text calls below (_call_text_model_with_retry_stream,
# generate_top_up_suggestions) were bare generate_content()/
# generate_content_stream() calls with no http_options at all — the exact
# same gap that caused the vision path's 72.6s single-photo anomaly
# (step1_fridge_vision.py's _call_gemini_vision), just never propagated
# here. Left at the SDK's own default (up to 5 internal attempts, backoff
# up to 60s max delay EACH), a single call in either function could
# legitimately take minutes once quota/latency issues hit multiple models
# in TEXT_MODEL_FALLBACK_CHAIN — found live: a real scan got stuck on
# "Still working on it" at the top-up-suggestions stage with no overall
# timeout wrapping app.py's `await top_up_task` to cut it short.
# attempts=1 (no SDK-level retry) rather than raising it: both call sites
# already have their own app-level resilience (the cross-model fallback
# chain in both functions, plus _call_text_model_with_retry_stream's own
# outer retry loop) - an SDK-level retry on an identical slow/loaded model
# rarely helps and only compounds the wait, same reasoning already applied
# to vision.
_TEXT_CALL_HTTP_OPTIONS = types.HttpOptions(
    timeout=25_000,
    retry_options=types.HttpRetryOptions(attempts=1, initial_delay=0.5, max_delay=3.0, exp_base=2.0),
)


# ---------------------------------------------------------------------------
# Fridge / staple matching — the have/missing/staple *decision* is
# deterministic, Python-side (not left to the LLM to self-report, since
# that proved unreliable in practice). What counts as a "staple" is no
# longer a hardcoded list, though: Gemini classifies each recipe
# ingredient's category (staple/specialty/perishable) per-dish as part of
# the meal-planning response (see RecipeIngredient.category, _RECIPE_RULES
# below) — a fixed India-wide staples list can't know that a north Indian
# recipe assumes ghee but a niche regional one doesn't. _STAPLES now only
# backstops _safe_category() when Gemini's category field is missing or
# invalid.
# ---------------------------------------------------------------------------

_STAPLES = [
    "salt", "oil", "ghee", "butter", "water", "flour", "sugar",
    "cumin seeds", "mustard seeds", "turmeric", "red chilli powder",
    "coriander powder", "garam masala", "onions", "garlic", "ginger",
    "green chillies", "potatoes", "tomatoes", "lemon",
]

_DESCRIPTIVE_WORDS = {
    "fresh", "chopped", "whole", "medium", "large", "small", "grated",
    "sliced", "minced", "dried", "ripe", "raw", "boiled", "cooked",
    "or", "and", "of", "the", "a",
}

# Spelling variants that the naive pluralization heuristic below turns
# into different strings (e.g. "chili"/"chilies"/"chilly"/"chily" from
# "chilli"/"chillies") — canonicalize them to one token so they still match.
_SPELLING_VARIANTS = {
    "chili": "chilli", "chilies": "chilli", "chily": "chilli", "chilly": "chilli",
    "yogurt": "yoghurt", "curd": "yoghurt",
}

# Whole-word/phrase synonyms, applied to the raw name BEFORE word-splitting
# (not a single-word canonicalization like _SPELLING_VARIANTS above) —
# vision-accuracy audit (2026-09) found a real "clearly visible item
# reported missing" case: Gemini reporting "capsicum" for a recipe that
# calls it "bell pepper" shared no words at all after normalization, so the
# subset-containment match in _fuzzy_ingredient_match() below never fired
# despite both naming the same vegetable. Deliberately a phrase-level
# substitution rather than mapping the single word "capsicum" -> "pepper":
# that coarser fix would make capsicum/bell-pepper falsely match "black
# pepper" or "pepper powder" (both contain the word "pepper" too) — an
# unrelated spice, not the vegetable. Substituting the whole phrase first
# means "capsicum" only ever contributes the word set {"bell", "pepper"},
# which correctly subset-matches "bell pepper" / "red bell pepper" and
# never touches anything that was never named "capsicum" to begin with.
_PHRASE_SYNONYMS = {
    "capsicum": "bell pepper",
}


def _normalize_ingredient_words(name: str) -> set[str]:
    """Lowercase, apply phrase-level synonyms, strip descriptive words, and
    naively singularize each word so "Fresh Tomatoes" and "tomato" both
    reduce to {"tomato"}."""
    lowered = name.lower()
    for phrase, replacement in _PHRASE_SYNONYMS.items():
        lowered = re.sub(rf"\b{re.escape(phrase)}\b", replacement, lowered)
    words = re.findall(r"[a-z]+", lowered)
    result = set()
    for word in words:
        if word in _DESCRIPTIVE_WORDS:
            continue
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("oes") and len(word) > 4:
            # "-oes" plurals only (tomato/tomatoes, potato/potatoes, mango/mangoes) — a
            # narrower rule than the old blanket "any -es" strip, which also caught
            # regular -s plurals of words already ending in "e" (grape+s, apple+s,
            # olive+s) and mis-stemmed them ("grapes" -> "grap" instead of "grape"),
            # silently breaking the match against a plain "grape" from the fridge scan.
            word = word[:-2]
        elif word.endswith("s") and len(word) > 3:
            word = word[:-1]
        word = _SPELLING_VARIANTS.get(word, word)
        result.add(word)
    return result


# Canonical-ingredient resolution (vision-accuracy overhaul, Phase D) — an
# in-memory {normalized-word-set: canonical_id} cache built once per process
# from the DB-seeded canonical_ingredients table (db.py, seeded by
# seed_canonical_ingredients.py). Deliberately loaded via plain synchronous
# sqlite3, not db.py's async aiosqlite connection: _fuzzy_ingredient_match is
# a hot-path function called deep inside a background thread
# (plan_meals_stream, invoked via app.py's threading.Thread — not an asyncio
# task, so there's no event loop to await against there) from many call
# sites; making it async to query the DB live would cascade that change into
# every caller for a lookup that's better served by an in-memory cache
# anyway. SQLite handles concurrent readers over the same file fine, so this
# coexists safely with Phase C's async CRUD routes.
#
# "Never a hard dependency" (per the original plan): ANY failure loading
# this (DB file missing, table missing, corrupt row) falls back to an empty
# cache, silently — _fuzzy_ingredient_match's existing word-overlap
# comparison below is completely unaffected either way, exactly as before
# Phase D existed.
_canonical_cache: dict[frozenset, int] | None = None


def _load_canonical_cache() -> dict[frozenset, int]:
    global _canonical_cache
    if _canonical_cache is not None:
        return _canonical_cache
    cache: dict[frozenset, int] = {}
    try:
        conn = sqlite3.connect(db.DEFAULT_DB_PATH)
        try:
            rows = conn.execute("SELECT id, canonical_name, aliases FROM canonical_ingredients").fetchall()
            for canonical_id, canonical_name, aliases_json in rows:
                for name in [canonical_name, *json.loads(aliases_json or "[]")]:
                    words = frozenset(_normalize_ingredient_words(name))
                    if words:
                        cache[words] = canonical_id
        finally:
            conn.close()
    except Exception as e:
        console.print(f"[yellow][WARNING] canonical-ingredient cache load failed, falling back to string matching only: {type(e).__name__}: {e}[/yellow]")
    _canonical_cache = cache
    return cache


def _fuzzy_ingredient_match(recipe_name: str, candidate_names: list[str]) -> bool:
    """True if `recipe_name` fuzzy-matches any of `candidate_names` —
    case/plural/descriptive-word insensitive. Tries canonical-ID resolution
    first (e.g. "onion" vs "pyaz" — share zero words, a gap the
    word-overlap comparison below can't close on its own since Hindi
    transliterations don't share letters with their English name), then
    falls back to ingredient_matching.recipe_item_in_fridge()'s strict
    same-head-noun rule.

    The fallback used to be plain subset containment (`candidate_words <=
    recipe_words or recipe_words <= candidate_words`), which produced false
    matches like fridge "milk" matching recipe "coconut milk" — ported from
    main's fridge-scan matching fix (FRIDGE_SCAN_FIX_REPORT.md F3/F4,
    2026-09-30). The canonical-cache lookup above is untouched: it's checked
    first, exactly as before, and only what happens on a cache miss changed.
    "ginger-garlic paste" still matches a plain "ginger" (recipe_item_in_fridge's
    own paste exception, which additionally now correctly requires BOTH
    ginger AND garlic to be present, not just one)."""
    recipe_words = _normalize_ingredient_words(recipe_name)
    if not recipe_words:
        return False
    cache = _load_canonical_cache()
    recipe_canonical = cache.get(frozenset(recipe_words))
    if recipe_canonical is not None:
        for candidate in candidate_names:
            candidate_words = _normalize_ingredient_words(candidate)
            if candidate_words and cache.get(frozenset(candidate_words)) == recipe_canonical:
                return True
    return recipe_item_in_fridge(recipe_name, candidate_names)


# Never stored in a fridge (dry goods / spice jars) — always "staple",
# skip the fridge scan entirely regardless of what Gemini's own category
# field says for them.
_PANTRY_ONLY_STAPLES = {
    'salt', 'water', 'oil', 'sugar', 'atta', 'maida', 'flour',
    'turmeric powder', 'turmeric', 'haldi',
    'cumin powder', 'jeera powder',
    'coriander powder', 'dhania powder',
    'red chilli powder', 'lal mirch powder',
    'garam masala', 'black pepper', 'pepper powder',
    'mustard seeds', 'rai',
    'asafoetida', 'hing',
    'carom seeds', 'ajwain',
    'fennel seeds', 'saunf',
    'bay leaf', 'tej patta',
    'cardamom', 'elaichi',
    'cloves', 'laung',
    'cinnamon', 'dalchini',
    'star anise', 'chakra phool',
    'dry red chilli', 'dried red chilli',
    'ghee', 'butter',
    'vinegar', 'baking soda', 'baking powder',
}

# Commonly kept in an Indian fridge, not just the pantry, and Gemini can
# actually see these in a photo — check the fridge scan before falling
# back to the staple assumption, so a tomato/ginger/garlic Gemini *did*
# spot shows as "in fridge" instead of being silently assumed like salt.
# ("curry leaves" is deliberately NOT in _PANTRY_ONLY_STAPLES above — it
# belongs only here, since it's exactly the kind of fresh item that should
# get a fridge-scan check rather than being assumed sight-unseen.)
_FRIDGE_STAPLES = {
    'tomato', 'tomatoes',
    'onion', 'onions', 'pyaz',
    'garlic', 'lahsun',
    'ginger', 'adrak',
    'green chilli', 'green chillies', 'hari mirch',
    'lemon', 'lime', 'nimbu',
    'coriander leaves', 'fresh coriander', 'cilantro', 'dhania',
    'mint leaves', 'pudina',
    'curry leaves',
}

# Ground/dry spices and pantry basics that vision detection is unreliable
# for (a jar is rarely readable well enough to confirm exactly which spice
# it holds). Built from _PANTRY_ONLY_STAPLES specifically — NOT the old
# flat _STAPLES list, which mixed those in with fresh items (tomatoes,
# onions, garlic, ginger) that are now _FRIDGE_STAPLES and are explicitly
# supposed to be checked against the fridge scan. Blocking those here
# would silently undo that check.
_VISION_BLOCKED_TERMS = list(_PANTRY_ONLY_STAPLES) + [
    "mace", "nutmeg", "kasuri methi", "dried fenugreek", "fenugreek seeds",
]


def _is_vision_blocked(name: str) -> bool:
    return _fuzzy_ingredient_match(name, _VISION_BLOCKED_TERMS)


VALID_CATEGORIES = {"staple", "specialty", "perishable"}


def _safe_category(category: str, ingredient_name: str) -> str:
    """Validate Gemini's per-ingredient category, falling back to a
    keyword guess against _STAPLES (never "have"-by-default beyond that —
    an unrecognized/missing category defaults to "specialty", not
    "staple", so an unclassified ingredient still has to clear the fridge
    match to count as available)."""
    if category in VALID_CATEGORIES:
        return category
    if matches_any(ingredient_name, _STAPLES):
        return "staple"
    return "specialty"


def _classify_ingredient_status(name: str, category: str, fridge_items: list[str]) -> str:
    """
    Returns 'staple', 'have', or 'missing' for one recipe ingredient.
    'staple'  -> pre-checked in the UI, user can uncheck to add to the order
    'have'    -> detected in the fridge scan, pre-checked, not orderable by default
    'missing' -> not found, unchecked, orderable

    Three tiers, checked in order:
    1. _PANTRY_ONLY_STAPLES — never in a fridge photo (salt, spice powders),
       so there's nothing to check; always "staple".
    2. _FRIDGE_STAPLES — commonly kept in the fridge, not just assumed:
       tomato/onion/ginger/garlic/etc. Gemini vision can genuinely see
       these, so the fridge scan gets first say — only falls back to the
       staple assumption if the scan didn't detect it. This intentionally
       overrides whatever Gemini's own `category` field said for these
       specific ingredients (it's told to call them "staple" too, per
       _RECIPE_RULES — that's fine, since the fridge-scan result here
       takes priority over that guess regardless).
    3. Everything else — Gemini's per-dish category call is trusted,
       falling through to the same fridge-scan check for
       specialty/perishable ingredients.
    """
    if matches_any(name, _PANTRY_ONLY_STAPLES):
        return "staple"

    if matches_any(name, _FRIDGE_STAPLES):
        if not _is_vision_blocked(name) and _fuzzy_ingredient_match(name, fridge_items):
            return "have"
        return "staple"

    if category == "staple":
        return "staple"
    if _is_vision_blocked(name):
        return "missing"
    if _fuzzy_ingredient_match(name, fridge_items):
        return "have"
    return "missing"


def _compute_derived_fields(meal: MealSuggestion, fridge_names: list[str]) -> None:
    """
    Fills in missing_ingredients, total_order_price_inr, and
    matched_fridge_items on a single suggestion IN PLACE, from its
    recipe_ingredients' already-classified is_staple/found_in_fridge (see
    _classify_ingredient_status). Pulled out of _enrich_recipe_ingredients()
    so it can run for every suggestion, not just recommended_meal — the
    "Meal Suggestions" picker needs every suggestion's own missing list and
    matched fridge chips to switch instantly, with no new Gemini call, and
    /api/replan's known-suggestion path (app.py) reuses this same function
    for a single meal outside a full MealPlan.
    """
    if not meal or not meal.recipe_ingredients:
        return

    missing = [ri for ri in meal.recipe_ingredients if not (ri.is_staple or ri.found_in_fridge)]
    meal.missing_ingredients = [ri.name for ri in missing]
    meal.total_order_price_inr = sum(ri.estimated_price_inr for ri in missing)

    # Which scanned fridge items (exact detected names) this specific
    # recipe actually uses — same deterministic fuzzy matcher as
    # found_in_fridge above, just from the fridge's side rather than
    # the recipe's, so the fridge chips UI can show relevant items
    # first. Staples are excluded — they're assumed available, so
    # they shouldn't appear as "detected in fridge" chips either.
    # Filters on the computed ri.is_staple (set just above), not the
    # raw ri.category — a _FRIDGE_STAPLES ingredient (tomato, ginger,
    # ...) can resolve to "have" despite Gemini tagging its category
    # "staple", and that one should still show up as a matched chip.
    non_staple_recipe_names = [ri.name for ri in meal.recipe_ingredients if not ri.is_staple]
    meal.matched_fridge_items = [
        name for name in fridge_names
        if not _is_vision_blocked(name) and _fuzzy_ingredient_match(name, non_staple_recipe_names)
    ]


def classify_and_enrich_known_meal(meal: MealSuggestion, fridge: FridgeContents) -> MealSuggestion:
    """
    Public entry point for a meal whose recipe_ingredients are already known
    (the frontend picked one of the suggestions /api/scan already generated
    and sent back its recipe_ingredients as-is) — runs the same deterministic
    classify + derive steps _enrich_recipe_ingredients() runs per-suggestion,
    without needing a MealPlan or a fresh Gemini call. Used by app.py's
    /api/replan for the "known suggestion" case; the "custom free-text dish"
    case instead goes through plan_meals(), which calls
    _enrich_recipe_ingredients() as usual.
    """
    fridge_names = [ing.name for ing in fridge.ingredients]
    for ri in meal.recipe_ingredients or []:
        status = _classify_ingredient_status(ri.name, ri.category, fridge_names)
        ri.is_staple = status == "staple"
        ri.found_in_fridge = status == "have"
    _compute_derived_fields(meal, fridge_names)
    return meal


def _enrich_recipe_ingredients(plan: MealPlan, fridge: FridgeContents) -> MealPlan:
    """
    Deterministically (not via LLM self-report on have/missing — Gemini
    only supplies each ingredient's category, see _RECIPE_RULES) fill in
    is_staple and found_in_fridge on every recipe ingredient, then derive
    each suggestion's missing_ingredients (name + total price) from
    whatever's left unchecked — neither a staple nor detected in the
    fridge photo. Runs for every suggestion (not just recommended_meal) so
    the frontend can switch its active suggestion instantly, with the
    switched-to dish's missing list/matched chips/total price already
    computed — see _compute_derived_fields(). No cook/order_groceries/
    order_dish decision is made here; the user picks for themselves between
    ordering the missing items or ordering the finished dish.
    """
    fridge_names = [ing.name for ing in fridge.ingredients]

    for suggestion in plan.suggestions:
        if not suggestion.recipe_ingredients:
            continue
        for ri in suggestion.recipe_ingredients:
            status = _classify_ingredient_status(ri.name, ri.category, fridge_names)
            ri.is_staple = status == "staple"
            ri.found_in_fridge = status == "have"
        _compute_derived_fields(suggestion, fridge_names)

    # MealPlan.matched_fridge_items mirrors recommended_meal's own — kept for
    # existing callers that read it at the plan level (e.g. app.py's step2
    # "matched_fridge_items" field before this change).
    if plan.recommended_meal:
        plan.matched_fridge_items = plan.recommended_meal.matched_fridge_items

    return plan


def _ascii_safe(value) -> str:
    """
    ASCII-only string repr for logging arbitrary LLM output (emoji, etc.)
    to stdout. Both plain print() and rich's Console() have proven
    unreliable with wide/multi-codepoint Unicode when stdout is a
    redirected (non-TTY) stream rather than a real console.
    """
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


def _dedupe(models: list[str | None]) -> list[str]:
    """Remove falsy/duplicate entries while preserving order."""
    seen = set()
    result = []
    for m in models:
        if m and m not in seen:
            seen.add(m)
            result.append(m)
    return result


# Models tried in order until one succeeds. Each Gemini model has its own
# separate free-tier daily quota, so exhausting one doesn't mean they're
# all exhausted.
#
# Vision-accuracy audit (2026-09): this chain's fourth entry
# (gemini-2.0-flash-lite) is the same dead-model bug found and fixed in
# VISION_MODEL_FALLBACK_CHAIN (step1_fridge_vision.py) — a hard 404 "no
# longer available" from the live API. Removed outright and replaced with
# gemini-3.1-pro-preview appended at the end (same reasoning as the vision
# chain: fast/light options stay first, the slower pro-tier model is a
# last resort). Reachability verified with this project's actual API key,
# not just client.models.list() — the vision-chain fix also caught
# gemini-2.5-pro being list-visible but 404ing as "no longer available to
# new users" for this key specifically, so list membership alone isn't
# proof of access. The other four entries here already had confirmed real
# (non-404) traffic against this key during that same audit.
TEXT_MODEL_FALLBACK_CHAIN = _dedupe([
    os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash"),
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-3.1-pro-preview",
])

# Multi-key rotation (2026-09) — same pool and same reasoning as
# step1_fridge_vision.py's VISION_API_KEYS: only adds real headroom if
# GOOGLE_API_KEY_2/_3 belong to separate Google Cloud projects from
# GOOGLE_API_KEY, since Gemini's free-tier daily quota is scoped per
# project, not per key. Kept as its own copy here rather than shared with
# step1 — this codebase already keeps step1/step2 self-contained (e.g.
# _dedupe itself is defined independently in both files).
TEXT_API_KEYS = load_api_keys()


def _build_text_clients() -> list[tuple[str, genai.Client]]:
    """One (label, client) pair per configured production key — labels
    only ("key1", "key2", ...), never real key values, so logging which
    key served a request never risks leaking one."""
    return [(f"key{i + 1}", genai.Client(api_key=k)) for i, k in enumerate(TEXT_API_KEYS)]


# ---------------------------------------------------------------------------
# Fallback suggestions (when API quota is exceeded)
# ---------------------------------------------------------------------------

def _fallback_meal_plan(
    fridge: FridgeContents,
    target_dish: Optional[str] = None
) -> MealPlan:
    """Return sensible defaults when Google API quota is exceeded."""
    if target_dish:
        # Small heuristic mapping for a few common dishes to create a sensible shopping list
        core_map = {
            "chole": ["chickpeas (dried or canned)", "onion", "garlic", "ginger", "tomato", "spices (cumin, coriander, garam masala)", "oil"],
            "bhature": ["all-purpose flour (maida)", "yeast or baking soda", "oil for frying"],
            "omelette": ["eggs", "salt", "pepper", "oil or butter"],
            "pancake": ["flour", "milk", "egg", "baking powder", "oil or butter"],
            "sandwich": ["bread", "butter", "cheese or spread", "vegetables"],
        }

        low = target_dish.lower()
        core = []
        for k, v in core_map.items():
            if k in low:
                core = v
                break

        if not core:
            # Generic fallback shopping list for an unknown target dish
            core = ["flour", "oil", "salt", "spices", "one fresh vegetable"]

        missing = [it for it in core if not any(it.split()[0].lower() in ing.name.lower() for ing in fridge.ingredients)]

        suggestions = [
            MealSuggestion(
                name=target_dish,
                description=f"A practical suggestion to make {target_dish}.",
                can_cook_now=(len(missing) == 0),
                missing_ingredients=missing or [],
                cuisine="Various",
                prep_time_minutes=30,
                cooking_steps=[
                    "Gather and prep all the ingredients listed above.",
                    f"Follow your usual method for {target_dish}, adjusting seasoning to taste.",
                    "Cook until done, then serve hot.",
                ],
            )
        ]
        decision = Decision.COOK if len(missing) == 0 else Decision.ORDER_GROCERIES
        if len(missing) == 0:
            reasoning = f"You appear to have the core ingredients to make {target_dish}."
        else:
            reasoning = (
                f"You're missing {len(missing)} core items for {target_dish}. "
                f"Suggested quick grocery items: {', '.join(missing[:6])}."
            )
    else:
        has_eggs = any(ing.name.lower() in ["eggs", "egg"] for ing in fridge.ingredients)
        has_bread = any(ing.name.lower() in ["bread", "bread rolls", "flatbread"] for ing in fridge.ingredients)
        has_veggies = any(
            ing.name.lower() in ["tomato", "cucumber", "lettuce", "carrot", "onion"]
            for ing in fridge.ingredients
        )
        
        suggestions = []
        if has_eggs and has_bread:
            suggestions.append(MealSuggestion(
                name="Egg Toast", description="Quick breakfast.",
                can_cook_now=True, missing_ingredients=[], cuisine="Simple", prep_time_minutes=10,
            ))
        if has_veggies:
            suggestions.append(MealSuggestion(
                name="Vegetable Salad", description="Fresh & healthy.",
                can_cook_now=True, missing_ingredients=[], cuisine="International", prep_time_minutes=5,
            ))
        if len(fridge.ingredients) >= 3:
            suggestions.append(MealSuggestion(
                name="Stir-fry", description="With available ingredients.",
                can_cook_now=True, missing_ingredients=[], cuisine="Asian", prep_time_minutes=15,
            ))
        if not suggestions:
            suggestions.append(MealSuggestion(
                name="Order Food",
                description="You have limited usable ingredients — ordering a ready dish is recommended.",
                can_cook_now=False,
                missing_ingredients=["pantry staples: salt, oil, spices, flour"],
                cuisine="Any",
                prep_time_minutes=0,
            ))

        decision = Decision.COOK if any(s.can_cook_now for s in suggestions) else Decision.ORDER_DISH
        reasoning = "Based on what's in your fridge right now."
    
    recommended = suggestions[0] if suggestions else None
    return MealPlan(suggestions=suggestions, decision=decision, recommended_meal=recommended, reasoning=reasoning)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_RECIPE_RULES = """\
RECIPE INGREDIENTS — for the suggested dish, return every single
ingredient needed to cook it. Do not decide "have" vs "missing" and do not
compare against the fridge contents — a separate process (not you)
determines that from the category you assign below plus the fridge scan.

INGREDIENT CATEGORY — classify each ingredient into exactly one of:
- "staple": something virtually every Indian household always has on
  hand (salt, oil, water, ghee, butter, sugar, common ground/whole
  spices, basic aromatics like onion/garlic/ginger/green chilli). Be
  generous here — these get pre-checked for the user, who can still
  uncheck ones they're personally out of.
- "specialty": ingredients specific to this dish that cannot be assumed
  present (e.g. kasuri methi, a particular dal, paneer, coconut milk,
  tamarind, a specific flour or rice variety, saffron, jaggery).
- "perishable": fresh ingredients that go bad quickly and must be bought
  fresh (fresh vegetables other than onion/tomato/garlic/ginger, fresh
  herbs, fresh meat/fish, fresh paneer, lemon/lime).
Misclassifying a specialty or perishable ingredient as a staple means the
user won't be reminded to buy it — only use "staple" for things that are
genuinely always in the kitchen, regardless of this specific dish.

QUANTITIES — scale every ingredient's quantity to the requested number
of servings (see below), and include the unit in the same field, e.g.
"200g", "2 medium", "1 tsp".

PRICES — every ingredient must include a realistic estimated_price_inr
as a plain integer in Indian Rupees, for the quantity listed. Never
null, never "--", never omit this field.
"""

_PROMPT_TEMPLATE = _RECIPE_RULES + """
You are an expert chef and nutritionist helping a busy person decide what to eat.

Ingredients detected in their fridge (for inspiration only):
{ingredient_list}

Suggest 3 to 5 meals inspired by what's available. For each meal, give a
complete recipe per the RECIPE INGREDIENTS rules above.

Also return a complete ingredient list for cooking each suggested dish for {servings} people
with exact quantities, SCALED to {servings} servings — do not use a fixed base-recipe amount
regardless of the number of people. Work out the per-serving amount and multiply it by
{servings}. Example: if a base recipe for 2 people needs "1 cup rice", for {servings} people
that becomes roughly "{servings_half} cups rice" (i.e. 0.5 cup per person x {servings}). Apply
that same scaling logic to every quantity. Be specific: "2 medium onions", "200ml fresh cream",
"3 cloves garlic", "1 tsp cumin seeds".

Also return clear step-by-step cooking instructions as a numbered "cooking_steps" array — one
imperative sentence per step (e.g. "Heat oil in a pan over medium heat", "Add chopped onions
and saute until golden"), enough steps to actually cook the dish start to finish. This is the
recipe itself, so it must be complete and followable, not a summary. prep_time_minutes must be
a realistic estimate for this specific dish, not a generic default like 30 for everything.

Return ONLY valid JSON (no markdown, no prose):
{{
  "suggestions": [
    {{
      "name": "<meal name>",
      "description": "<one sentence>",
      "cuisine": "<e.g. Indian, Italian, Mexican>",
      "prep_time_minutes": <integer>,
      "recipe_ingredients": [
        {{
          "name": "<ingredient name>",
          "quantity": "<exact amount with unit, e.g. '200ml', '2 medium'>",
          "estimated_price_inr": <integer>,
          "category": "<staple|specialty|perishable>"
        }}
      ],
      "cooking_steps": ["<step 1>", "<step 2>", ...]
    }}
  ],
  "recommended_meal": "<meal name from the list above>",
  "reasoning": "<one or two sentences about the recommended dish>"
}}
"""


_TARGET_DISH_PROMPT = _RECIPE_RULES + """
You are an expert chef and nutritionist helping a busy person.

The user explicitly wants to eat: "{target_dish}"

Ingredients detected in their fridge (for inspiration only):
{ingredient_list}

Give a complete recipe for "{target_dish}" per the RECIPE INGREDIENTS
rules above.

Also return a complete ingredient list for cooking "{target_dish}" for {servings} people
with exact quantities, SCALED to {servings} servings — do not use a fixed base-recipe amount
regardless of the number of people. Work out the per-serving amount and multiply it by
{servings}. Example: if a base recipe for 2 people needs "1 cup rice", for {servings} people
that becomes roughly "{servings_half} cups rice" (i.e. 0.5 cup per person x {servings}). Apply
that same scaling logic to every quantity. Be specific: "2 medium onions", "200ml fresh cream",
"3 cloves garlic", "1 tsp cumin seeds".

Also return clear step-by-step cooking instructions as a numbered "cooking_steps" array — one
imperative sentence per step (e.g. "Heat oil in a pan over medium heat", "Add chopped onions
and saute until golden"), enough steps to actually cook "{target_dish}" start to finish. This
is the recipe itself, so it must be complete and followable, not a summary. prep_time_minutes
must be a realistic estimate for "{target_dish}" specifically, not a generic default like 30
for everything.

Return ONLY valid JSON (no markdown, no prose) with a single suggestion representing the target dish:
{{
  "suggestions": [
    {{
      "name": "<name of the target dish>",
      "description": "<one sentence describing the dish>",
      "cuisine": "<cuisine type>",
      "prep_time_minutes": <integer>,
      "recipe_ingredients": [
        {{
          "name": "<ingredient name>",
          "quantity": "<exact amount with unit, e.g. '200ml', '2 medium'>",
          "estimated_price_inr": <integer>,
          "category": "<staple|specialty|perishable>"
        }}
      ],
      "cooking_steps": ["<step 1>", "<step 2>", ...]
    }}
  ],
  "recommended_meal": "<name of the target dish>",
  "reasoning": "<one or two sentences about the dish>"
}}
"""


# ---------------------------------------------------------------------------
# Core planner function
# ---------------------------------------------------------------------------

def _parse_meal_plan_payload(raw_text: str) -> MealPlan:
    """Shared JSON-parsing tail for both the streaming and non-streaming
    text-model calls — kept in one place so parsing logic can't drift
    between the two call paths."""
    raw_text = (raw_text or "").strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    payload = json.loads(raw_text)

    suggestions = [
        MealSuggestion(
            name=s["name"],
            description=s.get("description", ""),
            # No more have/missing classification, so this no longer
            # reflects fridge contents — it's unused by the UI.
            can_cook_now=True,
            cuisine=s.get("cuisine", ""),
            prep_time_minutes=int(s.get("prep_time_minutes", 0)),
            # is_staple / found_in_fridge are filled in afterwards by
            # _enrich_recipe_ingredients() — deterministic Python
            # matching against the category below, not left to the LLM
            # to self-report have/missing.
            recipe_ingredients=[
                RecipeIngredient(
                    name=ri.get("name", ""),
                    quantity=ri.get("quantity", ""),
                    estimated_price_inr=int(ri.get("estimated_price_inr", 0) or 0),
                    category=_safe_category(ri.get("category", ""), ri.get("name", "")),
                )
                for ri in s.get("recipe_ingredients", [])
            ] or None,
            cooking_steps=[step for step in s.get("cooking_steps", []) if step],
        )
        for s in payload.get("suggestions", [])
    ]

    decision = Decision(payload.get("decision", Decision.COOK))
    recommended_name = payload.get("recommended_meal", "")
    recommended = next((s for s in suggestions if s.name == recommended_name), None)
    if recommended is None and suggestions:
        recommended = suggestions[0]

    return MealPlan(
        suggestions=suggestions,
        decision=decision,
        recommended_meal=recommended,
        reasoning=payload.get("reasoning", ""),
    )


def _call_text_model_with_retry_stream(client: genai.Client, model: str, prompt: str):
    """
    Streaming counterpart of _call_text_model_with_retry(): same retry/
    backoff behavior and the same final JSON parsing, but yields partial
    text chunks as they arrive from the model so the caller can forward
    them before the full response (and therefore the parsed MealPlan) is
    ready. Yields ("partial", chunk_text) for each streamed chunk, then
    exactly one ("result", MealPlan) before returning. Raises the last
    exception if all attempts fail, same as the non-streaming version.
    """
    max_retries = 3
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            full_text = ""
            for chunk in client.models.generate_content_stream(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(http_options=_TEXT_CALL_HTTP_OPTIONS),
            ):
                if chunk.text:
                    full_text += chunk.text
                    yield ("partial", chunk.text)

            raw_text = full_text.strip()

            if "error" in raw_text.lower() or "resource_exhausted" in raw_text.lower():
                console.print(f"[yellow][WARNING] {model} API error detected in response[/yellow]")
                raise RuntimeError("API returned error-like payload")

            yield ("result", _parse_meal_plan_payload(raw_text))
            return

        except Exception as e:
            console.print(f"[yellow]{model} attempt {attempt} failed:[/yellow] {type(e).__name__}: {e}")
            if attempt == max_retries:
                raise
            time.sleep(backoff)
            backoff *= 2

    raise RuntimeError(f"{model} failed after {max_retries} attempts")  # unreachable safeguard


def _build_plan_prompt(fridge: FridgeContents, target_dish: Optional[str], servings: int) -> str:
    ingredient_list = "\n".join(
        f"- {ing.name}" + (f" ({ing.quantity})" if ing.quantity else "")
        for ing in fridge.ingredients
    )
    if not ingredient_list:
        ingredient_list = "(no ingredients detected)"

    servings_half = round(servings * 0.5, 1)
    if servings_half == int(servings_half):
        servings_half = int(servings_half)

    if target_dish:
        return _TARGET_DISH_PROMPT.format(
            ingredient_list=ingredient_list, target_dish=target_dish,
            servings=servings, servings_half=servings_half,
        )
    return _PROMPT_TEMPLATE.format(
        ingredient_list=ingredient_list, servings=servings, servings_half=servings_half
    )


def plan_meals_stream(
    fridge: FridgeContents,
    *,
    target_dish: Optional[str] = None,
    model: str | None = None,
    client: Optional[genai.Client] = None,
    servings: int = 2,
):
    """
    Streaming counterpart of plan_meals(): same model fallback chain,
    retry/backoff behavior, and local-fallback-on-total-failure, but
    yields ("partial", text_chunk) as Gemini streams its response, then
    exactly one ("result", MealPlan) once the full response has arrived
    and been parsed. The prompt, JSON schema, and parsing logic are
    unchanged from plan_meals() — only the delivery timing differs.
    """
    clients = [("injected", client)] if client is not None else _build_text_clients()
    prompt = _build_plan_prompt(fridge, target_dish, servings)
    chain = _dedupe([model, *TEXT_MODEL_FALLBACK_CHAIN]) if model else TEXT_MODEL_FALLBACK_CHAIN

    # Model-first/key-second, same reasoning as vision's
    # _call_gemini_vision_with_fallback: try the strongest available model
    # on every key before ever settling for a weaker model.
    for chain_model in chain:
        for key_label, key_client in clients:
            try:
                for kind, payload in _call_text_model_with_retry_stream(key_client, chain_model, prompt):
                    if kind == "partial":
                        yield ("partial", payload)
                    else:
                        console.print(f"[green][OK] Meal planning succeeded with model: {chain_model} on {key_label}[/green]")
                        yield ("result", _enrich_recipe_ingredients(payload, fridge))
                        return
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    console.print(f"[yellow][WARNING] {chain_model} on {key_label} quota exhausted, trying next...[/yellow]")
                else:
                    console.print(f"[yellow][WARNING] {chain_model} on {key_label} failed with: {e}, trying next...[/yellow]")

    console.print("[yellow][WARNING] All Gemini text models quota exhausted, using fallback[/yellow]")
    yield ("result", _enrich_recipe_ingredients(_fallback_meal_plan(fridge, target_dish), fridge))


def plan_meals(
    fridge: FridgeContents,
    *,
    target_dish: Optional[str] = None,
    model: str | None = None,
    client: Optional[genai.Client] = None,
    servings: int = 2,
) -> MealPlan:
    """
    Suggest meals and decide cook-vs-order given fridge contents.
    If target_dish is provided, evaluate that specific dish instead of suggesting random meals.

    Parameters
    ----------
    fridge:
        Output of step1 identify_ingredients().
    target_dish:
        Optional specific dish the user wants to make.
    model:
        Optional Gemini model override. If omitted, tries each model in
        TEXT_MODEL_FALLBACK_CHAIN in order until one succeeds.
    client:
        Optional pre-built Gemini client.
    servings:
        How many people the recipe_ingredients quantities should be
        scaled for. Defaults to 2.

    Returns
    -------
    MealPlan with suggestions, a Decision, and the recommended meal.

    Retries transient API errors (quota/overload) up to 3 times with
    exponential backoff per model. If a model's quota is exhausted (or it
    keeps failing after retries), moves on to the next model in the
    fallback chain before giving up and returning a local fallback plan.
    """
    for kind, payload in plan_meals_stream(
        fridge, target_dish=target_dish, model=model, client=client, servings=servings
    ):
        if kind == "result":
            return payload
    raise RuntimeError("plan_meals_stream ended without a result")  # unreachable safeguard


# ---------------------------------------------------------------------------
# Top-up suggestions — small upsell items shown alongside the meal plan
# ---------------------------------------------------------------------------

_TOP_UP_PROMPT = """\
You are a smart shopping assistant for Swiggy, India's leading food
delivery platform.

The user is planning to make: {meal_name}
Their fridge contains: {ingredient_list}
Ingredients already missing for this dish (being ordered separately —
never suggest these here): {missing_ingredients}
AI decision: {decision}

Suggest 4 to 5 smart "upgrade" items that would genuinely improve
this specific meal. These should be small, affordable, impulse purchases.

RULES:
- If decision is "cook" or "order_groceries": suggest items from
  Swiggy Instamart (fresh ingredients, condiments, toppings that
  elevate the dish)
- If decision is "order_dish": suggest complementary items from
  Swiggy Food (side dishes, drinks, desserts that pair well)
- Never suggest anything already listed in the missing ingredients above
- Never suggest a pantry staple: salt, sugar, water, cooking oil, ghee,
  butter, cumin seeds, mustard seeds, turmeric powder, red chilli powder,
  coriander powder, cumin powder, garam masala, hing, bay leaves, cloves,
  cardamom, cinnamon, black pepper, dried red chillies, onions, garlic,
  ginger, green chillies, tomatoes, potatoes, lemon, lime, wheat flour,
  baking soda, vinegar
- Never suggest something the user already has in their fridge
- Every suggestion must be vegetarian
- Each suggestion must be a genuine upgrade specific to {meal_name}, not
  a generic add-on that would fit any dish
- Price should be realistic for Indian market (₹30-₹200 range)
- At least one suggestion should be under ₹60 (low friction)

Return ONLY a valid JSON array with 4 to 5 objects:
[
  {{
    "name": "Fresh Strawberries",
    "reason": "Makes your French Toast feel like a cafe breakfast",
    "estimated_price": 49,
    "source": "instamart",
    "emoji": "🍓"
  }},
  ...
]
source must be either "instamart" or "swiggy_food".
Do not include any text outside the JSON array.
"""


def _parse_top_up_response(raw_text: str) -> list[dict]:
    raw_text = (raw_text or "").strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    items = json.loads(raw_text)
    if not isinstance(items, list):
        return []

    valid_sources = {"instamart", "swiggy_food"}
    suggestions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        if source not in valid_sources:
            continue
        name = item.get("name", "")
        if not name:
            continue
        try:
            price = int(float(item.get("estimated_price", 0)))
        except (TypeError, ValueError):
            continue
        suggestions.append({
            "name": name,
            "reason": item.get("reason", ""),
            "estimated_price": price,
            "source": source,
            "emoji": item.get("emoji", "✨"),
        })
    return suggestions[:5]


def generate_top_up_suggestions(
    fridge: FridgeContents,
    meal: MealSuggestion,
    decision: Decision,
    model: str | None = None,
) -> list[dict]:
    """
    Suggest 3 small upsell items (Instamart or Swiggy Food) that would
    elevate the given meal. Best-effort only — any failure (API error,
    malformed JSON, exhausted quota on every model, etc.) returns an
    empty list rather than raising, since this is a nice-to-have upsell
    card and must never block the main flow.
    """
    try:
        clients = _build_text_clients()
        if not clients:
            raise RuntimeError("no GOOGLE_API_KEY configured")
    except Exception as e:
        console.print(f"[yellow][WARNING] generate_top_up_suggestions failed to init client: {type(e).__name__}: {e}[/yellow]")
        return []

    ingredient_list = ", ".join(ing.name for ing in fridge.ingredients) or "(nothing detected)"
    missing_ingredients = ", ".join(meal.missing_ingredients) if meal and meal.missing_ingredients else "(none)"
    prompt = _TOP_UP_PROMPT.format(
        meal_name=meal.name if meal else "this meal",
        ingredient_list=ingredient_list,
        missing_ingredients=missing_ingredients,
        decision=decision.value,
    )

    chain = _dedupe([model, *TEXT_MODEL_FALLBACK_CHAIN]) if model else TEXT_MODEL_FALLBACK_CHAIN

    missing_names = meal.missing_ingredients if meal and meal.missing_ingredients else []

    # Model-first/key-second, same reasoning as vision's
    # _call_gemini_vision_with_fallback and plan_meals_stream above.
    for chain_model in chain:
        for key_label, client in clients:
            print(f"[TOP_UP] Attempting with model: {chain_model} on {key_label}")
            try:
                response = client.models.generate_content(
                    model=chain_model, contents=prompt,
                    config=types.GenerateContentConfig(http_options=_TEXT_CALL_HTTP_OPTIONS),
                )
                suggestions = _parse_top_up_response(response.text)
                suggestions = [
                    s for s in suggestions
                    if not _fuzzy_ingredient_match(s["name"], missing_names)
                ]
                print(f"[TOP_UP] Result: {_ascii_safe(suggestions)}")
                if suggestions:
                    console.print(f"[green][OK] Top-up suggestions succeeded with model: {chain_model} on {key_label}[/green]")
                    return suggestions[:5]
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    console.print(f"[yellow][WARNING] {chain_model} on {key_label} quota exhausted, trying next...[/yellow]")
                else:
                    console.print(f"[yellow][WARNING] {chain_model} on {key_label} top-up failed with: {e}, trying next...[/yellow]")

    console.print("[yellow][WARNING] All Gemini models failed for top-up suggestions, skipping[/yellow]")
    return []


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------

def display_meal_plan(plan: MealPlan) -> None:
    decision_colors = {
        Decision.COOK: "green",
        Decision.ORDER_DISH: "red",
        Decision.ORDER_GROCERIES: "yellow",
    }
    decision_labels = {
        Decision.COOK: "Cook at home",
        Decision.ORDER_DISH: "Order the dish",
        Decision.ORDER_GROCERIES: "Order missing groceries",
    }

    console.rule("[bold blue]Meal Suggestions")

    table = Table(show_lines=True)
    table.add_column("Meal", style="cyan")
    table.add_column("Cuisine", style="magenta")
    table.add_column("Prep (min)", justify="right")
    table.add_column("Ready to cook?", justify="center")
    table.add_column("Missing")

    for s in plan.suggestions:
        ready = "[green]Yes[/green]" if s.can_cook_now else "[red]No[/red]"
        missing = ", ".join(s.missing_ingredients) if s.missing_ingredients else "—"
        table.add_row(s.name, s.cuisine, str(s.prep_time_minutes), ready, missing)

    console.print(table)

    color = decision_colors[plan.decision]
    label = decision_labels[plan.decision]
    rec_name = plan.recommended_meal.name if plan.recommended_meal else "—"

    console.print(
        Panel(
            f"[bold]Recommended:[/bold] {rec_name}\n"
            f"[bold]Decision:[/bold] [{color}]{label}[/{color}]\n\n"
            f"[italic]{plan.reasoning}[/italic]",
            title="Action",
            border_style=color,
        )
    )


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plan meals from fridge ingredients.")
    p.add_argument(
        "--ingredients",
        required=True,
        help="Comma-separated ingredient list, e.g. 'eggs,butter,cheese'",
    )
    p.add_argument("--model", default="gemini-2.5-flash")
    p.add_argument("--target-dish", default=None, help="Specific dish you want to cook")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    names = [n.strip() for n in args.ingredients.split(",") if n.strip()]
    fridge = FridgeContents(ingredients=[Ingredient(name=n) for n in names])

    if args.target_dish:
        console.print(f"[bold]Evaluating target dish:[/bold] {args.target_dish}")
    else:
        console.print(f"[bold]Planning meals for:[/bold] {', '.join(names)}")
        
    plan = plan_meals(fridge, target_dish=args.target_dish, model=args.model)

    if args.json:
        import json as _json
        data = {
            "decision": plan.decision.value,
            "recommended_meal": plan.recommended_meal.name if plan.recommended_meal else None,
            "reasoning": plan.reasoning,
            "suggestions": [
                {
                    "name": s.name,
                    "cuisine": s.cuisine,
                    "can_cook_now": s.can_cook_now,
                    "missing_ingredients": s.missing_ingredients,
                    "prep_time_minutes": s.prep_time_minutes,
                }
                for s in plan.suggestions
            ],
        }
        print(_json.dumps(data, indent=2))
    else:
        display_meal_plan(plan)


if __name__ == "__main__":
    main()
