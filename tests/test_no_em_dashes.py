"""
No em dashes in the app's voice: not in the text the UI shows, and not coming back from Gemini.

Two halves: the prompts sent to Gemini must end with an explicit "no em dashes" rule and contain no other em dash
(the model imitates what it is shown), and no runtime string in the backend may contain one. Pure unit tests: the Gemini
call is mocked, zero network/quota cost. The frontend has the same guard in frontend/lib/noEmDash.test.ts.
"""

import ast
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from fridge_to_fork import prompt_rules
from fridge_to_fork import step1_fridge_vision as vision
from fridge_to_fork import step2_meal_planner as planner
from fridge_to_fork.models import Decision, FridgeContents, Ingredient, MealSuggestion

EM = chr(0x2014)
FRIDGE = FridgeContents(ingredients=[Ingredient(name="egg", confidence=0.9), Ingredient(name="tomato", confidence=0.8)])
MEAL = MealSuggestion(name="Omelette", description="d", can_cook_now=False, missing_ingredients=["salt"])


def assert_styled(prompt: str):
    assert prompt.rstrip().endswith(prompt_rules.NO_EM_DASH_RULE), "the rule must be the last paragraph"
    # the instruction itself shows the character once; every other part of the prompt must be free of it
    assert prompt.count(EM) == 1, f"{prompt.count(EM)} em dashes in the prompt (expected only the one inside the rule)"


# ---- the prompts, as actually constructed -------------------------------------------------------------------------

def test_wide_scan_prompt():
    assert_styled(vision._build_wide_scan_prompt(""))


def test_wide_scan_prompt_with_a_target_dish():
    assert_styled(vision._build_wide_scan_prompt("Paneer Tikka"))


def test_deep_scan_prompt():
    assert_styled(vision._build_deep_scan_prompt(["egg", "milk"]))
    assert_styled(vision._build_deep_scan_prompt([]))


def test_meal_planning_prompt_free_choice():
    assert_styled(planner._build_plan_prompt(FRIDGE, None, 2))


def test_meal_planning_prompt_for_a_target_dish():
    assert_styled(planner._build_plan_prompt(FRIDGE, "Poha", 4))


def test_top_up_prompt_as_sent_to_gemini():
    seen = {}
    client = MagicMock()

    def generate_content(model, contents, config):
        seen["prompt"] = contents
        return SimpleNamespace(text="[]")

    client.models.generate_content.side_effect = generate_content
    with patch.object(planner, "_build_text_clients", return_value=[("key1", client)]):
        planner.generate_top_up_suggestions(FRIDGE, MEAL, Decision.ORDER_GROCERIES)
    assert_styled(seen["prompt"])


def test_the_meal_plan_prompt_is_what_the_stream_call_actually_sends():
    seen = {}
    client = MagicMock()

    def stream(model, contents, config):
        seen["prompt"] = contents
        raise RuntimeError("stop here")  # the request payload is all this test needs

    client.models.generate_content_stream.side_effect = stream
    with patch.object(planner, "_build_text_clients", return_value=[("key1", client)]):
        list(planner.plan_meals_stream(FRIDGE, target_dish="Poha"))  # falls back locally after the failure
    assert_styled(seen["prompt"])


def test_the_vision_call_payload_carries_the_rule():
    seen = {}
    client = MagicMock()

    def generate_content(model, contents, config):
        seen["contents"] = contents
        return SimpleNamespace(text="[]")

    client.models.generate_content.side_effect = generate_content
    vision._call_gemini_vision(b"img", vision._build_wide_scan_prompt(""), client, "gemini-2.5-flash")
    prompt = [c for c in seen["contents"] if isinstance(c, str)][0]
    assert_styled(prompt)


def test_append_rule_is_idempotent():
    once = prompt_rules.append_rule("hello")
    assert prompt_rules.append_rule(once) == once


# ---- no runtime string in the backend contains an em dash ---------------------------------------------------------------

# Console-only messages of the legacy command-line tools, not shown in the app.
CLI_ONLY = {"agent.py", "step3_order_router.py"}


def _runtime_strings_with_em_dash():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = [os.path.join(root, "app.py")]
    pkg = os.path.join(root, "fridge_to_fork")
    files += [os.path.join(pkg, f) for f in sorted(os.listdir(pkg)) if f.endswith(".py") and f not in CLI_ONLY and f != "prompt_rules.py"]
    found = []
    for path in files:
        tree = ast.parse(open(path, encoding="utf-8").read())
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and EM in node.value and id(node) not in docstrings:
                found.append(f"{os.path.relpath(path, root)}:{node.lineno}: {node.value[:70]!r}")
    return found


def test_no_backend_runtime_string_contains_an_em_dash():
    assert _runtime_strings_with_em_dash() == []
