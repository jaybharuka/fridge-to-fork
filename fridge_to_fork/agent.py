"""
Fridge-to-Fork Agent Orchestrator
==================================
Ties all three steps into a single end-to-end pipeline:

    fridge image → ingredients → meal plan → order (or cook instruction)

Usage:
    fridge-to-fork --image path/to/fridge.jpg
    fridge-to-fork --image path/to/fridge.jpg --dry-run
    python -m fridge_to_fork.agent --image fridge.jpg

Requires OPENAI_API_KEY in .env
"""

import argparse
import asyncio
import os
import sys
import time

from dotenv import load_dotenv
from rich.console import Console

from .step1_fridge_vision import display_fridge_contents, identify_ingredients
from .step2_meal_planner import display_meal_plan, plan_meals
from .step3_order_router import display_order_result, route_order

load_dotenv()

console = Console()


def run_pipeline(
    image_source: str,
    *,
    target_dish: str | None = None,
    delivery_address: str | None = None,
    dry_run: bool = False,
    vision_model: str = "gemini-2.5-flash",
    planner_model: str = "gemini-2.5-flash",
) -> None:
    """
    Execute the full fridge-to-fork pipeline.

    Parameters
    ----------
    image_source:
        File path or public URL for the fridge image.
    delivery_address:
        Where to deliver (falls back to DELIVERY_ADDRESS env var).
    dry_run:
        Simulate MCP order calls without hitting real endpoints.
    vision_model:
        OpenAI model for image analysis (default: gpt-4o).
    planner_model:
        OpenAI model for meal planning (default: gpt-4o-mini).
    """
    address = delivery_address or os.environ.get("DELIVERY_ADDRESS", "Mumbai, India")

    console.rule("[bold magenta]Fridge to Fork[/bold magenta]")
    console.print()

    # ── Step 1: Vision ───────────────────────────────────────────────────────
    console.print("[bold]Step 1/3[/bold] — Scanning fridge contents with Claude Vision...")
    t0 = time.perf_counter()
    fridge = identify_ingredients(image_source, model=vision_model)
    console.print(f"  Done in {time.perf_counter() - t0:.1f}s — "
                  f"found {len(fridge.ingredients)} ingredients.\n")
    display_fridge_contents(fridge)
    console.print()

    # ── Step 2: Meal planning ────────────────────────────────────────────────
    if target_dish:
        console.print(f"[bold]Step 2/3[/bold] — Evaluating target dish: {target_dish}...")
    else:
        console.print("[bold]Step 2/3[/bold] — Planning meals with Claude...")
    t0 = time.perf_counter()
    plan = plan_meals(fridge, target_dish=target_dish, model=planner_model)
    console.print(f"  Done in {time.perf_counter() - t0:.1f}s.\n")
    display_meal_plan(plan)
    console.print()

    # ── Step 3: Order routing ────────────────────────────────────────────────
    console.print("[bold]Step 3/3[/bold] — Routing order...")
    result = asyncio.run(route_order(plan, address, dry_run=dry_run))
    if result:
        display_order_result(result)

    console.print()
    console.rule("[bold magenta]Done[/bold magenta]")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AI agent: fridge photo → meal suggestion → order"
    )
    p.add_argument("--image", required=True, help="Fridge image path or public URL")
    p.add_argument(
        "--address",
        default=None,
        help="Delivery address (overrides DELIVERY_ADDRESS env var)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate MCP order calls (no real orders placed)",
    )
    p.add_argument(
        "--target-dish",
        default=None,
        help="Specific dish you want to cook",
    )
    p.add_argument("--vision-model", default="gemini-2.5-flash", help="Gemini vision model")
    p.add_argument("--planner-model", default="gemini-2.5-flash", help="Gemini planner model")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if not os.environ.get("GOOGLE_API_KEY"):
        console.print("[bold red]Error:[/bold red] GOOGLE_API_KEY is not set.")
        console.print("Get a free key at https://aistudio.google.com/app/apikey")
        sys.exit(1)

    run_pipeline(
        args.image,
        target_dish=args.target_dish,
        delivery_address=args.address,
        dry_run=args.dry_run,
        vision_model=args.vision_model,
        planner_model=args.planner_model,
    )


if __name__ == "__main__":
    main()
