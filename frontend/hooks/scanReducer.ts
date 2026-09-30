// Pure state/reducer for useScanStream, split out so it can be unit-tested
// (hooks/useScanStream.test.ts) via Node's test runner without pulling in
// React or the fetch-only modules (lib/auth, lib/backend, lib/sse) that
// useScanStream.ts uses for the actual network call — those use extensionless
// value imports that only a bundler (not node --experimental-strip-types)
// can resolve.
import type { ChecklistItem, DetectedIngredient, MealSuggestion, RecipeIngredient, ScanEvent, TopUpSuggestion } from '../lib/types';

/** Shared by step2, SELECT_MEAL and REPLAN_SUCCESS — every place that turns
 *  a dish's recipe_ingredients into the checklist the Order tab renders. */
export function buildChecklist(ingredients: RecipeIngredient[]): ChecklistItem[] {
  return ingredients.map(ing => {
    const foundInFridge = ing.found_in_fridge === true;
    const isStaple = ing.is_staple === true;
    return {
      name: ing.name,
      quantity: ing.quantity,
      estimated_price_inr: ing.estimated_price_inr || 0,
      foundInFridge,
      isStaple,
      checked: foundInFridge || isStaple,
    };
  });
}

export interface ScanState {
  phase: 'idle' | 'loading' | 'photo-scanning' | 'results' | 'error';
  hasPhoto: boolean;
  detectedIngredients: DetectedIngredient[];
  matchedFridgeItems: string[];
  suggestions: MealSuggestion[];
  recommendedMeal: string | null;
  reasoning: string;
  checklist: ChecklistItem[];
  cookingSteps: string[];
  topUpSuggestions: TopUpSuggestion[];
  awaitingChoice: boolean;
  recipeTabUnlocked: boolean;
  /** True while a dish switch's backend call is in flight — the background
   *  top-up refresh after picking an existing suggestion (checklist itself
   *  switches instantly, only top-up needs a fresh call, since it's
   *  dish-specific and was never pre-generated for every suggestion), or
   *  the full /api/replan call for a free-text custom dish. */
  replanPending: boolean;
  /** Set only by a failed custom-dish request — an existing suggestion's
   *  background top-up refresh fails silently (matches the backend's own
   *  "top-up is best-effort, never blocks the main flow" behavior), since
   *  its checklist switch already succeeded locally either way. */
  replanError: string | null;
  /** What a failed scan leaves on screen (ScanStatusCard): an error, or an expired Swiggy session. */
  scanOutcome:
    | null
    | { kind: 'auth_required'; message?: string }
    | { kind: 'error'; message: string };
  scanError: string | null;
  timedOutVision: boolean;
  /** True once the 'step1' event has actually arrived, even if it detected
   *  zero ingredients. Distinguishes "not scanned yet" from "scanned, found
   *  nothing" — both leave `detectedIngredients` as `[]`, so consumers that
   *  need to react only once real (possibly empty) results are in must key
   *  on this, not `detectedIngredients.length`. */
  step1Received: boolean;
}

export type Action =
  | ScanEvent
  | { type: 'SCAN_START'; hasPhoto: boolean }
  | { type: 'TOGGLE_ITEM'; index: number }
  | { type: 'RESET' }
  | {
      type: 'RESTORE';
      recommendedMeal: string;
      reasoning: string;
      checklist: ChecklistItem[];
      topUpSuggestions: TopUpSuggestion[];
    }
  // Picking an already-known suggestion (Meal Suggestions card click) —
  // instant, local, no network call for the checklist itself.
  | { type: 'SELECT_MEAL'; suggestion: MealSuggestion }
  // Free-text custom dish ("or tell us what you'd like to make instead"),
  // and the background top-up refresh SELECT_MEAL triggers — both go
  // through POST /api/replan.
  | { type: 'REPLAN_START' }
  | { type: 'REPLAN_SUCCESS'; suggestion: MealSuggestion; topUpSuggestions: TopUpSuggestion[] }
  | { type: 'REPLAN_ERROR'; message: string }
  // The background top-up-only refresh after SELECT_MEAL failed — clears
  // replanPending without surfacing an error (best-effort, see topUpSuggestions doc comment above).
  | { type: 'REPLAN_TOP_UP_FAILED' };

