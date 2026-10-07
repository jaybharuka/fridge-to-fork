// What the landing page's main button says and whether it can be pressed, from the two independent, optional inputs: a dish name
// and fridge photos. Pure (no React) so it is unit tested in plain Node: see landingAction.test.ts.
//
//   dish only   -> recipe for that dish        ("Get recipe")
//   photo only  -> dishes suggested from the fridge ("Find dishes from my fridge")
//   both        -> a recipe for the dish, built around the fridge ("Get recipe using my fridge")
//   neither     -> nothing to do: the button is disabled (it used to run a plan on an empty fridge and return generic dishes)

export type LandingMode = 'empty' | 'dish' | 'photo' | 'both';

export interface LandingAction {
  mode: LandingMode;
  label: string;
  /** False only when there is neither a dish nor a photo. */
  enabled: boolean;
}

/** A dish counts only when it has something other than whitespace in it. */
export const hasDish = (dish: string): boolean => dish.trim() !== '';

export function landingMode(dish: string, photoCount: number): LandingMode {
  const dishGiven = hasDish(dish);
  const photoGiven = photoCount > 0;
  if (dishGiven && photoGiven) return 'both';
  if (dishGiven) return 'dish';
  if (photoGiven) return 'photo';
  return 'empty';
}

const LABELS: Record<LandingMode, string> = {
  empty: 'Get recipe',
  dish: 'Get recipe',
  photo: 'Find dishes from my fridge',
  both: 'Get recipe using my fridge',
};

export function landingAction(dish: string, photoCount: number): LandingAction {
  const mode = landingMode(dish, photoCount);
  return { mode, label: LABELS[mode], enabled: mode !== 'empty' };
}

/** Shown under the disabled button, so it stays obvious why it is disabled. */
export const DISABLED_HELP = 'Add a dish or a fridge photo to continue.';

/** The line under the thumbnails once a fridge photo has been added. */
export function fridgeHint(dish: string): string {
  return hasDish(dish)
    ? "Fridge added. We'll build the recipe around what you have."
    : 'Fridge added. Type a dish to cook with it, or just tap Find dishes.';
}
