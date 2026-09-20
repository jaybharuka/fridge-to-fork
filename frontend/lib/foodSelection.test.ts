// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import type { FoodResult } from './food.ts';
import { initialPicks, pickProblem, setQuantity, setVariant, toggleAddon, toSelection } from './foodSelection.ts';

const restaurant = { id: 'r2', name: 'Biryani House', area: null, etaMinutes: 35, etaRange: null, distanceKm: null, rating: 4.1, costForTwo: null, offer: null, open: true };

const plain: FoodResult = {
  menuItemId: 'm-plain', name: 'Butter Chicken', price: 320, isVeg: false, imageUrl: null, rating: null, ratingCount: null, bestseller: false, available: true,
  restaurant: { ...restaurant, id: 'r1', name: 'Punjabi Tadka' },
  customization: { format: null, variantGroups: [], addonGroups: [], supported: true },
};

const bowl: FoodResult = {
  ...plain, menuItemId: 'm-v2', name: 'Butter Chicken Bowl', restaurant,
  customization: {
    format: 'variantsV2', supported: true,
    variantGroups: [{ groupId: 'g-size', name: 'Size', options: [
      { id: 'v-half', name: 'Half', price: 250, default: true, available: true },
      { id: 'v-full', name: 'Full', price: 420, default: false, available: true },
      { id: 'v-xl', name: 'XL', price: 600, default: false, available: false },
    ] }],
    addonGroups: [{ groupId: 'g-extra', name: 'Extras', min: 0, max: 2, choices: [
      { id: 'a-raita', name: 'Raita', price: 30 }, { id: 'a-naan', name: 'Butter Naan', price: 40 }, { id: 'a-salad', name: 'Salad', price: 20 },
    ] }],
  },
};

const required: FoodResult = {
  ...bowl,
  customization: { ...bowl.customization, addonGroups: [{ groupId: 'g-must', name: 'Spice level', min: 1, max: 1, choices: [{ id: 's-mild', name: 'Mild', price: 0 }, { id: 's-hot', name: 'Hot', price: 0 }] }] },
};

describe('initialPicks', () => {
  it("pre-selects Swiggy's own default variant and nothing else", () => {
    assert.deepEqual(initialPicks(bowl), { variants: { 'g-size': 'v-half' }, addons: {}, quantity: 1 });
  });
  it('does not invent a default when Swiggy marks none', () => {
    const noDefault = { ...bowl, customization: { ...bowl.customization, variantGroups: [{ ...bowl.customization.variantGroups[0], options: bowl.customization.variantGroups[0].options.map(o => ({ ...o, default: false })) }] } };
    assert.deepEqual(initialPicks(noDefault).variants, {});
    assert.match(pickProblem(noDefault, initialPicks(noDefault)) ?? '', /Choose size/);
  });
  it('never pre-selects a default that is out of stock', () => {
    const oos = { ...bowl, customization: { ...bowl.customization, variantGroups: [{ ...bowl.customization.variantGroups[0], options: bowl.customization.variantGroups[0].options.map(o => ({ ...o, available: o.id !== 'v-half' })) }] } };
    assert.deepEqual(initialPicks(oos).variants, {});
  });
});

describe('pickProblem', () => {
  it('a plain dish is complete as is', () => {
    assert.equal(pickProblem(plain, initialPicks(plain)), null);
  });
  it('a customizable dish is complete once every variant group has a pick', () => {
    assert.equal(pickProblem(bowl, initialPicks(bowl)), null);
    assert.match(pickProblem(bowl, { ...initialPicks(bowl), variants: {} }) ?? '', /Choose size/);
  });
  it('an out-of-stock variant cannot be chosen', () => {
    assert.match(pickProblem(bowl, setVariant(initialPicks(bowl), 'g-size', 'v-xl')) ?? '', /XL is out of stock/);
  });
  it('a variant id that is not in the group is treated as no pick', () => {
    assert.match(pickProblem(bowl, setVariant(initialPicks(bowl), 'g-size', 'from-another-dish')) ?? '', /Choose size/);
  });
  it('enforces the add-on minimum', () => {
    assert.match(pickProblem(required, initialPicks(required)) ?? '', /at least 1 from Spice level/);
    assert.equal(pickProblem(required, toggleAddon(initialPicks(required), 'g-must', 's-mild', 1)), null);
  });
  it('enforces the add-on maximum even if a caller bypasses toggleAddon', () => {
    const picks = { ...initialPicks(bowl), addons: { 'g-extra': ['a-raita', 'a-naan', 'a-salad'] } };
    assert.match(pickProblem(bowl, picks) ?? '', /at most 2 from Extras/);
  });
  it('an out-of-stock or unsupported dish is never orderable', () => {
    assert.match(pickProblem({ ...plain, available: false }, initialPicks(plain)) ?? '', /out of stock/);
    assert.match(pickProblem({ ...plain, customization: { ...plain.customization, supported: false } }, initialPicks(plain)) ?? '', /Swiggy app/);
  });
});

