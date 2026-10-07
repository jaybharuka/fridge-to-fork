"""
How the app reacts when a Gemini call fails, shared by the vision (step1) and planner (step2) fallback loops.

Why this exists (2026-10-03 incident): scans failed "try again" although quota had reset. gemini-2.5-flash was timing
out (504) on keys of two different projects, 25s each (and the planner retried each timeout 3 times: 250s for one plan),
so the budget was gone before a working model was tried; and the two newest projects get a permanent 404 for
gemini-2.5-flash ("no longer available to new users"), which was retried like a transient error. Thinking, on by
default for these models, was the main cause of the slow calls: with it off, the same vision call took ~9s instead of
timing out at 25s.

What each failure now means (see failure_kind):
- TIMEOUT      the model is slow on Google's side, not a key problem  -> next MODEL, and skip this model for a while
- QUOTA        this project's quota is spent                          -> next KEY (each project has its own quota)
- OVERLOADED   503 "high demand", transient                           -> next key, but only MAX_OVERLOADED_PER_MODEL times
- UNAVAILABLE  404 "no longer available to new users" (per key)       -> never retry that (model, key); skip it for hours
- OTHER        anything else (bad JSON, ...)                          -> next key
"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
from typing import Callable, Iterable, Iterator, Sequence

from google.genai import types

TIMEOUT, QUOTA, OVERLOADED, UNAVAILABLE, OTHER = "timeout", "quota", "overloaded", "unavailable", "other"

MODEL_COOLDOWN_SECONDS = 600.0          # a model that timed out is skipped this long
UNAVAILABLE_COOLDOWN_SECONDS = 6 * 3600.0  # a (model, key) that 404'd "no longer available" is skipped this long
MAX_OVERLOADED_PER_MODEL = 2

NEXT_KEY, NEXT_MODEL = "next_key", "next_model"


def _env_seconds(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


# Per-attempt timeouts (2026-10-06). Chosen from the successful-call durations in the Render logs of 2026-10-03
# (vision 2.8-17.1s, plan 1.7-13.0s, top-up 1.5-12.0s): 15s would have cut off ~5% of successes, 18s none, against 25s
# before, which made every timeout cost 25s. Google enforces the deadline itself (the SDK sends it as X-Server-Timeout),
# so a call cut off here is cancelled on their side too. Overridable per step to tune without a deploy of code.
VISION_TIMEOUT_SECONDS = _env_seconds("GEMINI_VISION_TIMEOUT_SECONDS", 15.0)
PLAN_TIMEOUT_SECONDS = _env_seconds("GEMINI_PLAN_TIMEOUT_SECONDS", 18.0)
TOP_UP_TIMEOUT_SECONDS = _env_seconds("GEMINI_TOP_UP_TIMEOUT_SECONDS", 15.0)
# Longest a plan stream may go quiet AFTER its first chunk before it counts as stalled (2026-10-06). gemini-2.5-flash has
# twice answered the first chunk in ~2-4s and then said nothing until the total cutoff (2026-10-03 10:41, 2026-10-06
# 12:39); waiting out the cutoff cost 18-25s. A healthy plan finishes 6-13s after its first chunk, so 8s of silence in the
# middle of a stream is a stall. The total PLAN_TIMEOUT_SECONDS stays the ceiling.
PLAN_STREAM_IDLE_SECONDS = _env_seconds("GEMINI_PLAN_STREAM_IDLE_SECONDS", 8.0)


def http_options(timeout_seconds: float) -> types.HttpOptions:
    """One attempt, no SDK-level retry (the fallback loops are the retry layer), capped at `timeout_seconds`."""
    return types.HttpOptions(
        timeout=int(timeout_seconds * 1000),
        retry_options=types.HttpRetryOptions(attempts=1, initial_delay=0.5, max_delay=3.0, exp_base=2.0),
    )


def log_success(step: str, model: str, key_label: str, started: float) -> None:
    """One greppable line per successful call: `[TIMING] gemini_call <step> <model> on <keyN>: 4.12s`. `started` is a
    time.monotonic() reading taken just before the call. Key label only, never the key."""
    print(f"[TIMING] gemini_call {step} {model} on {key_label}: {time.monotonic() - started:.2f}s")

_now = time.monotonic  # patchable in tests
_lock = threading.Lock()
_cold_until: dict[str, float] = {}
_unavailable_until: dict[tuple[str, str], float] = {}


class StreamStalledTimeout(TimeoutError):
    """A stream that had started went quiet for longer than the idle limit. Its name contains "timeout", so failure_kind() files
    it as a TIMEOUT: next model, and the slow model is skipped for MODEL_COOLDOWN_SECONDS, exactly like a total timeout."""


def iter_with_idle_timeout(
    open_stream: Callable[[], Iterable],
    idle_seconds: float,
    first_chunk_seconds: float,
    stats: dict | None = None,
) -> Iterator:
    """Yields what `open_stream()` yields, but raises StreamStalledTimeout if, once the first chunk has arrived, no further
    chunk comes within `idle_seconds`. (Before the first chunk only `first_chunk_seconds` applies, a safety net behind the SDK's
    own deadline: waiting for the first token is not a stall.)

    The blocking stream is read on a helper daemon thread that hands chunks over through a queue, because a blocked read cannot be
    interrupted from outside. After a stall the helper is abandoned: it ends by itself when the SDK's own request deadline (the
    http timeout set on the call, enforced server side) aborts the request, so it can outlive the call by at most that long and
    never accumulates. Errors raised by the stream are re-raised here unchanged. `stats`, if given, gets `chunks` and `max_gap`
    (the longest silence between consecutive chunks, in seconds) so healthy streams can be measured."""
    handoff: queue.Queue = queue.Queue()
    abandoned = threading.Event()

    def pump() -> None:
        try:
            for chunk in open_stream():
                if abandoned.is_set():
                    return
                handoff.put(("chunk", chunk))
            handoff.put(("end", None))
        except BaseException as exc:  # noqa: BLE001 - handed to the consumer, which re-raises it
            handoff.put(("error", exc))

    threading.Thread(target=pump, daemon=True, name="gemini-stream-pump").start()
    chunks, max_gap, last = 0, 0.0, None
    try:
        while True:
            wait = idle_seconds if chunks else first_chunk_seconds
            try:
                kind, payload = handoff.get(timeout=wait)
            except queue.Empty:
                what = f"no chunk for {idle_seconds:g}s after {chunks} chunk(s)" if chunks else f"no first chunk within {first_chunk_seconds:g}s"
                raise StreamStalledTimeout(what) from None
            if kind == "end":
                return
            if kind == "error":
                raise payload
            now = _now()
            if last is not None:
                max_gap = max(max_gap, now - last)
            last = now
            chunks += 1
            if stats is not None:
                stats.update(chunks=chunks, max_gap=max_gap)
            yield payload
    finally:
        abandoned.set()


def failure_kind(exc: BaseException) -> str:
    text = f"{type(exc).__name__} {exc}"
    if "timeout" in type(exc).__name__.lower() or "DEADLINE_EXCEEDED" in text or "timed out" in text.lower() or re.search(r"\b504\b", text):
        return TIMEOUT
    if "RESOURCE_EXHAUSTED" in text or re.search(r"\b429\b", text):
        return QUOTA
    if "no longer available" in text or ("NOT_FOUND" in text and "model" in text.lower()):
        return UNAVAILABLE
    if "UNAVAILABLE" in text or re.search(r"\b503\b", text):
        return OVERLOADED
    return OTHER


def is_cold(model: str) -> bool:
    with _lock:
        return _cold_until.get(model, 0.0) > _now()


def is_unavailable(model: str, key_label: str) -> bool:
    with _lock:
        return _unavailable_until.get((model, key_label), 0.0) > _now()


def attempt_plan(chain: Sequence[str], clients: Sequence[tuple[str, object]]) -> list[tuple[str, list[tuple[str, object]]]]:
    """The (model, [clients]) pairs worth trying, in order: cold models are dropped (unless every model is cold, then
    all are kept so a total outage still gets tried), and so are (model, key) pairs known to be unavailable."""
    models = [m for m in chain if not is_cold(m)] or list(chain)
    plan = []
    for model in models:
        usable = [c for c in clients if not is_unavailable(model, c[0])]
        if usable:
            plan.append((model, usable))
    return plan


def note_success(model: str) -> None:
    with _lock:
        _cold_until.pop(model, None)


class ModelAttempt:
    """Per-model bookkeeping while a loop walks the keys: counts overloaded answers so the loop can give up on a model."""

    def __init__(self) -> None:
        self.overloaded = 0


def note_failure(model: str, key_label: str, exc: BaseException, attempt: ModelAttempt) -> str:
    """Records what the failure says about the model/key and returns NEXT_KEY or NEXT_MODEL for the caller's loop."""
    kind = failure_kind(exc)
    print(f"[Gemini] {model} on {key_label} failed ({kind}): {type(exc).__name__}: {str(exc)[:160]}")
    if kind == TIMEOUT:
        with _lock:
            _cold_until[model] = _now() + MODEL_COOLDOWN_SECONDS
        print(f"[Gemini] {model} is slow: trying the next model, and skipping it for {MODEL_COOLDOWN_SECONDS:g}s")
        return NEXT_MODEL
    if kind == UNAVAILABLE:
        with _lock:
            _unavailable_until[(model, key_label)] = _now() + UNAVAILABLE_COOLDOWN_SECONDS
        print(f"[Gemini] {model} is not available to {key_label}: skipping that pair for {UNAVAILABLE_COOLDOWN_SECONDS / 3600:g}h")
        return NEXT_KEY
    if kind == OVERLOADED:
        attempt.overloaded += 1
        if attempt.overloaded >= MAX_OVERLOADED_PER_MODEL:
            return NEXT_MODEL
    return NEXT_KEY


def is_retryable_in_place(exc: BaseException) -> bool:
    """Whether retrying the SAME model on the SAME key could help. Only for the odd transient (bad JSON, a dropped
    stream). Timeouts, quota, overload and not-available are decided by the caller's loop, not repeated in place."""
    return failure_kind(exc) == OTHER


def thinking_config_for(model: str) -> types.ThinkingConfig | None:
    """Turns thinking down where this app's calls (structured extraction and templated JSON) don't need it and where the
    model is known to accept it. gemini-2.5-flash with thinking off answered the vision call in ~9s (vs timing out at
    25s); gemini-3.x takes a level, not a budget. Aliases (gemini-flash-latest, ...) are left on their default because
    what they point at can change and an unsupported config would be rejected."""
    if model.startswith("gemini-2.5-flash"):
        return types.ThinkingConfig(thinking_budget=0)
    if model.startswith("gemini-3") and "pro" not in model:
        return types.ThinkingConfig(thinking_level="LOW")
    return None


def reset_for_tests() -> None:
    with _lock:
        _cold_until.clear()
        _unavailable_until.clear()
