"""
How the Gemini fallback loops (vision and planner) react to each kind of failure, and the multi-project key list.
2026-10-03 incident: gemini-2.5-flash timed out on keys of two different projects (25s each; the planner retried each
timeout 3 times, 250s for one plan) so the scan budget was gone before a working model was tried, and the two newest
projects get a permanent 404 for gemini-2.5-flash. Pure unit tests: Gemini is mocked, zero network/quota cost.
"""

import itertools
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from fridge_to_fork import gemini_keys
from fridge_to_fork import gemini_resilience as res
from fridge_to_fork import step1_fridge_vision as vision
from fridge_to_fork import step2_meal_planner as planner
from fridge_to_fork.models import FridgeContents, Ingredient

M1, M2, M3 = vision.VISION_MODEL_FALLBACK_CHAIN[:3]
OK = [{"name": "tomato", "confidence": 90}]
TIMEOUT_ERR = RuntimeError("504 DEADLINE_EXCEEDED. The request timed out")
NOT_AVAILABLE = RuntimeError("404 NOT_FOUND. This model models/gemini-2.5-flash is no longer available to new users.")
OVERLOADED_ERR = RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand")
CLIENTS = [("key1", "A"), ("key2", "B"), ("key3", "C")]


@pytest.fixture(autouse=True)
def clean_state():
    res.reset_for_tests()
    vision._scan_counter = itertools.count()
    yield
    res.reset_for_tests()


def scripted(outcomes):
    """A fake _call_gemini_vision: outcomes maps (model, client) -> result or an exception; unlisted -> 429."""
    calls = []

    def fake(image_bytes, prompt, client, model):
        calls.append((model, client))
        out = outcomes.get((model, client), RuntimeError("429 RESOURCE_EXHAUSTED quota"))
        if isinstance(out, Exception):
            raise out
        return out

    return calls, fake


def run_vision(outcomes, clients=CLIENTS):
    calls, fake = scripted(outcomes)
    with patch.object(vision, "_call_gemini_vision", side_effect=fake):
        result = vision._call_gemini_vision_with_fallback(clients, b"i", "p")
    return result, calls


# ---- classifying a failure ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("exc,kind", [
    (httpx.ReadTimeout("The read operation timed out"), res.TIMEOUT),
    (RuntimeError("504 DEADLINE_EXCEEDED. {'error': {'code': 504}}"), res.TIMEOUT),
    (RuntimeError("429 RESOURCE_EXHAUSTED. You exceeded your current quota"), res.QUOTA),
    (OVERLOADED_ERR, res.OVERLOADED),
    (NOT_AVAILABLE, res.UNAVAILABLE),
    (ValueError("Unterminated string starting at: line 1 column 80"), res.OTHER),
])
def test_failure_kinds(exc, kind):
    assert res.failure_kind(exc) == kind


# ---- vision: timeouts go to the next MODEL and are remembered ----------------------------------------------------------

def test_a_timeout_goes_to_the_next_model_without_trying_the_other_keys():
    result, calls = run_vision({(M1, "A"): TIMEOUT_ERR, (M2, "A"): OK})
    assert result == OK
    assert calls == [(M1, "A"), (M2, "A")]  # the old behaviour was (M1,A) (M1,B) (M1,C) (M2,A): 3 x 25s wasted


def test_the_incident_sequence_needs_three_calls_not_five():
    result, calls = run_vision({(M1, "A"): TIMEOUT_ERR, (M2, "A"): OVERLOADED_ERR, (M2, "B"): OK})
    assert result == OK
    assert calls == [(M1, "A"), (M2, "A"), (M2, "B")]


def test_a_timed_out_model_is_skipped_by_the_next_pass_of_the_same_scan():
    calls, fake = scripted({(M1, "A"): TIMEOUT_ERR, (M2, "A"): OK})
    with patch.object(vision, "_call_gemini_vision", side_effect=fake):
        vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "pass1")
        calls.clear()
        vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "pass2")
    assert calls == [(M2, "A")]  # pass 2 goes straight to the model that worked


