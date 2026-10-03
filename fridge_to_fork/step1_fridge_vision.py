"""
Step 1 — Fridge Vision
======================
Accepts a fridge image (file path, URL, or raw bytes) and uses Google
Gemini Vision, in two passes per photo (wide scan + deep scan for what
the first pass missed), to identify all visible ingredients with
confidence scores. See identify_ingredients() for the full approach.
(LogMeal and AWS Rekognition were tried as primary/secondary detectors in
earlier iterations — neither proved reliable for fridge scanning, so
Gemini is the sole detector.)

Run standalone for a quick smoke-test:
    python -m fridge_to_fork.step1_fridge_vision --image path/to/fridge.jpg
"""

import argparse
import io
import itertools
import json
import os
import time
from pathlib import Path
from typing import Union

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image, ImageEnhance
from rich.console import Console
from rich.table import Table

from . import gemini_resilience as resilience
from .gemini_keys import load_api_keys
from .ingredient_matching import dedupe_detections, is_blocked_detection, passes_confidence
from .models import FridgeContents, Ingredient

load_dotenv()

console = Console()


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
# Vision-accuracy audit (2026-09): the previous chain's first entry
# (gemini-2.0-flash) and fourth entry (gemini-2.0-flash-lite) both return a
# hard 404 "no longer available" from the live API — confirmed by actually
# calling client.models.list(), not assumed from docs, since model
# availability has drifted out from under this chain silently before.
# identify_ingredients() was quietly running on the third entry for every
# scan with nobody noticing, since the fallback machinery's own resilience
# hid the failure. Mixed pinned-version and "-latest" alias entries on
# purpose: a pinned entry (gemini-2.5-flash) is predictable; the "-latest"
# aliases auto-repoint to whatever Google currently considers current, so
# a future retirement degrades gracefully instead of 404ing outright the
# way a pinned name does. Ordered strongest-and-fast first (matches
# GEMINI_TEXT_MODEL's already-correct default, and is what most scans
# should actually run on), fast/light fallback next, and the
# slower-but-strongest pro-tier model last — worth the extra latency only
# once earlier attempts have already failed and something is better
# than an empty fridge. gemini-2.5-pro itself turned out to be a second,
# subtler version of the same drift problem this audit exists to catch:
# client.models.list() lists it as existing, but calling it with this
# project's actual API key 404s with "no longer available to new users" —
# listed existence isn't the same as this key having access. Verified
# gemini-3.1-pro-preview (Google's own suggested replacement) is reachable
# with this key (a 429 rate-limit, not a 404) before using it here.
#
# gemini-2.5-flash-lite removed (2026-09-30, live prod incident) — hard
# 404s ("no longer available to new users") on 2 of 3 configured keys,
# confirmed live in Render's logs. Same drift problem the two paragraphs
# above already describe; this pinned entry hit it too. Guaranteed-dead
# weight on every single scan until Google's own replacement
# (gemini-3.5-flash-lite, per the 404 body) is verified reachable with
# this project's actual keys the same way gemini-3.1-pro-preview was.
VISION_MODEL_FALLBACK_CHAIN = _dedupe([
    os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash"),
    # Google's own suggested replacement for 2.5-flash (named in its "no longer available to new users" 404s, which
    # projects created recently get). Verified 2026-10-03 to answer on all four of this app's projects; occasionally
    # 503 "high demand", which the fallback handles.
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-3.1-pro-preview",
])

# Multi-key rotation (2026-09) — each Gemini free-tier daily quota is
# scoped per API key's underlying Google Cloud PROJECT, not just per key
# (confirmed by the quota error's own id:
# "GenerateRequestsPerDayPerProjectPerModel-FreeTier") — GOOGLE_API_KEY_2/_3
# only add real headroom if they belong to separate projects from
# GOOGLE_API_KEY; keys sharing one project share its quota and rotation
# does nothing for them. Order matters: GOOGLE_API_KEY stays primary/first.
VISION_API_KEYS = load_api_keys()


