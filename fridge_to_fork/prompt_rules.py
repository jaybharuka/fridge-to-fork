"""
Style rules appended to every prompt sent to Gemini (vision, meal planning, top-up suggestions).

The app's voice does not use em dashes, and generated copy that has them reads as machine-written. The prompts used to
contain em dashes themselves (which the model imitates) and said nothing against them. Now the prompt text is free of
them and ends with an explicit instruction.
"""

from __future__ import annotations

import functools
from typing import Callable

EM_DASH = chr(0x2014)  # built here so this source file itself contains no em dash character

NO_EM_DASH_RULE = (
    f"STYLE RULE: Never use em dashes ({EM_DASH}) anywhere in your response. "
    "Use commas, periods, or a plain hyphen with spaces instead."
)


def append_rule(prompt: str) -> str:
    """The prompt with the style rule on its own final paragraph. Idempotent."""
    if NO_EM_DASH_RULE in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{NO_EM_DASH_RULE}\n"


def styled(build_prompt: Callable[..., str]) -> Callable[..., str]:
    """Decorator for the prompt-building functions: whatever they return gets the rule appended."""

    @functools.wraps(build_prompt)
    def wrapper(*args, **kwargs) -> str:
        return append_rule(build_prompt(*args, **kwargs))

    return wrapper
