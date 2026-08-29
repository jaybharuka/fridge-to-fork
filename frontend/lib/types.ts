export interface DetectedIngredient { name: string; quantity: string; confidence: number; }
export interface RecipeIngredient {
  name: string; quantity: string; estimated_price_inr: number;
  found_in_fridge: boolean; is_staple: boolean; category?: string;
}
export interface MealSuggestion {
  name: string; description: string; cuisine: string;
  can_cook_now: boolean; missing_ingredients: string[]; prep_time_minutes: number;
}
export interface TopUpSuggestion { name: string; estimated_price?: number; category?: string; }

export type ScanEvent =
  | { type: 'progress'; step: number; message: string }
  | { type: 'step1'; raw_description: string; ingredients: DetectedIngredient[]; source?: string; timed_out?: boolean }
  | { type: 'step2_partial'; text: string }
  | { type: 'step2'; decision: string; recommended_meal: string | null; reasoning: string;
      suggestions: MealSuggestion[]; recipe_ingredients: RecipeIngredient[];
      cooking_steps: string[]; matched_fridge_items: string[] }
  | { type: 'awaiting_user_choice'; reasoning: string; recommended_meal: string | null;
      missing_ingredients: string[]; total_order_price_inr: number }
  | { type: 'top_up'; suggestions: TopUpSuggestion[] }
  | { type: 'complete' }
  | { type: 'cook_confirmed'; message: string }
  | { type: 'step3'; decision: string; placed: boolean; order_id: string | null;
      platform: string | null; items: string[]; eta_minutes: number | null }
  | { type: 'error'; message: string }
  | { type: 'auth_required'; message?: string };

export interface ChecklistItem {
  name: string; quantity: string; estimated_price_inr: number;
  foundInFridge: boolean; isStaple: boolean; checked: boolean;
}
