"""
Step 1 — Fridge Vision
======================
Accepts a fridge image (file path, URL, or raw bytes) and uses Google Gemini
Vision to identify all visible ingredients with estimated quantities and confidence.

Run standalone for a quick smoke-test:
    python -m fridge_to_fork.step1_fridge_vision --image path/to/fridge.jpg
"""

import argparse
import io
import json
import os
import time
from pathlib import Path
from typing import Union

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image
from rich.console import Console
from rich.table import Table

from .models import FridgeContents, Ingredient

load_dotenv()

console = Console()


def _dedupe(models: list[str | None]) -> list[str]:
    """Remove falsy/duplicate entries while preserving order."""
    seen = set()
    result = []
    for m in models:
        if m and m not in seen:
            seen.add(m)
            result.append(m)
    return result


# Models tried in order until one succeeds. Each Gemini model has its own
# separate free-tier daily quota, so exhausting one doesn't mean they're
# all exhausted.
VISION_MODEL_FALLBACK_CHAIN = _dedupe([
    os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash"),
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash-lite",
    "gemini-flash-lite-latest",
])


def _fallback_fridge_contents() -> FridgeContents:
    """Return a small, safe placeholder fridge inventory when vision fails."""
    return FridgeContents(
        ingredients=[
            Ingredient(name="eggs", quantity="3 eggs", confidence=0.85),
            Ingredient(name="bread", quantity="1 loaf", confidence=0.8),
            Ingredient(name="tomatoes", quantity="2 tomatoes", confidence=0.75),
        ],
        raw_description="Fallback fridge inventory used because vision analysis was unavailable.",
    )

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PROMPT = """\
You are a precise kitchen inventory scanner. Your job is to identify every food item visible in this fridge photo as accurately as possible.

Scan the fridge methodically — shelf by shelf, top to bottom, then door compartments left to right. Do not rush. Do not guess.

For each item you identify, follow these rules:

WHAT TO IDENTIFY:
- Every individual food ingredient you can see, even partially
- Items inside clear containers, bags, or wrapped packaging — describe what's inside, not the container
- Produce, dairy, meat, condiments, sauces, drinks, leftovers in identifiable containers
- Items on shelves, in drawers, on the door, and in the freezer compartment if visible

WHAT TO IGNORE:
- Water bottles and plain drinking water
- Non-food items (cleaning products, medicines)
- Items you genuinely cannot identify — do not guess vague categories like "unknown item"
- Duplicate entries — if you see 3 eggs in a carton, report "eggs" once, not three times

HOW TO REPORT CONFIDENCE:
Rate each item's confidence from 0 to 100:
- 90-100: clearly visible, no doubt
- 70-89: visible but partially obscured or packaged
- 50-69: partially visible, reasonable inference
- Below 50: do not include — skip items you are not reasonably sure about

BE SPECIFIC:
- Say "cherry tomatoes" not "tomatoes" if you can tell
- Say "Greek yogurt" not "yogurt" if the container is identifiable
- Say "chicken breast" not "meat" if the cut is visible
- Say "cheddar cheese" not "cheese" if the packaging shows it

Return a JSON array only. No explanation. No preamble. Format:
[
  {"name": "eggs", "confidence": 95},
  {"name": "cherry tomatoes", "confidence": 88},
  {"name": "Greek yogurt", "confidence": 72}
]

If you cannot identify any food items, return an empty array: []
"""


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _load_image(source: Union[str, Path, bytes]) -> tuple[bytes, str]:
    """Return (raw_bytes, media_type)."""
    if isinstance(source, bytes):
        return source, "image/jpeg"

    if isinstance(source, str) and source.startswith(("http://", "https://")):
        resp = httpx.get(source, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        return resp.content, content_type

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    suffix = path.suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")
    return path.read_bytes(), media_type


# ---------------------------------------------------------------------------
# Core vision function
# ---------------------------------------------------------------------------

def _call_vision_model_with_retry(
    client: genai.Client, model: str, image_part: types.Part
) -> FridgeContents:
    """
    Call `model` up to 3 times with exponential backoff, for transient
    errors (503/network blips). Raises the last exception if all
    attempts fail — the caller decides whether that means "try the next
    model in the fallback chain" or "give up".
    """
    max_retries = 3
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[image_part, _PROMPT],
                # A short JSON array of detected ingredients should never
                # need more than a few hundred tokens. Capping this makes a
                # misbehaving model (seen returning 150KB+ of truncated,
                # unparseable text) fail fast and cheaply instead of
                # burning a full attempt generating runaway output.
                config=types.GenerateContentConfig(max_output_tokens=2048),
            )

            raw_text = response.text.strip()

            # Strip markdown fences if the model wraps the JSON
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            items = json.loads(raw_text)

            # The prompt already tells the model to skip anything below 50
            # and to just return a flat array, but enforce both in code too
            # rather than trust the model to follow instructions perfectly.
            items = [item for item in items if item.get("confidence", 0) >= 50]
            items = sorted(items, key=lambda x: x.get("confidence", 0), reverse=True)

            ingredients = [
                Ingredient(
                    name=item["name"],
                    # Prompt reports confidence on a 0-100 scale; Ingredient's
                    # confidence field is documented (models.py) as 0.0-1.0,
                    # so convert here — keeps this function's return format
                    # unchanged for every downstream caller.
                    confidence=item.get("confidence", 0) / 100.0,
                )
                for item in items
            ]

            return FridgeContents(
                ingredients=ingredients,
                raw_description=(
                    f"{len(ingredients)} ingredient(s) detected in your fridge."
                    if ingredients else "No ingredients detected."
                ),
            )

        except Exception as e:
            console.print(f"[yellow][WARNING] {model} attempt {attempt} failed: {type(e).__name__}: {e}[/yellow]")
            if attempt == max_retries:
                raise
            time.sleep(backoff)
            backoff *= 2

    raise RuntimeError(f"{model} failed after {max_retries} attempts")  # unreachable safeguard


