"""Shared data models for the fridge-to-fork pipeline."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    COOK = "cook"
    ORDER_DISH = "order_dish"       # order a ready dish from Swiggy Food
    ORDER_GROCERIES = "order_groceries"  # order missing ingredients from Instamart
    # Add items to the Instamart cart only — explicitly NOT checkout-capable.
    # See swiggy_agent._build_instruction(): the instruction text for this
    # decision must never mention checkout/place order/COD (security-review
    # fix — ORDER_GROCERIES's checkout instruction was previously the only
    # option available to the cart-fill "Add" flow, see app.py cart_fill()).
    ADD_TO_CART = "add_to_cart"


@dataclass
class Ingredient:
    name: str
    quantity: Optional[str] = None   # e.g. "2", "half block", "plenty"
    confidence: float = 1.0          # 0–1 from vision model


@dataclass
class FridgeContents:
    ingredients: list[Ingredient] = field(default_factory=list)
    raw_description: str = ""        # free-text from vision model


@dataclass
class RecipeIngredient:
    name: str
    quantity: str
    estimated_price_inr: int = 0
    found_in_fridge: bool = False     # fuzzy-matched against a scanned fridge photo
    is_staple: bool = False           # assumed available regardless of fridge photo
    # AI-classified by Gemini per-ingredient (see step2_meal_planner._safe_category):
    # "staple" | "specialty" | "perishable". Drives is_staple/found_in_fridge above.
    category: str = "specialty"


@dataclass
class MealSuggestion:
    name: str
    description: str
    can_cook_now: bool               # True  → all ingredients present
    missing_ingredients: list[str] = field(default_factory=list)
    cuisine: str = ""
    prep_time_minutes: int = 0
    recipe_ingredients: list[RecipeIngredient] = None
    cooking_steps: list[str] = field(default_factory=list)
    total_order_price_inr: int = 0


@dataclass
class MealPlan:
    suggestions: list[MealSuggestion] = field(default_factory=list)
    decision: Decision = Decision.COOK
    recommended_meal: Optional[MealSuggestion] = None
    reasoning: str = ""
    # Names of scanned fridge items (exact detected names, not recipe
    # ingredient names) that are actually used by recommended_meal —
    # fuzzy-matched deterministically in _enrich_recipe_ingredients(),
    # same matcher as found_in_fridge, not self-reported by the LLM.
    matched_fridge_items: list[str] = field(default_factory=list)


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    platform: str = ""               # "swiggy_food" | "swiggy_instamart"
    items: list[str] = field(default_factory=list)
    estimated_minutes: Optional[int] = None
    error: Optional[str] = None
    not_found: list[str] = field(default_factory=list)  # missing_ingredients with no product match
