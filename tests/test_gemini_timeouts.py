"""
Per-attempt Gemini timeouts (vision 15s, plan 18s, top-up 15s) and the one-line duration log per successful call.
Pure unit tests: Gemini is mocked, zero network/quota cost.
"""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from google.genai import _api_client

from fridge_to_fork import gemini_resilience as res
from fridge_to_fork import step1_fridge_vision as vision
from fridge_to_fork import step2_meal_planner as planner
from fridge_to_fork.models import Decision, FridgeContents, Ingredient, MealSuggestion

OK = [{"name": "tomato", "confidence": 90}]
PLAN = json.dumps({
    "decision": "cook", "recommended_meal": "Omelette", "reasoning": "r",
    "suggestions": [{"name": "Omelette", "recipe_ingredients": [{"name": "egg", "quantity": "2", "estimated_price_inr": 10, "category": "produce"}], "cooking_steps": ["beat"]}],
})
TOP_UP = json.dumps([{"name": "mint chutney", "reason": "fresh", "estimated_price_inr": 40, "source": "instamart"}])
FRIDGE = FridgeContents(ingredients=[Ingredient(name="egg", confidence=0.9)])


@pytest.fixture(autouse=True)
def clean_state():
    res.reset_for_tests()
    yield
    res.reset_for_tests()


def test_defaults():
    assert (res.VISION_TIMEOUT_SECONDS, res.PLAN_TIMEOUT_SECONDS, res.TOP_UP_TIMEOUT_SECONDS) == (15.0, 18.0, 15.0)


def test_env_override_and_bad_values_fall_back(monkeypatch):
    monkeypatch.setenv("GEMINI_PLAN_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("GEMINI_VISION_TIMEOUT_SECONDS", "banana")
    monkeypatch.setenv("GEMINI_TOP_UP_TIMEOUT_SECONDS", "-3")
    try:
        importlib.reload(res)
        assert (res.PLAN_TIMEOUT_SECONDS, res.VISION_TIMEOUT_SECONDS, res.TOP_UP_TIMEOUT_SECONDS) == (9.0, 15.0, 15.0)
    finally:
        monkeypatch.undo()
        importlib.reload(res)


def test_the_server_deadline_header_follows_the_option():
    for seconds in (15, 18):
        opts = res.http_options(seconds)
        assert opts.timeout == seconds * 1000
        assert opts.retry_options.attempts == 1
        headers = {}
        _api_client.populate_server_timeout_header(headers, _api_client.get_timeout_in_seconds(opts.timeout))
        assert headers["X-Server-Timeout"] == str(seconds)


def test_vision_call_uses_the_vision_timeout():
    seen = {}
    client = MagicMock()
    client.models.generate_content.side_effect = lambda model, contents, config: seen.update(c=config) or SimpleNamespace(text=json.dumps(OK))
    vision._call_gemini_vision(b"img", "p", client, "gemini-2.5-flash")
    assert seen["c"].http_options.timeout == 15_000


def test_plan_stream_uses_the_plan_timeout():
    seen = {}
    client = MagicMock()

    def stream(model, contents, config):
        seen["c"] = config
        yield SimpleNamespace(text=PLAN)

    client.models.generate_content_stream.side_effect = stream
    with patch.object(planner, "_build_text_clients", return_value=[("key1", client)]):
        list(planner.plan_meals_stream(FRIDGE))
    assert seen["c"].http_options.timeout == 18_000


def test_top_up_uses_the_top_up_timeout_and_logs_its_duration(capsys):
    seen = {}
    client = MagicMock()
    client.models.generate_content.side_effect = lambda model, contents, config: seen.update(c=config) or SimpleNamespace(text=TOP_UP)
    meal = MealSuggestion(name="Omelette", description="d", can_cook_now=True, missing_ingredients=["egg"])
    with patch.object(planner, "_build_text_clients", return_value=[("key2", client)]):
        assert planner.generate_top_up_suggestions(FRIDGE, meal, Decision.COOK)
    assert seen["c"].http_options.timeout == 15_000
    assert f"[TIMING] gemini_call top_up {planner.TEXT_MODEL_FALLBACK_CHAIN[0]} on key2: " in capsys.readouterr().out


def test_a_vision_timeout_still_moves_to_the_next_model_and_starts_the_cooldown():
    first, second = vision.VISION_MODEL_FALLBACK_CHAIN[:2]
    calls = []

    def fake(image_bytes, prompt, client, model):
        calls.append(model)
        if model == first:
            raise RuntimeError("504 DEADLINE_EXCEEDED. Deadline expired before operation could complete")
        return OK

    with patch.object(vision, "_call_gemini_vision", side_effect=fake):
        assert vision._call_gemini_vision_with_fallback([("key1", "A"), ("key2", "B")], b"i", "p") == OK
    assert calls == [first, second]          # one attempt on the slow model, not one per key
    assert res.is_cold(first)


def test_the_overall_vision_ceiling_is_unchanged():
    import app
    assert app.STEP1_TIMEOUT_SECONDS == 60.0


def test_vision_and_plan_success_lines(capsys):
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(OK))
    vision._call_gemini_vision_with_fallback([("key3", client)], b"i", "p")
    pclient = MagicMock()
    pclient.models.generate_content_stream.side_effect = lambda model, contents, config: iter([SimpleNamespace(text=PLAN)])
    with patch.object(planner, "_build_text_clients", return_value=[("key1", pclient)]):
        list(planner.plan_meals_stream(FRIDGE))
    out = capsys.readouterr().out
    assert f"[TIMING] gemini_call vision {vision.VISION_MODEL_FALLBACK_CHAIN[0]} on key3: " in out
    assert f"[TIMING] gemini_call plan {planner.TEXT_MODEL_FALLBACK_CHAIN[0]} on key1: " in out
    assert "AIza" not in out
