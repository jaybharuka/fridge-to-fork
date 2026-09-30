"""
Swiggy MCP Agent — Google ADK
==============================
A real AI agent that connects to Swiggy's MCP servers and autonomously
selects from available tools to fulfill food/grocery ordering tasks.

This replaces the hardcoded step3_order_router.py routing logic.
The agent receives a natural language instruction derived from the
meal plan decision and uses Gemini to decide which Swiggy tools to call.
"""

import asyncio
import json
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
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .models import Decision, MealPlan, OrderResult

FOOD_MCP_URL = os.environ.get(
    "SWIGGY_FOOD_MCP_URL", "https://mcp.swiggy.com/food"
)
INSTAMART_MCP_URL = os.environ.get(
    "SWIGGY_INSTAMART_MCP_URL", "https://mcp.swiggy.com/im"
)
DINEOUT_MCP_URL = os.environ.get(
    "SWIGGY_DINEOUT_MCP_URL", "https://mcp.swiggy.com/dineout"
)
AGENT_MODEL = os.environ.get("SWIGGY_AGENT_MODEL", "gemini-2.5-flash")

# ponytail: exact poll cadence isn't in the operate/ docs (rate limits page
# wasn't retrievable in full) — 5s x 6 = 30s is a reasonable guess, tune
# once Swiggy's rate-limit/SLA reference is actually readable.
PAYMENT_POLL_INTERVAL_SECONDS = 5
MAX_PAYMENT_POLLS = 6


def _build_instruction(plan: MealPlan, delivery_address: str) -> str:
    """Convert a MealPlan into a natural language instruction for the agent."""
    meal_name = plan.recommended_meal.name if plan.recommended_meal else "the meal"
    missing = plan.recommended_meal.missing_ingredients if plan.recommended_meal else []

    if plan.decision == Decision.ORDER_DISH:
        return (
            f"You have access to Swiggy Food and Instamart tools. "
            f"The user wants to order '{meal_name}' as a ready-made dish from "
            f"a restaurant. Use Swiggy Food tools to search for this dish, "
            f"find the best restaurant, and place a delivery order to: {delivery_address}. "
            f"Report the order ID and ETA."
        )
    elif plan.decision == Decision.ORDER_GROCERIES:
        items_str = ", ".join(missing) if missing else "the missing ingredients"
        return (
            f"You have access to Swiggy Food and Instamart tools. "
            f"The user wants to cook '{meal_name}' and needs these ingredients: "
            f"{items_str}. Use Swiggy Instamart tools to search for each item, "
            f"add to cart, and checkout for delivery to: {delivery_address}. "
            f"Report what was ordered and the estimated delivery time."
        )
    elif plan.decision == Decision.ADD_TO_CART:
        items_str = ", ".join(missing) if missing else "the requested items"
        return (
            f"You have access to Swiggy Instamart tools. "
            f"The user wants these items added to their Instamart cart: "
            f"{items_str}. Use Swiggy Instamart tools to search for each item "
            f"and add it to the cart. "
            f"Do not check out. Do not place an order. Do not call checkout, "
            f"confirm_order, or any payment/order-placement tool. Only add "
            f"these items to the cart so the user can review and pay "
            f"themselves later. Report which items were successfully added "
            f"to the cart."
        )
    else:
        return f"The user has all ingredients to cook '{meal_name}' at home."


# Decisions the agent is explicitly allowed to complete a real purchase for.
# ADD_TO_CART is deliberately excluded — see _build_instruction() above and
# _agent_system_instruction() below, which scopes the COD-default-payment
# line to only these decisions so it can never bleed into an add-to-cart
# instruction.
_CHECKOUT_CAPABLE_DECISIONS = {Decision.ORDER_DISH, Decision.ORDER_GROCERIES}


