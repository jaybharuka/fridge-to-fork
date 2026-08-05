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
import json
import os
import time
from pathlib import Path
from typing import Union

import boto3
import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image, ImageEnhance
from rich.console import Console
from rich.table import Table

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
VISION_MODEL_FALLBACK_CHAIN = _dedupe([
    os.environ.get("GEMINI_VISION_MODEL", "gemini-2.0-flash"),
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash-lite",
    "gemini-flash-lite-latest",
])


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
# Prompt
# ---------------------------------------------------------------------------

def _build_vision_prompt(dish_name: str = "") -> str:
    """
    Built per-call (not a module constant) so the scan can be primed with
    the dish the user is targeting — Gemini pays extra attention to
    ingredients that dish commonly needs, without narrowing the scan to
    just those (it still reports everything visible).

    Deliberately shifted the false-positive/false-negative tradeoff to the
    code side rather than the prompt: an earlier, stricter version of this
    prompt ("only report if you're almost certain") suppressed real,
    clearly-visible items (mushrooms partially in a bag) along with the
    guessed ones (chicken/fish inferred from wrapped packaging). Asking
    Gemini to both detect thoroughly AND self-police confidence in one
    pass pushed it toward under-reporting. This version asks it to report
    everything it can identify — VISION_BLACKLIST and
    _deduplicate_items() below are the actual line of defense against
    false positives and repeat variants, not the model's own restraint.
    """
    dish_context = ""
    if dish_name:
        dish_context = f"\nContext: The user wants to cook {dish_name}. Pay special attention to ingredients relevant to this dish, but scan and report ALL visible food items regardless.\n"

    return f"""You are a comprehensive kitchen inventory scanner with excellent vision.{dish_context}

YOUR GOAL: Identify every food item visible in this fridge photo. Be thorough and complete. Missing a real item is worse than including an uncertain one — the code will filter out false positives.

SCANNING METHOD:
Scan the fridge systematically in this exact order:
1. Top shelf — left to right
2. Second shelf — left to right
3. Third shelf — left to right
4. Lower shelves and drawers — left to right
5. Door compartments — top to bottom

For each area, ask yourself: "What food items can I see here, even partially?"

WHAT TO REPORT:
- Fresh vegetables and fruits — even if partially visible or in bags
- Dairy products — milk, yogurt, paneer, cheese, butter, cream
- Eggs — if you can see an egg carton or individual eggs
- Fresh herbs — coriander, mint, curry leaves if visible
- Condiments and sauces — if you can identify them
- Cooked food in containers — describe what it appears to be
- Any clearly identifiable packaged food item

WHAT TO NEVER REPORT (hard rules, no exceptions):
- Meat, chicken, fish, seafood — ONLY if 100% unambiguously visible and unwrapped
- Sugar, flour, atta, maida — dry goods not stored in fridges
- Water bottles — not a food ingredient
- Generic "spices" or "condiments" — must be specific
- Non-food items
- Items you genuinely cannot see at all

CONFIDENCE SCORING:
- 90-100: Completely clear, no doubt whatsoever
- 75-89: Clearly visible but slightly obscured or partially in bag
- 60-74: Reasonably confident — include these, the code will verify
- Below 60: Skip

NAMING RULES:
- Standard English names only, never Hindi
- Singular: "tomato" not "tomatoes", "mushroom" not "mushrooms"
- Specific when possible: "button mushroom" not just "mushroom"
- Never brand names

Return ONLY a JSON array, no explanation, no markdown:
[
  {{"name": "button mushroom", "confidence": 82}},
  {{"name": "bell pepper", "confidence": 90}},
  {{"name": "eggs", "confidence": 95}}
]

If truly nothing is identifiable, return: []
"""


# ---------------------------------------------------------------------------
# Two-pass scan prompts — used by identify_ingredients() below.
# _build_vision_prompt() above is kept but no longer called directly by
# identify_ingredients(); superseded by these two.
# ---------------------------------------------------------------------------

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

