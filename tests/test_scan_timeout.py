"""
/api/scan after a step1 (vision) timeout. 2026-10-02 live incident: the 60s vision ceiling tripped, and the backend went
on to plan meals on an EMPTY fridge ("9 of 17 ingredients" was just the staples), then ran top-up and Instamart work for a
plan nobody could trust, which the UI rendered behind its error card. A timed-out scan now stops right after the
timed_out step1 event. Run: python -m unittest tests.test_scan_timeout
"""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork.models import FridgeContents, Ingredient

client = TestClient(a.app)
PHOTO = {"fridge_photo_0": ("fridge.jpg", b"not-really-a-jpeg", "image/jpeg")}


def events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def slow_vision(_paths, _dish=""):
    time.sleep(0.4)  # outlives the patched timeout, like a hung Gemini call
    return FridgeContents(ingredients=[Ingredient(name="late tomato", confidence=0.9)])


def fast_vision(_paths, _dish=""):
    return FridgeContents(ingredients=[Ingredient(name="tomato", confidence=0.9)])


def finish_planning(_fridge, _dish, _servings, q):
    q.put(("done", None))  # no plan: the route falls back to its local plan, which is all this test needs


class VisionTimeoutTests(unittest.TestCase):
    def setUp(self):
        # The top-up step calls Gemini for real; nothing here may.
        self.top_up = MagicMock(return_value=[])
        patcher = patch.object(a, "generate_top_up_suggestions", self.top_up)
        patcher.start()
        self.addCleanup(patcher.stop)

    def scan(self, vision):
        planner = MagicMock(side_effect=finish_planning)
        with patch.object(a, "identify_ingredients", vision), patch.object(a, "STEP1_TIMEOUT_SECONDS", 0.05), patch.object(a, "_run_plan_meals_stream", planner):
            response = client.post("/api/scan", files=PHOTO, data={"servings": "2"})
        return response, planner

    def test_a_vision_timeout_sends_the_timed_out_step1_and_nothing_after_it(self):
        response, _ = self.scan(slow_vision)
        self.assertEqual(response.status_code, 200)
        sent = events(response)
        self.assertEqual([e["type"] for e in sent], ["progress", "step1"])
        self.assertTrue(sent[1]["timed_out"])
        self.assertEqual(sent[1]["ingredients"], [])

    def test_meal_planning_never_starts_on_an_empty_fridge(self):
        _, planner = self.scan(slow_vision)
        planner.assert_not_called()
        self.top_up.assert_not_called()  # and neither does the Gemini top-up call that used to follow it

    def test_the_stream_has_no_plan_or_complete_event_to_overwrite_the_error(self):
        types = {e["type"] for e in events(self.scan(slow_vision)[0])}
        self.assertFalse(types & {"step2", "step2_partial", "awaiting_user_choice", "top_up", "complete"})

    def test_a_scan_that_does_not_time_out_still_plans_and_completes(self):
        response, planner = self.scan(fast_vision)
        sent = events(response)
        planner.assert_called_once()
        self.assertFalse(any(e.get("timed_out") for e in sent))
        step1 = next(e for e in sent if e["type"] == "step1")
        self.assertEqual([i["name"] for i in step1["ingredients"]], ["tomato"])
        self.assertIn("step2", [e["type"] for e in sent])

    def test_recipe_only_mode_is_unaffected_because_it_has_no_vision_step(self):
        planner = MagicMock(side_effect=finish_planning)
        with patch.object(a, "STEP1_TIMEOUT_SECONDS", 0.05), patch.object(a, "_run_plan_meals_stream", planner):
            response = client.post("/api/scan", data={"mode": "recipe", "target_dish": "Poha", "servings": "2"})
        sent = events(response)
        planner.assert_called_once()
        self.assertEqual(next(e for e in sent if e["type"] == "step1").get("source"), "recipe")
        self.assertIn("step2", [e["type"] for e in sent])

    def test_temp_photo_files_are_cleaned_up_after_a_timeout(self):
        seen: list[list[str]] = []

        def spying_vision(paths, dish=""):
            seen.append(list(paths))
            return slow_vision(paths, dish)

        self.scan(spying_vision)
        import os
        self.assertTrue(seen and not any(os.path.exists(p) for p in seen[0]))


if __name__ == "__main__":
    unittest.main()
