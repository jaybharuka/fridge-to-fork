"""
Live Swiggy MCP Server
======================
This server uses the official Swiggy MCP SDK to provide tools for searching Swiggy Food and Instamart.

Note: This is a placeholder integration awaiting official MCP API credentials from Swiggy.
Once credentials are provided, this will be updated to use the official Swiggy MCP Food, Instamart,
and Dineout endpoints.

Run this server directly to start stdio communication, or agent.py will launch it.
"""

from typing import Any
import uuid

from mcp.server.fastmcp import FastMCP

# Create a FastMCP server
mcp = FastMCP("Swiggy Live MCP")

@mcp.tool()
def swiggy_food_search(query: str, delivery_address: str) -> dict[str, Any]:
    """
    Search for a dish or restaurant on Swiggy Food.
    
    Args:
        query: The dish or restaurant to search for (e.g. "Pizza").
        delivery_address: Human-readable delivery address for the search.
    
    NOTE: This is a placeholder implementation awaiting official Swiggy MCP API credentials.
    Once credentials are obtained, this will call: https://api.mcp.swiggy.com/food/search
    with proper authentication headers and return real search results.
    """
    # Demo stub: return a deterministic simulated result so the UI can exercise
    # the confirmed-order path while official Swiggy credentials are pending.
    dish_name = query.strip().title() or "Chef Special"
    return {
        "status": "ok",
        "restaurants": [
            {
                "id": f"rest-{uuid.uuid4().hex[:8]}",
                "name": f"Demo Kitchen for {dish_name}",
                "top_dish": {
                    "id": f"dish-{uuid.uuid4().hex[:8]}",
                    "name": dish_name,
                    "price": 249,
                },
            }
        ],
    }

@mcp.tool()
def swiggy_food_place_order(restaurant_id: str, dish_id: str, delivery_address: str) -> dict:
    """Place an order on Swiggy Food. Simulated pending official MCP credentials."""
    import uuid
    return {
        "status": "confirmed",
        "order_id": f"SWG-FOOD-{uuid.uuid4().hex[:8].upper()}",
        "eta_minutes": 35
    }

@mcp.tool()
def instamart_search(query: str, delivery_address: str) -> dict[str, Any]:
    """
    Search for grocery items on Swiggy Instamart.
    
    Args:
        query: The item to search for (e.g. "tomato").
        delivery_address: Human-readable delivery address.
    
    NOTE: This is a placeholder implementation awaiting official Swiggy MCP API credentials.
    Once credentials are obtained, this will call: https://api.mcp.swiggy.com/instamart/search
    with proper authentication headers and return real product inventory.
    """
    # Demo stub: return a deterministic simulated product result so grocery
    # ordering can complete in the UI without real Swiggy credentials.
    product_name = query.strip().lower() or "item"
    return {
        "status": "ok",
        "products": [
            {
                "id": f"prod-{uuid.uuid4().hex[:8]}",
                "name": product_name,
                "price": 99,
            }
        ],
    }

@mcp.tool()
def instamart_place_order(cart: list, delivery_address: str) -> dict:
    """Place an order on Swiggy Instamart. Simulated pending official MCP credentials."""
    import uuid
    return {
        "status": "confirmed",
        "order_id": f"SWG-IM-{uuid.uuid4().hex[:8].upper()}",
        "eta_minutes": 15
    }

if __name__ == "__main__":
    mcp.run()
