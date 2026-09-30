"""
Throwaway Groq vision sanity-check
===================================
NOT a substitute for the real Gemini Phase 2 baseline
(tests/eval_vision_accuracy.py) — this is a second-opinion run against a
different vision model, purely to sanity-check the eval harness itself
same-day while Gemini's 20/day free-tier quota is exhausted. Groq's free
tier is 30 RPM / 1,000 RPD for its vision model (checked live via
console.groq.com/docs, not assumed), so it doesn't hit the same wall.

Reuses the exact same ground_truth.json, the same wide+deep two-pass
prompts and image preprocessing from step1_fridge_vision.py, and the same
scoring logic from eval_vision_accuracy.py — only the model-calling layer
is swapped for Groq's OpenAI-compatible chat completions endpoint. Does
NOT touch step1_fridge_vision.py or the real pipeline in any way.

Model: qwen/qwen3.8-27b — Groq's current vision-capable model (verified
live against console.groq.com/docs/vision and /docs/rate-limits; "Llama
3.2 Vision", the obvious training-data guess, is deprecated on Groq as of
this check). A much smaller/weaker general-purpose model than Gemini 2.5
Flash — expect this score to run lower. That's not new information about
the app's real accuracy, just about swapping in a weaker model; only
useful as a check that the harness scores something sane end-to-end.

Each pass sends exactly 1 image (same as the Gemini path), well under
Groq's 3-images-per-request cap — so the two-pass shape itself is not a
fair-comparison concession here, only the model swap is.

Requires GROQ_API_KEY in .env.

    python -m tests.eval_vision_accuracy_groq
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fridge_to_fork.ingredient_matching import dedupe_detections, is_blocked_detection, passes_confidence
from fridge_to_fork.step1_fridge_vision import (
    _build_deep_scan_prompt,
    _build_wide_scan_prompt,
    _load_image,
    _preprocess_for_gemini,
)
from tests.eval_vision_accuracy import GROUND_TRUTH_PATH, PHOTOS_DIR, _score_photo, print_scorecard

load_dotenv()

GROQ_MODEL = "qwen/qwen3.8-27b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _call_groq_vision(image_bytes: bytes, prompt: str) -> list[dict]:
    """One Groq vision call for one prompt/image — plain httpx against the
    OpenAI-compatible endpoint (httpx is already a dependency here; no
    need to add the groq SDK for one REST call)."""
    api_key = os.environ["GROQ_API_KEY"]
    b64 = base64.b64encode(image_bytes).decode()
    resp = httpx.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": GROQ_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            "max_tokens": 2048,
            "temperature": 0.2,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    raw_text = resp.json()["choices"][0]["message"]["content"].strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    # Qwen sometimes wraps the array in a sentence despite "JSON only" —
    # grab the first [...] block rather than failing the whole pass.
    start, end = raw_text.find("["), raw_text.rfind("]")
    if start != -1 and end != -1:
        raw_text = raw_text[start:end + 1]

    items = json.loads(raw_text)
    return items if isinstance(items, list) else []


def _identify_with_groq(photo_path: Path) -> list[str]:
    """Same wide+deep two-pass structure identify_ingredients() uses for
    Gemini, reusing its exact prompt builders and image preprocessing —
    only the model-calling layer differs."""
    raw_bytes, _ = _load_image(str(photo_path))
    image_bytes = _preprocess_for_gemini(raw_bytes)

    all_items: dict[str, int] = {}

    for item in _call_groq_vision(image_bytes, _build_wide_scan_prompt()):
        name = item.get("name", "").lower().strip()
        if name:
            all_items[name] = max(all_items.get(name, 0), item.get("confidence", 0))

    for item in _call_groq_vision(image_bytes, _build_deep_scan_prompt(list(all_items.keys()))):
        name = item.get("name", "").lower().strip()
        if name and name not in all_items:
            all_items[name] = item.get("confidence", 0)

    items = [{"name": n, "confidence": c} for n, c in all_items.items()]
    items = [i for i in items if not is_blocked_detection(i["name"])]
    # floor=50, matching step1_fridge_vision.py's identify_ingredients() —
    # not the module's default 60.
    items = [i for i in items if passes_confidence(i["name"], i["confidence"], floor=50)]
    items = dedupe_detections(items)
    return [i["name"] for i in items]


def run_eval() -> list:
    ground_truth = json.loads(GROUND_TRUTH_PATH.read_text())
    results = []
    for entry in ground_truth["photos"]:
        photo_path = PHOTOS_DIR / entry["file"]
        if not photo_path.exists():
            print(f"SKIP  {entry['file']} — not found in {PHOTOS_DIR}")
            continue

        print(f"Scanning {entry['file']}  ({entry['description']})...")
        t0 = time.perf_counter()
        try:
            detected = _identify_with_groq(photo_path)
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            detected = []
        elapsed = time.perf_counter() - t0

        result = _score_photo(entry["file"], detected, entry)
        result.seconds = elapsed
        results.append(result)

        print(f"  {elapsed:.1f}s — detected: {detected}")
        print(f"  matched {len(result.matched_certain)}/{len(entry['certain'])} certain items"
              + (f", missed: {result.missed_certain}" if result.missed_certain else ""))
        if result.distractor_hits:
            print(f"  [!] hallucinated distractor(s): {result.distractor_hits}")
        if result.unmatched_extra:
            print(f"  unmatched/extra: {result.unmatched_extra}")
        print()
    return results


def main() -> None:
    results = run_eval()
    print_scorecard(results, model_label=f"groq:{GROQ_MODEL} — SANITY CHECK ONLY, not the real Gemini number")


if __name__ == "__main__":
    main()