def _build_vision_clients() -> list[tuple[str, "genai.Client"]]:
    """One (label, client) pair per configured production key. Labels are
    1-indexed positions ("key1", "key2", ...), never the key values
    themselves — nothing that touches a real key value should ever reach a
    log line."""
    return [(f"key{i + 1}", genai.Client(api_key=k)) for i, k in enumerate(VISION_API_KEYS)]


def _fallback_fridge_contents() -> FridgeContents:
    """Return a small, safe placeholder fridge inventory when vision fails."""
    return FridgeContents(
        ingredients=[
            Ingredient(name="eggs", quantity="3 eggs", confidence=0.85),
            Ingredient(name="bread", quantity="1 loaf", confidence=0.8),
            Ingredient(name="tomatoes", quantity="2 tomatoes", confidence=0.75),
        ],
        raw_description="Fallback fridge inventory used because vision analysis was unavailable.",
    )

# ---------------------------------------------------------------------------
# Two-pass scan prompts — used by identify_ingredients() below.
# (The old single-pass _build_vision_prompt() this superseded, and the
# single-pass call/fallback machinery that used it, were deleted along
# with the retired LogMeal/Rekognition detectors — see identify_ingredients()'s
# own docstring below.)
# ---------------------------------------------------------------------------

# Shared across both passes — vision-accuracy overhaul, Phase B. Kept as one
# constant, not copy-pasted into each prompt, so the schema can't silently
# drift between wide/deep scans the way VISION_MODEL_FALLBACK_CHAIN and
# GEMINI_VISION_MODEL drifted out of sync before the audit caught it.
#
# The "NEVER FABRICATE" rule directly targets the failure mode the overhaul
# was scoped around: a model reporting "Tata Sampann Moong Dal 500g" at high
# confidence off an unreadable label isn't detection, it's a guess dressed
# up as one. needs_confirmation is the model's own admission it's guessing;
# _assign_tier() below backstops it for a response that gets the confidence
# number right but forgets to set the flag (or vice versa) — see its
# docstring for why the number and the flag are each other's check, not
# either one used alone.
_EXTENDED_FIELDS_BLOCK = """EXTENDED FIELDS — include these on every item too:
- "category": one of "produce", "dairy", "grain_legume", "condiment_sauce", "cooked_food", "packaged_other"
- "estimated_quantity": for discrete/countable items, {"type": "count", "value": <integer>, "unit": "<piece/packet/carton/etc>"};
  for liquids, bulk, or anything in an opaque container, {"type": "level", "value": "<full/half/low/unknown>", "unit": null}.
  Always approximate — never invent a precise weight or volume (never "247g", never "1.5L") you could not actually measure from a photo.
- "state": one of "fresh", "packaged", "cooked", "opened", "unknown"
- "needs_confirmation": true if you cannot confidently identify the EXACT product/variety, false otherwise
- "possible_matches": if needs_confirmation is true and a small number of specific identities are plausible, list 2-3 (e.g. ["moong dal", "toor dal", "masoor dal"]); otherwise []

CRITICAL — NEVER FABRICATE WHAT YOU CANNOT READ:
If a packaged item's brand or exact product/variety is not clearly legible, report ONLY the generic category term
you CAN actually see (e.g. "dal", not "Tata Sampann Moong Dal 500g"; "cooking oil", not a specific brand or variety),
set needs_confirmation: true, and list possible_matches if a few specific candidates are plausible. Guessing a
specific brand, variety, or size you cannot actually read is worse than reporting the generic term — never do it,
even if a specific-sounding guess would otherwise score higher on your own confidence scale."""