def test_the_cooldown_expires():
    now = [1000.0]
    calls, fake = scripted({(M1, "A"): TIMEOUT_ERR, (M2, "A"): OK})
    with patch.object(vision, "_call_gemini_vision", side_effect=fake), patch.object(res, "_now", lambda: now[0]):
        vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p")
        now[0] += res.MODEL_COOLDOWN_SECONDS - 1
        calls.clear()
        vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p")
        assert calls[0][0] == M2  # still cold
        now[0] += 2
        calls.clear()
        vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p")
        assert calls[0] == (M1, "A")  # tried again


def test_when_every_model_is_cold_they_are_all_still_tried():
    for m in vision.VISION_MODEL_FALLBACK_CHAIN:
        res._cold_until[m] = res._now() + 1000
    result, calls = run_vision({(M2, "A"): OK})
    assert result == OK  # not a silent []
    assert calls[0][0] == M1


def test_success_on_a_model_clears_its_cold_mark():
    for m in vision.VISION_MODEL_FALLBACK_CHAIN:
        res._cold_until[m] = res._now() + 1000
    run_vision({(M1, "A"): OK})
    assert not res.is_cold(M1)


# ---- quota, overload and "not available to this key" -------------------------------------------------------------------

def test_quota_errors_rotate_through_every_key_of_the_same_model():
    result, calls = run_vision({(M1, "C"): OK})
    assert result == OK
    assert calls == [(M1, "A"), (M1, "B"), (M1, "C")]
    assert not res.is_cold(M1)  # a quota error says nothing about the model's speed


def test_overload_gets_a_second_key_then_moves_on_to_the_next_model():
    result, calls = run_vision({(M1, "A"): OVERLOADED_ERR, (M1, "B"): OVERLOADED_ERR, (M1, "C"): OK, (M2, "A"): OK})
    assert result == OK
    assert calls == [(M1, "A"), (M1, "B"), (M2, "A")]  # key C of M1 never tried


def test_a_model_that_404s_for_a_key_is_never_tried_on_that_key_again():
    result, calls = run_vision({(M1, "A"): NOT_AVAILABLE, (M1, "B"): NOT_AVAILABLE, (M1, "C"): OK})
    assert result == OK
    assert calls == [(M1, "A"), (M1, "B"), (M1, "C")]  # a 404 is not retried in place and does not end the model
    # a second pass: keys A and B are skipped for M1, so the very first call is already key C
    result2, calls2 = run_vision({(M1, "C"): OK})
    assert calls2 == [(M1, "C")]
    assert res.is_unavailable(M1, "key1") and res.is_unavailable(M1, "key2") and not res.is_unavailable(M1, "key3")


def test_everything_failing_returns_empty_rather_than_raising():
    result, _ = run_vision({}, CLIENTS[:2])
    assert result == []


# ---- thinking is turned down only where it is known to be accepted ----------------------------------------------------

def test_thinking_config_per_model():
    assert res.thinking_config_for("gemini-2.5-flash").thinking_budget == 0
    assert res.thinking_config_for("gemini-2.5-flash-lite").thinking_budget == 0
    assert str(res.thinking_config_for("gemini-3.8-flash").thinking_level).endswith("LOW")
    assert res.thinking_config_for("gemini-3.1-pro-preview") is None   # pro models can't switch thinking off
    assert res.thinking_config_for("gemini-flash-latest") is None      # aliases move; an unsupported config would be rejected


def test_the_vision_call_sends_the_thinking_config():
    seen = {}
    client = MagicMock()

    def generate_content(model, contents, config):
        seen["config"] = config
        return SimpleNamespace(text=json.dumps(OK))

    client.models.generate_content.side_effect = generate_content
    vision._call_gemini_vision(b"img", "prompt", client, "gemini-2.5-flash")
    assert seen["config"].thinking_config.thinking_budget == 0


# ---- the planner follows the same rules --------------------------------------------------------------------------------

PLAN = json.dumps({
    "decision": "cook", "recommended_meal": "Omelette", "reasoning": "r",
    "suggestions": [{"name": "Omelette", "recipe_ingredients": [{"name": "egg", "quantity": "2", "estimated_price_inr": 10, "category": "produce"}], "cooking_steps": ["beat", "cook"]}],
})