export const initialState: ScanState = {
  phase: 'idle',
  hasPhoto: false,
  detectedIngredients: [],
  matchedFridgeItems: [],
  suggestions: [],
  recommendedMeal: null,
  reasoning: '',
  checklist: [],
  cookingSteps: [],
  topUpSuggestions: [],
  awaitingChoice: false,
  recipeTabUnlocked: false,
  scanOutcome: null,
  scanError: null,
  timedOutVision: false,
  step1Received: false,
  replanPending: false,
  replanError: null,
};

export function reducer(state: ScanState, action: Action): ScanState {
  switch (action.type) {
    case 'SCAN_START':
      return {
        ...initialState,
        hasPhoto: action.hasPhoto,
        phase: action.hasPhoto ? 'photo-scanning' : 'loading',
      };

    case 'step1':
      // app.py's own 60s vision ceiling (asyncio.wait_for around
      // identify_ingredients()) sends step1 with timed_out: true and an
      // empty ingredients list when Gemini didn't respond in time — that
      // is NOT a real "0 items in your fridge" result, and must not be
      // treated like one (2026-09-30 live incident: a visibly full fridge
      // photo rendered "Nothing detected in your fridge — 0 items
      // detected", a confident wrong claim rather than an honest failure).
      // timedOutVision below was already being set from this field, but
      // nothing ever read it — this is that fix. Reuses the EXACT same
      // mechanism a genuine 'error' event already uses (scanOutcome +
      // phase), rather than inventing a new one: step1Received/
      // detectedIngredients deliberately stay at their pre-scan values, so
      // PhotoScanScreen's own "give way to the error card when step1 never
      // really landed" logic (see app/page.tsx's showPhotoScan comment)
      // applies unchanged, and FridgeSummaryHeader/FridgeChipsDropdown
      // (both keyed on step1Received) never render their "0 detected" UI
      // for this case either.
      if (action.timed_out) {
        return {
          ...state,
          timedOutVision: true,
          phase: state.phase === 'results' ? 'results' : 'error',
          scanOutcome: { kind: 'error', message: "The scan didn't complete. Please try again." },
        };
      }
      return {
        ...state,
        detectedIngredients: action.ingredients,
        timedOutVision: false,
        step1Received: true,
        // A photo scan stays in 'photo-scanning' — the PhotoScanScreen
        // component owns the reveal animation and its own transition to
        // 'results'. Recipe-only mode has no such screen, so go straight
        // to results.
        phase: state.hasPhoto ? state.phase : 'results',
      };

    case 'step2': {
      const checklist = buildChecklist(action.recipe_ingredients);
      return {
        ...state,
        suggestions: action.suggestions,
        recommendedMeal: action.recommended_meal,
        reasoning: action.reasoning,
        cookingSteps: action.cooking_steps,
        matchedFridgeItems: action.matched_fridge_items,
        checklist,
      };
    }

    case 'awaiting_user_choice':
      return {
        ...state,
        reasoning: action.reasoning,
        recommendedMeal: action.recommended_meal || state.recommendedMeal,
        awaitingChoice: true,
        recipeTabUnlocked: true,
      };

    case 'top_up':
      if (!state.suggestions.length) return state;
      return { ...state, topUpSuggestions: action.suggestions, replanPending: false };

    // Clicking a Meal Suggestions card — the suggestion's full recipe
    // already arrived with step2 (see MealSuggestion's recipe_ingredients
    // in lib/types.ts), so the checklist switch is instant and local: no
    // network call, works identically whether switching away from the
    // original recommended dish or back to it. Top-up suggestions ARE
    // dish-specific (generate_top_up_suggestions prompts on the meal's own
    // name + missing_ingredients) and were only ever generated for the
    // previously-active dish, so they're cleared here and refreshed by a
    // background /api/replan call the caller (useScanStream.selectMeal)
    // kicks off right after dispatching this.
    case 'SELECT_MEAL':
      return {
        ...state,
        recommendedMeal: action.suggestion.name,
        checklist: buildChecklist(action.suggestion.recipe_ingredients),
        cookingSteps: action.suggestion.cooking_steps,
        matchedFridgeItems: action.suggestion.matched_fridge_items,
        topUpSuggestions: [],
        replanPending: true,
        replanError: null,
      };

    case 'REPLAN_START':
      return { ...state, replanPending: true, replanError: null };

    // A free-text custom dish came back from /api/replan — same checklist
    // switch as SELECT_MEAL, plus add it to `suggestions` so it's now also
    // clickable/re-selectable like any other suggestion, and its top-up
    // suggestions arrive in the same response (no second request needed).
    case 'REPLAN_SUCCESS': {
      const alreadyKnown = state.suggestions.some(s => s.name === action.suggestion.name);
      return {
        ...state,
        suggestions: alreadyKnown
          ? state.suggestions.map(s => (s.name === action.suggestion.name ? action.suggestion : s))
          : [...state.suggestions, action.suggestion],
        recommendedMeal: action.suggestion.name,
        checklist: buildChecklist(action.suggestion.recipe_ingredients),
        cookingSteps: action.suggestion.cooking_steps,
        matchedFridgeItems: action.suggestion.matched_fridge_items,
        topUpSuggestions: action.topUpSuggestions,
        replanPending: false,
        replanError: null,
      };
    }

    case 'REPLAN_ERROR':
      return { ...state, replanPending: false, replanError: action.message };

    case 'REPLAN_TOP_UP_FAILED':
      return { ...state, replanPending: false };

    case 'complete':
      // app.py deliberately does NOT abort the stream after a step1 vision
      // timeout — it falls through to step2 meal-planning on an empty
      // fridge (the same path "no photo uploaded" recipe-only mode uses)
      // and still reaches its own `yield _sse({"type": "complete"})` 30-90s
      // later. Unconditionally flipping phase to 'results' here silently
      // overwrote the 'error' state the 'step1' case above had just set:
      // phase === 'results' makes app/page.tsx's resultsAlreadyShown true,
      // which downgrades ScanStatusCard from the full "scan didn't
      // complete" card to a barely-visible inline strip — exactly backward,
      // since the fridge was never actually scanned (2026-09-30/10-01 live
      // incident, third in one night). No "recipe found, fridge unknown"
      // state exists in ScanStatusCard today, and app.py's own error paths
      // never send both an error-carrying event and a later 'complete' in
      // the same stream (see app.py's except branches) — so a prior error
      // outcome here is unambiguously this timeout case, and the correct,
      // narrowest fix is the same "honest failure over confident
      // wrong-looking success" principle as the timeout fix itself: leave
      // the error state exactly as 'step1' set it, don't resurrect it into
      // 'results'.
      if (state.scanOutcome?.kind === 'error') return state;
      return { ...state, phase: 'results' };

    case 'error':
      return {
        ...state,
        // The original's error branch calls hideLoadingOverlay() +
        // revealResultsSection() (templates/index.html:4693-4695), so an
        // error must leave 'loading'/'photo-scanning' or the overlay hangs
        // forever. Results that were already on screen stay 'results' —
        // ScanStatusCard keys its inline-vs-full error card off that.
        phase: state.phase === 'results' ? 'results' : 'error',
        scanOutcome: { kind: 'error', message: action.message },
        scanError: action.message,
      };

    case 'auth_required':
      return { ...state, scanOutcome: { kind: 'auth_required', message: action.message } };

    case 'TOGGLE_ITEM':
      return {
        ...state,
        checklist: state.checklist.map((item, i) =>
          i === action.index ? { ...item, checked: !item.checked } : item
        ),
      };

    case 'RESET':
      return initialState;

    // Rehydrates just enough of the Order tab (checklist + top-up
    // suggestions) to reopen the order sheet after the full-page OAuth
    // redirect — see lib/pendingOrder.ts. Recipe tab content (cooking
    // steps, suggestions) intentionally isn't restored: it was never
    // persisted, since the user's goal here is finishing the order, not
    // rereading the recipe.
    case 'RESTORE':
      return {
        ...initialState,
        phase: 'results',
        hasPhoto: false,
        step1Received: true,
        recommendedMeal: action.recommendedMeal,
        reasoning: action.reasoning,
        checklist: action.checklist,
        topUpSuggestions: action.topUpSuggestions,
        awaitingChoice: true,
        recipeTabUnlocked: true,
      };

    // 'progress' and 'step2_partial' don't drive any state the UI reads
    // (matches old handleEvent()'s dead-tracked streamedIngredientNames).
    case 'progress':
    case 'step2_partial':
      return state;

    default:
      return state;
  }
}
