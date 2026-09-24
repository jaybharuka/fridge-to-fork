"""
Fridge-vision accuracy eval harness
====================================
Phase 1 of the vision-accuracy audit (see the conversation this was built
from — no eval methodology existed before this). Runs the REAL
identify_ingredients() pipeline (real Gemini calls, real cost/latency)
against a small hand-labeled photo set and prints a precision/recall
scorecard — the thing that turns "I think this prompt/model change helped"
into an actual number.

Deliberately NOT part of the mocked pytest suite (tests/test_step1_*.py) —
this hits the live API on purpose and costs real (tiny) money and ~10-30s
per photo. Run it explicitly, before and after any pipeline change:

    python -m tests.eval_vision_accuracy
    python -m tests.eval_vision_accuracy --model gemini-2.5-flash

Requires GOOGLE_API_KEY in .env, same as the app itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fridge_to_fork.step1_fridge_vision import identify_ingredients
from fridge_to_fork.step2_meal_planner import _fuzzy_ingredient_match

load_dotenv()

EVAL_DATA = Path(__file__).parent / "eval_data"
GROUND_TRUTH_PATH = EVAL_DATA / "ground_truth.json"
PHOTOS_DIR = EVAL_DATA / "photos"


@dataclass
class PhotoResult:
    file: str
    detected: list[str]
    matched_certain: list[str] = field(default_factory=list)
    missed_certain: list[str] = field(default_factory=list)
    matched_partial: list[str] = field(default_factory=list)
    distractor_hits: list[str] = field(default_factory=list)
    unmatched_extra: list[str] = field(default_factory=list)
    seconds: float = 0.0


def _score_photo(file: str, detected_names: list[str], gt: dict) -> PhotoResult:
    """Fuzzy-matches detected names against this photo's ground truth, using the
    exact same word-overlap matcher step2_meal_planner.py uses to decide
    have-vs-missing in the real app — so this eval's notion of "found" matches
    what the app itself would credit, including catching the same kind of
    vocabulary-mismatch gap (e.g. "capsicum" vs "bell pepper") the app has."""
    r = PhotoResult(file=file, detected=detected_names)
    remaining = list(detected_names)

    def _claim(name: str) -> bool:
        for d in remaining:
            if _fuzzy_ingredient_match(name, [d]) or _fuzzy_ingredient_match(d, [name]):
                remaining.remove(d)
                return True
        return False

    for name in gt["certain"]:
        (r.matched_certain if _claim(name) else r.missed_certain).append(name)
    for name in gt["partial"]:
        if _claim(name):
            r.matched_partial.append(name)
    for name in gt.get("distractors", []):
        if _claim(name):
            r.distractor_hits.append(name)

    r.unmatched_extra = remaining  # whatever's left wasn't claimed by certain/partial/distractor
    return r


def run_eval(model: str | None = None) -> list[PhotoResult]:
    ground_truth = json.loads(GROUND_TRUTH_PATH.read_text())
    results = []

    for entry in ground_truth["photos"]:
        photo_path = PHOTOS_DIR / entry["file"]
        if not photo_path.exists():
            print(f"SKIP  {entry['file']} — not found in {PHOTOS_DIR}")
            continue

        print(f"Scanning {entry['file']}  ({entry['description']})...")
        t0 = time.perf_counter()
        fridge = identify_ingredients(str(photo_path), model=model)
        elapsed = time.perf_counter() - t0

        detected = [i.name for i in fridge.ingredients]
        result = _score_photo(entry["file"], detected, entry)
        result.seconds = elapsed
        results.append(result)

        print(f"  {elapsed:.1f}s — detected: {detected}")
        print(f"  matched {len(result.matched_certain)}/{len(entry['certain'])} certain items"
              + (f", missed: {result.missed_certain}" if result.missed_certain else ""))
        if result.distractor_hits:
            print(f"  [!] hallucinated distractor(s): {result.distractor_hits}")
        if result.unmatched_extra:
            print(f"  unmatched/extra (review — could be real or a hallucination): {result.unmatched_extra}")
        print()

    return results


def print_scorecard(results: list[PhotoResult], model_label: str) -> None:
    total_certain = sum(len(r.matched_certain) + len(r.missed_certain) for r in results)
    total_matched_certain = sum(len(r.matched_certain) for r in results)
    total_detected = sum(len(r.detected) for r in results)
    total_distractor_hits = sum(len(r.distractor_hits) for r in results)
    total_unmatched = sum(len(r.unmatched_extra) for r in results)
    total_partial_matched = sum(len(r.matched_partial) for r in results)
    total_seconds = sum(r.seconds for r in results)

    recall = total_matched_certain / total_certain if total_certain else 0.0
    # A detection counts as "not a hallucination" if it matched a certain OR
    # partial ground-truth item; only a distractor hit or a fully-unmatched
    # extra counts against precision.
    acceptable_detections = total_detected - total_distractor_hits - total_unmatched
    precision = acceptable_detections / total_detected if total_detected else 0.0

    print("=" * 70)
    print(f"SCORECARD — model={model_label}, {len(results)} photo(s)")
    print("=" * 70)
    print(f"Recall (certain items found):     {total_matched_certain}/{total_certain}  ({recall:.0%})")
    print(f"Precision (detections not junk):  {acceptable_detections}/{total_detected}  ({precision:.0%})")
    print(f"  of which distractor hallucinations: {total_distractor_hits}")
    print(f"  of which unmatched/needs-review:    {total_unmatched}")
    print(f"Bonus: partial (hard) items recovered anyway: {total_partial_matched}")
    print(f"Total wall-clock time: {total_seconds:.1f}s ({total_seconds / len(results):.1f}s/photo avg)" if results else "")
    print()
    print("Per-photo missed certain items (the 'clearly visible but reported missing' failure mode):")
    for r in results:
        if r.missed_certain:
            print(f"  {r.file}: {r.missed_certain}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the fridge-vision accuracy eval against the hand-labeled photo set.")
    p.add_argument("--model", default=None, help="Gemini model override (default: whatever identify_ingredients() uses in production)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    results = run_eval(model=args.model)
    print_scorecard(results, model_label=args.model or "(production default)")


if __name__ == "__main__":
    main()
