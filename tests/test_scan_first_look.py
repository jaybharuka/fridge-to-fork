"""
Progressive "first look" of a fridge scan: identify_ingredients(on_pass1=...) reports each photo's pass-1 items, /api/scan
forwards them as step1_partial events, and the final result is the same with or without them. Gemini is scripted: zero
network or quota cost. Run: pytest tests/test_scan_first_look.py
"""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork import step1_fridge_vision as vision
from fridge_to_fork.models import FridgeContents, Ingredient


def item(name, confidence, **extra):
    return {"name": name, "confidence": confidence, "category": "produce", "state": "fresh", "needs_confirmation": False, "possible_matches": [], **extra}


def run(passes, sources=(b"a",), on_pass1=None):
    """identify_ingredients with each Gemini call answered from `passes` in order (wide, deep, wide, deep, ...)."""
    replies = iter(passes)
    with patch.object(vision, "_call_gemini_vision_with_fallback", side_effect=lambda *args, **kw: next(replies)), \
         patch.object(vision, "_preprocess_for_gemini", side_effect=lambda raw: raw):
        return vision.identify_ingredients(list(sources), client=MagicMock(), on_pass1=on_pass1)


PASS1 = [item("tomato", 90), item("salt", 95), item("onion", 40), item("milk", 70), item("paneer", 85)]
PASS2 = [item("lemon", 75), item("cherry tomato", 80)]


class FirstLookCallbackTests(unittest.TestCase):
    def test_the_result_is_identical_with_and_without_the_callback(self):
        plain = run([PASS1, PASS2])
        seen = []
        hooked = run([PASS1, PASS2], on_pass1=lambda *args: seen.append(args))
        self.assertEqual(plain.ingredients, hooked.ingredients)
        self.assertEqual(plain.raw_description, hooked.raw_description)
        self.assertTrue(seen)

    def test_it_is_called_once_per_photo_with_the_filtered_sorted_shape_the_step1_event_uses(self):
        seen = []
        run([PASS1, PASS2], on_pass1=lambda *args: seen.append(args))
        self.assertEqual(len(seen), 1)
        items, photo_index, photo_count = seen[0]
        self.assertEqual((photo_index, photo_count), (1, 1))
        # salt is a blocked pantry item and onion is under the confidence floor of 50; sorted by confidence like the final list
        self.assertEqual(items, [
            {"name": "tomato", "quantity": "", "confidence": 90},
            {"name": "paneer", "quantity": "", "confidence": 85},
            {"name": "milk", "quantity": "", "confidence": 70},
        ])

    def test_it_is_not_called_when_pass_1_found_nothing(self):
        seen = []
        run([[], PASS2], on_pass1=lambda *args: seen.append(args))
        self.assertEqual(seen, [])

    def test_it_is_not_called_when_everything_in_pass_1_is_filtered_out(self):
        seen = []
        run([[item("salt", 95), item("onion", 40)], []], on_pass1=lambda *args: seen.append(args))
        self.assertEqual(seen, [])

    def test_a_failing_callback_never_breaks_the_scan(self):
        def boom(*args):
            raise RuntimeError("queue is on fire")

        hooked = run([PASS1, PASS2], on_pass1=boom)
        self.assertEqual(hooked.ingredients, run([PASS1, PASS2]).ingredients)

    def test_multi_photo_calls_are_cumulative_and_numbered(self):
        seen = []
        run([[item("tomato", 90)], [], [item("milk", 80)], []], sources=(b"a", b"b"), on_pass1=lambda *args: seen.append(args))
        self.assertEqual([(i, n) for _, i, n in seen], [(1, 2), (2, 2)])
        self.assertEqual([x["name"] for x in seen[0][0]], ["tomato"])
        self.assertEqual([x["name"] for x in seen[1][0]], ["tomato", "milk"])  # everything so far, not just photo 2

    def test_nothing_shown_early_is_missing_from_the_final_list_in_the_ordinary_case(self):
        seen = []
        final = run([PASS1, [item("lemon", 75)]], on_pass1=lambda *args: seen.append(args))
        shown = {x["name"] for x in seen[0][0]}
        self.assertTrue(shown <= {i.name for i in final.ingredients})
        self.assertEqual(final.early_superseded, [])

    def test_a_variant_that_replaces_an_early_item_is_reported_and_logged(self):
        # first look shows "tomato" (90); pass 2 returns "cherry tomato" (95): the final dedupe keeps the higher-confidence variant
        with patch("builtins.print") as printed:
            final = run([[item("tomato", 90)], [item("cherry tomato", 95)]], on_pass1=lambda *args: None)
        self.assertEqual([i.name for i in final.ingredients], ["cherry tomato"])
        self.assertEqual(final.early_superseded, [{"from": "tomato", "to": "cherry tomato"}])
        lines = " ".join(str(c.args[0]) for c in printed.call_args_list if c.args)
        self.assertIn("first_look superseded: 'tomato' -> 'cherry tomato'", lines)
        self.assertIn("first_look summary: shown=1 final=1 superseded=1", lines)

    def test_no_early_event_means_nothing_is_reported_as_superseded(self):
        self.assertEqual(run([[item("tomato", 90)], [item("cherry tomato", 95)]]).early_superseded, [])

    def test_an_empty_scan_still_returns_an_empty_fridge(self):
        self.assertEqual(run([[], []], on_pass1=lambda *args: None).ingredients, [])