def _build_wide_scan_prompt(dish_name: str = "") -> str:
    """Pass 1 — broad, zone-by-zone scan for everything visible, primed
    with Indian-fridge-specific context (dabbas, plastic-bagged produce,
    door condiments) so Gemini knows what it's likely looking at."""
    dish_context = ""
    if dish_name:
        dish_context = f"\nThe user wants to cook {dish_name}. Pay special attention to ingredients this dish needs, but scan and report ALL food items regardless.\n"

    return f"""You are an expert kitchen inventory AI with specialized knowledge of Indian household fridges.{dish_context}

Your task: Identify every single food item visible in this fridge photo.

SCANNING APPROACH — scan zone by zone:

ZONE 1 — TOP SHELF: What is on the top shelf? Look carefully at every container, box, and item.
ZONE 2 — MIDDLE SHELVES: Scan each shelf left to right. Look inside transparent containers if possible.
ZONE 3 — LOWER SHELVES AND DRAWERS: Check crisper drawers, lower shelves, any visible produce.
ZONE 4 — DOOR COMPARTMENTS: Scan every door shelf top to bottom. Bottles, jars, condiments, packets.
ZONE 5 — VISIBLE CONTAINERS: Any dabba, tiffin box, or covered container — what might it contain based on context?

INDIAN FRIDGE CONTEXT — you will commonly see:
- Dabbas and tiffin boxes containing cooked dal, sabzi, rice, roti
- Pressure cooker or steel pots with leftover food
- Plastic bags containing vegetables like coriander, mint, green chillies
- Packaged items: milk pouches, paneer packets, curd containers, butter packets
- Condiment bottles: ketchup, soy sauce, pickle jars, chutney
- Fresh produce: tomatoes, onions, green chillies, ginger, garlic, lemons
- Door shelves with juice cartons, water bottles, sauce bottles

WHAT TO REPORT:
- Every food item you can identify with reasonable certainty
- Fresh vegetables and fruits even if in plastic bags
- Dairy items — milk, curd/yogurt, paneer, butter, cheese
- Cooked food in containers if identifiable
- Condiments and sauces if identifiable
- Packaged items if you can read or infer the label
- Eggs if visible

WHAT TO NEVER REPORT:
- Non-food items (cleaning products, medicines)
- Water bottles (not a cooking ingredient)
- Items you genuinely cannot identify at all
- Meat, chicken, fish ONLY if 100% clearly visible and unwrapped

CONFIDENCE SCORING:
- 90-100: Completely certain, clearly visible
- 75-89: Clearly visible, slightly obscured
- 60-74: Reasonably confident
- 50-59: Partially visible but identifiable
- Below 50: Skip

NAMING RULES:
- Standard English names only
- Singular form: "tomato" not "tomatoes"
- Be specific: "green chilli" not just "chilli"
- Indian food items by their common English name: "curd" not "yogurt" if it looks like Indian curd
- Never brand names, never Hindi names

{_EXTENDED_FIELDS_BLOCK}

Return ONLY a JSON array, no explanation:
[
  {{"name": "tomato", "confidence": 88, "category": "produce", "estimated_quantity": {{"type": "count", "value": 3, "unit": "piece"}}, "state": "fresh", "needs_confirmation": false, "possible_matches": []}},
  {{"name": "dal", "confidence": 60, "category": "grain_legume", "estimated_quantity": {{"type": "count", "value": 1, "unit": "packet"}}, "state": "packaged", "needs_confirmation": true, "possible_matches": ["moong dal", "toor dal", "masoor dal"]}}
]

If nothing identifiable: []"""