def text_client(outcomes, log):
    """A fake client whose generate_content_stream follows `outcomes` (model -> text or exception) and logs every call."""
    client = MagicMock()

    def stream(model, contents, config):
        log.append(model)
        out = outcomes.get(model, RuntimeError("429 RESOURCE_EXHAUSTED"))
        if isinstance(out, Exception):
            raise out
        yield SimpleNamespace(text=out)

    client.models.generate_content_stream.side_effect = stream
    return client


FRIDGE = FridgeContents(ingredients=[Ingredient(name="egg", confidence=0.9)])
TEXT_CHAIN = planner.TEXT_MODEL_FALLBACK_CHAIN


def run_plan(outcomes, n_keys=3):
    log = []
    with patch.object(planner, "_build_text_clients", return_value=[(f"key{i + 1}", text_client(outcomes, log)) for i in range(n_keys)]):
        results = [p for k, p in planner.plan_meals_stream(FRIDGE) if k == "result"]
    return results, log


def test_a_planner_timeout_is_not_retried_in_place_and_moves_to_the_next_model():
    results, log = run_plan({TEXT_CHAIN[0]: TIMEOUT_ERR, TEXT_CHAIN[1]: PLAN})
    assert results and results[0].recommended_meal.name == "Omelette"
    assert log == [TEXT_CHAIN[0], TEXT_CHAIN[1]]  # was 3 attempts x 3 keys of the slow model first (225s)
    assert res.is_cold(TEXT_CHAIN[0])


def test_the_planner_skips_a_model_the_vision_step_just_found_slow():
    res._cold_until[TEXT_CHAIN[0]] = res._now() + 1000
    _, log = run_plan({TEXT_CHAIN[1]: PLAN})
    assert log == [TEXT_CHAIN[1]]


def test_a_planner_404_for_a_key_is_not_retried_and_is_remembered():
    results, log = run_plan({TEXT_CHAIN[0]: NOT_AVAILABLE, TEXT_CHAIN[1]: PLAN})
    assert results
    # all three keys 404 on the first model once each (no 3x in-place retry), then the next model answers
    assert log == [TEXT_CHAIN[0]] * 3 + [TEXT_CHAIN[1]]
    assert all(res.is_unavailable(TEXT_CHAIN[0], f"key{i}") for i in (1, 2, 3))


def test_a_planner_parse_failure_is_still_retried_once_in_place():
    results, log = run_plan({TEXT_CHAIN[0]: "not json at all", TEXT_CHAIN[1]: PLAN}, n_keys=1)
    assert results
    assert log[:2] == [TEXT_CHAIN[0]] * 2  # one in-place retry for a transient oddity, then on


def test_the_planner_stream_call_sends_the_thinking_config():
    seen = {}
    client = MagicMock()

    def stream(model, contents, config):
        seen["config"] = config
        yield SimpleNamespace(text=PLAN)

    client.models.generate_content_stream.side_effect = stream
    with patch.object(planner, "_build_text_clients", return_value=[("key1", client)]):
        list(planner.plan_meals_stream(FRIDGE))
    assert seen["config"].thinking_config.thinking_budget == 0


# ---- starting each scan on a different key ----------------------------------------------------------------------------

def test_each_scan_starts_on_the_next_key_and_labels_keep_their_identity():
    firsts = [vision._rotate_for_scan(list(CLIENTS))[0][0] for _ in range(4)]
    assert firsts == ["key1", "key2", "key3", "key1"]
    assert sorted(label for label, _ in vision._rotate_for_scan(list(CLIENTS))) == ["key1", "key2", "key3"]


def test_a_single_client_is_left_alone():
    assert vision._rotate_for_scan([("key1", "A")]) == [("key1", "A")]


# ---- the key list -----------------------------------------------------------------------------------------------------

def test_keys_load_in_order_across_numbered_variables_with_gaps_blanks_and_duplicates_handled():
    env = {"GOOGLE_API_KEY": "k1", "GOOGLE_API_KEY_2": "  ", "GOOGLE_API_KEY_4": "k4", "GOOGLE_API_KEY_5": "k1", "GOOGLE_API_KEY_9": "k9", "GOOGLE_API_KEY_10": "ignored"}
    assert gemini_keys.load_api_keys(env) == ["k1", "k4", "k9"]


def test_no_keys_configured_is_an_empty_list():
    assert gemini_keys.load_api_keys({}) == []
