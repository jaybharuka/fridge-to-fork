"""
The Gemini API keys the app rotates across: GOOGLE_API_KEY, then GOOGLE_API_KEY_2 ... GOOGLE_API_KEY_9.

Gemini's free-tier daily quota is scoped per Google Cloud PROJECT (and per model), not per key, so a key only adds quota
if it comes from a project the other keys don't (verified 2026-10-03: key 1 = project A, keys 2 and 3 = project B,
key 4 = project C, key 5 = project D; keys 2 and 3 are the same project, so the second one adds nothing).
Shared by the vision (step1) and planner (step2) modules, which each build their own client pool from this list.
"""

from __future__ import annotations

import os
from typing import Mapping

MAX_KEYS = 9


def key_env_names() -> list[str]:
    return ["GOOGLE_API_KEY"] + [f"GOOGLE_API_KEY_{i}" for i in range(2, MAX_KEYS + 1)]


def load_api_keys(environ: Mapping[str, str] | None = None) -> list[str]:
    """Configured keys in order, blanks skipped, identical values collapsed (a copy-pasted duplicate must not become
    two clients for one real key). Gaps are fine: a missing _4 does not hide a set _5."""
    env = os.environ if environ is None else environ
    seen: set[str] = set()
    keys: list[str] = []
    for name in key_env_names():
        value = (env.get(name) or "").strip()
        if value and value not in seen:
            seen.add(value)
            keys.append(value)
    return keys