# ---- the /api/scan stream -------------------------------------------------------------------------------------------------

client = TestClient(a.app)
PHOTO = {"fridge_photo_0": ("fridge.jpg", b"not-really-a-jpeg", "image/jpeg")}


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def finish_planning(_fridge, _dish, _servings, q):
    q.put(("done", None))


EARLY = [{"name": "tomato", "quantity": "", "confidence": 90}]


class ScanStreamTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(a, "generate_top_up_suggestions", MagicMock(return_value=[]))  # the top-up step calls Gemini for real
        patcher.start()
        self.addCleanup(patcher.stop)

    def scan(self, vision_fn, timeout=None):
        planner = MagicMock(side_effect=finish_planning)
        with patch.object(a, "identify_ingredients", vision_fn), patch.object(a, "_run_plan_meals_stream", planner), \
             patch.object(a, "STEP1_TIMEOUT_SECONDS", timeout if timeout is not None else a.STEP1_TIMEOUT_SECONDS):
            return events(client.post("/api/scan", files=PHOTO, data={"servings": "2"}))

    def test_first_look_events_come_before_step1_and_the_final_step1_is_unchanged(self):
        def vision_fn(_paths, _dish="", on_pass1=None):
            on_pass1(EARLY, 1, 1)
            time.sleep(0.05)
            return FridgeContents(
                ingredients=[Ingredient(name="tomato", confidence=0.9), Ingredient(name="lemon", confidence=0.75)],
                raw_description="2 ingredient(s) detected in your fridge.",
            )

        sent = self.scan(vision_fn)
        types = [e["type"] for e in sent]
        self.assertEqual(types[:3], ["progress", "step1_partial", "step1"])
        partial = sent[1]
        self.assertEqual((partial["ingredients"], partial["photo_index"], partial["photo_count"]), (EARLY, 1, 1))
        step1 = sent[2]
        self.assertEqual([i["name"] for i in step1["ingredients"]], ["tomato", "lemon"])
        self.assertNotIn("early_superseded", step1)  # nothing was replaced: the field is absent, exactly as before
        self.assertIn("step2", types)

    def test_superseded_pairs_ride_on_the_final_step1(self):
        def vision_fn(_paths, _dish="", on_pass1=None):
            on_pass1(EARLY, 1, 1)
            return FridgeContents(ingredients=[Ingredient(name="cherry tomato", confidence=0.95)], early_superseded=[{"from": "tomato", "to": "cherry tomato"}])

        step1 = next(e for e in self.scan(vision_fn) if e["type"] == "step1")
        self.assertEqual(step1["early_superseded"], [{"from": "tomato", "to": "cherry tomato"}])

    def test_the_old_backend_behaviour_without_any_first_look_is_unchanged(self):
        def vision_fn(_paths, _dish="", on_pass1=None):
            return FridgeContents(ingredients=[Ingredient(name="tomato", confidence=0.9)], raw_description="1 ingredient(s) detected in your fridge.")

        sent = self.scan(vision_fn)
        self.assertNotIn("step1_partial", [e["type"] for e in sent])
        step1 = next(e for e in sent if e["type"] == "step1")
        self.assertEqual(set(step1), {"type", "raw_description", "ingredients"})
        self.assertEqual(step1["ingredients"], [{"name": "tomato", "quantity": "", "confidence": 90}])

    def test_a_first_look_does_not_extend_the_vision_ceiling(self):
        def hung(_paths, _dish="", on_pass1=None):
            on_pass1(EARLY, 1, 1)
            time.sleep(0.5)  # outlives the patched ceiling
            return FridgeContents(ingredients=[Ingredient(name="late", confidence=0.9)])

        sent = self.scan(hung, timeout=0.1)  # (wall time is not asserted: the test client waits for the worker thread to exit)
        self.assertEqual([e["type"] for e in sent], ["progress", "step1_partial", "step1"])
        self.assertTrue(sent[-1]["timed_out"])
        self.assertEqual(sent[-1]["ingredients"], [])

    def test_a_vision_error_ends_the_scan_with_the_same_error_event_as_before(self):
        def broken(_paths, _dish="", on_pass1=None):
            raise RuntimeError("vision exploded")

        sent = self.scan(broken)
        self.assertEqual([e["type"] for e in sent], ["progress", "error"])
        self.assertEqual(sent[-1]["message"], "Unable to complete analysis.")


if __name__ == "__main__":
    unittest.main()