def _build_deep_scan_prompt(already_found: list[str]) -> str:
    """Pass 2 — told explicitly what Pass 1 already found, and asked to
    hunt specifically for what a first pass commonly misses (door
    shelves, small items, back-of-shelf items) rather than re-scanning
    the same obvious things."""
    found_str = ", ".join(already_found) if already_found else "nothing yet"

    return f"""You are an expert kitchen inventory AI doing a SECOND PASS scan of this fridge.

Already identified in first pass: {found_str}

Your job now: Find everything that was MISSED in the first pass.

Focus specifically on:
1. DOOR SHELVES — every single bottle, jar, packet, and container on the door
2. LOWER DRAWERS — crisper drawers, vegetable compartments at the bottom
3. BACK OF SHELVES — items pushed to the back that might have been overlooked
4. SMALL ITEMS — lemons, green chillies, ginger pieces, garlic that are easy to miss
5. PACKAGED ITEMS — any carton, packet, or wrapper with identifiable contents
6. CONTAINERS — steel dabbas, plastic containers, glass jars — what do they likely contain?

Do NOT repeat items already found: {found_str}

Report only NEW items not in the already-found list.

Indian fridge items commonly missed in first pass:
- Lemons and limes tucked in corners
- Green chillies in small plastic bags
- Ginger and garlic pieces
- Small pickle jars
- Butter or margarine packets
- Cheese blocks or slices
- Leftover cooked food in steel containers
- Juice cartons or milk pouches on door

Same confidence scoring as before. Same naming rules.

{_EXTENDED_FIELDS_BLOCK}

Return ONLY a JSON array of NEW items:
[{{"name": "lemon", "confidence": 78, "category": "produce", "estimated_quantity": {{"type": "count", "value": 2, "unit": "piece"}}, "state": "fresh", "needs_confirmation": false, "possible_matches": []}}]

If nothing new found: []"""


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _load_image(source: Union[str, Path, bytes]) -> tuple[bytes, str]:
    """Return (raw_bytes, media_type)."""
    if isinstance(source, bytes):
        return source, "image/jpeg"

    if isinstance(source, str) and source.startswith(("http://", "https://")):
        resp = httpx.get(source, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        return resp.content, content_type

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    suffix = path.suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")
    return path.read_bytes(), media_type


# VISION_BLACKLIST / _is_blacklisted() / _deduplicate_items() removed —
# their word-subset rules were deleting real, distinct ingredients (see
# main's FRIDGE_SCAN_FIX_REPORT.md F1/F2, ported 2026-09-30). Replaced
# everywhere by ingredient_matching.is_blocked_detection() /
# dedupe_detections(), which use the same head-noun + safe-modifier rule
# step2 uses for fridge matching, imported at the top of this file.


# ---------------------------------------------------------------------------
# Confidence -> tier — vision-accuracy overhaul, Phase B. Application-side
# rules layered over Gemini's own raw confidence number AND its own
# self-reported needs_confirmation flag — neither trusted alone (the whole
# point of tiering: a model that's told to self-police "am I sure enough to
# skip confirmation" is exactly the kind of self-report that proved
# unreliable for have/missing status in step2_meal_planner.py, hence that
# staying deterministic Python-side too). CONFIRMED items are the ones the
# frontend can auto-advance past without a review step; PROBABLE/UNCERTAIN
# gate it. See _build_wide_scan_prompt's "NEVER FABRICATE" instruction for
# what needs_confirmation is meant to catch at the source; this is the
# backstop for a response that gets the number right but forgets to set the
# flag, or vice versa.
# ---------------------------------------------------------------------------

TIER_CONFIRMED = "confirmed"
TIER_PROBABLE = "probable"
TIER_UNCERTAIN = "uncertain"

CONFIRMED_CONFIDENCE_FLOOR = 80
PROBABLE_CONFIDENCE_FLOOR = 60


def _assign_tier(item: dict) -> str:
    """Assumes `item` already cleared the existing >=50 confidence filter
    upstream (identify_ingredients()) — this only decides which of the
    three tiers a surviving item lands in, never whether to drop it."""
    if item.get("needs_confirmation") is True:
        return TIER_UNCERTAIN

    confidence = item.get("confidence", 0)

    # Backstop for a packaged item Gemini scored confidently but didn't
    # flag: state=="packaged" plus a non-empty possible_matches is the same
    # "I'm not sure of the exact product" signal needs_confirmation is
    # meant to carry, just via a different field the model filled in
    # instead. Treat it the same way rather than trusting the bare number.
    if item.get("state") == "packaged" and item.get("possible_matches"):
        return TIER_UNCERTAIN

    if confidence >= CONFIRMED_CONFIDENCE_FLOOR:
        return TIER_CONFIRMED
    if confidence >= PROBABLE_CONFIDENCE_FLOOR:
        return TIER_PROBABLE
    return TIER_UNCERTAIN


def _preprocess_for_gemini(image_bytes: bytes) -> bytes:
    """
    Full preprocessing pipeline optimized for dark, cluttered Indian
    fridge photos, used by identify_ingredients() before every Gemini
    call: resize to 1024px, then brightness/contrast/sharpness/saturation
    enhancement. Self-contained — the retired Rekognition path's own
    _resize_image()/_enhance_for_detection() helpers this never depended
    on have since been deleted entirely.
    """
    img = Image.open(io.BytesIO(image_bytes))

    if img.mode != "RGB":
        img = img.convert("RGB")

    # Resize to optimal resolution for Gemini — 1024px longest side
    img.thumbnail((1024, 1024), Image.LANCZOS)

    # Brightness — Indian fridges are often dark inside
    img = ImageEnhance.Brightness(img).enhance(1.4)

    # Contrast — helps distinguish items from shadows
    img = ImageEnhance.Contrast(img).enhance(1.3)

    # Sharpness — helps read labels and identify items in bags
    img = ImageEnhance.Sharpness(img).enhance(1.5)

    # Color saturation — makes vegetables and fruits more distinguishable
    img = ImageEnhance.Color(img).enhance(1.2)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Two-pass Gemini scanning — used by identify_ingredients() below.
# (The old single-pass _call_vision_model_with_retry(), _resize_image(),
# and the retired LogMeal/AWS Rekognition detectors that preceded Gemini
# in earlier iterations were deleted here — none had any caller left once
# _identify_with_gemini_fallback() below was also removed. See
# identify_ingredients()'s own docstring for why they existed at all.)
# ---------------------------------------------------------------------------

def _call_gemini_vision(image_bytes: bytes, prompt: str, client: genai.Client, model: str) -> list[dict]:
    """
    Single Gemini vision call for one prompt/image. Raises on failure
    (network error, quota exhaustion, unparseable response) rather than
    swallowing it — _call_gemini_vision_with_fallback() below is what
    catches that and moves on to the next model in the fallback chain.
    Returns a plain list[dict] of {"name", "confidence"}
    rather than a FridgeContents, since two passes' worth of results get
    merged (in identify_ingredients()) before that conversion happens.

    Uses types.Part.from_bytes() (the same pattern already proven
    throughout this file) rather than hand-building a base64 inline_data
    payload — the google-genai SDK's generate_content() expects Part
    objects, not raw REST-style dicts.

    http_options below caps what one model attempt can cost in time. Left
    at its default, the SDK retries a single call up to 5 times internally
    on 429/5xx (1s/2s/4s/8s/16s backoff, up to 60s max delay per the SDK's
    own defaults) before ever raising — invisible to
    _call_gemini_vision_with_fallback() below, which just sees one very
    slow exception and only then moves to the next model. That's exactly
    what turned two unlucky 503s into 72s for a single photo during the
    accuracy-audit eval run. This app's own fallback chain is already the
    resilience layer across models (each with a separate quota pool), so
    retrying much within a single model attempt is redundant — better to
    fail one model fast and let the chain move on, which is also just
    more time actually spent making progress within the 60s whole-scan
    budget app.py enforces.
    """
    response = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt],
        config=types.GenerateContentConfig(
            # Phase B (vision-accuracy overhaul) added 5 more fields per
            # item (category, estimated_quantity, state, needs_confirmation,
            # possible_matches) - the combined eval run afterward showed
            # near-constant JSONDecodeError ("Unterminated string",
            # "Expecting ',' delimiter" - truncation, not garbage-from-the-
            # start) on gemini-2.5-flash/gemini-flash-latest, and two photos
            # took 94.6s/99.9s: the old 2048 cap was cutting the response
            # off mid-item on any photo with enough items in it, forcing
            # the fallback chain deeper every time. A fridge photo has
            # produced up to ~26-30 items in one pass in this project's own
            # eval runs; budgeting ~100 tokens/item (generous vs. the
            # ~50-60 the extended schema's JSON actually costs) for 80
            # items covers any realistically busy fridge with real margin,
            # not just enough for the two photos that happened to fail.
            max_output_tokens=8192,
            # Thinking is on by default for these models and was the main reason this call timed out (504 at 25s); off,
            # the same call takes ~9s. Extraction from a photo doesn't need it. See gemini_resilience.thinking_config_for.
            thinking_config=resilience.thinking_config_for(model),
            # timeout is PER ATTEMPT, not a shared budget across retries (confirmed against the
            # google-genai SDK's own source, _api_client.py: _request_once() receives this same
            # value on every call _retry() makes) — so worst case for ONE model in the fallback
            # chain is roughly timeout * attempts + backoff, not timeout alone. That's the real
            # constraint on sizing this, given app.py's 60s whole-scan ceiling has to fit multiple
            # models' worth of attempts, not just one.
            #
            # Raising max_output_tokens 2048->8192 fixed the JSON-truncation failures (Phase B's
            # combined eval), but the very next clean run hit near-constant 504 DEADLINE_EXCEEDED
            # on gemini-2.5-flash instead, at the old timeout=15_000/attempts=2 (worst case ~33s
            # incl. backoff for that one model). Root cause isn't fully separable from today's
            # general Gemini free-tier flakiness (503 "high demand" showed up the same day) — but
            # a larger token cap can legitimately need more wall-clock time for a genuinely busy
            # photo's response to complete, and 15s no longer has margin for that either way.
            #
            # attempts dropped 2->1 rather than raising both: this file's own retry-vs-fallback
            # reasoning already holds (a slow/loaded model rarely recovers on an identical
            # immediate retry; the cross-model fallback chain is the layer that actually helps,
            # and only gets a fair shot if one model's failure doesn't eat too much of the 60s
            # budget by itself). timeout raised 15s->25s to give a legitimately larger response
            # real headroom. Worst case per model: ~25s (no retry multiplier) — leaves ~35s of
            # the 60s ceiling for at least one, ideally two, fallback models to also get tried,
            # versus ~33s a single model could already consume before this change.
            http_options=types.HttpOptions(
                timeout=25_000,
                retry_options=types.HttpRetryOptions(attempts=1, initial_delay=0.5, max_delay=3.0, exp_base=2.0),
            ),
        ),
    )

    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    items = json.loads(raw_text)
    return items if isinstance(items, list) else []


