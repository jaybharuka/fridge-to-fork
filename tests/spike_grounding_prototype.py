"""
SPIKE — Gemini object-detection ("grounding") bounding-box prototype.
======================================================================
Investigation for the YOLO-fusion follow-up: does asking Gemini for
bounding boxes (instead of / alongside the current free-text ingredient
list) give usable per-instance counts, and what does it cost in latency
against the app's real 60s-per-scan budget?

NOT wired into app.py or step1_fridge_vision.py. This file defines its
own standalone `_detect_boxes()` call and only *reads* two pure helpers
from step1_fridge_vision.py (_load_image, _preprocess_for_gemini) so the
image going into this experiment is prepared identically to what the real
pipeline sees — nothing in the production path is modified or imported in
a way that changes its behaviour.

Prompting approach is NOT response_schema/structured output. A benchmark
(simedw.com, 5000-image eval) found response_schema measurably *hurts*
bounding-box mAP on Flash and Flash-Lite specifically (the two model
families that make up 4 of 5 entries in VISION_MODEL_FALLBACK_CHAIN) —
Flash: 0.261 mAP unstructured vs 0.224 structured; Flash-Lite: 0.211 vs
0.156. Structured output only helps the Pro tier. So this spike uses the
same free-text-prompt-then-json.loads() pattern the current ingredient
scan already uses, on gemini-2.5-flash (the chain's primary model) only —
matching what most real scans actually run on.

Run:
    python -m tests.spike_grounding_prototype
    python -m tests.spike_grounding_prototype --photo ZUhM8LE_HGc.jpg

Requires GOOGLE_API_KEY in .env. Hits the live API — real (tiny) cost.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google import genai
from google.genai import types

from fridge_to_fork.step1_fridge_vision import (
    _load_image,
    _preprocess_for_gemini,
    identify_ingredients,
)

load_dotenv()

EVAL_DATA = Path(__file__).parent / "eval_data"
PHOTOS_DIR = EVAL_DATA / "photos"
MODEL = "gemini-2.5-flash"  # chain's primary model — see module docstring

GROUNDING_PROMPT = """\
Detect the 2D bounding boxes of every distinct food/grocery item instance
visible in this fridge photo. If the same kind of item appears more than
once (e.g. 3 separate eggs, 2 tomatoes), report EACH instance as its own
box — do not collapse repeats into one box.

Output ONLY a JSON array, no markdown fences, no prose. Each element:
{"box_2d": [ymin, xmin, ymax, xmax], "label": "item name"}
Coordinates are normalized to a 0-1000 scale (Gemini's standard box format).
"""


def _detect_boxes(image_bytes: bytes, client: genai.Client) -> list[dict]:
    """One free-text grounding call. Raises on failure — caller times/catches."""
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            GROUNDING_PROMPT,
        ],
        config=types.GenerateContentConfig(max_output_tokens=4096),
    )
    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def _counts_by_label(boxes: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for b in boxes:
        label = str(b.get("label", "?")).strip().lower()
        counts[label] = counts.get(label, 0) + 1
    return counts


def run_one(photo_path: Path, client: genai.Client) -> dict:
    result: dict = {"file": photo_path.name}

    # --- baseline: today's real production call (unmodified) ---
    t0 = time.time()
    try:
        fridge = identify_ingredients(str(photo_path), client=client)
        result["baseline_seconds"] = round(time.time() - t0, 2)
        result["baseline_items"] = [i.name for i in fridge.ingredients]
        result["baseline_has_counts"] = any(
            i.quantity for i in fridge.ingredients
        )  # expected False — see module docstring
    except Exception as e:
        result["baseline_seconds"] = round(time.time() - t0, 2)
        result["baseline_error"] = f"{type(e).__name__}: {e}"

    # --- grounding spike: new standalone call ---
    raw_bytes, _ = _load_image(str(photo_path))
    image_bytes = _preprocess_for_gemini(raw_bytes)
    t1 = time.time()
    try:
        boxes = _detect_boxes(image_bytes, client)
        result["grounding_seconds"] = round(time.time() - t1, 2)
        result["grounding_box_count"] = len(boxes)
        result["grounding_counts_by_label"] = _counts_by_label(boxes)
    except Exception as e:
        result["grounding_seconds"] = round(time.time() - t1, 2)
        result["grounding_error"] = f"{type(e).__name__}: {e}"

    result["combined_seconds"] = round(
        result.get("baseline_seconds", 0) + result.get("grounding_seconds", 0), 2
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", default=None, help="Single photo filename to test")
    args = parser.parse_args()

    import os

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    photos = (
        [PHOTOS_DIR / args.photo]
        if args.photo
        else sorted(PHOTOS_DIR.glob("*.jpg"))
    )

    results = []
    for photo in photos:
        print(f"\n=== {photo.name} ===")
        r = run_one(photo, client)
        results.append(r)
        print(json.dumps(r, indent=2))

    print("\n\n===== SUMMARY =====")
    print(f"{'file':<20} {'baseline_s':>10} {'grounding_s':>12} {'combined_s':>11} {'boxes':>6}")
    for r in results:
        print(
            f"{r['file']:<20} {r.get('baseline_seconds', '-'):>10} "
            f"{r.get('grounding_seconds', '-'):>12} {r.get('combined_seconds', '-'):>11} "
            f"{r.get('grounding_box_count', '-'):>6}"
        )
    worst = max((r.get("combined_seconds", 0) for r in results), default=0)
    print(f"\nWorst combined (baseline + grounding) single-photo time: {worst}s vs 60s budget")

    out_path = EVAL_DATA / "spike_grounding_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"Full results written to {out_path}")


if __name__ == "__main__":
    main()
