"""
Step 3 — Order Router
=====================
Routes the meal plan to the correct Swiggy MCP:
  • Swiggy Food MCP   → order a ready-made dish (order_dish)
  • Swiggy Instamart  → order missing ingredients (order_groceries)

MCP communication is done via HTTP POST to the MCP endpoint.
The MCPs are stubbed so this layer is fully testable in isolation;
replace _call_mcp() with real MCP SDK calls when MCPs are available.

Run standalone:
    python -m fridge_to_fork.step3_order_router \
        --decision order_groceries \
        --items "onion,tomato,garlic"
"""

import argparse
import json
import os
import time
import uuid
from typing import Any

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from .models import Decision, MealPlan, OrderResult

load_dotenv()

console = Console()

# ---------------------------------------------------------------------------
# MCP client helper
# ---------------------------------------------------------------------------

MCP_TIMEOUT = 10  # seconds


def _call_mcp(base_url: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Send a JSON-RPC 2.0 tool-call to an MCP server.

    This is the single seam to replace with an official MCP SDK client
    once Swiggy publishes their MCP packages.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    try:
        resp = httpx.post(
            f"{base_url}/mcp",
            json=payload,
            timeout=MCP_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json().get("result", {})
    except httpx.HTTPError as exc:
        raise RuntimeError(f"MCP call failed ({base_url}, {tool}): {exc}") from exc


# ---------------------------------------------------------------------------
# Swiggy Food MCP  —  order a dish
# ---------------------------------------------------------------------------

def order_dish_from_swiggy(
    meal_name: str,
    delivery_address: str,
    *,
    mcp_url: str | None = None,
    dry_run: bool = False,
) -> OrderResult:
    """
    Search Swiggy Food for 'meal_name' and place the top result.

    Parameters
    ----------
    meal_name:
        The name of the dish to search for (e.g. "Butter Chicken").
    delivery_address:
        Human-readable delivery address string.
    mcp_url:
        Override for SWIGGY_FOOD_MCP_URL env var.
    dry_run:
        If True, skip the actual MCP call and return a simulated result.
    """
    url = mcp_url or os.environ.get("SWIGGY_FOOD_MCP_URL", "http://localhost:8002")

    if dry_run:
        return OrderResult(
            success=True,
            order_id=f"SWG-FOOD-{uuid.uuid4().hex[:8].upper()}",
            platform="swiggy_food",
            items=[meal_name],
            estimated_minutes=35,
        )

    # Step 1: search for the dish
    search_result = _call_mcp(url, "swiggy_food_search", {
        "query": meal_name,
        "delivery_address": delivery_address,
    })

    restaurants = search_result.get("restaurants", [])
    if not restaurants:
        return OrderResult(
            success=False,
            platform="swiggy_food",
            error=f"No restaurants found for '{meal_name}'",
        )

    # Pick first result
    restaurant = restaurants[0]
    dish = restaurant.get("top_dish", {})

    # Step 2: place the order
    order_result = _call_mcp(url, "swiggy_food_place_order", {
        "restaurant_id": restaurant["id"],
        "dish_id": dish["id"],
        "delivery_address": delivery_address,
    })

    return OrderResult(
        success=order_result.get("status") == "confirmed",
        order_id=order_result.get("order_id"),
        platform="swiggy_food",
        items=[dish.get("name", meal_name)],
        estimated_minutes=order_result.get("eta_minutes"),
        error=order_result.get("error"),
    )


# ---------------------------------------------------------------------------
# Swiggy Instamart MCP  —  order groceries
# ---------------------------------------------------------------------------

def order_groceries_from_instamart(
    items: list[str],
    delivery_address: str,
    *,
    mcp_url: str | None = None,
    dry_run: bool = False,
) -> OrderResult:
    """
    Search Swiggy Instamart for each item and place a consolidated order.

    Parameters
    ----------
    items:
        List of grocery/ingredient names to order.
    delivery_address:
        Human-readable delivery address.
    mcp_url:
        Override for SWIGGY_INSTAMART_MCP_URL env var.
    dry_run:
        Skip actual MCP calls; return simulated result.
    """
    url = mcp_url or os.environ.get("SWIGGY_INSTAMART_MCP_URL", "http://localhost:8001")

    if dry_run:
        return OrderResult(
            success=True,
            order_id=f"SWG-IM-{uuid.uuid4().hex[:8].upper()}",
            platform="swiggy_instamart",
            items=items,
            estimated_minutes=15,
        )

    cart_items = []
    unavailable = []

    for item in items:
        search_result = _call_mcp(url, "instamart_search", {
            "query": item,
            "delivery_address": delivery_address,
        })
        products = search_result.get("products", [])
        if products:
            cart_items.append({
                "product_id": products[0]["id"],
                "quantity": 1,
            })
        else:
            unavailable.append(item)

    if not cart_items:
        return OrderResult(
            success=False,
            platform="swiggy_instamart",
            error=f"None of the items found on Instamart: {unavailable}",
        )

    order_result = _call_mcp(url, "instamart_place_order", {
        "cart": cart_items,
        "delivery_address": delivery_address,
    })

    return OrderResult(
        success=order_result.get("status") == "confirmed",
        order_id=order_result.get("order_id"),
        platform="swiggy_instamart",
        items=[i for i in items if i not in unavailable],
        estimated_minutes=order_result.get("eta_minutes"),
        error=(
            f"Unavailable: {unavailable}" if unavailable else order_result.get("error")
        ),
    )


# ---------------------------------------------------------------------------
# Router — dispatches based on MealPlan.decision
# ---------------------------------------------------------------------------

def route_order(
    plan: MealPlan,
    delivery_address: str,
    *,
    dry_run: bool = False,
) -> OrderResult | None:
    """
    Dispatch to the correct Swiggy MCP based on the meal plan decision.

    Returns None when decision is COOK (no order needed).
    """
    if plan.decision == Decision.COOK:
        console.print("[green]Decision: cook at home — no order placed.[/green]")
        return None

    meal_name = plan.recommended_meal.name if plan.recommended_meal else "meal"

    if plan.decision == Decision.ORDER_DISH:
        console.print(f"[bold]Ordering '{meal_name}' from Swiggy Food...[/bold]")
        return order_dish_from_swiggy(meal_name, delivery_address, dry_run=dry_run)

    if plan.decision == Decision.ORDER_GROCERIES:
        missing = (
            plan.recommended_meal.missing_ingredients
            if plan.recommended_meal
            else []
        )
        if not missing:
            console.print("[yellow]order_groceries chosen but no missing ingredients — cooking instead.[/yellow]")
            return None
        console.print(f"[bold]Ordering groceries from Swiggy Instamart:[/bold] {missing}")
        return order_groceries_from_instamart(missing, delivery_address, dry_run=dry_run)

    return None  # unreachable


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------

def display_order_result(result: OrderResult) -> None:
    if result.success:
        console.print(
            Panel(
                f"[bold green]Order confirmed![/bold green]\n"
                f"Order ID : {result.order_id}\n"
                f"Platform : {result.platform}\n"
                f"Items    : {', '.join(result.items)}\n"
                f"ETA      : {result.estimated_minutes} min",
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


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Place an order via Swiggy MCP.")
    p.add_argument(
        "--decision",
        choices=["order_dish", "order_groceries"],
        required=True,
    )
    p.add_argument("--items", required=True, help="Comma-separated items / dish name")
    p.add_argument("--address", default=os.environ.get("DELIVERY_ADDRESS", "Test Address"))
    p.add_argument("--dry-run", action="store_true", default=True, help="Simulate MCP (default: True)")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    items = [i.strip() for i in args.items.split(",") if i.strip()]

    if args.decision == "order_dish":
        result = order_dish_from_swiggy(items[0], args.address, dry_run=args.dry_run)
    else:
        result = order_groceries_from_instamart(items, args.address, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(result.__dict__, indent=2))
    else:
        display_order_result(result)


if __name__ == "__main__":
    main()