# What each kind of failure means for what is tried next lives in gemini_resilience.py (shared with the planner):
# timeouts move to the next MODEL and mark the slow one cold, quota errors rotate keys, 404 "no longer available" pairs
# are skipped for hours.
_scan_counter = itertools.count()


def _rotate_for_scan(clients: list) -> list:
    """Start each scan on a different key (labels keep their real identity), so a day's requests and the per-minute
    limits spread over every project instead of draining the first key's."""
    if len(clients) < 2:
        return clients
    start = next(_scan_counter) % len(clients)
    return clients[start:] + clients[:start]


def _call_gemini_vision_with_fallback(
    clients: list[tuple[str, "genai.Client"]], image_bytes: bytes, prompt: str, model: str | None = None
) -> list[dict]:
    """Walks VISION_MODEL_FALLBACK_CHAIN (an explicit `model` override first, if given), strongest first, following the
    rules in gemini_resilience (see its docstring). Returns [] only if every attempt fails.
    `clients` is a list of (label, Client) pairs; the label (never the key value) is what gets logged."""
    chain = _dedupe([model, *VISION_MODEL_FALLBACK_CHAIN]) if model else VISION_MODEL_FALLBACK_CHAIN
    for chain_model, model_clients in resilience.attempt_plan(chain, clients):
        attempt = resilience.ModelAttempt()
        for key_label, client in model_clients:
            try:
                result = _call_gemini_vision(image_bytes, prompt, client, chain_model)
                resilience.note_success(chain_model)
                if len(clients) > 1 or key_label != "key1":
                    console.print(f"[green][Gemini] {chain_model} succeeded on {key_label}[/green]")
                return result
            except Exception as e:
                if resilience.note_failure(chain_model, key_label, e, attempt) == resilience.NEXT_MODEL:
                    break
    return []


