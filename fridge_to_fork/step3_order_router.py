"""
Step 3 — Order Router
=====================
CLI/plan-level entry point (route_order). It only simulates (--dry-run) or refuses
via swiggy_agent.py: real orders are placed by the staged flows that show the user
the real cart before any money moves, groceries in instamart.py and the dish in
food.py. The web app does not call this module.
"""

import argparse
import asyncio
import json
import os

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from .models import Decision, MealPlan, MealSuggestion, OrderResult

load_dotenv()

console = Console()


async def route_order(
    plan: MealPlan,
    delivery_address: str,
    access_token: str | None = None,
    *,
    dry_run: bool = False,
) -> OrderResult | None:
    """Dispatch the meal plan to the Swiggy ordering agent."""
    if plan.decision == Decision.COOK:
        console.print("[green]Decision: cook at home — no order placed.[/green]")
        return None

    if plan.decision == Decision.ORDER_GROCERIES:
        missing = plan.recommended_meal.missing_ingredients if plan.recommended_meal else []
        if not missing:
            console.print("[yellow]order_groceries chosen but no missing ingredients — cooking instead.[/yellow]")
            return None

    from .swiggy_agent import run_swiggy_agent
    return await run_swiggy_agent(plan, delivery_address, access_token, dry_run=dry_run)


def display_order_result(result: OrderResult) -> None:
    if result.success:
        items_list = "\\n  • ".join([""] + result.items)
        console.print(
            Panel(
                f"[bold green]Order confirmed![/bold green]\n"
                f"Order ID : {result.order_id}\n"
                f"Platform : {result.platform}\n"
                f"ETA      : {result.estimated_minutes} min\n"
                f"Items    :{items_list}",
                title="Order Placed",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]Order failed.[/bold red]\n{result.error}",
                title="Order Error",
                border_style="red",
            )
        )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Place an order via Swiggy MCP.")
    p.add_argument(
        "--decision",
        choices=["order_dish", "order_groceries"],
        required=True,
    )
    p.add_argument("--items", required=True, help="Comma-separated items / dish name")
    p.add_argument("--address", default=os.environ.get("DELIVERY_ADDRESS", "Test Address"))
    p.add_argument("--access-token", default=None, help="Swiggy Bearer access token")
    p.add_argument("--dry-run", action="store_true", default=False, help="Simulate order placement")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


async def main_async() -> None:
    args = _parse_args()
    items = [i.strip() for i in args.items.split(",") if i.strip()]

    # Fake MealPlan to test routing standalone
    fake_meal = MealSuggestion(
        name=items[0] if args.decision == "order_dish" else "Fake Meal",
        description="Fake", can_cook_now=False,
        missing_ingredients=items if args.decision == "order_groceries" else [],
        cuisine="Fake", prep_time_minutes=0
    )
    plan = MealPlan(
        suggestions=[fake_meal],
        decision=Decision.ORDER_DISH if args.decision == "order_dish" else Decision.ORDER_GROCERIES,
        recommended_meal=fake_meal,
        reasoning="Test"
    )

    result = await route_order(
        plan, args.address, dry_run=args.dry_run, access_token=args.access_token
    )
    if not result:
        return

    if args.json:
        print(json.dumps(result.__dict__, indent=2))
    else:
        display_order_result(result)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
