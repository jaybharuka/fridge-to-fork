"""Shared data models for the fridge-to-fork pipeline."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    COOK = "cook"
    ORDER_DISH = "order_dish"       # order a ready dish from Swiggy Food
    ORDER_GROCERIES = "order_groceries"  # order missing ingredients from Instamart


@dataclass
class Ingredient:
    name: str
    quantity: Optional[str] = None   # e.g. "2", "half block", "plenty"
    confidence: float = 1.0          # 0–1 from vision model
    # Vision-accuracy overhaul, Phase B (step1_fridge_vision.py's extended
    # scan schema) — all optional/defaulted so every existing construction
    # site (the fallback inventory, tests, step2's synthetic FridgeContents)
    # stays valid unchanged; only identify_ingredients() actually populates
    # these today.
    category: Optional[str] = None          # "produce" | "dairy" | "grain_legume" | "condiment_sauce" | "cooked_food" | "packaged_other"
    estimated_quantity: Optional[dict] = None  # {"type": "count", "value": int, "unit": str} or {"type": "level", "value": str, "unit": None} — always approximate, see step1_fridge_vision.py's prompt
    state: Optional[str] = None             # "fresh" | "packaged" | "cooked" | "opened" | "unknown"
    tier: str = "confirmed"                 # "confirmed" | "probable" | "uncertain" — see step1_fridge_vision._assign_tier(); defaults to "confirmed" so anything constructed without vision data (fallback inventory, tests) doesn't spuriously need review
    needs_confirmation: bool = False        # the model's own admission it's guessing at an exact product/variety — see step1_fridge_vision.py's "NEVER FABRICATE" prompt rule
    possible_matches: list[str] = field(default_factory=list)  # candidate identities when needs_confirmation is true


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