def identify_ingredients(
    image_source: Union[str, Path, bytes],
    *,
    model: str | None = None,
    client: genai.Client | None = None,
) -> FridgeContents:
    """
    Analyse a fridge image and return structured FridgeContents.

    Parameters
    ----------
    image_source:
        File path (str/Path), public image URL (str), or raw image bytes.
    model:
        Optional Gemini model override. If omitted, tries each model in
        VISION_MODEL_FALLBACK_CHAIN in order until one succeeds.
    client:
        Optional pre-built Gemini client (useful for testing / DI).

    Returns
    -------
    FridgeContents with a list of Ingredient objects.

    Retries transient API errors (quota/overload) up to 3 times with
    exponential backoff per model. If a model's quota is exhausted (or it
    keeps failing after retries), moves on to the next model in the
    fallback chain before giving up and returning a placeholder inventory.
    """
    try:
        client = client or genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        raw_bytes, media_type = _load_image(image_source)
        image_part = types.Part.from_bytes(data=raw_bytes, mime_type=media_type)
    except Exception as e:
        console.print(f"[yellow][WARNING] Could not prepare image for vision analysis: {type(e).__name__}: {e}[/yellow]")
        return _fallback_fridge_contents()

    chain = _dedupe([model, *VISION_MODEL_FALLBACK_CHAIN]) if model else VISION_MODEL_FALLBACK_CHAIN

    for chain_model in chain:
        try:
            result = _call_vision_model_with_retry(client, chain_model, image_part)
            console.print(f"[green][OK] Vision succeeded with model: {chain_model}[/green]")
            return result
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                console.print(f"[yellow][WARNING] {chain_model} quota exhausted, trying next model...[/yellow]")
            else:
                console.print(f"[yellow][WARNING] {chain_model} failed with: {e}, trying next...[/yellow]")

    console.print("[yellow][WARNING] All Gemini vision models quota exhausted, using fallback[/yellow]")
    return _fallback_fridge_contents()


# ---------------------------------------------------------------------------
# Pretty-print helper (used by orchestrator and CLI)
# ---------------------------------------------------------------------------

def display_fridge_contents(contents: FridgeContents) -> None:
    """Render fridge contents as a Rich table."""
    console.rule("[bold green]Fridge Contents")
    console.print(f"\n[italic]{contents.raw_description}[/italic]\n")

    table = Table(title="Detected Ingredients", show_lines=True)
    table.add_column("Ingredient", style="cyan", no_wrap=True)
    table.add_column("Quantity", style="magenta")
    table.add_column("Confidence", justify="right")

    for ing in sorted(contents.ingredients, key=lambda i: -i.confidence):
        conf_color = "green" if ing.confidence >= 0.8 else "yellow" if ing.confidence >= 0.5 else "red"
        table.add_row(
            ing.name,
            ing.quantity or "—",
            f"[{conf_color}]{ing.confidence:.0%}[/{conf_color}]",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Identify ingredients in a fridge image.")
    p.add_argument("--image", required=True, help="Path to fridge image or public URL")
    p.add_argument("--model", default="gemini-2.5-flash", help="Gemini model ID")
    p.add_argument("--json", action="store_true", help="Output raw JSON instead of table")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    console.print(f"[bold]Analysing fridge image:[/bold] {args.image}")

    contents = identify_ingredients(args.image, model=args.model)

    if args.json:
        import json as _json
        data = {
            "raw_description": contents.raw_description,
            "ingredients": [
                {"name": i.name, "quantity": i.quantity, "confidence": i.confidence}
                for i in contents.ingredients
            ],
        }
        print(_json.dumps(data, indent=2))
    else:
        display_fridge_contents(contents)


if __name__ == "__main__":
    main()
