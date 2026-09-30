// Run: npm test   (node --experimental-strip-types --test hooks/*.test.ts lib/*.test.ts)
//
// Tests for the "switch the active dish" feature (2026-10-01): picking a
// different Meal Suggestions card, or a free-text custom dish, without
// re-scanning the fridge photo. See scanReducer.ts's SELECT_MEAL/
// REPLAN_START/REPLAN_SUCCESS/REPLAN_ERROR/REPLAN_TOP_UP_FAILED cases.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { buildChecklist, initialState, reducer } from './scanReducer.ts';
import type { MealSuggestion, RecipeIngredient } from '../lib/types.ts';

function ri(overrides: Partial<RecipeIngredient> = {}): RecipeIngredient {
  return {
    name: 'chicken', quantity: '500g', estimated_price_inr: 200,
    found_in_fridge: false, is_staple: false, category: 'perishable',
    ...overrides,
  };
}

function meal(overrides: Partial<MealSuggestion> = {}): MealSuggestion {
  return {
    name: 'Butter Chicken', description: 'Creamy tomato curry.', cuisine: 'Indian',
    can_cook_now: false, missing_ingredients: ['chicken'], prep_time_minutes: 40,
    recipe_ingredients: [ri()], cooking_steps: ['Marinate the chicken.', 'Cook the gravy.'],
    total_order_price_inr: 200, matched_fridge_items: ['butter'],
    ...overrides,
  };
}

const recommended = meal();
const alternative = meal({
  name: 'Paneer Tikka', description: 'Grilled paneer skewers.', cuisine: 'Indian',
  missing_ingredients: ['paneer'],
  recipe_ingredients: [ri({ name: 'paneer', found_in_fridge: false })],
  cooking_steps: ['Marinate the paneer.', 'Grill it.'],
  total_order_price_inr: 120, matched_fridge_items: [],
});

const resultsState = {
  ...initialState,
  phase: 'results' as const,
  suggestions: [recommended, alternative],
  recommendedMeal: recommended.name,
  checklist: buildChecklist(recommended.recipe_ingredients),
  cookingSteps: recommended.cooking_steps,
  matchedFridgeItems: recommended.matched_fridge_items,
  topUpSuggestions: [{ name: 'Garlic Naan' }],
};

describe('buildChecklist', () => {
  it('checks off staples and found-in-fridge items, leaves genuinely missing ones unchecked', () => {
    const checklist = buildChecklist([
      ri({ name: 'butter', is_staple: true, found_in_fridge: false }),
      ri({ name: 'tomato', is_staple: false, found_in_fridge: true }),
      ri({ name: 'chicken', is_staple: false, found_in_fridge: false }),
    ]);
    assert.deepEqual(checklist.map(c => [c.name, c.checked]), [
      ['butter', true],
      ['tomato', true],
      ['chicken', false],
    ]);
  });
});

describe('scanReducer — SELECT_MEAL (picking an existing suggestion)', () => {
  it('switches the checklist/cooking steps/matched items instantly from the suggestion itself, no network call needed', () => {
    const result = reducer(resultsState, { type: 'SELECT_MEAL', suggestion: alternative });

    assert.equal(result.recommendedMeal, 'Paneer Tikka');
    assert.deepEqual(result.cookingSteps, alternative.cooking_steps);
    assert.deepEqual(result.matchedFridgeItems, alternative.matched_fridge_items);
    assert.equal(result.checklist.length, 1);
    assert.equal(result.checklist[0].name, 'paneer');
  });

  it('clears stale top-up suggestions (they are dish-specific) and marks a refresh pending', () => {
    const result = reducer(resultsState, { type: 'SELECT_MEAL', suggestion: alternative });
    assert.deepEqual(result.topUpSuggestions, []);
    assert.equal(result.replanPending, true);
  });

  it('switching back to the original recommended dish works the same instant way, not just by coincidence', () => {
    const switchedAway = reducer(resultsState, { type: 'SELECT_MEAL', suggestion: alternative });
    const switchedBack = reducer(switchedAway, { type: 'SELECT_MEAL', suggestion: recommended });

    assert.equal(switchedBack.recommendedMeal, recommended.name);
    assert.deepEqual(switchedBack.checklist, buildChecklist(recommended.recipe_ingredients));
    assert.deepEqual(switchedBack.cookingSteps, recommended.cooking_steps);
    assert.deepEqual(switchedBack.matchedFridgeItems, recommended.matched_fridge_items);
    // Exactly the state a fresh switch to `recommended` would produce —
    // round-tripping isn't a special case, it's the same SELECT_MEAL path.
    assert.deepEqual(switchedBack, reducer(resultsState, { type: 'SELECT_MEAL', suggestion: recommended }));
  });
});