Return ONLY a JSON array, no explanation:
[
  {{"name": "tomato", "confidence": 88}},
  {{"name": "green chilli", "confidence": 82}},
  {{"name": "curd", "confidence": 90}}
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
Return ONLY a JSON array of NEW items:
[{{"name": "lemon", "confidence": 78}}]

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


# Items that are almost never identified correctly from a fridge photo —
# either pantry staples that don't normally live in a fridge (sugar, flour,
# rice, dal), or the single most damaging class of false positive: meat/
# fish reported off a wrapped/opaque container's shape alone. Code-side
# backstop for the prompt above — never trust the model's own restraint
# alone for these.
VISION_BLACKLIST = {
    'sugar', 'flour', 'maida', 'atta', 'wheat flour',
    'rice', 'dal', 'lentil', 'lentils',
    'salt', 'water', 'water bottle',
    'spices', 'condiments', 'sauce', 'masala',
    'chicken', 'fish', 'meat', 'beef', 'pork', 'mutton', 'lamb',
    'shrimp', 'prawns', 'seafood',
    'bread', 'roti', 'chapati',
    'juice', 'soda', 'cola', 'drink',
    'oil', 'vegetable oil', 'cooking oil',
    'vinegar', 'pickle',
    # Rekognition's own FOOD_CATEGORIES label names — these bleed through
    # as detected "items" in their own right (a tomato photo gets both
    # "Tomato" and "Vegetable" as separate labels; the allowlist in
    # _identify_with_rekognition() correctly keeps both since it filters
    # by category membership, not name — this is what strips the generic
    # one back out afterward).
    'food', 'vegetable', 'fruit', 'produce', 'beverage',
    'dairy', 'herb', 'spice', 'grain', 'legume',
    'nut', 'condiment', 'baked goods', 'dessert', 'ingredient',
    'cooking', 'cuisine', 'meal', 'dish', 'snack', 'groceries',
    # Vessels/packaging Gemini reports as if they were the food itself
    # (a jar or dabba lid described in place of, or alongside, its actual
    # contents) — these are containers, not ingredients.
    'steel container', 'container', 'packet', 'package', 'wrapper',
    'bottle', 'jar', 'box', 'carton', 'bag', 'pouch', 'dabba',
    'utensil', 'vessel', 'pot', 'pan', 'bowl', 'plate', 'tray',
    'plastic bag', 'plastic container', 'glass container',
    'almond', 'cashew', 'walnut', 'raisin', 'dry fruit',
    # Dry/ground spices — never actually visible in a fridge photo
    # (stored in pantry jars, not the fridge), so any report of these is
    # a hallucination from generic "Indian kitchen" priors, not something
    # actually seen in the image.
    'cardamom', 'cinnamon', 'cloves', 'star anise', 'mace', 'nutmeg',
    'black pepper', 'white pepper', 'cumin', 'coriander powder',
    'turmeric', 'chilli powder', 'garam masala', 'bay leaf',
    'mustard seed', 'fenugreek', 'asafoetida', 'hing',
}


def _is_blacklisted(name: str) -> bool:
    """Word-boundary match, not substring — "bell pepper" must not get
    blocked just because "pepper" alone isn't blacklisted but shares
    letters with something that is. A blocked term (possibly multi-word,
    e.g. "water bottle") only fires when every one of its words appears
    as a whole word somewhere in the item name — so "rice" blocks
    "basmati rice", but "bell pepper" survives untouched."""
    name_words = set(name.lower().strip().split())
    for blocked in VISION_BLACKLIST:
        blocked_words = set(blocked.split())
        if blocked_words.issubset(name_words):
            return True
    return False


def _deduplicate_items(items: list[dict]) -> list[dict]:
    """
    Collapse variants of the same ingredient Gemini reported separately —
    e.g. "bell pepper", "red bell pepper", "green bell pepper" all landing
    as distinct items in one response. Keeps only the highest-confidence
    version of each. Sharing one word 4+ chars long is treated as "same
    ingredient" — good enough for the common "<color/descriptor> + noun"
    pattern without needing a real ingredient taxonomy.
    """
    items = sorted(items, key=lambda x: x.get('confidence', 0), reverse=True)

    kept = []
    for item in items:
        name = item['name'].lower().strip()
        name_words = set(name.split())

        is_duplicate = False
        for k in kept:
            k_name = k['name'].lower().strip()
            k_words = set(k_name.split())

            shared = name_words & k_words
            significant_shared = [w for w in shared if len(w) >= 4]

            if significant_shared:
                is_duplicate = True
                break

        if not is_duplicate:
            kept.append(item)

    return kept


def _preprocess_for_gemini(image_bytes: bytes) -> bytes:
    """
    Full preprocessing pipeline optimized for dark, cluttered Indian
    fridge photos, used by identify_ingredients() before every Gemini
    call: resize to 1024px, then brightness/contrast/sharpness/saturation
    enhancement. Self-contained (doesn't call _resize_image() or
    _enhance_for_detection() below) so it isn't coupled to those two,
    which are now dead code left over from the retired Rekognition path.
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


def _resize_image(image_bytes: bytes, max_size: int = 800) -> bytes:
    """Downscale to at most max_size px on the longest side and re-encode
    as JPEG before sending to Gemini — smaller payloads upload faster and
    keep multi-image scans well under Gemini's per-request limits. Always
    returns JPEG bytes regardless of the source format, so the caller must
    use "image/jpeg" as the mime type for the result, not the original."""
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    if img.mode not in ("RGB", "L"):
        # JPEG has no alpha channel — flatten PNGs/GIFs with transparency.
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


# ---------------------------------------------------------------------------
# AWS Rekognition — tried before Gemini (see identify_ingredients() below).
# Purpose-built label detection, 5000 free calls/month on the AWS free
# tier; Gemini is the emergency fallback when Rekognition has no
# credentials configured, errors, or returns nothing food-relevant.
# ---------------------------------------------------------------------------

# STRICT FOOD ALLOWLIST — only accept labels that Rekognition explicitly
# puts in one of these categories. No name-based blocklist, no confidence
# bypass: a label with none of these categories is skipped regardless of
# how high its own confidence is. Scales to anything Rekognition might
# detect (a person, a device, furniture, ...) without needing to keep
# expanding a blocklist to match every non-food thing it could ever return.
FOOD_CATEGORIES = {
    'food and drink',
    'food',
    'drink',
    'fruit',
    'vegetable',
    'dairy',
    'meat',
    'seafood',
    'herb and spice',
    'grain',
    'legume',
    'nut',
    'condiment and sauce',
    'baked goods',
    'dessert',
    'beverage',
    'produce',
}


def _enhance_for_detection(image_bytes: bytes) -> bytes:
    """
    Enhance image brightness and contrast for better detection in dark or
    poorly lit conditions — common in Indian household fridges (dim
    interior fridge lighting, photos often taken in an otherwise-dark
    kitchen). Applied before Rekognition, not before Gemini — Gemini's
    fallback path re-loads the original file independently.
    """
    img = Image.open(io.BytesIO(image_bytes))

    if img.mode != "RGB":
        img = img.convert("RGB")

    brightness = ImageEnhance.Brightness(img)
    img = brightness.enhance(1.3)

    contrast = ImageEnhance.Contrast(img)
    img = contrast.enhance(1.2)

    sharpness = ImageEnhance.Sharpness(img)
    img = sharpness.enhance(1.3)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _identify_with_rekognition(image_bytes: bytes) -> list[dict]:
    """
    AWS Rekognition — specialized label detection. Returns food-specific
    labels with high accuracy. 5000 free calls/month on the AWS free tier.
    Returns [] (never raises) on any failure — missing credentials, a
    network error, or an API error all just mean "no results from this
    source", not a scan failure.
    """
    access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    region = os.getenv("AWS_REGION", "ap-south-1")

    if not access_key or not secret_key:
        print("[Rekognition] No AWS credentials found — skipping")
        return []

    try:
        client = boto3.client(
            "rekognition",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

        response = client.detect_labels(
            Image={"Bytes": image_bytes},
            MaxLabels=80,
            MinConfidence=50,
        )

        items = []

        for label in response.get("Labels", []):
            name = label.get("Name", "").lower().strip()
            confidence = int(label.get("Confidence", 0))

            # Get all categories Rekognition assigned to this label
            categories = {
                c.get("Name", "").lower()
                for c in label.get("Categories", [])
            }

            # ONLY include if at least one category is in our food allowlist
            # No exceptions, no confidence threshold bypass
            if not categories.intersection(FOOD_CATEGORIES):
                continue

            items.append({"name": name, "confidence": confidence})

        print(f"[Rekognition] Raw results: {len(items)} food items")
        return items

    except Exception as e:
        print(f"[Rekognition] Error: {e}")
        return []


# ---------------------------------------------------------------------------
# LogMeal — tried before Rekognition (see identify_ingredients() below).
# Purpose-built food segmentation/recognition, 200 free calls/month.
# ---------------------------------------------------------------------------

def _identify_with_logmeal(image_bytes: bytes) -> list[dict]:
    """
    LogMeal food recognition — purpose-built for food ingredient detection.
    Uses the /image/segmentation/complete endpoint. 200 free calls/month.
    Returns [] (never raises) on any failure — missing key, auth failure,
    network error, or non-200 response all just mean "no results from
    this source", not a scan failure.
    """
    api_key = os.getenv("LOGMEAL_API_KEY", "")
    if not api_key:
        print("[LogMeal] No API key found")
        return []

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.logmeal.com/v2/image/segmentation/complete",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"image": ("fridge.jpg", image_bytes, "image/jpeg")},
            )

            if resp.status_code == 401:
                print("[LogMeal] Auth failed — check LOGMEAL_API_KEY")
                return []

            if resp.status_code != 200:
                print(f"[LogMeal] Error {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json()
            items = []

            for food in data.get("segmentation_results", []):
                for recognition in food.get("recognition_results", []):
                    name = recognition.get("name", "").lower().strip()
                    prob = recognition.get("prob", 0)
                    confidence = int(prob * 100)

                    if name and confidence >= 50:
                        items.append({"name": name, "confidence": confidence})

            print(f"[LogMeal] Found {len(items)} items")
            return items

    except Exception as e:
        print(f"[LogMeal] Exception: {e}")
        return []


# ---------------------------------------------------------------------------
# Core vision function
# ---------------------------------------------------------------------------

def _call_vision_model_with_retry(
    client: genai.Client, model: str, image_parts: list[types.Part], prompt: str
) -> FridgeContents:
    """
    Call `model` up to 3 times with exponential backoff, for transient
    errors (503/network blips). Raises the last exception if all
    attempts fail — the caller decides whether that means "try the next
    model in the fallback chain" or "give up".
    """
    max_retries = 3
    backoff = 1.0
    # Gemini accepts multiple images in one call natively — no extra cost
    # or latency versus a single image. With more than one, tell it
    # explicitly not to double-count ingredients seen in more than one shot.
    contents = list(image_parts)
    if len(image_parts) > 1:
        contents.append(
            f"You are analyzing {len(image_parts)} photos of the same fridge, taken "
            "from different angles or shelves. Combine your findings across all "
            "photos — report each unique ingredient only once, even if it appears "
            "in more than one photo."
        )
    contents.append(prompt)
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                # A short JSON array of detected ingredients should never
                # need more than a few hundred tokens. Capping this makes a
                # misbehaving model (seen returning 150KB+ of truncated,
                # unparseable text) fail fast and cheaply instead of
                # burning a full attempt generating runaway output.
                config=types.GenerateContentConfig(max_output_tokens=2048),
            )

            raw_text = response.text.strip()

            # Strip markdown fences if the model wraps the JSON
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            items = json.loads(raw_text)

            # The prompt now asks Gemini to report thoroughly rather than
            # self-police confidence — these three code-side passes are
            # the actual accuracy gate: strip categories it should never
            # guess (meat/fish/pantry staples), drop anything genuinely
            # low-confidence, then collapse repeat variants of the same
            # ingredient ("bell pepper" / "red bell pepper" / "green bell
            # pepper") down to the best single report of each.
            items = [item for item in items if not _is_blacklisted(item.get("name", ""))]
            items = [item for item in items if item.get("confidence", 0) >= 60]
            items = _deduplicate_items(items)
            items = sorted(items, key=lambda x: x.get("confidence", 0), reverse=True)

            ingredients = [
                Ingredient(
                    name=item["name"],
                    # Prompt reports confidence on a 0-100 scale; Ingredient's
                    # confidence field is documented (models.py) as 0.0-1.0,
                    # so convert here — keeps this function's return format
                    # unchanged for every downstream caller.
                    confidence=item.get("confidence", 0) / 100.0,
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

        except Exception as e:
            console.print(f"[yellow][WARNING] {model} attempt {attempt} failed: {type(e).__name__}: {e}[/yellow]")
            if attempt == max_retries:
                raise
            time.sleep(backoff)
            backoff *= 2

    raise RuntimeError(f"{model} failed after {max_retries} attempts")  # unreachable safeguard


# ---------------------------------------------------------------------------
# Two-pass Gemini scanning — used by identify_ingredients() below.
# ---------------------------------------------------------------------------

def _call_gemini_vision(image_bytes: bytes, prompt: str, client: genai.Client, model: str) -> list[dict]:
    """
    Single Gemini vision call for one prompt/image. Raises on failure
    (network error, quota exhaustion, unparseable response) rather than
    swallowing it — _call_gemini_vision_with_fallback() below is what
    catches that and moves on to the next model in the fallback chain,
    same reasoning as _call_vision_model_with_retry() uses for the
    single-pass path. Returns a plain list[dict] of {"name", "confidence"}
    rather than a FridgeContents, since two passes' worth of results get
    merged (in identify_ingredients()) before that conversion happens.

    Uses types.Part.from_bytes() (the same pattern already proven
    throughout this file) rather than hand-building a base64 inline_data
    payload — the google-genai SDK's generate_content() expects Part
    objects, not raw REST-style dicts.
    """
    response = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt],
        config=types.GenerateContentConfig(max_output_tokens=2048),
    )

    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    items = json.loads(raw_text)
    return items if isinstance(items, list) else []


def _call_gemini_vision_with_fallback(
    client: genai.Client, image_bytes: bytes, prompt: str, model: str | None = None
) -> list[dict]:
    """Tries each model in VISION_MODEL_FALLBACK_CHAIN (an explicit
    `model` override first, if given, same convention as
    _identify_with_gemini_fallback()) until one succeeds. Returns []
    only if every model in the chain fails — this is the resilience the
    rest of this file relies on for quota exhaustion, applied per scan
    pass instead of once per whole scan."""
    chain = _dedupe([model, *VISION_MODEL_FALLBACK_CHAIN]) if model else VISION_MODEL_FALLBACK_CHAIN
    for chain_model in chain:
        try:
            return _call_gemini_vision(image_bytes, prompt, client, chain_model)
        except Exception as e:
            print(f"[Gemini] {chain_model} failed: {type(e).__name__}: {e}")
    return []


def _gemini_wide_scan(image_bytes: bytes, dish_name: str, client: genai.Client, model: str | None = None) -> list[dict]:
    """Pass 1 — scan entire fridge for all visible food items."""
    prompt = _build_wide_scan_prompt(dish_name)
    return _call_gemini_vision_with_fallback(client, image_bytes, prompt, model)


def _gemini_deep_scan(image_bytes: bytes, found_items: list[str], client: genai.Client, model: str | None = None) -> list[dict]:
    """Pass 2 — focus on areas and items that might have been missed."""
    prompt = _build_deep_scan_prompt(found_items)
    return _call_gemini_vision_with_fallback(client, image_bytes, prompt, model)


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
    good fit for kitchen ingredients). _identify_with_logmeal() and
    _identify_with_rekognition() are left defined but unused rather than
    deleted, in case either is worth revisiting later — same for the
    single-pass _call_vision_model_with_retry()/_identify_with_gemini_fallback()
    machinery this two-pass approach supersedes.

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
        Optional pre-built Gemini client (useful for testing / DI).

    Returns
    -------
    FridgeContents with a list of Ingredient objects.
    """
    sources = image_source if isinstance(image_source, list) else [image_source]

    try:
        client = client or genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    except Exception as e:
        console.print(f"[yellow][WARNING] Could not init Gemini client: {type(e).__name__}: {e}[/yellow]")
        return _fallback_fridge_contents()

    all_items: dict[str, int] = {}  # name -> highest confidence across all photos/passes

    for source in sources:
        try:
            raw_bytes, _media_type = _load_image(source)
            image_bytes = _preprocess_for_gemini(raw_bytes)
        except Exception as e:
            console.print(f"[yellow][WARNING] Could not prepare image: {type(e).__name__}: {e}[/yellow]")
            continue

        pass1_items = _gemini_wide_scan(image_bytes, dish_name, client, model)
        console.print(f"[green][Gemini Pass 1] Found {len(pass1_items)} item(s)[/green]")
        for item in pass1_items:
            name = item.get("name", "").lower().strip()
            if not name:
                continue
            confidence = item.get("confidence", 0)
            if name not in all_items or confidence > all_items[name]:
                all_items[name] = confidence

        # Pass 2 sees what THIS photo's Pass 1 found so far, not items
        # found in a previous photo in a multi-photo scan — it's hunting
        # for what this specific image's first pass missed.
        found_names = list(all_items.keys())
        pass2_items = _gemini_deep_scan(image_bytes, found_names, client, model)
        console.print(f"[green][Gemini Pass 2] Found {len(pass2_items)} additional item(s)[/green]")
        for item in pass2_items:
            name = item.get("name", "").lower().strip()
            if not name or name in all_items:
                continue
            all_items[name] = item.get("confidence", 0)

    if not all_items:
        console.print("[yellow][WARNING] Gemini found nothing across both passes[/yellow]")
        return FridgeContents(ingredients=[])

    items = [{"name": name, "confidence": confidence} for name, confidence in all_items.items()]
    items = [item for item in items if not _is_blacklisted(item["name"])]
    items = [item for item in items if item["confidence"] >= 50]
    items = _deduplicate_items(items)
    items = sorted(items, key=lambda x: x["confidence"], reverse=True)

    console.print(f"[green][OK] Vision succeeded: {len(items)} item(s) after filtering[/green]")

    ingredients = [
        Ingredient(name=item["name"], confidence=item["confidence"] / 100.0)
        for item in items
    ]

    return FridgeContents(
        ingredients=ingredients,
        raw_description=(
            f"{len(ingredients)} ingredient(s) detected in your fridge."
            if ingredients else "No ingredients detected."
        ),
    )


def _identify_with_gemini_fallback(
    image_source: Union[str, Path, bytes, list[Union[str, Path, bytes]]],
    dish_name: str = "",
    *,
    model: str | None = None,
    client: genai.Client | None = None,
) -> FridgeContents:
    """
    Last-resort fallback when both LogMeal and Rekognition return nothing
    for a photo — the original Gemini-only implementation, unchanged in
    behavior, just no longer the primary path (see identify_ingredients()
    above).

    Parameters
    ----------
    image_source:
        A single file path (str/Path), public image URL (str), or raw image
        bytes — or a list of up to 3 of those (e.g. several angles/shelves
        of the same fridge). All images in a list are sent to Gemini
        together in one call; the model is told to de-duplicate ingredients
        it sees in more than one photo.
    dish_name:
        Optional dish the user is targeting — when given, the scan is
        primed to pay extra attention to that dish's typical ingredients
        without narrowing the scan to just those (see
        _build_vision_prompt()). Omit for a generic, unprimed scan.
    model:
        Optional Gemini model override. If omitted, tries each model in
        VISION_MODEL_FALLBACK_CHAIN in order until one succeeds.
    client:
        Optional pre-built Gemini client (useful for testing / DI).

    Returns
    -------
    FridgeContents with a list of Ingredient objects.

    Retries transient API errors (quota/overload) up to 3 times with
    exponential backoff per model. If a model's quota is exhausted (or it
    keeps failing after retries), moves on to the next model in the
    fallback chain before giving up and returning a placeholder inventory.
    """
    sources = image_source if isinstance(image_source, list) else [image_source]
    prompt = _build_vision_prompt(dish_name)

    try:
        client = client or genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        image_parts = []
        for source in sources:
            raw_bytes, _media_type = _load_image(source)
            # _resize_image() always re-encodes as JPEG regardless of the
            # source format, so the mime type sent alongside it must be
            # "image/jpeg" too — not the original _media_type (e.g. a PNG
            # sent as image/jpeg would be malformed).
            raw_bytes = _resize_image(raw_bytes)
            image_parts.append(types.Part.from_bytes(data=raw_bytes, mime_type="image/jpeg"))
    except Exception as e:
        console.print(f"[yellow][WARNING] Could not prepare image(s) for vision analysis: {type(e).__name__}: {e}[/yellow]")
        return _fallback_fridge_contents()

    chain = _dedupe([model, *VISION_MODEL_FALLBACK_CHAIN]) if model else VISION_MODEL_FALLBACK_CHAIN

    for chain_model in chain:
        try:
            result = _call_vision_model_with_retry(client, chain_model, image_parts, prompt)
            console.print(f"[green][OK] Vision succeeded with model: {chain_model}[/green]")
            return result
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                console.print(f"[yellow][WARNING] {chain_model} quota exhausted, trying next model...[/yellow]")
            else:
                console.print(f"[yellow][WARNING] {chain_model} failed with: {e}, trying next...[/yellow]")

    console.print("[yellow][WARNING] All Gemini vision models quota exhausted, using fallback[/yellow]")
    return _fallback_fridge_contents()


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