describe('toggleAddon', () => {
  it('adds, removes, and stops at the group maximum', () => {
    let picks = initialPicks(bowl);
    picks = toggleAddon(picks, 'g-extra', 'a-raita', 2);
    picks = toggleAddon(picks, 'g-extra', 'a-naan', 2);
    picks = toggleAddon(picks, 'g-extra', 'a-salad', 2); // over the max: ignored
    assert.deepEqual(picks.addons['g-extra'], ['a-raita', 'a-naan']);
    picks = toggleAddon(picks, 'g-extra', 'a-raita', 2);
    assert.deepEqual(picks.addons['g-extra'], ['a-naan']);
  });
  it('does not mutate the previous picks', () => {
    const before = initialPicks(bowl);
    toggleAddon(before, 'g-extra', 'a-raita', 2);
    assert.deepEqual(before.addons, {});
  });
  it('a group with no maximum is unbounded', () => {
    let picks = initialPicks(bowl);
    for (const id of ['a', 'b', 'c', 'd']) picks = toggleAddon(picks, 'g-extra', id, null);
    assert.equal(picks.addons['g-extra'].length, 4);
  });
});

describe('setQuantity', () => {
  it('clamps to 1..20 and rejects junk', () => {
    const picks = initialPicks(plain);
    assert.equal(setQuantity(picks, 0).quantity, 1);
    assert.equal(setQuantity(picks, -3).quantity, 1);
    assert.equal(setQuantity(picks, 99).quantity, 20);
    assert.equal(setQuantity(picks, Number.NaN).quantity, 1);
    assert.equal(setQuantity(picks, 2.9).quantity, 2);
  });
});

describe('toSelection', () => {
  it('a plain dish carries only its ids and quantity', () => {
    assert.deepEqual(toSelection(plain, setQuantity(initialPicks(plain), 2)), {
      restaurant_id: 'r1', restaurant_name: 'Punjabi Tadka', menu_item_id: 'm-plain', quantity: 2, format: null, variants: [], addons: [],
    });
  });
  it('variantsV2 keeps its format and every id exactly as returned', () => {
    let picks = setVariant(initialPicks(bowl), 'g-size', 'v-full');
    picks = toggleAddon(picks, 'g-extra', 'a-raita', 2);
    assert.deepEqual(toSelection(bowl, picks), {
      restaurant_id: 'r2', restaurant_name: 'Biryani House', menu_item_id: 'm-v2', quantity: 1, format: 'variantsV2',
      variants: [{ group_id: 'g-size', variation_id: 'v-full' }], addons: [{ group_id: 'g-extra', addon_id: 'a-raita', quantity: 1 }],
    });
  });
  it("legacy `variations` is sent as the cart's `variants`", () => {
    const legacy = { ...bowl, customization: { ...bowl.customization, format: 'variations' as const, addonGroups: [] } };
    assert.equal(toSelection(legacy, initialPicks(legacy)).format, 'variants');
  });
  it('drops picks for groups the dish does not have', () => {
    const picks = { ...initialPicks(bowl), variants: { 'g-size': 'v-half', 'not-a-group': 'x' }, addons: { 'not-a-group': ['y'] } };
    const sel = toSelection(bowl, picks);
    assert.deepEqual(sel.variants, [{ group_id: 'g-size', variation_id: 'v-half' }]);
    assert.deepEqual(sel.addons, []);
  });
});
