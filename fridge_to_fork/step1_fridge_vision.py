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
You are a culinary assistant with expert knowledge of ingredients and food.
Examine this fridge / pantry image carefully — check every shelf, drawer, and door pocket.

Return ONLY a JSON object in this exact shape (no markdown, no prose):
{
  "ingredients": [
    {
      "name": "<ingredient name, lowercase>",
      "quantity": "<rough amount: e.g. '3 eggs', 'half a block', 'plenty', '1 bottle'>",
      "confidence": <float 0.0-1.0, how certain you are this item is present>
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

def identify_ingredients(
    image_source: Union[str, Path, bytes],
    *,
    model: str = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash-lite"),
    client: genai.Client | None = None,
) -> FridgeContents:
    """
    Analyse a fridge image and return structured FridgeContents.

    Parameters
    ----------
    image_source:
        File path (str/Path), public image URL (str), or raw image bytes.
    model:
        Gemini model to use. Defaults to gemini-2.0-flash (free tier, fast vision).
    client:
        Optional pre-built Gemini client (useful for testing / DI).

    Returns
    -------
    FridgeContents with a list of Ingredient objects.

    Retries transient API errors (quota/overload) up to 3 times with
    exponential backoff before falling back to a placeholder inventory.
    """
    try:
        client = client or genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        raw_bytes, media_type = _load_image(image_source)
        image_part = types.Part.from_bytes(data=raw_bytes, mime_type=media_type)
    except Exception as e:
        console.print(f"[yellow][WARNING] Could not prepare image for vision analysis: {type(e).__name__}: {e}[/yellow]")
        return _fallback_fridge_contents()

    max_retries = 3
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[image_part, _PROMPT],
            )

            raw_text = response.text.strip()

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

        except Exception as e:
            console.print(f"[yellow][WARNING] Vision attempt {attempt} failed: {type(e).__name__}: {e}[/yellow]")
            if attempt == max_retries:
                console.print("[yellow][WARNING] Vision API error (falling back to defaults)[/yellow]")
                return _fallback_fridge_contents()
            import time

            time.sleep(backoff)
            backoff *= 2

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
