export interface DetectedIngredient { name: string; quantity: string; confidence: number; }
export interface RecipeIngredient {
  name: string; quantity: string; estimated_price_inr: number;
  found_in_fridge: boolean; is_staple: boolean; category?: string;
}
export interface MealSuggestion {
  name: string; description: string; cuisine: string;
  can_cook_now: boolean; missing_ingredients: string[]; prep_time_minutes: number;
  // Full recipe for this specific suggestion — step2_meal_planner.py's one
  // meal-planning call already generates these for every suggestion, not
  // just the recommended one, so picking a different suggestion can build
  // its checklist instantly, no new request needed.
  recipe_ingredients: RecipeIngredient[];
  cooking_steps: string[];
  total_order_price_inr: number;
  matched_fridge_items: string[];
}
export interface TopUpSuggestion { name: string; estimated_price?: number; category?: string; }

export type ScanEvent =
  | { type: 'progress'; step: number; message: string }
  | { type: 'step1'; raw_description: string; ingredients: DetectedIngredient[]; source?: string; timed_out?: boolean;
      /** Early items the final merge replaced with a higher-confidence variant (absent when none). */
      early_superseded?: { from: string; to: string }[] }
  /** Cumulative pass-1 items ("first look"), once per photo while pass 2 still runs; photo_index is 1-based. Additive only. */
  | { type: 'step1_partial'; ingredients: DetectedIngredient[]; photo_index: number; photo_count: number }
  | { type: 'step2_partial'; text: string }
  | { type: 'step2'; decision: string; recommended_meal: string | null; reasoning: string;
      suggestions: MealSuggestion[]; recipe_ingredients: RecipeIngredient[];
      cooking_steps: string[]; matched_fridge_items: string[] }
  | { type: 'awaiting_user_choice'; reasoning: string; recommended_meal: string | null;
      missing_ingredients: string[]; total_order_price_inr: number }
  | { type: 'top_up'; suggestions: TopUpSuggestion[] }
  | { type: 'complete' }
  | { type: 'error'; message: string }
  | { type: 'auth_required'; message?: string };

export interface ChecklistItem {
  name: string; quantity: string; estimated_price_inr: number;
  foundInFridge: boolean; isStaple: boolean; checked: boolean;
}
