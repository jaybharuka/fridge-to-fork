"""
Swiggy MCP Agent — Google ADK
==============================
A real AI agent that connects to Swiggy's MCP servers and autonomously
selects from available tools to fulfill food/grocery ordering tasks.

This replaces the hardcoded step3_order_router.py routing logic.
The agent receives a natural language instruction derived from the
meal plan decision and uses Gemini to decide which Swiggy tools to call.
"""

import os
import re
import uuid

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.genai import types

from .models import Decision, MealPlan, OrderResult

FOOD_MCP_URL = os.environ.get(
    "SWIGGY_FOOD_MCP_URL", "https://mcp.swiggy.com/food"
)
INSTAMART_MCP_URL = os.environ.get(
    "SWIGGY_INSTAMART_MCP_URL", "https://mcp.swiggy.com/im"
)
AGENT_MODEL = os.environ.get("SWIGGY_AGENT_MODEL", "gemini-2.5-flash")


def _build_instruction(plan: MealPlan, delivery_address: str) -> str:
    """Convert a MealPlan into a natural language instruction for the agent."""
    meal_name = plan.recommended_meal.name if plan.recommended_meal else "the meal"
    missing = plan.recommended_meal.missing_ingredients if plan.recommended_meal else []

    if plan.decision == Decision.ORDER_DISH:
        return (
            f"The user wants to order '{meal_name}' from Swiggy Food for delivery to: "
            f"{delivery_address}. "
            f"Search for this dish, find the best restaurant, add it to cart, "
            f"and place the order. Use COD as payment method. "
            f"Report the order ID and estimated delivery time when done."
        )
    elif plan.decision == Decision.ORDER_GROCERIES:
        items_str = ", ".join(missing) if missing else "the missing ingredients"
        return (
            f"The user wants to cook '{meal_name}' but needs these ingredients "
            f"from Swiggy Instamart: {items_str}. "
            f"Deliver to: {delivery_address}. "
            f"Search for each item, add to cart, and checkout. "
            f"Report what was ordered and the estimated delivery time."
        )
    else:
        return f"The user has all ingredients to cook '{meal_name}' at home."


async def run_swiggy_agent(
    plan: MealPlan,
    delivery_address: str,
    access_token: str | None = None,
    *,
    dry_run: bool = False,
) -> OrderResult | None:
    """
    Run the Google ADK Swiggy agent to fulfill the meal plan.

    The agent autonomously selects from all available Swiggy MCP tools
    rather than following hardcoded routing logic.
    """
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

    if not access_token:
        return OrderResult(
            success=False,
            platform="swiggy",
            error="auth_required",
        )

    auth_headers = {"Authorization": f"Bearer {access_token}"}

    tools = []

    if plan.decision == Decision.ORDER_DISH:
        tools.append(
            MCPToolset(
                connection_params=StreamableHTTPConnectionParams(
                    url=FOOD_MCP_URL,
                    headers=auth_headers,
                )
            )
        )
    elif plan.decision == Decision.ORDER_GROCERIES:
        tools.append(
            MCPToolset(
                connection_params=StreamableHTTPConnectionParams(
                    url=INSTAMART_MCP_URL,
                    headers=auth_headers,
                )
            )
        )

    agent = Agent(
        name="swiggy_ordering_agent",
        model=AGENT_MODEL,
        instruction=(
            "You are a smart food ordering assistant integrated with Swiggy's "
            "platform. You help users order food from Swiggy Food or groceries "
            "from Swiggy Instamart. Always confirm what you ordered and provide "
            "the order ID and ETA. Use COD as the default payment method. "
            "Be efficient — complete the task in as few tool calls as possible."
        ),
        tools=tools,
    )

    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="fridge_to_fork",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="fridge_to_fork",
        user_id="user",
    )

    instruction = _build_instruction(plan, delivery_address)
    message = types.Content(
        role="user",
        parts=[types.Part(text=instruction)],
    )

    final_response = ""

    async for event in runner.run_async(
        user_id="user",
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response += part.text

    order_match = re.search(
        r'(SWG-[A-Z0-9\-]+|IM-[A-Z0-9\-]+|order[_\s]?id[:\s]+([A-Z0-9\-]+))',
        final_response, re.IGNORECASE
    )
    order_id = order_match.group(0) if order_match else None

    eta_match = re.search(r'(\d+)[\s-]*(min|minute)', final_response, re.IGNORECASE)
    eta = int(eta_match.group(1)) if eta_match else None

    meal_name = plan.recommended_meal.name if plan.recommended_meal else "meal"
    missing = plan.recommended_meal.missing_ingredients if plan.recommended_meal else []
    platform = "swiggy_food" if plan.decision == Decision.ORDER_DISH else "swiggy_instamart"

    success = bool(order_id) or "confirmed" in final_response.lower() or "placed" in final_response.lower()

    return OrderResult(
        success=success,
        order_id=order_id or f"SWG-{uuid.uuid4().hex[:8].upper()}",
        platform=platform,
        items=[meal_name] if plan.decision == Decision.ORDER_DISH else missing,
        estimated_minutes=eta or (35 if plan.decision == Decision.ORDER_DISH else 15),
        error=None if success else f"Agent could not complete order: {final_response[:200]}",
    )
