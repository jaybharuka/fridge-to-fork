"""
Step 3 — Order Router
=====================
Routes the meal plan to the correct Swiggy MCP:
  • Swiggy Food MCP   → order a ready-made dish (order_dish)
  • Swiggy Instamart  → order missing ingredients (order_groceries)

Uses the official `mcp` Python SDK to communicate via stdio with the local
`swiggy_live_mcp.py` server, which fetches real data from Swiggy APIs.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.panel import Panel

from .models import Decision, MealPlan, OrderResult

load_dotenv()

console = Console()

# Path to our local live MCP server
SERVER_PATH = str(Path(__file__).parent / "swiggy_live_mcp.py")


async def order_dish_from_swiggy(
    meal_name: str,
    delivery_address: str,
    session: ClientSession,
    *,
    dry_run: bool = False,
) -> OrderResult:
    """Search Swiggy Food for 'meal_name' and place the top result."""
    
    # Step 1: search for the dish
    search_result = await session.call_tool("swiggy_food_search", {
        "query": meal_name,
        "delivery_address": delivery_address,
    })
    
    # Parse the text response from the tool
    data = json.loads(search_result.content[0].text)
    
    if "error" in data:
        return OrderResult(success=False, platform="swiggy_food", error=data["error"])
        
    restaurants = data.get("restaurants", [])
    if not restaurants:
        return OrderResult(
            success=False,
            platform="swiggy_food",
            error=f"No restaurants found for '{meal_name}' on Swiggy.",
        )

    # Pick first result
    restaurant = restaurants[0]
    dish = restaurant.get("top_dish", {})
    
    if dry_run:
        return OrderResult(
            success=True,
            order_id="DRY-RUN",
            platform="swiggy_food",
            items=[f"{dish.get('name')} from {restaurant.get('name')} (₹{dish.get('price')})"],
            estimated_minutes=35,
        )

    # Step 2: place the order
    order_result = await session.call_tool("swiggy_food_place_order", {
        "restaurant_id": restaurant["id"],
        "dish_id": dish["id"],
        "delivery_address": delivery_address,
    })
    
    order_data = json.loads(order_result.content[0].text)

    return OrderResult(
        success=order_data.get("status") == "confirmed",
        order_id=order_data.get("order_id"),
        platform="swiggy_food",
        items=[f"{dish.get('name')} from {restaurant.get('name')} (₹{dish.get('price')})"],
        estimated_minutes=order_data.get("eta_minutes"),
        error=order_data.get("error"),
    )


async def order_groceries_from_instamart(
    items: list[str],
    delivery_address: str,
    session: ClientSession,
    *,
    dry_run: bool = False,
) -> OrderResult:
    """Search Swiggy Instamart for each item and place a consolidated order."""
    
    cart_items = []
    unavailable = []
    receipt_items = []

    for item in items:
        search_result = await session.call_tool("instamart_search", {
            "query": item,
            "delivery_address": delivery_address,
        })
        data = json.loads(search_result.content[0].text)
        products = data.get("products", [])
        
        if products:
            prod = products[0]
            cart_items.append({
                "product_id": prod["id"],
                "quantity": 1,
            })
            receipt_items.append(f"{prod['name']} (₹{prod['price']})")
        else:
            unavailable.append(item)

    if not cart_items:
        return OrderResult(
            success=False,
            platform="swiggy_instamart",
            error=f"None of the items found on Instamart: {unavailable}",
        )

    if dry_run:
        return OrderResult(
            success=True,
            order_id="DRY-RUN",
            platform="swiggy_instamart",
            items=receipt_items,
            estimated_minutes=15,
        )

    order_result = await session.call_tool("instamart_place_order", {
        "cart": cart_items,
        "delivery_address": delivery_address,
    })
    
    order_data = json.loads(order_result.content[0].text)

    return OrderResult(
        success=order_data.get("status") == "confirmed",
        order_id=order_data.get("order_id"),
        platform="swiggy_instamart",
        items=receipt_items,
        estimated_minutes=order_data.get("eta_minutes"),
        error=(
            f"Unavailable: {unavailable}" if unavailable else order_data.get("error")
        ),
    )


async def route_order(
    plan: MealPlan,
    delivery_address: str,
    *,
    dry_run: bool = False,
    access_token: str | None = None,
) -> OrderResult | None:
    """Dispatch to the correct Swiggy MCP based on the meal plan decision."""
    if plan.decision == Decision.COOK:
        console.print("[green]Decision: cook at home — no order placed.[/green]")
        return None

    meal_name = plan.recommended_meal.name if plan.recommended_meal else "meal"

    if plan.decision == Decision.ORDER_DISH:
        console.print(f"[bold]Ordering '{meal_name}' from Swiggy Food...[/bold]")
    elif plan.decision == Decision.ORDER_GROCERIES:
        missing = plan.recommended_meal.missing_ingredients if plan.recommended_meal else []
        if not missing:
            console.print("[yellow]order_groceries chosen but no missing ingredients — cooking instead.[/yellow]")
            return None
        console.print(f"[bold]Ordering groceries from Swiggy Instamart:[/bold] {missing}")

    # Start MCP connection and execute routing
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_PATH],
        env=None
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            if plan.decision == Decision.ORDER_DISH:
                return await order_dish_from_swiggy(meal_name, delivery_address, session, dry_run=dry_run)
            elif plan.decision == Decision.ORDER_GROCERIES:
                return await order_groceries_from_instamart(missing, delivery_address, session, dry_run=dry_run)

    return None


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
    p = argparse.ArgumentParser(description="Place an order via Swiggy Live MCP.")
    p.add_argument(
        "--decision",
        choices=["order_dish", "order_groceries"],
        required=True,
    )
    p.add_argument("--items", required=True, help="Comma-separated items / dish name")
    p.add_argument("--address", default=os.environ.get("DELIVERY_ADDRESS", "Test Address"))
    p.add_argument("--dry-run", action="store_true", default=False, help="Simulate order placement")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


async def main_async() -> None:
    args = _parse_args()
    items = [i.strip() for i in args.items.split(",") if i.strip()]
    
    # Fake MealPlan to test routing standalone
    from .models import Ingredient, MealPlan, MealSuggestion
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

    result = await route_order(plan, args.address, dry_run=args.dry_run)
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