def _agent_system_instruction(decision: Decision) -> str:
    """
    The agent's main/system instruction. The COD-default-payment sentence
    only applies when `decision` is one this call is actually allowed to
    check out for — never for ADD_TO_CART, so the agent has no textual
    basis to infer it should also pay/checkout when only asked to add
    items to a cart.
    """
    base = (
        "You are a smart food assistant integrated with Swiggy's full platform. "
        "You have access to Swiggy Food (restaurant delivery), Swiggy Instamart "
        "(grocery delivery), and Swiggy Dineout (table reservations) tools. "
        "Choose the right platform and tools based on the user's request. "
        "Always confirm what you did and provide the confirmation ID (if an "
        "order was placed) or a summary (if not)."
    )
    if decision in _CHECKOUT_CAPABLE_DECISIONS:
        return (
            base
            + " Use COD as the default payment method for orders you are "
            "explicitly instructed to place."
        )
    return (
        base
        + " For this request you are NOT authorized to check out, place an "
        "order, or make any payment — follow the user instruction's own "
        "scope exactly, even if a tool to check out is available to you."
    )


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
        # ADD_TO_CART never places an order — no order_id, no ETA, and the
        # fabricated success only claims items were added to the cart.
        if plan.decision == Decision.ADD_TO_CART:
            return OrderResult(
                success=True,
                order_id=None,
                platform=platform,
                items=missing,
                estimated_minutes=None,
            )
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

    platform = "swiggy_food" if plan.decision == Decision.ORDER_DISH else "swiggy_instamart"

    auth_headers = {"Authorization": f"Bearer {access_token}"}

    tools = [
        MCPToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=FOOD_MCP_URL,
                headers=auth_headers,
            )
        ),
        MCPToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=INSTAMART_MCP_URL,
                headers=auth_headers,
            )
        ),
        MCPToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=DINEOUT_MCP_URL,
                headers=auth_headers,
            )
        ),
    ]

    agent = Agent(
        name="swiggy_ordering_agent",
        model=AGENT_MODEL,
        instruction=_agent_system_instruction(plan.decision),
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

    try:
        async for event in runner.run_async(
            user_id="user",
            session_id=session.id,
            new_message=message,
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if part.text:
                        final_response += part.text
    except Exception as e:
        err_str = str(e).lower()
        if any(x in err_str for x in ["401", "32001", "unauthorized", "unauthenticated", "token"]):
            return OrderResult(
                success=False,
                platform=platform,
                error="auth_required",
            )
        return OrderResult(
            success=False,
            platform=platform,
            error=f"Agent error: {str(e)[:200]}",
        )

    order_match = re.search(
        r'(SWG-[A-Z0-9\-]+|IM-[A-Z0-9\-]+|order[_\s]?id[:\s]+([A-Z0-9\-]+))',
        final_response, re.IGNORECASE
    )
    order_id = order_match.group(0) if order_match else None

    eta_match = re.search(r'(\d+)[\s-]*(min|minute)', final_response, re.IGNORECASE)
    eta = int(eta_match.group(1)) if eta_match else None

    meal_name = plan.recommended_meal.name if plan.recommended_meal else "meal"
    missing = plan.recommended_meal.missing_ingredients if plan.recommended_meal else []

    # ADD_TO_CART is never allowed to look like a placed order downstream —
    # judged on "added"/"cart" language, never on the checkout-oriented
    # "confirmed"/"placed" keywords below, and never carries a fabricated
    # SWG- order_id or an ETA (nothing was ordered, so nothing is arriving).
    if plan.decision == Decision.ADD_TO_CART:
        resp_lower = final_response.lower()
        if any(x in resp_lower for x in ["401", "unauthorized", "unauthenticated", "token expired"]):
            return OrderResult(success=False, platform=platform, error="auth_required")
        added = "added" in resp_lower or "cart" in resp_lower
        return OrderResult(
            success=added,
            order_id=None,
            platform=platform,
            items=missing,
            estimated_minutes=None,
            error=None if added else f"Agent could not add items to cart: {final_response[:200]}",
        )

    success = bool(order_id) or "confirmed" in final_response.lower() or "placed" in final_response.lower()

    if not success:
        resp_lower = final_response.lower()
        if any(x in resp_lower for x in ["401", "unauthorized", "unauthenticated", "token expired"]):
            return OrderResult(
                success=False,
                platform=platform,
                error="auth_required",
            )

    return OrderResult(
        success=success,
        order_id=order_id or f"SWG-{uuid.uuid4().hex[:8].upper()}",
        platform=platform,
        items=[meal_name] if plan.decision == Decision.ORDER_DISH else missing,
        estimated_minutes=eta or (35 if plan.decision == Decision.ORDER_DISH else 15),
        error=None if success else f"Agent could not complete order: {final_response[:200]}",
    )


# ---------------------------------------------------------------------------
# Deterministic Instamart flow — explicit MCP call sequence, no agent/regex.
#
# Tool names and the argument keys below follow the documented tool
# catalogue (mcp.swiggy.com/builders/docs/reference/instamart/). The
# overview page lists tool names and categories but not per-tool parameter
# schemas (those live on individual /reference/instamart/<tool>/ pages that
# weren't fetchable at implementation time) — so argument keys are
# best-effort based on tool descriptions, not confirmed field-by-field.
# Re-verify against the live per-tool docs before a real order.
#
# Swiggy Food doesn't have a confirmed tool catalogue yet, so
# run_swiggy_agent() above stays as-is for the "order the dish" path. Give
# it the same deterministic treatment once Food's MCP reference is available.
# ---------------------------------------------------------------------------


async def _call_tool(session: ClientSession, name: str, **arguments) -> dict:
    """Call one MCP tool and return its structured result as a dict."""
    result = await session.call_tool(name, arguments)
    if result.isError:
        text = "; ".join(getattr(c, "text", "") for c in result.content)
        try:
            await session.call_tool(
                "report_error", {"tool": name, "message": text[:300]}
            )
        except Exception:
            pass
        raise RuntimeError(f"{name} failed: {text[:200]}")

    if result.structuredContent is not None:
        return result.structuredContent
    for c in result.content:
        text = getattr(c, "text", None)
        if text:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"text": text}
    return {}


async def _resolve_address(session: ClientSession) -> str | None:
    """Return a saved address id, or None. Never fabricates address data."""
    addresses = await _call_tool(session, "get_addresses")
    addr_list = addresses.get("addresses") or addresses.get("data") or []
    if not addr_list:
        return None
    return addr_list[0].get("id") or addr_list[0].get("address_id")


async def _resolve_products(
    session: ClientSession, missing_ingredients: list[str], address_id: str
) -> tuple[list[dict], list[str]]:
    """search_products per item; top match wins, misses go to not_found."""
    resolved, not_found = [], []
    for item in missing_ingredients:
        found = await _call_tool(
            session, "search_products", query=item, address_id=address_id
        )
        products = found.get("products") or found.get("results") or []
        if not products:
            not_found.append(item)
            continue
        top = products[0]
        product_id = top.get("product_id") or top.get("id")
        resolved.append({"product_id": product_id, "name": top.get("name", item)})
    return resolved, not_found


async def _finalize_checkout(session: ClientSession, checkout: dict) -> dict:
    """Handle checkout's PENDING_PAYMENT (UPI) path via check_payment_status."""
    if checkout.get("status") != "PENDING_PAYMENT":
        return checkout

    order_id = checkout.get("order_id")
    for _ in range(MAX_PAYMENT_POLLS):
        await asyncio.sleep(PAYMENT_POLL_INTERVAL_SECONDS)
        payment = await _call_tool(session, "check_payment_status", order_id=order_id)
        status = payment.get("status")
        if status == "SUCCESS":
            return await _call_tool(session, "confirm_order", order_id=order_id)
        if status == "FAILED":
            return {"status": "FAILED", "order_id": order_id}
    return {"status": "TIMED_OUT", "order_id": order_id}


async def _run_instamart_sequence(
    session: ClientSession, missing_ingredients: list[str]
) -> OrderResult:
    address_id = await _resolve_address(session)
    if address_id is None:
        return OrderResult(
            success=False,
            platform="swiggy_instamart",
            error="No saved delivery address on this Swiggy account",
        )

    resolved, not_found = await _resolve_products(
        session, missing_ingredients, address_id
    )
    if not resolved:
        return OrderResult(
            success=False,
            platform="swiggy_instamart",
            error="No items could be matched to Instamart products",
            not_found=not_found,
        )

    await _call_tool(
        session,
        "update_cart",
        items=[{"product_id": p["product_id"], "quantity": 1} for p in resolved],
    )
    cart = await _call_tool(session, "get_cart")
    await _call_tool(session, "get_payment_options")

    checkout = await _call_tool(session, "checkout")
    order = await _finalize_checkout(session, checkout)

    status = order.get("status")
    success = status in ("CONFIRMED", "SUCCESS", "PLACED")
    return OrderResult(
        success=success,
        order_id=order.get("order_id"),
        platform="swiggy_instamart",
        items=[p["name"] for p in resolved],
        estimated_minutes=order.get("eta_minutes") or cart.get("eta_minutes"),
        error=None if success else f"checkout status: {status}",
        not_found=not_found,
    )


def _dry_run_instamart_result(missing_ingredients: list[str]) -> OrderResult:
    return OrderResult(
        success=True,
        order_id=f"SWG-{uuid.uuid4().hex[:8].upper()}",
        platform="swiggy_instamart",
        items=list(missing_ingredients),
        estimated_minutes=15,
    )


async def order_from_instamart_mcp(
    missing_ingredients: list[str],
    access_token: str | None,
    delivery_address: str | None = None,
    *,
    dry_run: bool = False,
) -> OrderResult:
    """
    Deterministic Instamart ordering: explicit MCP tool call sequence
    (get_addresses -> search_products -> update_cart -> get_cart ->
    get_payment_options -> checkout [-> check_payment_status -> confirm_order]),
    replacing the autonomous-agent/regex-parsing approach for this flow.

    `delivery_address` is currently unused beyond address resolution via
    get_addresses (see _resolve_address) — Instamart tools take an
    address_id from the account's saved addresses, not a free-text address,
    per the docs. Kept as a parameter for API-shape parity / future use
    (e.g. matching against a specific saved address).
    """
    if not missing_ingredients:
        return OrderResult(success=True, platform="swiggy_instamart", items=[])

    if dry_run:
        return _dry_run_instamart_result(missing_ingredients)

    if not access_token:
        return OrderResult(success=False, platform="swiggy_instamart", error="auth_required")

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with streamablehttp_client(INSTAMART_MCP_URL, headers=headers) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await _run_instamart_sequence(session, missing_ingredients)
    except Exception as e:
        err_str = str(e).lower()
        if any(x in err_str for x in ["401", "unauthorized", "unauthenticated", "token"]):
            return OrderResult(success=False, platform="swiggy_instamart", error="auth_required")
        return OrderResult(
            success=False,
            platform="swiggy_instamart",
            error=f"MCP error: {str(e)[:200]}",
        )