def _gemini_wide_scan(image_bytes: bytes, dish_name: str, clients: list[tuple[str, "genai.Client"]], model: str | None = None) -> list[dict]:
    """Pass 1 — scan entire fridge for all visible food items."""
    prompt = _build_wide_scan_prompt(dish_name)
    return _call_gemini_vision_with_fallback(clients, image_bytes, prompt, model)


def _gemini_deep_scan(image_bytes: bytes, found_items: list[str], clients: list[tuple[str, "genai.Client"]], model: str | None = None) -> list[dict]:
    """Pass 2 — focus on areas and items that might have been missed."""
    prompt = _build_deep_scan_prompt(found_items)
    return _call_gemini_vision_with_fallback(clients, image_bytes, prompt, model)


def identify_ingredients(
    image_source: Union[str, Path, bytes, list[Union[str, Path, bytes]]],
    dish_name: str = "",
    *,
    model: str | None = None,
    client: genai.Client | None = None,
) -> FridgeContents:
    """
    Analyse one or more fridge photos and return structured FridgeContents.

    Gemini Vision is the sole detector, run as two passes per photo:
    Pass 1 (wide scan) finds everything it can; Pass 2 (deep scan) is
    told what Pass 1 already found and asked specifically for what a
    first pass commonly misses (door shelves, lower drawers, small
    items). Results from both passes are merged (highest confidence per
    name wins) before the usual blacklist/confidence/dedupe filtering.

    LogMeal and AWS Rekognition were tried as the primary/secondary
    detectors in earlier iterations — neither proved reliable for fridge
    scanning (LogMeal's account/plan kept blocking the segmentation
    endpoint; Rekognition's general-purpose label vocabulary wasn't a
    good fit for kitchen ingredients). Both detectors, and the single-pass
    _call_vision_model_with_retry()/_identify_with_gemini_fallback()
    machinery this two-pass approach supersedes, have been deleted —
    confirmed zero callers before removal; recoverable from git history
    if ever worth revisiting.

    Parameters
    ----------
    image_source:
        A single file path (str/Path), public image URL (str), or raw
        image bytes — or a list of up to 3 of those. Each photo gets its
        own wide+deep pass (Gemini's ability to combine multiple images
        in one call isn't used here, since Pass 2 needs Pass 1's
        per-photo results to know what to look for); results are merged
        by ingredient name, keeping the highest confidence seen for each
        across all photos and both passes.
    dish_name:
        Optional dish the user is targeting — passed to the wide-scan
        prompt only (see _build_wide_scan_prompt()).
    model:
        Optional Gemini model override, tried before the rest of
        VISION_MODEL_FALLBACK_CHAIN for every call.
    client:
        Optional pre-built Gemini client (useful for testing / DI) — bypasses
        the multi-key rotation pool entirely and is used as the sole client,
        same as before this existed.

    Returns
    -------
    FridgeContents with a list of Ingredient objects.
    """
    sources = image_source if isinstance(image_source, list) else [image_source]

    try:
        if client is not None:
            clients: list[tuple[str, "genai.Client"]] = [("injected", client)]
        else:
            clients = _rotate_for_scan(_build_vision_clients())
            if not clients:
                raise RuntimeError("no GOOGLE_API_KEY configured")
    except Exception as e:
        console.print(f"[yellow][WARNING] Could not init Gemini client: {type(e).__name__}: {e}[/yellow]")
        return _fallback_fridge_contents()

    # name -> the winning full item dict (highest confidence across all
    # photos/passes) — keeps the extended schema fields (category, state,
    # estimated_quantity, needs_confirmation, possible_matches) alongside
    # confidence, not just the bare number the old dict[str, int] held.
    all_items: dict[str, dict] = {}

    for source in sources:
        try:
            raw_bytes, _media_type = _load_image(source)
            image_bytes = _preprocess_for_gemini(raw_bytes)
        except Exception as e:
            console.print(f"[yellow][WARNING] Could not prepare image: {type(e).__name__}: {e}[/yellow]")
            continue

        pass1_items = _gemini_wide_scan(image_bytes, dish_name, clients, model)
        console.print(f"[green][Gemini Pass 1] Found {len(pass1_items)} item(s)[/green]")
        for item in pass1_items:
            name = item.get("name", "").lower().strip()
            if not name:
                continue
            confidence = item.get("confidence", 0)
            if name not in all_items or confidence > all_items[name].get("confidence", 0):
                all_items[name] = item

        # Pass 2 sees what THIS photo's Pass 1 found so far, not items
        # found in a previous photo in a multi-photo scan — it's hunting
        # for what this specific image's first pass missed.
        found_names = list(all_items.keys())
        pass2_items = _gemini_deep_scan(image_bytes, found_names, clients, model)
        console.print(f"[green][Gemini Pass 2] Found {len(pass2_items)} additional item(s)[/green]")
        for item in pass2_items:
            name = item.get("name", "").lower().strip()
            if not name or name in all_items:
                continue
            all_items[name] = item

    if not all_items:
        console.print("[yellow][WARNING] Gemini found nothing across both passes[/yellow]")
        return FridgeContents(ingredients=[])

    # Re-key each dict's own "name" onto the (already lowercased/stripped)
    # merge key — dedupe_detections() and is_blocked_detection() below both
    # read item["name"], and the extended fields ride along unchanged.
    items = [{**item, "name": name} for name, item in all_items.items()]
    items = [item for item in items if not is_blocked_detection(item["name"])]
    # floor=50 explicitly, not the module's default 60 — preserves this
    # path's existing confidence threshold; this is a matching-logic fix,
    # not a confidence-tuning change.
    items = [
        item for item in items
        if passes_confidence(item["name"], item.get("confidence", 0), floor=50)
    ]
    items = dedupe_detections(items)
    items = sorted(items, key=lambda x: x.get("confidence", 0), reverse=True)

    console.print(f"[green][OK] Vision succeeded: {len(items)} item(s) after filtering[/green]")

    ingredients = [
        Ingredient(
            name=item["name"],
            confidence=item.get("confidence", 0) / 100.0,
            category=item.get("category"),
            estimated_quantity=item.get("estimated_quantity"),
            state=item.get("state"),
            tier=_assign_tier(item),
            needs_confirmation=bool(item.get("needs_confirmation")),
            possible_matches=[m for m in (item.get("possible_matches") or []) if isinstance(m, str)],
        )
        for item in items
    ]

    return FridgeContents(
        ingredients=ingredients,
        raw_description=(
            f"{len(ingredients)} ingredient(s) detected in your fridge."
            if ingredients else "No ingredients detected."
        ),
    )


