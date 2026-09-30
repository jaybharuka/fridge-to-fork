"""
Tests for POST /api/replan — switching the active dish on an already-scanned
fridge (Meal Suggestions picker + free-text custom dish). All Gemini calls
are mocked; TestClient pattern matches tests/test_root_redirect.py.

Run: python -m unittest tests.test_replan
"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork.models import Decision, MealPlan, MealSuggestion, RecipeIngredient

client = TestClient(a.app)


def _known_meal(name="Butter Chicken"):
    return MealSuggestion(
        name=name, description="", can_cook_now=True,
        cooking_steps=["Heat oil.", "Add chicken."],
        recipe_ingredients=[
            RecipeIngredient(name="chicken", quantity="500g", estimated_price_inr=200,
                              found_in_fridge=False, is_staple=False, category="perishable"),
        ],
        missing_ingredients=["chicken"],
        total_order_price_inr=200,
        matched_fridge_items=["butter"],
    )


class TestReplanKnownSuggestion(unittest.TestCase):
    """dish_name + recipe_ingredients already known (a Meal Suggestions card
    click) — must skip plan_meals() entirely (no new Gemini recipe-generation
    call) and only classify/enrich + fetch top-up."""

    def test_skips_plan_meals_and_returns_enriched_checklist(self):
        with patch.object(a, "plan_meals") as mock_plan_meals, \
             patch.object(a, "generate_top_up_suggestions", return_value=[{"name": "Naan"}]) as mock_top_up:
            res = client.post("/api/replan", json={
                "dish_name": "Butter Chicken",
                "fridge_ingredients": [{"name": "butter", "quantity": "1", "confidence": 0.9}],
                "servings": 2,
                "recipe_ingredients": [
                    {"name": "chicken", "quantity": "500g", "estimated_price_inr": 200, "category": "perishable"},
                    {"name": "butter", "quantity": "50g", "estimated_price_inr": 0, "category": "staple"},
                ],
                "cooking_steps": ["Heat oil.", "Add chicken."],
            })

        self.assertEqual(res.status_code, 200)
        mock_plan_meals.assert_not_called()
        mock_top_up.assert_called_once()

        body = res.json()
        self.assertEqual(body["recommended_meal"], "Butter Chicken")
        self.assertEqual(body["cooking_steps"], ["Heat oil.", "Add chicken."])
        self.assertEqual(body["top_up_suggestions"], [{"name": "Naan"}])
        # butter is a recipe ingredient AND a detected fridge item -> found_in_fridge.
        by_name = {ri["name"]: ri for ri in body["recipe_ingredients"]}
        self.assertTrue(by_name["butter"]["found_in_fridge"] or by_name["butter"]["is_staple"])
        # chicken was never in fridge_ingredients -> missing.
        self.assertIn("chicken", body["missing_ingredients"])


class TestReplanCustomDish(unittest.TestCase):
    """No recipe_ingredients in the request -> arbitrary free-text dish,
    must go through plan_meals() (the same function /api/scan's
    target_dish path already uses)."""

    def test_calls_plan_meals_with_target_dish(self):
        plan = MealPlan(
            suggestions=[_known_meal("Paneer Tikka")],
            decision=Decision.COOK,
            recommended_meal=_known_meal("Paneer Tikka"),
            reasoning="Sounds great.",
        )
        with patch.object(a, "plan_meals", return_value=plan) as mock_plan_meals, \
             patch.object(a, "generate_top_up_suggestions", return_value=[]):
            res = client.post("/api/replan", json={
                "dish_name": "Paneer Tikka",
                "fridge_ingredients": [],
                "servings": 3,
            })

        self.assertEqual(res.status_code, 200)
        mock_plan_meals.assert_called_once()
        _, kwargs = mock_plan_meals.call_args
        self.assertEqual(kwargs["target_dish"], "Paneer Tikka")
        self.assertEqual(kwargs["servings"], 3)
        self.assertEqual(res.json()["recommended_meal"], "Paneer Tikka")

    def test_plan_meals_returning_no_recommendation_is_a_502(self):
        empty_plan = MealPlan(suggestions=[], decision=Decision.COOK, recommended_meal=None)
        with patch.object(a, "plan_meals", return_value=empty_plan):
            res = client.post("/api/replan", json={"dish_name": "Nonexistent Dish"})
        self.assertEqual(res.status_code, 502)


class TestReplanValidation(unittest.TestCase):
    def test_blank_dish_name_is_a_400(self):
        res = client.post("/api/replan", json={"dish_name": "   "})
        self.assertEqual(res.status_code, 400)

    def test_missing_dish_name_is_a_422(self):
        res = client.post("/api/replan", json={})
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()
