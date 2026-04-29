"""
Step 1 — Fridge Vision
======================
Accepts a fridge image (file path, URL, or raw bytes) and uses Claude Vision
to identify all visible ingredients with estimated quantities and confidence.

Run standalone for a quick smoke-test:
    python -m fridge_to_fork.step1_fridge_vision --image path/to/fridge.jpg
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Union

import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .models import FridgeContents, Ingredient

load_dotenv()

console = Console()

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a culinary assistant with expert knowledge of ingredients and food.
Your job is to examine fridge / pantry images and produce a structured inventory.
Be thorough: check every shelf, drawer, and door pocket.
Always respond with valid JSON — nothing else.
"""

_USER_PROMPT = """\
Look carefully at this fridge image.
List every ingredient you can see.

Return ONLY a JSON object in this exact shape:
{
  "ingredients": [
    {
      "name": "<ingredient name, lowercase>",
      "quantity": "<rough amount: e.g. '3 eggs', 'half a block', 'plenty', '1 bottle'>",
      "confidence": <float 0.0–1.0, how certain you are this item is present>
    }
  ],
  "raw_description": "<one short paragraph describing overall fridge contents>"
}

Rules:
- Include items even if partially obscured (lower the confidence score).
- Omit condiments unless clearly identifiable (ketchup, mustard, etc. are ok).
- Use the ingredient's generic name, not the brand name.
- Do NOT include packaging materials, non-food items, or containers with unidentifiable contents.
"""


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _load_image_as_base64(source: Union[str, Path, bytes]) -> tuple[str, str]:
    """Return (base64_data, media_type)."""
    if isinstance(source, bytes):
        # caller already has raw bytes
        data = source
        media_type = "image/jpeg"
    elif isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")
        data = path.read_bytes()
        suffix = path.suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(suffix, "image/jpeg")
    else:
        raise TypeError(f"Unsupported image source type: {type(source)}")

    return base64.standard_b64encode(data).decode("utf-8"), media_type


def _is_url(source: Union[str, Path, bytes]) -> bool:
    return isinstance(source, str) and source.startswith(("http://", "https://"))


# ---------------------------------------------------------------------------
# Core vision function
# ---------------------------------------------------------------------------

def identify_ingredients(
    image_source: Union[str, Path, bytes],
    *,
    model: str = "claude-opus-4-7",
    max_tokens: int = 1024,
    client: anthropic.Anthropic | None = None,
) -> FridgeContents:
    """
    Analyse a fridge image and return structured FridgeContents.

    Parameters
    ----------
    image_source:
        File path (str/Path), public image URL (str), or raw image bytes.
    model:
        Claude model to use. Defaults to claude-opus-4-7 for best vision accuracy.
    max_tokens:
        Maximum tokens for the response.
    client:
        Optional pre-built Anthropic client (useful for testing / DI).

    Returns
    -------
    FridgeContents with a list of Ingredient objects.
    """
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Build the image block
    if _is_url(image_source):
        image_block: dict = {
            "type": "image",
            "source": {"type": "url", "url": image_source},
        }
    else:
        b64_data, media_type = _load_image_as_base64(image_source)
        image_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64_data,
            },
        }

    messages = [
        {
            "role": "user",
            "content": [
                image_block,
                {"type": "text", "text": _USER_PROMPT},
            ],
        }
    ]

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=_SYSTEM_PROMPT,
        messages=messages,
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown fences if the model wraps the JSON
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    payload = json.loads(raw_text)

    ingredients = [
        Ingredient(
            name=item["name"],
            quantity=item.get("quantity"),
            confidence=float(item.get("confidence", 1.0)),
        )
        for item in payload.get("ingredients", [])
    ]

    return FridgeContents(
        ingredients=ingredients,
        raw_description=payload.get("raw_description", ""),
    )


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
    p.add_argument("--model", default="claude-opus-4-7", help="Claude model ID")
    p.add_argument("--json", action="store_true", help="Output raw JSON instead of table")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    console.print(f"[bold]Analysing fridge image:[/bold] {args.image}")

    contents = identify_ingredients(args.image, model=args.model)

    if args.json:
        data = {
            "raw_description": contents.raw_description,
            "ingredients": [
                {"name": i.name, "quantity": i.quantity, "confidence": i.confidence}
                for i in contents.ingredients
            ],
        }
        print(json.dumps(data, indent=2))
    else:
        display_fridge_contents(contents)


if __name__ == "__main__":
    main()