describe('scanReducer — top_up also settles a pending SELECT_MEAL refresh', () => {
  it('clears replanPending when the background top-up refresh succeeds', () => {
    const pending = reducer(resultsState, { type: 'SELECT_MEAL', suggestion: alternative });
    const settled = reducer(pending, { type: 'top_up', suggestions: [{ name: 'Mint Chutney' }] });

    assert.equal(settled.replanPending, false);
    assert.deepEqual(settled.topUpSuggestions, [{ name: 'Mint Chutney' }]);
  });
});

describe('scanReducer — REPLAN_TOP_UP_FAILED', () => {
  it('clears replanPending silently, without surfacing an error (best-effort, matches the backend)', () => {
    const pending = reducer(resultsState, { type: 'SELECT_MEAL', suggestion: alternative });
    const settled = reducer(pending, { type: 'REPLAN_TOP_UP_FAILED' });

    assert.equal(settled.replanPending, false);
    assert.equal(settled.replanError, null);
    // The checklist switch already happened locally and must not be undone.
    assert.equal(settled.recommendedMeal, 'Paneer Tikka');
  });
});

describe('scanReducer — free-text custom dish (REPLAN_START/SUCCESS/ERROR)', () => {
  it('REPLAN_START marks pending and clears any previous error', () => {
    const withError = { ...resultsState, replanError: 'previous failure' };
    const result = reducer(withError, { type: 'REPLAN_START' });
    assert.equal(result.replanPending, true);
    assert.equal(result.replanError, null);
  });

  it('REPLAN_SUCCESS for a genuinely new dish appends it to suggestions and makes it active', () => {
    const custom = meal({ name: 'Mushroom Risotto', recipe_ingredients: [ri({ name: 'mushroom' })] });
    const pending = reducer(resultsState, { type: 'REPLAN_START' });
    const result = reducer(pending, { type: 'REPLAN_SUCCESS', suggestion: custom, topUpSuggestions: [{ name: 'Parmesan' }] });

    assert.equal(result.suggestions.length, 3);
    assert.equal(result.suggestions[2].name, 'Mushroom Risotto');
    assert.equal(result.recommendedMeal, 'Mushroom Risotto');
    assert.deepEqual(result.topUpSuggestions, [{ name: 'Parmesan' }]);
    assert.equal(result.replanPending, false);
    assert.equal(result.replanError, null);
  });

  it('REPLAN_SUCCESS for a dish that already matches an existing suggestion replaces it rather than duplicating', () => {
    const updated = meal({ ...recommended, total_order_price_inr: 999 });
    const result = reducer(resultsState, { type: 'REPLAN_SUCCESS', suggestion: updated, topUpSuggestions: [] });

    assert.equal(result.suggestions.length, 2);
    assert.equal(result.suggestions.find(s => s.name === recommended.name)?.total_order_price_inr, 999);
  });

  it('REPLAN_ERROR leaves the current dish/checklist untouched and surfaces the message', () => {
    const pending = reducer(resultsState, { type: 'REPLAN_START' });
    const result = reducer(pending, { type: 'REPLAN_ERROR', message: "Couldn't plan that dish. Please try again." });

    assert.equal(result.replanPending, false);
    assert.equal(result.replanError, "Couldn't plan that dish. Please try again.");
    assert.equal(result.recommendedMeal, recommended.name);
    assert.deepEqual(result.checklist, resultsState.checklist);
  });
});
