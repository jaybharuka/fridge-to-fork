"""
Idle timeout on the streamed meal plan: a stream that starts and then goes quiet fails over to the next model after
PLAN_STREAM_IDLE_SECONDS instead of waiting out the whole plan cutoff (2026-10-06 12:39: gemini-2.5-flash gave a first chunk at
1.8s and then nothing until the 18s cutoff). Gemini is scripted: zero network or quota cost. Run: pytest tests/test_plan_stream_idle.py
"""

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from fridge_to_fork import gemini_resilience as res
from fridge_to_fork import step2_meal_planner as planner
from fridge_to_fork.models import FridgeContents, Ingredient

PLAN = json.dumps({
    "decision": "cook", "recommended_meal": "Omelette", "reasoning": "r",
    "suggestions": [{"name": "Omelette", "recipe_ingredients": [{"name": "egg", "quantity": "2", "estimated_price_inr": 10, "category": "produce"}], "cooking_steps": ["beat", "cook"]}],
})
FRIDGE = FridgeContents(ingredients=[Ingredient(name="egg", confidence=0.9)])
FIRST, SECOND = planner.TEXT_MODEL_FALLBACK_CHAIN[:2]
IDLE = 0.3


@pytest.fixture(autouse=True)
def clean_state():
    res.reset_for_tests()
    with patch.object(res, "PLAN_STREAM_IDLE_SECONDS", IDLE):
        yield
    res.reset_for_tests()


def split(text, n):
    size = -(-len(text) // n)
    return [text[i:i + size] for i in range(0, len(text), size)]


def client_for(streams, log):
    """A fake client whose generate_content_stream follows `streams` (model -> callable returning a chunk generator)."""
    client = MagicMock()

    def stream(model, contents, config):
        log.append(model)
        return streams[model]()

    client.models.generate_content_stream.side_effect = stream
    return client


def run(streams, n_keys=3):
    log = []
    clients = [(f"key{i + 1}", client_for(streams, log)) for i in range(n_keys)]
    with patch.object(planner, "_build_text_clients", return_value=clients):
        results = [p for k, p in planner.plan_meals_stream(FRIDGE) if k == "result"]
    return results, log


def healthy():
    for part in split(PLAN, 4):
        yield SimpleNamespace(text=part)


def test_default_and_env_override(monkeypatch):
    import importlib
    assert res.PLAN_STREAM_IDLE_SECONDS == IDLE  # patched by the fixture; the real default is checked below
    with patch.dict("os.environ", {}, clear=False):
        monkeypatch.delenv("GEMINI_PLAN_STREAM_IDLE_SECONDS", raising=False)
        monkeypatch.setenv("GEMINI_PLAN_STREAM_IDLE_SECONDS", "banana")
        try:
            importlib.reload(res)
            assert res.PLAN_STREAM_IDLE_SECONDS == 8.0
            monkeypatch.setenv("GEMINI_PLAN_STREAM_IDLE_SECONDS", "5")
            importlib.reload(res)
            assert res.PLAN_STREAM_IDLE_SECONDS == 5.0
        finally:
            monkeypatch.undo()
            importlib.reload(res)
    assert res.PLAN_STREAM_IDLE_SECONDS == 8.0
    assert res.PLAN_TIMEOUT_SECONDS == 18.0  # the total cutoff stays the ceiling


def test_a_stream_that_stalls_after_one_chunk_fails_over_without_waiting_for_the_cutoff(capsys):
    release = threading.Event()

    def stalls():
        yield SimpleNamespace(text=PLAN[:20])
        release.wait(10)  # then silence, like gemini-2.5-flash on 2026-10-06

    started = time.monotonic()
    try:
        results, log = run({FIRST: stalls, SECOND: healthy})
    finally:
        release.set()
    elapsed = time.monotonic() - started
    assert results and results[0].recommended_meal.name == "Omelette"
    assert elapsed < 3, f"took {elapsed:.1f}s: it waited for something longer than the idle limit"
    assert log == [FIRST, SECOND]  # one attempt on the stalled model (no retry in place, no other key), then the next model
    assert res.is_cold(FIRST)       # same cooldown as a timeout
    assert not res.is_cold(SECOND)
    out = capsys.readouterr().out
    assert "StreamStalledTimeout" in out and "no chunk for" in out
    assert f"{FIRST} is slow: trying the next model" in out


def test_a_slow_but_steady_stream_is_not_cut_off(capsys):
    def steady():
        for part in split(PLAN, 8):
            time.sleep(0.1)  # eight gaps of 0.1s: 0.8s in all, far over the 0.3s idle limit, but never silent for that long
            yield SimpleNamespace(text=part)

    results, log = run({FIRST: steady, SECOND: healthy})
    assert results and log == [FIRST]
    assert not res.is_cold(FIRST)
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("[TIMING] plan_stream"))
    assert f"plan_stream {FIRST}: chunks=8" in line
    gap = float(line.split("max_gap=")[1].rstrip("s"))
    assert 0.05 < gap < IDLE


def test_waiting_for_the_first_chunk_is_not_a_stall():
    def slow_start():
        time.sleep(0.6)  # longer than the idle limit, but nothing has started yet
        yield from healthy()

    results, log = run({FIRST: slow_start, SECOND: healthy})
    assert results and log == [FIRST]
    assert not res.is_cold(FIRST)


def test_a_stall_is_classified_as_a_timeout_and_not_retried_in_place():
    exc = res.StreamStalledTimeout("no chunk for 8s after 3 chunk(s)")
    assert res.failure_kind(exc) == res.TIMEOUT
    assert not res.is_retryable_in_place(exc)
    assert res.note_failure(FIRST, "key1", exc, res.ModelAttempt()) == res.NEXT_MODEL


def test_errors_from_the_stream_reach_the_caller_unchanged():
    boom = RuntimeError("429 RESOURCE_EXHAUSTED quota")

    def failing():
        yield SimpleNamespace(text="x")
        raise boom

    with pytest.raises(RuntimeError) as caught:
        list(res.iter_with_idle_timeout(failing, IDLE, 5))
    assert caught.value is boom
    assert res.failure_kind(caught.value) == res.QUOTA


def test_an_abandoned_stream_does_not_leave_its_thread_behind():
    release = threading.Event()

    def stalls():
        yield "a"
        release.wait(10)
        yield "b"

    with pytest.raises(res.StreamStalledTimeout):
        list(res.iter_with_idle_timeout(stalls, IDLE, 5))
    release.set()  # the SDK's own deadline would do this in real life
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and any(t.name == "gemini-stream-pump" and t.is_alive() for t in threading.enumerate()):
        time.sleep(0.02)
    assert not any(t.name == "gemini-stream-pump" and t.is_alive() for t in threading.enumerate())


def test_closing_the_consumer_early_stops_the_reader():
    produced = []

    def endless():
        for i in range(10_000):
            produced.append(i)
            yield i
            time.sleep(0.01)

    gen = res.iter_with_idle_timeout(endless, 5, 5)
    assert next(gen) == 0
    gen.close()
    time.sleep(0.2)
    count = len(produced)
    time.sleep(0.2)
    assert len(produced) == count  # nothing more is read after the consumer is gone