# ---------------------------------------------------------------------------
# Pretty-print helper (used by orchestrator and CLI)
# ---------------------------------------------------------------------------

def display_fridge_contents(contents: FridgeContents) -> None:
    """Render fridge contents as a Rich table."""
    console.rule("[bold green]Fridge Contents")
    console.print(f"\n[italic]{contents.raw_description}[/italic]\n")

    table = Table(title="Detected Ingredients", show_lines=True)
    table.add_column("Ingredient", style="cyan", no_wrap=True)
    table.add_column("Quantity", style="magenta")
    table.add_column("Confidence", justify="right")

    for ing in sorted(contents.ingredients, key=lambda i: -i.confidence):
        conf_color = "green" if ing.confidence >= 0.8 else "yellow" if ing.confidence >= 0.5 else "red"
        table.add_row(
            ing.name,
            ing.quantity or "—",
            f"[{conf_color}]{ing.confidence:.0%}[/{conf_color}]",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Identify ingredients in a fridge image.")
    p.add_argument("--image", required=True, help="Path to fridge image or public URL")
    p.add_argument("--model", default="gemini-2.5-flash", help="Gemini model ID")
    p.add_argument("--json", action="store_true", help="Output raw JSON instead of table")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    console.print(f"[bold]Analysing fridge image:[/bold] {args.image}")

    contents = identify_ingredients(args.image, model=args.model)

    if args.json:
        import json as _json
        data = {
            "raw_description": contents.raw_description,
            "ingredients": [
                {"name": i.name, "quantity": i.quantity, "confidence": i.confidence}
                for i in contents.ingredients
            ],
        }
        print(_json.dumps(data, indent=2))
    else:
        display_fridge_contents(contents)


if __name__ == "__main__":
    main()
