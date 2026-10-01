// What the user has picked for one Food dish, and whether it is complete enough to put in the cart.
//
// Pure (no React, no network) so the rules can be unit tested in plain Node — see foodSelection.test.ts.
// Nothing is defaulted silently: Swiggy's own "default" option is pre-selected so it is visible on screen, and
// every variant group must still have a pick before the cart is built. Add-ons are optional within min/max.

import type { AddonGroup, FoodResult, FoodSelection } from './food';

export interface Picks {
  /** groupId -> chosen variation id */
  variants: Record<string, string>;
  /** groupId -> chosen add-on ids */
  addons: Record<string, string[]>;
  quantity: number;
}

export const MAX_QUANTITY = 20;

/**
 * Swiggy models "the item you picked" as a required add-on group with one free choice (Burger King: "Selected Burger -
 * Chicken Makhani Burst Burger" / "Selected - Chicken Makhani Burst Burger", ₹0). It isn't a decision. Deliberately
 * narrow: exactly one choice, priced exactly 0 (an unknown price is not assumed free) and in stock; anything else, such as
 * two free sizes, a ₹10 choice or an out-of-stock one, is a real requirement.
 */
export function isPlaceholderGroup(group: AddonGroup): boolean {
  const [only] = group.choices;
  return group.choices.length === 1 && only.price === 0 && only.available;
}

/**
 * The dish after its add-ons were loaded from Swiggy's cart. Swiggy's cart refuses EVERY add-on request we could build
 * (INVALID_ADDON, ~30 shapes, two restaurants, a nonsense control failed identically), so add-ons are never offered:
 *  - all groups optional (the only case seen so far): orderable as listed, with a note that add-ons can't be set here;
 *  - a required group with real choices (minAddons > 0, e.g. a size): can't be ordered without a pick, so it stays the
 *    "order it in the Swiggy app" dead end;
 *  - a required group that is only a placeholder (see isPlaceholderGroup) doesn't count: a real Burger King cart with it
 *    unselected reviewed with no blockers (canCheckout true, 2026-10-02), though no order has been placed that way.
 * Putting the groups back into `addonGroups` re-enables the picker once Swiggy accepts them.
 */
export function withLoadedOptions(result: FoodResult, addonGroups: AddonGroup[]): FoodResult {
  const required = addonGroups.some(g => g.min > 0 && !isPlaceholderGroup(g));
  return {
    ...result,
    customization: { ...result.customization, addonGroups: [], supported: !required, optionsOnDemand: false, addonsUnavailable: !required && addonGroups.length > 0 },
  };
}

/** Start from Swiggy's default variant of each group (shown selected on screen), no add-ons, quantity 1. */
export function initialPicks(result: FoodResult): Picks {
  const variants: Record<string, string> = {};
  for (const group of result.customization.variantGroups) {
    const chosen = group.options.find(o => o.default && o.available);
    if (chosen) variants[group.groupId] = chosen.id;
  }
  return { variants, addons: {}, quantity: 1 };
}

export function setVariant(picks: Picks, groupId: string, optionId: string): Picks {
  return { ...picks, variants: { ...picks.variants, [groupId]: optionId } };
}

/** Toggle one add-on. Turning one on beyond the group's max is ignored (the UI disables it too). */
export function toggleAddon(picks: Picks, groupId: string, addonId: string, max: number | null): Picks {
  const current = picks.addons[groupId] ?? [];
  if (current.includes(addonId)) return { ...picks, addons: { ...picks.addons, [groupId]: current.filter(id => id !== addonId) } };
  if (max !== null && current.length >= max) return picks;
  return { ...picks, addons: { ...picks.addons, [groupId]: [...current, addonId] } };
}

export function setQuantity(picks: Picks, quantity: number): Picks {
  return { ...picks, quantity: Math.min(Math.max(Math.trunc(quantity) || 1, 1), MAX_QUANTITY) };
}

/** Why this pick can't go in the cart yet, or null when it is complete. */
export function pickProblem(result: FoodResult, picks: Picks): string | null {
  const { customization } = result;
  if (!result.available) return 'This dish is out of stock.';
  if (!customization.supported) return "This dish needs options we can't set here. Order it in the Swiggy app.";
  for (const group of customization.variantGroups) {
    const id = picks.variants[group.groupId];
    const option = group.options.find(o => o.id === id);
    if (!option) return `Choose ${group.name.toLowerCase()}.`;
    if (!option.available) return `${option.name} is out of stock. Choose another.`;
  }
  for (const group of customization.addonGroups) {
    const chosen = picks.addons[group.groupId] ?? [];
    const gone = group.choices.find(c => !c.available && chosen.includes(c.id));
    if (gone) return `${gone.name} is out of stock. Remove it.`;
    const count = chosen.length;
    if (count < group.min) return `Choose at least ${group.min} from ${group.name}.`;
    if (group.max !== null && count > group.max) return `Choose at most ${group.max} from ${group.name}.`;
  }
  return null;
}

/** The cart request for a complete pick. Ids are copied exactly as Swiggy returned them; `variations` maps to the cart's `variants`. */
export function toSelection(result: FoodResult, picks: Picks): FoodSelection {
  const { customization } = result;
  const variants = customization.variantGroups.flatMap(g => (picks.variants[g.groupId] ? [{ group_id: g.groupId, variation_id: picks.variants[g.groupId] }] : []));
  const addons = customization.addonGroups.flatMap(g => (picks.addons[g.groupId] ?? []).map(id => ({ group_id: g.groupId, addon_id: id, quantity: 1 })));
  return {
    restaurant_id: result.restaurant.id,
    restaurant_name: result.restaurant.name || null,
    menu_item_id: result.menuItemId,
    quantity: picks.quantity,
    format: variants.length === 0 ? null : customization.format === 'variantsV2' ? 'variantsV2' : 'variants',
    variants,
    addons,
  };
}
