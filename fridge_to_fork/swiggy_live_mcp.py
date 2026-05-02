"""
Live Swiggy MCP Server
======================
This server uses the official `mcp` SDK to provide tools for searching Swiggy Food and Instamart.
It scrapes Swiggy's public web APIs to return real data without requiring an OAuth token.

Run this server directly to start stdio communication, or agent.py will launch it.
"""

import json
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# Create a FastMCP server
mcp = FastMCP("Swiggy Live MCP")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Origin": "https://www.swiggy.com",
    "Referer": "https://www.swiggy.com/",
}

# Default coordinates for search (Bangalore as fallback)
DEFAULT_LAT = "12.9715987"
DEFAULT_LNG = "77.5945627"

@mcp.tool()
def swiggy_food_search(query: str, delivery_address: str) -> dict[str, Any]:
    """
    Search for a dish or restaurant on Swiggy Food.
    
    Args:
        query: The dish or restaurant to search for (e.g. "Pizza").
        delivery_address: Human-readable delivery address (currently maps to default coordinates).
    """
    url = "https://www.swiggy.com/dapi/restaurants/search/v3"
    params = {
        "lat": DEFAULT_LAT,
        "lng": DEFAULT_LNG,
        "str": query,
        "trackingId": "null",
        "submitAction": "ENTER"
    }
    
    try:
        with httpx.Client(headers=HEADERS, timeout=10) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json().get("data", {})
    except Exception as e:
        return {"error": f"Failed to fetch from Swiggy API: {str(e)}"}

    restaurants = []
    
    # Traverse Swiggy's complex JSON structure
    for card in data.get("cards", []):
        dish_cards = card.get("groupedCard", {}).get("cardGroupMap", {}).get("DISH", {}).get("cards", [])
        for d in dish_cards:
            dish = d.get("card", {}).get("card", {})
            if "info" in dish and "restaurant" in dish:
                dish_info = dish["info"]
                rest_info = dish["restaurant"].get("info", {})
                
                price = dish_info.get("price", dish_info.get("defaultPrice", 0)) / 100
                
                restaurants.append({
                    "id": rest_info.get("id", "unknown"),
                    "name": rest_info.get("name", "Unknown Restaurant"),
                    "rating": rest_info.get("avgRating", "N/A"),
                    "top_dish": {
                        "id": dish_info.get("id", "unknown"),
                        "name": dish_info.get("name", "Unknown Dish"),
                        "price": price,
                    }
                })
                
                if len(restaurants) >= 5:
                    break
        if restaurants:
            break
            
    return {"restaurants": restaurants}

@mcp.tool()
def swiggy_food_place_order(restaurant_id: str, dish_id: str, delivery_address: str) -> dict[str, Any]:
    """
    Place an order on Swiggy Food. (Simulated for safety)
    """
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
    """
    # Note: Swiggy Instamart's dedicated API (/api/instamart/search) is heavily protected 
    # by AWS WAF which blocks raw Python httpx requests. 
    # To demonstrate a live API integration that reliably works for demos, 
    # we route grocery queries through Swiggy's main Food Search API which returns 
    # real products/dishes from grocery stores without WAF blocks.
    
    url = "https://www.swiggy.com/dapi/restaurants/search/v3"
    params = {
        "lat": DEFAULT_LAT,
        "lng": DEFAULT_LNG,
        "str": query,
        "trackingId": "null",
        "submitAction": "ENTER"
    }
    
    try:
        with httpx.Client(headers=HEADERS, timeout=10) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json().get("data", {})
    except Exception as e:
        return {"error": f"Failed to fetch from Swiggy API: {str(e)}"}

    products = []
    
    # Traverse Swiggy's complex JSON structure for DISH results
    for card in data.get("cards", []):
        dish_cards = card.get("groupedCard", {}).get("cardGroupMap", {}).get("DISH", {}).get("cards", [])
        for d in dish_cards:
            dish = d.get("card", {}).get("card", {})
            if "info" in dish and "restaurant" in dish:
                dish_info = dish["info"]
                rest_info = dish["restaurant"].get("info", {})
                
                price = dish_info.get("price", dish_info.get("defaultPrice", 0)) / 100
                
                products.append({
                    "id": f"IM-{dish_info.get('id', 'unknown')}",
                    "name": f"{dish_info.get('name', 'Unknown Product')} (via {rest_info.get('name', 'Store')})",
                    "price": price,
                    "in_stock": dish_info.get("inStock", 1) == 1
                })
                
                if len(products) >= 5:
                    break
        if products:
            break
            
    # Fallback to simulated data if search yields zero results (rare, but handles weird queries gracefully)
    if not products:
        import random
        base_price = (len(query) * 7) % 150 + 20
        products.append({
            "id": f"IM-{random.randint(10000, 99999)}",
            "name": f"Fresh {query.title()} (Simulated Fallback)",
            "price": base_price,
            "in_stock": True
        })
            
    return {"products": products}

@mcp.tool()
def instamart_place_order(cart: list[dict[str, Any]], delivery_address: str) -> dict[str, Any]:
    """
    Place an order on Swiggy Instamart. (Simulated for safety)
    """
    import uuid
    return {
        "status": "confirmed",
        "order_id": f"SWG-IM-{uuid.uuid4().hex[:8].upper()}",
        "eta_minutes": 15
    }

if __name__ == "__main__":
    mcp.run()
