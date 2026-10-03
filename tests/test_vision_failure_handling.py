"""
How the vision fallback reacts to each kind of Gemini failure, and the multi-project key list (2026-10-03 incident:
gemini-2.5-flash timed out on keys of two different projects, 25s each, so the 60s scan budget was gone before the
working gemini-flash-latest was ever tried). Pure unit tests: the Gemini call is mocked, zero network/quota cost.
"""

import itertools
from unittest.mock import patch

import httpx
import pytest

from fridge_to_fork import gemini_keys
from fridge_to_fork import step1_fridge_vision as vision

M1, M2, M3 = vision.VISION_MODEL_FALLBACK_CHAIN[:3]
OK = [{"name": "tomato", "confidence": 90}]


@pytest.fixture(autouse=True)
def clean_state():
    vision._cold_until.clear()
    vision._scan_counter = itertools.count()
    yield
    vision._cold_until.clear()


def scripted(outcomes):
    """A fake _call_gemini_vision: outcomes maps (model, client) -> result or an exception; anything unlisted raises 429."""
    calls = []

    def fake(image_bytes, prompt, client, model):
        calls.append((model, client))
        out = outcomes.get((model, client), RuntimeError("429 RESOURCE_EXHAUSTED quota"))
        if isinstance(out, Exception):
            raise out
        return out

    return calls, fake


TIMEOUT_ERR = RuntimeError("504 DEADLINE_EXCEEDED. The request timed out")
CLIENTS = [("key1", "A"), ("key2", "B"), ("key3", "C")]


# ---- classifying a failure ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("exc,kind", [
    (httpx.ReadTimeout("The read operation timed out"), vision.TIMEOUT),
    (RuntimeError("504 DEADLINE_EXCEEDED. {'error': {'code': 504}}"), vision.TIMEOUT),
    (RuntimeError("429 RESOURCE_EXHAUSTED. You exceeded your current quota"), vision.QUOTA),
    (RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand"), vision.OVERLOADED),
    (ValueError("Unterminated string starting at: line 1 column 80"), vision.OTHER),
    (RuntimeError("404 NOT_FOUND. no longer available to new users"), vision.OTHER),
])
def test_failure_kinds(exc, kind):
    assert vision._failure_kind(exc) == kind


# ---- timeouts: next MODEL, not next key; and remembered ---------------------------------------------------------------

def test_a_timeout_goes_to_the_next_model_without_trying_the_other_keys():
    calls, fake = scripted({(M1, "A"): TIMEOUT_ERR, (M2, "A"): OK})
    with patch.object(vision, "_call_gemini_vision", side_effect=fake):
        assert vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p") == OK
    assert calls == [(M1, "A"), (M2, "A")]  # the old behaviour was (M1,A) (M1,B) (M1,C) (M2,A): 3 x 25s wasted


def test_the_incident_sequence_needs_three_calls_not_five():
    # 2.5-flash times out; flash-latest is overloaded on key 1 and fine on key 2.
    calls, fake = scripted({(M1, "A"): TIMEOUT_ERR, (M2, "A"): RuntimeError("503 UNAVAILABLE high demand"), (M2, "B"): OK})
    with patch.object(vision, "_call_gemini_vision", side_effect=fake):
        assert vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p") == OK
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
    with patch.object(vision, "_call_gemini_vision", side_effect=fake), patch.object(vision, "_now", lambda: now[0]):
        vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p")
        now[0] += vision.MODEL_COOLDOWN_SECONDS - 1
        calls.clear()
        vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p")
        assert calls[0][0] == M2  # still cold
        now[0] += 2
        calls.clear()
        vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p")
        assert calls[0] == (M1, "A")  # tried again


def test_when_every_model_is_cold_they_are_all_still_tried():
    for m in vision.VISION_MODEL_FALLBACK_CHAIN:
        vision._mark_cold(m)
    calls, fake = scripted({(M2, "A"): OK})
    with patch.object(vision, "_call_gemini_vision", side_effect=fake):
        assert vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p") == OK  # not a silent []
    assert calls[0][0] == M1


def test_success_on_a_model_clears_its_cold_mark():
    vision._mark_cold(M1)
    for m in vision.VISION_MODEL_FALLBACK_CHAIN[1:]:
        vision._mark_cold(m)
    calls, fake = scripted({(M1, "A"): OK})
    with patch.object(vision, "_call_gemini_vision", side_effect=fake):
        vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p")
    assert not vision._is_cold(M1)


# ---- quota and overload ---------------------------------------------------------------------------------------------

def test_quota_errors_rotate_through_every_key_of_the_same_model():
    calls, fake = scripted({(M1, "C"): OK})
    with patch.object(vision, "_call_gemini_vision", side_effect=fake):
        assert vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p") == OK
    assert calls == [(M1, "A"), (M1, "B"), (M1, "C")]
    assert not vision._is_cold(M1)  # a quota error says nothing about the model's speed


def test_overload_gets_a_second_key_then_moves_on_to_the_next_model():
    overloaded = RuntimeError("503 UNAVAILABLE high demand")
    calls, fake = scripted({(M1, "A"): overloaded, (M1, "B"): overloaded, (M1, "C"): OK, (M2, "A"): OK})
    with patch.object(vision, "_call_gemini_vision", side_effect=fake):
        assert vision._call_gemini_vision_with_fallback(CLIENTS, b"i", "p") == OK
    assert calls == [(M1, "A"), (M1, "B"), (M2, "A")]  # key C of M1 never tried


def test_everything_failing_returns_empty_rather_than_raising():
    calls, fake = scripted({})
    with patch.object(vision, "_call_gemini_vision", side_effect=fake):
        assert vision._call_gemini_vision_with_fallback(CLIENTS[:2], b"i", "p") == []


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
