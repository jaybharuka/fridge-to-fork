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


@dataclass
class FridgeContents:
    ingredients: list[Ingredient] = field(default_factory=list)
    raw_description: str = ""        # free-text from vision model


@dataclass
class MealSuggestion:
    name: str
    description: str
    can_cook_now: bool               # True  → all ingredients present
    missing_ingredients: list[str] = field(default_factory=list)
    cuisine: str = ""
    prep_time_minutes: int = 0


@dataclass
class MealPlan:
    suggestions: list[MealSuggestion] = field(default_factory=list)
    decision: Decision = Decision.COOK
    recommended_meal: Optional[MealSuggestion] = None
    reasoning: str = ""


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    platform: str = ""               # "swiggy_food" | "swiggy_instamart"
    items: list[str] = field(default_factory=list)
    estimated_minutes: Optional[int] = None
    error: Optional[str] = None
