"""
Swiggy order hand-off for the CLI (`fridge-to-fork`, fridge_to_fork/agent.py).

This used to be a Google ADK / Gemini agent that picked Swiggy MCP tools on its own. It invented order IDs and read
success or failure out of free text, so it was retired: real orders are placed only by the deterministic, staged flows
that show the user the real cart before any money moves:

  * groceries -> fridge_to_fork/instamart.py
  * the dish  -> fridge_to_fork/food.py

What is left is the offline simulation the CLI's --dry-run uses (no network, no Swiggy) and refusals that point at
those flows.
"""

import uuid

from .models import Decision, MealPlan, OrderResult


async def run_swiggy_agent(
    plan: MealPlan,
    delivery_address: str,
    access_token: str | None = None,
    *,
    dry_run: bool = False,
) -> OrderResult | None:
    """Simulate (dry_run) or refuse. Never contacts Swiggy and never places an order."""
    if plan.decision == Decision.COOK:
        return None

    if dry_run:
        meal_name = plan.recommended_meal.name if plan.recommended_meal else "meal"
        missing = plan.recommended_meal.missing_ingredients if plan.recommended_meal else []
        platform = "swiggy_food" if plan.decision == Decision.ORDER_DISH else "swiggy_instamart"
        return OrderResult(
            success=True,
            order_id=f"SWG-{uuid.uuid4().hex[:8].upper()}",
            platform=platform,
            items=[meal_name] if plan.decision == Decision.ORDER_DISH else missing,
            estimated_minutes=35 if plan.decision == Decision.ORDER_DISH else 15,
        )

    if plan.decision == Decision.ORDER_GROCERIES:
        return OrderResult(
            success=False,
            platform="swiggy_instamart",
            error="Instamart orders use the staged flow in fridge_to_fork.instamart",
        )

    return OrderResult(
        success=False,
        platform="swiggy_food",
        error="Food orders use the staged flow in fridge_to_fork.food",
    )
