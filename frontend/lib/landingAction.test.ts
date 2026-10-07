// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
// The landing page's two independent, optional inputs (a dish, fridge photos) and what the main button does with them.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { DISABLED_HELP, fridgeHint, hasDish, landingAction, landingMode } from './landingAction.ts';

describe('landingAction: label and enabled state per combination', () => {
  it('nothing: disabled, with the dish-route label', () => {
    assert.deepEqual(landingAction('', 0), { mode: 'empty', label: 'Get recipe', enabled: false });
  });
  it('dish only: recipe', () => {
    assert.deepEqual(landingAction('Paneer Tikka', 0), { mode: 'dish', label: 'Get recipe', enabled: true });
  });
  it('photo only: dishes from the fridge', () => {
    assert.deepEqual(landingAction('', 1), { mode: 'photo', label: 'Find dishes from my fridge', enabled: true });
  });
  it('both: a recipe built around the fridge', () => {
    assert.deepEqual(landingAction('Paneer Tikka', 2), { mode: 'both', label: 'Get recipe using my fridge', enabled: true });
  });
  it('any number of photos (up to the limit of 3) counts the same', () => {
    for (const n of [1, 2, 3]) assert.equal(landingAction('', n).mode, 'photo');
  });
});

describe('a whitespace-only dish is not a dish', () => {
  it('does not enable the button on its own', () => {
    for (const blank of [' ', '   ', '\t', '\n ']) {
      assert.equal(hasDish(blank), false);
      assert.deepEqual(landingAction(blank, 0), { mode: 'empty', label: 'Get recipe', enabled: false });
    }
  });
  it('does not turn a photo-only scan into a "both"', () => {
    assert.equal(landingMode('   ', 1), 'photo');
    assert.equal(landingAction('   ', 1).label, 'Find dishes from my fridge');
  });
  it('a dish with surrounding spaces still counts', () => {
    assert.equal(landingMode('  Poha ', 0), 'dish');
  });
});

describe('the sequence a user actually goes through', () => {
  it('nothing, then a dish, then a photo, then back to nothing after removing both', () => {
    let state = { dish: '', photos: 0 };
    const now = () => landingAction(state.dish, state.photos);
    assert.equal(now().enabled, false);
    state = { ...state, dish: 'Poha' };
    assert.deepEqual([now().mode, now().enabled], ['dish', true]);
    state = { ...state, photos: 1 };
    assert.deepEqual([now().mode, now().label], ['both', 'Get recipe using my fridge']);
    state = { ...state, dish: '' };
    assert.deepEqual([now().mode, now().label], ['photo', 'Find dishes from my fridge']);
    state = { ...state, photos: 0 };
    assert.deepEqual([now().mode, now().enabled], ['empty', false]);
  });
  it('photos added then removed one by one stay enabled until the last is gone', () => {
    assert.equal(landingAction('', 3).enabled, true);
    assert.equal(landingAction('', 2).enabled, true);
    assert.equal(landingAction('', 1).enabled, true);
    assert.equal(landingAction('', 0).enabled, false);
  });
  it('a dish typed and then cleared with a photo present falls back to the photo-only label', () => {
    assert.equal(landingAction('Poha', 1).label, 'Get recipe using my fridge');
    assert.equal(landingAction('', 1).label, 'Find dishes from my fridge');
  });
});

describe('the helper copy', () => {
  it('explains the disabled button', () => {
    assert.equal(DISABLED_HELP, 'Add a dish or a fridge photo to continue.');
  });
  it('the fridge hint follows whether a dish is typed', () => {
    assert.equal(fridgeHint(''), 'Fridge added. Type a dish to cook with it, or just tap Find dishes.');
    assert.equal(fridgeHint('   '), 'Fridge added. Type a dish to cook with it, or just tap Find dishes.');
    assert.equal(fridgeHint('Poha'), "Fridge added. We'll build the recipe around what you have.");
  });
});
