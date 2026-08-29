# Next.js Frontend Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `templates/index.html` (a ~4950-line vanilla HTML/CSS/JS single-file app) with a Next.js 14+ App Router + TypeScript frontend in a new `frontend/` directory, byte-faithful in behavior, that talks to the existing untouched FastAPI backend (`app.py`, `fridge_to_fork/*`) over HTTP/SSE — plus two deliberate fixes (scrollable ingredient checklist container, dish-hero image waterfall order).

**Architecture:** A `next dev` server proxies `/api/*` and `/auth/*` to `localhost:8000` via `next.config.js` rewrites so the FastAPI backend needs zero changes. All client state lives in React (no global state library — the whole app is one page). SSE consumption is centralized in one hook (`useScanStream`) that mirrors the old `handleEvent()` switch, driving a single reducer-shaped state object consumed by presentational components. Styling is plain global CSS using the same CSS custom properties as the original (`--bg`, `--orange`, etc.) — no Tailwind, since the original design system isn't Tailwind-based (the CDN Tailwind import in the old file is only used for a handful of one-off utility classes on dead code / minor spots, ported as plain CSS instead).

**Tech Stack:** Next.js (App Router, TypeScript), lucide-react, plain CSS (globals.css + CSS Modules per component where it helps), native `fetch` + `ReadableStream` for SSE (no EventSource — the backend sends POST bodies, EventSource can't POST).

**Spec:** The full spec is the user's original request in this conversation (no separate spec file — this plan inlines every requirement). Source of truth for exact behavior/markup/CSS to port is `templates/index.html` (referenced throughout by line numbers as of this plan's writing) and `app.py` for the backend contract. **Do not modify `app.py`, `fridge_to_fork/*`, or `templates/index.html`** — read-only references.

## Global Constraints

- Backend contract is frozen: same endpoints (`/api/scan`, `/api/order`, `/api/youtube`, `/api/dish-suggestions` [unused by frontend — dish autocomplete is local `INSTANT_DISHES`, not this endpoint], `/api/dish-image`, `/api/ingredient-image`, `/api/cart-fill` [dead — no caller in old frontend, do not port], `/auth/login`, `/auth/callback`, `/auth/status`, `/auth/logout`), same SSE event names/payloads, same multipart field names (`fridge_photo_0/1/2`, `target_dish`, `mode`, `servings` for `/api/scan`; `action`, `meal_name`, `missing_ingredients` for `/api/order`).
- All `fetch`/SSE calls to the backend must use `credentials: 'same-origin'` (the default) or explicit `credentials: 'include'` so the Swiggy OAuth session cookie set by `SessionMiddleware` keeps working through the Next.js proxy.
- No new dependencies beyond: Next.js + TypeScript (from `create-next-app`), `lucide-react`. No state-management library, no CSS framework, no test framework (this migration is verified by manual walkthrough per the user's own Verification section, not unit tests — UI-porting work doesn't lend itself to meaningful unit coverage, and the user explicitly asked for a manual walkthrough instead).
- `templates/index.html` stays in place, untouched, as a fallback reference. Do not delete it.
- The Smart Cart modal (`#smartCartModal`, `openSmartCart()`, `showCartModal()`, lines 2117–2133 and ~4717–4935 of `templates/index.html`) has **zero callers** anywhere in the old file (verified: `openSmartCart` is never invoked from any `onclick` or event listener) — it is dead code. **Do not port it.**
- The old file's `setStep()`/`resetProgressSteps()`/`markProgressStepDone()`/`#pstep-N`/`#s1,#s2,#s3` progress-step machinery (lines ~2789–2827, referenced throughout `handleEvent`) targets DOM elements that **do not exist anywhere in the markup** (verified via grep) — every call is a guarded no-op. **Do not port this dead machinery**; the calls to it in the ported `handleEvent`/`useScanStream` logic are simply omitted.
- Dish-hero image waterfall order (already correct in the current source — verify, don't "fix" a regression that isn't there): **Unsplash → TheMealDB → YouTube thumbnail → placeholder**, confirmed at `templates/index.html:3638-3677`.
- Ingredient checklist must be its own internally-scrollable container (`max-height`, themed scrollbar, bottom fade-when-more-below) — port the existing `.recipe-rows` / `.recipe-rows-wrap` / `.recipe-rows-fade` CSS (lines 601–629) and `setupRecipeRowsFade()`/`updateRecipeRowsFade()` logic (lines 3291–3306) essentially as-is; it already implements this correctly in the old file, so this "fix" is really "port faithfully," confirmed against the sticky header (`#resultStickyHeader`, lines 1018–1022) which is a separate, non-scrolling sibling.

---

## File Structure

```
frontend/
  next.config.js                    # rewrites: /api/:path* and /auth/:path* -> http://localhost:8000
  package.json
  tsconfig.json
  app/
    layout.tsx                      # <html>, font links, theme init script (no FOUC), imports globals.css
    globals.css                     # CSS custom properties (light/dark), base/reset, typography, shared classes
    page.tsx                        # top-level orchestrator: renders Landing | LoadingOverlay | PhotoScanScreen | Results based on state from useScanStream
  lib/
    types.ts                        # SSE event payload types, Ingredient/RecipeIngredient/ChecklistItem/MealSuggestion types
    instantDishes.ts                # INSTANT_DISHES array, ported verbatim from templates/index.html:4246-4356
    foodEmoji.ts                    # FOOD_EMOJI_MAP, getEmojiForIngredient(), simplifyIngredientName() ported from lines 3038-3145, 2991-3003
    sse.ts                          # readSSEStream(response, onEvent) ported from lines 3178-3193
    dishHeroImage.ts                # loadDishHeroImage waterfall + tryLoadImage + per-dish-name image cache, ported/adapted from lines 3600-3677
    quantity.ts                     # getMissingIngredientDefaults(), parseQuantityString() ported from lines 3769-3775, 3882-3898
    theme.ts                        # theme get/set/localStorage helpers
  hooks/
    useTheme.ts                     # theme state + toggle, mirrors lines 2137-2162
    useScanStream.ts                # the SSE-consumption hook: owns fetch+readSSEStream for /api/scan and /api/order, reduces incoming events into ScanState, mirrors handleEvent() (lines 4486-4715) minus dead progress-step code and Smart Cart
    useRecipeChecklist.ts           # derived checklist state + toggle + getItemsToOrder(), mirrors lines 3195-3253, 3737-3767
    useAutocomplete.ts              # INSTANT_DISHES filtering + keyboard nav, mirrors lines 4358-4478
    usePhotoUpload.ts               # compressImage + fridgePhotos array + thumbnails, mirrors lines 2141-2243(state)/4132-4243
  components/
    landing/
      Hero.tsx                        # lines 1796-1799
      DishInput.tsx                   # input + suggestion dropdown, lines 1803-1805, 4358-4484
      ServingsSelector.tsx            # lines 1807-1820
      GetRecipeButton.tsx             # lines 1822-1826, loading/ready states (lines 2764-2787)
      PhotoUploadArea.tsx             # lines 1828-1844, 4190-4243
      PopularDishes.tsx               # lines 1846-1895 (static grid, 6 dishes)
    loading/
      LoadingOverlay.tsx              # lines 1899-1920, 2367-2426 (particles, fridge zone, stage checklist)
      PhotoScanScreen.tsx             # lines 1922-1951, 2462-2641 (scan line, sub-messages, timeout state, detected items reveal)
    results/
      AppHeader.tsx                   # lines 1782-1791 (brand + theme toggle)
      StickySummaryBar.tsx            # lines 1960-1967, 3519-3538
      ResultTabBar.tsx                # lines 1969-1982, 3548-3598
      DishHeroSection.tsx             # lines 1987-2003, wraps lib/dishHeroImage.ts
      FridgeSummaryHeader.tsx         # thumbnail row + chips dropdown + lightbox trigger, lines 2017-2039, 2649-2733 (morph animation), 2915-2983
      FridgeChipsDropdown.tsx         # lines 2830-2913 (chip building + matched/other split + toggle)
      FridgeLightbox.tsx              # lines 2082-2087, 2961-2983
      MealSuggestionsSection.tsx      # lines 2045-2048, 4569-4586
      IngredientChecklistCard.tsx     # THE SCROLL-FIX COMPONENT — lines 2050-2051, 3242-3349, 3499-3535, 3697-3767
      ChoiceCard.tsx                  # lines 2053, 3789-3831, "Powered by Swiggy" attribution included
      OrderBottomSheet.tsx            # lines 2089-2115, 3900-3957, 3992-4002 (swipe-to-dismiss)
      TopUpCard.tsx                   # lines 3914-3943, image load via /api/ingredient-image + emoji fallback
      OrderResultCard.tsx             # cook_confirmed / step3 (order placed) / auth_required / error states, lines 4637-4714
      RecipeStepsSection.tsx          # lines 3355-3372, 3491-3497
      YoutubeCarousel.tsx             # lines 3378-3448
      Toast.tsx                       # lines 2077, 3170-3176
  public/
    (favicon etc. — no image assets needed, everything is remote-fetched)
```

---

## Task 1: Scaffold the Next.js app, theming, and proxy config

**Files:**
- Create: `frontend/` (via `create-next-app`)
- Create: `frontend/next.config.js`
- Create: `frontend/app/globals.css`
- Create: `frontend/app/layout.tsx`
- Create: `frontend/lib/theme.ts`
- Create: `frontend/hooks/useTheme.ts`
- Modify: `frontend/app/page.tsx` (placeholder shell for now)

**Interfaces:**
- Produces: `getStoredTheme(): 'light' | 'dark' | null`, `setStoredTheme(t: 'light'|'dark'): void` (lib/theme.ts); `useTheme(): { theme: 'light'|'dark', toggle: () => void }` (hooks/useTheme.ts) — consumed by `AppHeader` in Task 7.

- [ ] **Step 1: Scaffold the app**

Run from `c:\Projects\fridge-to-fork`:
```
npx create-next-app@latest frontend --typescript --app --eslint --no-tailwind --src-dir=false --import-alias "@/*"
cd frontend
npm install lucide-react
```

- [ ] **Step 2: Configure the dev-server proxy**

```js
// frontend/next.config.js
/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      { source: '/api/:path*', destination: 'http://localhost:8000/api/:path*' },
      { source: '/auth/:path*', destination: 'http://localhost:8000/auth/:path*' },
    ];
  },
};
module.exports = nextConfig;
```

- [ ] **Step 3: Port the CSS custom properties and base styles into `globals.css`**

Copy `templates/index.html:22-171` (the `:root`/`[data-theme="dark"]` variable blocks and base `*`/`html`/`body`/typography rules) into `frontend/app/globals.css` verbatim — these are plain CSS custom properties, no translation needed. Include the `svg.lucide { width:1em; height:1em; ... }` rule (line 162) since `lucide-react` renders inline `<svg>` the same way the old `lucide.createIcons()` did, and every existing `font-size:Npx` icon-sizing rule in the ported component CSS depends on that 1em sizing. Include `@media (prefers-reduced-motion: reduce)` (lines 1774-1776) and the `button:focus-visible` rule (lines 150-152).

- [ ] **Step 4: `lib/theme.ts` and `hooks/useTheme.ts`**

```ts
// frontend/lib/theme.ts
export type Theme = 'light' | 'dark';

export function getStoredTheme(): Theme | null {
  if (typeof window === 'undefined') return null;
  const v = localStorage.getItem('theme');
  return v === 'dark' || v === 'light' ? v : null;
}

export function setStoredTheme(theme: Theme) {
  localStorage.setItem('theme', theme);
}

export function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-color-scheme: dark)').matches;
}
```

```ts
// frontend/hooks/useTheme.ts
'use client';
import { useState, useCallback, useLayoutEffect } from 'react';
import { getStoredTheme, setStoredTheme, systemPrefersDark, Theme } from '@/lib/theme';

export function useTheme() {
  const [theme, setTheme] = useState<Theme>('dark');

  useLayoutEffect(() => {
    const stored = getStoredTheme();
    const initial: Theme = stored ?? (systemPrefersDark() ? 'dark' : 'light');
    setTheme(initial);
    document.documentElement.setAttribute('data-theme', initial);
  }, []);

  const toggle = useCallback(() => {
    setTheme(prev => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark';
      setStoredTheme(next);
      document.documentElement.setAttribute('data-theme', next);
      return next;
    });
  }, []);

  return { theme, toggle };
}
```

- [ ] **Step 5: `layout.tsx` — inline no-FOUC theme script + fonts**

Port the Google Fonts `<link>` tags (`templates/index.html:8-9`) into `layout.tsx`'s `<head>`. Add an inline `<script>` (via `dangerouslySetInnerHTML`, runs before hydration) that reads `localStorage.theme` and sets `data-theme` on `<html>` immediately — this replaces the synchronous theme-apply call at the old file's bottom (`templates/index.html:2160-2162`) and prevents a flash of the wrong theme, since React hydration in Task 4's `useTheme` runs after first paint:

```tsx
<script
  dangerouslySetInnerHTML={{
    __html: `(function(){try{var t=localStorage.getItem('theme');if(!t){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`,
  }}
/>
```

- [ ] **Step 6: Verify**

Run: `cd frontend && npm run dev`
Expected: blank page loads at `localhost:3000` with no console errors; toggling OS dark mode / editing `localStorage.theme` in devtools and refreshing shows the right `data-theme` attribute on `<html>` with no flash.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat: scaffold Next.js frontend with theme system and backend proxy"
```

---

## Task 2: SSE plumbing and shared types

**Files:**
- Create: `frontend/lib/types.ts`
- Create: `frontend/lib/sse.ts`

**Interfaces:**
- Consumes: nothing (pure lib code)
- Produces: `readSSEStream(res: Response, onEvent: (ev: ScanEvent) => void): Promise<void>`; the full `ScanEvent` discriminated union — consumed by `useScanStream` in Task 3.

- [ ] **Step 1: Define the event types**

```ts
// frontend/lib/types.ts
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
```

- [ ] **Step 2: Port `readSSEStream`**

```ts
// frontend/lib/sse.ts
import type { ScanEvent } from './types';

export async function readSSEStream(res: Response, onEvent: (ev: ScanEvent) => void): Promise<void> {
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() ?? '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try { onEvent(JSON.parse(line.slice(6))); } catch { /* ignore malformed line, matches old behavior */ }
    }
  }
}
```

This is a direct, faithful port of `templates/index.html:3178-3193` — same buffering approach, same silent-catch-on-parse-error behavior (the old code does the same).

- [ ] **Step 3: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/sse.ts
git commit -m "feat: add SSE reader and scan event types"
```

---

## Task 3: `useScanStream` — the central SSE-driven state hook

This is the most architecturally significant departure from the old code: `handleEvent()` (lines 4486-4715) was one giant imperative function mutating ~15 module-level `let` variables and poking the DOM directly. This task collapses all of that into one `useReducer`-backed hook whose state shape presentational components read declaratively.

**Files:**
- Create: `frontend/hooks/useScanStream.ts`
- Create: `frontend/lib/quantity.ts`

**Interfaces:**
- Consumes: `readSSEStream` (Task 2), `ScanEvent`/`ChecklistItem`/`RecipeIngredient` types (Task 2)
- Produces:
```ts
export interface ScanState {
  phase: 'idle' | 'loading' | 'photo-scanning' | 'results' | 'error';
  hasPhoto: boolean;
  detectedIngredients: DetectedIngredient[];
  matchedFridgeItems: string[];
  suggestions: MealSuggestion[];
  recommendedMeal: string | null;
  reasoning: string;
  checklist: ChecklistItem[];              // consumed by Task 6's useRecipeChecklist wrapper
  cookingSteps: string[];
  topUpSuggestions: TopUpSuggestion[];
  awaitingChoice: boolean;
  recipeTabUnlocked: boolean;
  orderResult:
    | null
    | { kind: 'cook_confirmed' }
    | { kind: 'order_placed'; orderId: string; platform: string; items: string[]; etaMinutes: number }
    | { kind: 'cook_no_order' }
    | { kind: 'auth_required'; message?: string }
    | { kind: 'error'; message: string };
  scanError: string | null;
  timedOutVision: boolean;
}
export function useScanStream(): {
  state: ScanState;
  startScan: (mode: 'photo' | 'recipe', opts: { files?: File[]; targetDish: string; servings: number }) => Promise<void>;
  placeOrder: (action: 'cook' | 'order_groceries' | 'order_dish', mealName: string, missingIngredientNames: string[]) => Promise<void>;
  toggleChecklistItem: (index: number) => void;
  reset: () => void;
}
```
This is consumed by `app/page.tsx` (Task 14) and by every `results/*` component (Tasks 7–13) via props derived from `state`.

- [ ] **Step 1: Port the pure helper functions checklist toggling depends on**

```ts
// frontend/lib/quantity.ts
export function parseQuantityString(qtyStr: string): { qty_needed: number; unit: string } {
  const match = (qtyStr || '').match(/^([\d.]+)\s*(.*)$/);
  if (match) {
    return { qty_needed: parseFloat(match[1]) || 1, unit: match[2].trim() || 'unit' };
  }
  return { qty_needed: 1, unit: qtyStr || 'unit' };
}

export function getMissingIngredientDefaults(name: string): { unit: string; qty: number } {
  const lower = name.toLowerCase();
  const rules: { words: string[]; unit: string; qty: number }[] = [
    { words: ['dal', 'rice', 'atta', 'flour', 'sugar', 'salt', 'oil', 'ghee', 'masala', 'powder'], unit: 'kg', qty: 0.5 },
    { words: ['milk', 'juice', 'water', 'lassi'], unit: 'L', qty: 1 },
    { words: ['leaves', 'coriander', 'methi', 'curry'], unit: 'bunch', qty: 1 },
    { words: ['egg'], unit: 'piece', qty: 6 },
  ];
  for (const rule of rules) {
    if (rule.words.some(w => lower.includes(w))) return { unit: rule.unit, qty: rule.qty };
  }
  return { unit: 'pack', qty: 1 };
}
```
Direct port of `templates/index.html:3769-3775, 3882-3898`.

- [ ] **Step 2: Write the reducer**

Build `useScanStream.ts` around a reducer whose action types are exactly the `ScanEvent['type']` values plus three UI-driven actions (`SCAN_START`, `TOGGLE_ITEM`, `RESET`). Faithfully port the branch logic from `handleEvent()` (lines 4486-4715) into reducer cases, translating DOM mutation into state assignment:

- `'step1'` case: set `detectedIngredients`, `phase` stays whatever it was (the old code's photo-scan-reveal-vs-immediate-results branch becomes a `hasPhoto` flag the *component* reads to decide whether to run the detected-items reveal animation before flipping to `'results'` — see Task 6). Set `phase: hasPhoto ? 'photo-scanning' : 'results'`.
- `'step2'` case: set `suggestions`, `recommendedMeal`, `reasoning`, `cookingSteps`, `matchedFridgeItems`; build `checklist` from `recipe_ingredients` exactly as `renderRecipeChecklist()` does (lines 3227-3237): `checked = found_in_fridge || is_staple`.
- `'awaiting_user_choice'` case: set `reasoning`, `recommendedMeal` (fallback to existing), `awaitingChoice: true`, `recipeTabUnlocked: true`.
- `'top_up'`: set `topUpSuggestions` (only if `suggestions.length` — matches line 4632's early return on empty).
- `'complete'`: set `phase: 'results'` (idempotent safety net, matches lines 4614-4624).
- `'cook_confirmed'`: `orderResult = { kind: 'cook_confirmed' }`.
- `'step3'`: branch on `ev.placed` / `ev.decision === 'cook'` exactly as lines 4649-4672 to produce `orderResult`.
- `'error'`: `orderResult = { kind: 'error', message: ev.message }` AND `scanError = ev.message` — component layer (Task 14) decides which one to show based on whether results were already visible, replicating the `resultsAlreadyShown` check at line 4684 (pass `state.phase === 'results'` at dispatch time into the reducer, or check it in the component — component-level is simpler and keeps the reducer pure).
- `'auth_required'`: `orderResult = { kind: 'auth_required', message: ev.message }`.
- Ignore `'progress'` and `'step2_partial'` for state purposes beyond an optional `streamedText` field if you want to keep the live-preview text visible during step2 (nice-to-have, not required — the old UI didn't actually render `streamedIngredientNames` anywhere either, confirmed: it's tracked but never read back into the DOM in the current file, lines 4553-4563). **Skip rendering it** — match current (not aspirational) behavior.

- [ ] **Step 3: `startScan` and `placeOrder`**

```ts
async function startScan(mode, { files, targetDish, servings }) {
  dispatch({ type: 'SCAN_START', hasPhoto: mode === 'photo' && !!files?.length });
  const form = new FormData();
  if (mode === 'photo' && files?.length) {
    files.forEach((f, i) => form.append(`fridge_photo_${i}`, f));
  } else {
    form.append('mode', mode);
  }
  if (targetDish) form.append('target_dish', targetDish);
  form.append('servings', String(servings));
  try {
    const res = await fetch('/api/scan', { method: 'POST', body: form, credentials: 'same-origin' });
    if (!res.ok) throw new Error(`Server error: ${res.status}`);
    await readSSEStream(res, ev => dispatch(ev));
  } catch (err) {
    dispatch({ type: 'error', message: 'Something went wrong. Try again.' });
  }
}
```
Mirrors `startScan()` (lines 4015-4098) minus all direct DOM manipulation — the component layer (Task 14) owns transition timing (fade classes, overlay show/hide), the hook only owns data.

`placeOrder` mirrors `chooseAction()` (lines 3849-3877): posts to `/api/order` with `action`/`meal_name`/`missing_ingredients` (comma-joined names from `getItemsToOrder()`), reads the SSE stream the same way. Include the `orderInFlight` guard as a ref inside the hook (was a module-level `let` at line 3847) so a double-click can't fire two concurrent orders.

- [ ] **Step 4: `toggleChecklistItem`**

```ts
function toggleChecklistItem(index: number) {
  dispatch({ type: 'TOGGLE_ITEM', index });
}
```
Reducer case flips `checked` on `checklist[index]` immutably (new array, new item object) — this is the one place the plan's "no mutation" constraint actually matters, since the old code mutated `currentRecipeChecklist[idx].checked` in place (line 3740).

- [ ] **Step 5: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors. (Full behavioral verification happens once components exist, in Task 14's manual walkthrough.)

- [ ] **Step 6: Commit**

```bash
git add frontend/hooks/useScanStream.ts frontend/lib/quantity.ts
git commit -m "feat: add useScanStream hook centralizing SSE event handling"
```

---

## Task 4: Dish autocomplete data + hook

**Files:**
- Create: `frontend/lib/instantDishes.ts`
- Create: `frontend/hooks/useAutocomplete.ts`

**Interfaces:**
- Produces: `INSTANT_DISHES: string[]`; `useAutocomplete(query: string): { suggestions: string[]; activeIndex: number; onKeyDown: (e: React.KeyboardEvent) => void; setActiveIndex: (i: number) => void }` — consumed by `DishInput` (Task 5).

- [ ] **Step 1: Port the dish list verbatim**

Copy the full `INSTANT_DISHES` array literal from `templates/index.html:4246-4356` into `frontend/lib/instantDishes.ts` as `export const INSTANT_DISHES: string[] = [...]`. Copy every entry exactly, including the category comments as JS comments — this is pure data, no logic changes.

- [ ] **Step 2: Port the filtering + keyboard-nav logic**

```ts
// frontend/hooks/useAutocomplete.ts
'use client';
import { useMemo, useState, useCallback } from 'react';
import { INSTANT_DISHES } from '@/lib/instantDishes';

export function useAutocomplete(query: string) {
  const [activeIndex, setActiveIndex] = useState(-1);

  const suggestions = useMemo(() => {
    const q = query.trim();
    if (q.length < 2) return [];
    const qLower = q.toLowerCase();
    const startsWith: string[] = [];
    const contains: string[] = [];
    for (const d of INSTANT_DISHES) {
      const dLower = d.toLowerCase();
      if (dLower.startsWith(qLower)) startsWith.push(d);
      else if (dLower.includes(qLower)) contains.push(d);
    }
    return [...startsWith, ...contains].slice(0, 7);
  }, [query]);

  return { suggestions, activeIndex, setActiveIndex };
}
```
Faithful port of the filtering logic at `templates/index.html:4444-4452`. Note: `activeIndex` resets to `-1` implicitly whenever `suggestions` changes because the component (Task 5) re-derives it — actual reset-on-new-query behavior lives in the component via a `useEffect` keyed on `query`, since the hook itself has no lifecycle hook into "query changed vs re-render for other reasons" without that.

- [ ] **Step 3: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/instantDishes.ts frontend/hooks/useAutocomplete.ts
git commit -m "feat: port dish autocomplete data and filtering hook"
```

---

## Task 5: Landing screen components

**Files:**
- Create: `frontend/components/landing/Hero.tsx`
- Create: `frontend/components/landing/DishInput.tsx`
- Create: `frontend/components/landing/ServingsSelector.tsx`
- Create: `frontend/components/landing/GetRecipeButton.tsx`
- Create: `frontend/components/landing/PopularDishes.tsx`
- Create: `frontend/components/landing/landing.module.css` (or extend `globals.css` with the same class names as the source — component-scoped CSS Modules are fine here since none of these classes are referenced from outside `landing/`)

**Interfaces:**
- Consumes: `useAutocomplete` (Task 4)
- Produces: `<Landing targetDish, onTargetDishChange, servings, onServingsChange, onGetRecipe, canSubmit>` composed of the above — consumed by `page.tsx` (Task 14). `DishInput` also exposes an `onSelectDish(name: string)` prop so `PopularDishes` cards can fill it (mirrors `selectPopularDish()` calling `selectSuggestion()`, lines 4424-4435).

- [ ] **Step 1: `Hero.tsx`**

Port the static markup and CSS from `templates/index.html:1796-1799` (`.hero`, `.hero-title`, `.hero-sub`) plus the light/dark overrides at lines 215-216.

- [ ] **Step 2: `ServingsSelector.tsx`**

Port `templates/index.html:1807-1820` (8 pills, `.servings-pill`/`.servings-pill.active` CSS at lines 279-296). Props: `value: number`, `onChange: (n: number) => void`.

- [ ] **Step 3: `GetRecipeButton.tsx`**

Port `templates/index.html:1822-1826` markup and `.analyse-btn`/`.analyse-btn.ready`/`.analyse-btn.loading` CSS (lines 299-324), including the shimmer-sweep `::after` animation (lines 312-323). Props: `state: 'ready' | 'loading'`, `label: string`, `onClick: () => void`. When `state === 'loading'`, render the `.spin` div instead of the wand icon (matches lines 2776-2781).

- [ ] **Step 4: `DishInput.tsx`**

Port the input markup (line 1804/1803-1805) and the suggestion dropdown CSS (lines 4363-4376, inlined as a CSS Module class instead of the old inline `style.cssText`) plus row styling (lines 4394-4398) and highlight-on-hover/keyboard (lines 4410-4422, translated to React state `activeIndex` driving `className`/inline highlight styles instead of direct DOM `style` writes).

Use `useAutocomplete(query)` from Task 4. Wire keyboard handling directly in this component (`onKeyDown`) rather than a global `document` listener, replicating the exact behavior of lines 4455-4478 (ArrowDown/ArrowUp wrap-around, Enter selects active row, Escape closes) — React's synthetic events on the input itself replace the old code's `dishInput.addEventListener('keydown', ...)`. For "click outside closes it" (lines 4480-4484), use a `useEffect` with a `document.addEventListener('click', ...)` guarded by a ref to the input's wrapper `div`, cleaned up on unmount.

Highlight matching substring using the same regex approach as `renderSuggestions()` (lines 4390-4393): build a `RegExp` from the escaped query and wrap matches in a `<mark>`-equivalent styled `<span>` — implement via splitting the string in JS and rendering an array of text/`<span>` nodes (React can't use `dangerouslySetInnerHTML` here without re-solving XSS-safety the old code got via building strings after `escapeHtml`; splitting and rendering as React children is strictly safer and simpler).

- [ ] **Step 5: `PopularDishes.tsx`**

Port the static 6-card grid from `templates/index.html:1849-1895` verbatim (dish names, tags, `lucide-react` icon names: `Drumstick`, `Wheat`, `Soup`, `Flame`, `ChefHat`, `Sunrise`) and its CSS (lines 245-276). `onClick` on each card calls the `onSelectDish` prop (mirrors `selectPopularDish`, lines 4433-4435).

- [ ] **Step 6: Verify**

Run: `cd frontend && npm run dev`, temporarily render `<Hero/><DishInput .../><ServingsSelector .../><GetRecipeButton .../><PopularDishes .../>` in `page.tsx`.
Expected: typing 2+ chars into the dish input shows a filtered, keyboard-navigable dropdown matching `INSTANT_DISHES`; clicking a popular-dish card fills the input; servings pills toggle active state; visually matches the old landing screen in both themes.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/landing/
git commit -m "feat: port landing screen components (hero, dish input, servings, popular dishes)"
```

---

## Task 6: Photo upload + loading/photo-scan overlays

**Files:**
- Create: `frontend/hooks/usePhotoUpload.ts`
- Create: `frontend/components/landing/PhotoUploadArea.tsx`
- Create: `frontend/components/loading/LoadingOverlay.tsx`
- Create: `frontend/components/loading/PhotoScanScreen.tsx`

**Interfaces:**
- Consumes: nothing external beyond browser APIs (`Canvas`, `FileReader`, `Image`)
- Produces: `usePhotoUpload(): { photos: File[]; thumbnailUrls: string[]; addPhoto: (f: File) => Promise<void>; removePhoto: (i: number) => void; clear: () => void }` — consumed by `PhotoUploadArea` and by `page.tsx` (Task 14, which passes `photos` into `startScan`). `LoadingOverlay`/`PhotoScanScreen` are presentational, driven by props from `page.tsx`.

- [ ] **Step 1: `usePhotoUpload.ts` — port `compressImage` + photo array management**

```ts
'use client';
import { useState, useCallback, useRef, useEffect } from 'react';

function compressImage(file: File, maxWidth: number, maxHeight: number, quality: number): Promise<Blob> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        let width = img.width, height = img.height;
        if (width > maxWidth) { height = Math.round(height * maxWidth / width); width = maxWidth; }
        if (height > maxHeight) { width = Math.round(width * maxHeight / height); height = maxHeight; }
        canvas.width = width; canvas.height = height;
        canvas.getContext('2d')!.drawImage(img, 0, 0, width, height);
        canvas.toBlob((b) => resolve(b as Blob), 'image/jpeg', quality);
      };
      img.src = e.target!.result as string;
    };
    reader.readAsDataURL(file);
  });
}

export function usePhotoUpload() {
  const [photos, setPhotos] = useState<File[]>([]);
  const [thumbnailUrls, setThumbnailUrls] = useState<string[]>([]);

  useEffect(() => {
    const urls = photos.map(f => URL.createObjectURL(f));
    setThumbnailUrls(urls);
    return () => urls.forEach(u => URL.revokeObjectURL(u));
  }, [photos]);

  const addPhoto = useCallback(async (file: File) => {
    if (photos.length >= 3) return;
    const blob = await compressImage(file, 1200, 1200, 0.82);
    setPhotos(prev => prev.length >= 3 ? prev : [...prev, new File([blob], file.name, { type: 'image/jpeg' })]);
  }, [photos.length]);

  const removePhoto = useCallback((i: number) => {
    setPhotos(prev => prev.filter((_, idx) => idx !== i));
  }, []);

  const clear = useCallback(() => setPhotos([]), []);

  return { photos, thumbnailUrls, addPhoto, removePhoto, clear };
}
```
Faithful port of `compressImage` (lines 4141-4168), `addPhoto`/`removePhoto`/`clearFridgePhotos` (lines 4174-4218), with object-URL lifecycle moved into a `useEffect` cleanup (replaces the old manual `URL.revokeObjectURL` calls scattered across `renderPhotoThumbnails()`, line 4193).

- [ ] **Step 2: `PhotoUploadArea.tsx`**

Port markup/CSS from `templates/index.html:1832-1844` (button vs. thumbnail-row toggle, lines 4223-4235's `updatePhotoUI` logic becomes a simple conditional render on `photos.length === 0`), thumbnail CSS (lines 348-383). File input `accept="image/*" capture="environment" multiple`, `onChange` slices to `3 - photos.length` remaining slots and calls `addPhoto` for each (mirrors lines 4237-4243).

- [ ] **Step 3: `LoadingOverlay.tsx`**

Port `templates/index.html:1899-1920` markup and CSS (lines 1325-1331, 1562-1664). Implement the particle field (`initLoadingParticles`, lines 2384-2396) and staged-checklist advance (`LOADING_STAGES`, `startLoadingStages`, `setActiveStage`, `finishLoadingStages`, lines 2252-2319) as internal `useEffect`s keyed on a `hasPhoto`/`headlineText`/`active` prop set. Props: `{ visible: boolean; hasPhoto: boolean; headlineText: string }`. On `visible` becoming `false`, mirror `hideLoadingOverlay()`'s 300ms fade-then-unmount (lines 2419-2426) via a local `shouldRender` state delayed with `setTimeout`.

- [ ] **Step 4: `PhotoScanScreen.tsx`**

Port `templates/index.html:1922-1951` markup and CSS (lines 1343-1560). Implement:
- Scan-line sweep, stopped via a `scanning: boolean` prop (mirrors `.photo-scan-line.stopped`, `showDetectionChips` stopping it at line 2612-2613).
- Cycling sub-status messages (`PHOTO_SCAN_SUB_MESSAGES`, `startPhotoScanSubMessages`, lines 2432-2460) as a `useEffect` with `setInterval`, cleaned up on unmount/prop change.
- Multi-photo thumb strip (`switchScanPreview`, lines 2476-2489, 2512-2519) as local `activeIndex` state.
- Detected-items staggered reveal: accept a `detectedIngredients: DetectedIngredient[] | null` prop; when it transitions from `null` to populated, run the same 180ms-stagger reveal as `showDetectionChips()` (lines 2603-2641) via a `useEffect` that schedules `setTimeout`s to progressively reveal rows (state: `revealedCount`), and calls an `onRevealComplete` prop after `names.length * 180 + 800`ms (matches line 2640) — this is what `page.tsx` (Task 14) uses to trigger the transition-to-results morph (Task 7).
- Timeout state after `PHOTO_SCAN_TIMEOUT_MS = 35000` (line 2231) if `detectedIngredients` hasn't arrived — `useEffect` with a 35s timer, cleared on unmount or once ingredients arrive (mirrors lines 2545-2561, 2606-2608). Include a "Try again" button calling an `onRetry` prop (mirrors `retryPhotoScan`, lines 2566-2575).

- [ ] **Step 5: Verify**

Run: `cd frontend && npm run dev`. Temporarily wire `PhotoUploadArea` into the landing page stub and add a debug toggle to show `LoadingOverlay`/`PhotoScanScreen`.
Expected: adding a photo shows a compressed thumbnail + inline "+" button (caps at 3); `LoadingOverlay`'s stage checklist advances on schedule and the fridge zone only shows when `hasPhoto`; `PhotoScanScreen`'s detected-item rows stagger in with confidence-tiered colors and the timeout notice appears after 35s if forced (e.g. temporarily shorten the constant for testing, then revert).

- [ ] **Step 6: Commit**

```bash
git add frontend/hooks/usePhotoUpload.ts frontend/components/landing/PhotoUploadArea.tsx frontend/components/loading/
git commit -m "feat: port photo upload, loading overlay, and photo-scan screen"
```

---

## Task 7: Results shell — header, sticky bar, tabs, fridge summary, lightbox

**Files:**
- Create: `frontend/components/results/AppHeader.tsx`
- Create: `frontend/components/results/StickySummaryBar.tsx`
- Create: `frontend/components/results/ResultTabBar.tsx`
- Create: `frontend/components/results/FridgeSummaryHeader.tsx`
- Create: `frontend/components/results/FridgeChipsDropdown.tsx`
- Create: `frontend/components/results/FridgeLightbox.tsx`

**Interfaces:**
- Consumes: `useTheme` (Task 1), `ScanState` fields (Task 3): `detectedIngredients`, `matchedFridgeItems`, `checklist`, `recipeTabUnlocked`
- Produces: `<ResultsHeader tab, onTabChange, recipeUnlocked, checklist, dishName>` and `<FridgeSummaryHeader photoUrl, ingredientCount, ingredients, matchedFridgeItems>` — consumed by `page.tsx` (Task 14).

- [ ] **Step 1: `AppHeader.tsx`**

Port `templates/index.html:1782-1791` and CSS (lines 186-203). Uses `useTheme()` from Task 1; render `Moon`/`Sun` from `lucide-react` conditionally instead of the old `outerHTML` swap (lines 2137-2147) — this is strictly simpler in React (no manual `lucide.createIcons()` re-run needed, the icon is just a conditional JSX element). Port the 300ms `spinning` class animation on click (lines 2149-2158) via a local `useState` + `setTimeout`.

- [ ] **Step 2: `StickySummaryBar.tsx`**

Port `templates/index.html:1960-1967` and CSS (lines 1013-1050). Props: `{ visible: boolean; haveCount: number; total: number; dishName: string }`. Text logic ported from `updateStickySummaryBar()` (lines 3519-3533): `"{have} of {total} ingredient(s) · {missing} to order"`.

- [ ] **Step 3: `ResultTabBar.tsx`**

Port `templates/index.html:1969-1982` and CSS (lines 1052-1099). Props: `{ activeTab: 'order' | 'recipe'; onTabChange: (t) => void; recipeUnlocked: boolean; recipeHasUnreadDot: boolean }`. Clicking the locked recipe tab calls an `onLockedClick` prop instead of navigating (mirrors the toast-on-locked-click at lines 3551-3553 — `page.tsx` wires this to the `Toast` component from Task 13). Render `<span className="tab-loading-dot">` vs `<span className="tab-ready-dot">` based on `recipeUnlocked` (mirrors `unlockRecipeTab()`, lines 3571-3577); once the recipe tab is actually clicked while unlocked, the dot permanently disappears for this scan (`resetResultTabs()`'s recreate-per-scan behavior lives in `page.tsx`'s per-scan state reset, not here).

- [ ] **Step 4: `FridgeSummaryHeader.tsx`**

Port `templates/index.html:2017-2039` and CSS (lines 1180-1275). Props: `{ visible: boolean; thumbUrl: string; ingredientCount: number; onOpenLightbox: () => void; children (chips dropdown) }`. The thumbnail-click-stops-propagation-then-opens-lightbox behavior (lines 2980-2982) is a plain `onClick={(e) => { e.stopPropagation(); onOpenLightbox(); }}` on the thumb element, with the dropdown toggle on the parent row's own `onClick`.

**Do not implement the FLIP-clone morph animation from `transitionToResults()` (lines 2649-2733) as a literal DOM-clone trick** — that technique exists specifically to animate between two different fixed-position full-screen elements in vanilla DOM. In React, achieve the same visual result more simply with the [shared-element crossfade pattern]: render the photo thumbnail at its final position with `opacity: 0` the whole time `PhotoScanScreen` is showing, and when `PhotoScanScreen`'s `onRevealComplete` fires (Task 6), fade `PhotoScanScreen` out (its own opacity, CSS transition) while fading the thumbnail in (`opacity: 1`) over the same ~400-500ms — this reproduces "the photo appears to hand off to the results thumbnail" closely enough to be faithful without a manual `getBoundingClientRect` clone, which is fragile in React (fights the reconciler) for no behavioral gain the user would actually perceive as different. Note this simplification explicitly in the PR/handoff notes.

- [ ] **Step 5: `FridgeChipsDropdown.tsx`**

Port `templates/index.html:2030-2039, 1282-1320` (dropdown shell CSS) and the chip-building + matched/other-split logic from `buildFridgeChip()`/`rerenderFridgeChips()`/`toggleOtherFridgeItems()` (lines 2836-2913). Props: `{ ingredients: DetectedIngredient[]; matchedFridgeItems: string[]; open: boolean; onClose: () => void }`. Confidence-tier coloring (`confClass`, lines 2825-2827) and the "N other items" collapsible toggle (local `useState` for expanded/collapsed) are ported as-is. Empty/no-detection state (lines 4508-4515) is a separate small conditional render when `ingredients.length === 0`.

Click-outside-to-close: `useEffect` with a `document` click listener guarded against clicks inside the dropdown or the summary row (mirrors `outsideFridgeClick`, lines 2950-2956), attached only while `open`.

- [ ] **Step 6: `FridgeLightbox.tsx`**

Port `templates/index.html:2082-2087` and CSS (lines 1220-1259). Props: `{ open: boolean; imageUrl: string; onClose: () => void }`. Backdrop-click-closes via `onClick` on the outer div checking `e.target === e.currentTarget` (mirrors line 2977-2979).

- [ ] **Step 7: Verify**

Run: `cd frontend && npm run dev` with these wired into a temporary results stub in `page.tsx` behind mock data.
Expected: theme toggle spins and swaps icon with no flash; sticky bar text matches "X of Y ingredients · N to order" format; tab bar shows a pulsing dot while locked and a static orange dot once unlocked, clicking locked tab shows a toast instead of switching; fridge chips dropdown opens/closes on row click and outside click, splits matched-vs-other correctly, lightbox opens on thumbnail click without also toggling the dropdown.

- [ ] **Step 8: Commit**

```bash
git add frontend/components/results/AppHeader.tsx frontend/components/results/StickySummaryBar.tsx frontend/components/results/ResultTabBar.tsx frontend/components/results/FridgeSummaryHeader.tsx frontend/components/results/FridgeChipsDropdown.tsx frontend/components/results/FridgeLightbox.tsx
git commit -m "feat: port results shell (header, sticky bar, tabs, fridge summary, lightbox)"
```

---

## Task 8: Dish hero image waterfall

**Files:**
- Create: `frontend/lib/dishHeroImage.ts`
- Create: `frontend/components/results/DishHeroSection.tsx`

**Interfaces:**
- Produces: `resolveDishHeroImage(dishName: string, fetchYoutube: () => Promise<{ first_thumbnail: string }>): Promise<string | null>` (returns the first working image URL from the waterfall, or `null` if all fail) — consumed by `DishHeroSection`, which is consumed by `page.tsx` (Task 14).
- Consumes: the YouTube fetch function is injected (not called directly from this lib) so it can share the same cache as `YoutubeCarousel` (Task 12) — mirrors the old code's `cachedYoutubeDish`/`cachedYoutubeData` sharing between `loadDishHeroImage()` and `fetchYoutubeVideos()` (lines 3475-3489, 3667-3674).

- [ ] **Step 1: Port `tryLoadImage` and the waterfall**

```ts
// frontend/lib/dishHeroImage.ts
function tryLoadImage(url: string): Promise<boolean> {
  return new Promise(resolve => {
    const img = new Image();
    let settled = false;
    const finish = (ok: boolean) => { if (!settled) { settled = true; resolve(ok); } };
    img.onload = () => finish(true);
    img.onerror = () => finish(false);
    img.src = url;
    setTimeout(() => finish(false), 5000);
  });
}

const dishImageCache = new Map<string, string | null>();

export async function resolveDishHeroImage(
  dishName: string,
  fetchYoutubeFirstThumbnail: () => Promise<string>
): Promise<string | null> {
  if (dishImageCache.has(dishName)) return dishImageCache.get(dishName)!;

  // Source 1 — Unsplash
  try {
    const uRes = await fetch(`/api/dish-image?dish=${encodeURIComponent(dishName)}`);
    const uData = await uRes.json();
    if (uData.found && uData.image_url && await tryLoadImage(uData.image_url)) {
      dishImageCache.set(dishName, uData.image_url);
      return uData.image_url;
    }
  } catch { /* fall through */ }

  // Source 2 — TheMealDB
  try {
    const mealRes = await fetch(`https://www.themealdb.com/api/json/v1/1/search.php?s=${encodeURIComponent(dishName)}`);
    const mealData = await mealRes.json();
    const thumb = mealData?.meals?.[0]?.strMealThumb;
    if (thumb && await tryLoadImage(thumb)) {
      dishImageCache.set(dishName, thumb);
      return thumb;
    }
  } catch { /* fall through */ }

  // Source 3 — YouTube recipe video thumbnail
  try {
    const thumb = await fetchYoutubeFirstThumbnail();
    if (thumb && await tryLoadImage(thumb)) {
      dishImageCache.set(dishName, thumb);
      return thumb;
    }
  } catch { /* fall through */ }

  dishImageCache.set(dishName, null);
  return null;
}
```

This is a direct, order-preserving port of `templates/index.html:3604-3677` — **Unsplash → TheMealDB → YouTube → null(placeholder)**, confirmed as the current (correct, matching the requested fix) order in the source. The per-dish-name cache (`dishImageCache`) replaces the old `cachedYoutubeDish`/`cachedYoutubeData` pattern with a slightly broader cache keyed on the *final resolved image*, not just the YouTube leg — an improvement that still satisfies "cached per dish name, shared between hero image and carousel" since `fetchYoutubeFirstThumbnail` itself should be backed by the shared YouTube-response cache built in Task 12.

- [ ] **Step 2: `DishHeroSection.tsx`**

Port `templates/index.html:1987-2003, 1102-1179` (gradient overlay, name/meta text, placeholder-initial fallback). Props: `{ dishName: string; servings: number; cookTime: string | null; fetchYoutubeFirstThumbnail: () => Promise<string> }`. On mount / whenever `dishName` changes, call `resolveDishHeroImage` and set local `imageUrl` state; render the placeholder initial (`dishName.charAt(0).toUpperCase()`, matches line 3642) until it resolves, fade in via `opacity` transition + `onLoad` on the real `<img>` (mirrors `setHeroImage()`, lines 3616-3625).

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run dev` with a temporary test render passing a few dish names (`"Butter Chicken"`, a nonsense string to force fallthrough, e.g. `"zzzznotarealdish"`).
Expected: a well-known dish shows an Unsplash photo (check Network tab: `/api/dish-image` called first, `themealdb.com` only called if Unsplash's result 404s or returns `found: false`); a nonsense dish name falls through all three and shows the placeholder initial. Confirms waterfall order is Unsplash → TheMealDB → YouTube → placeholder.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/dishHeroImage.ts frontend/components/results/DishHeroSection.tsx
git commit -m "feat: port dish hero image waterfall (Unsplash -> TheMealDB -> YouTube -> placeholder)"
```

---

## Task 9: Ingredient checklist card — the scroll-fix component

**Files:**
- Create: `frontend/hooks/useRecipeChecklist.ts`
- Create: `frontend/components/results/IngredientChecklistCard.tsx`

**Interfaces:**
- Consumes: `checklist: ChecklistItem[]` + `toggleChecklistItem` from `useScanStream` (Task 3)
- Produces: `getItemsToOrder(checklist): ChecklistItem[]` (used by `ChoiceCard`/`OrderBottomSheet`, Task 10) and the rendered card — consumed by `page.tsx` (Task 14).

- [ ] **Step 1: `useRecipeChecklist.ts` — derived stats + hook text**

```ts
// frontend/hooks/useRecipeChecklist.ts
import type { ChecklistItem } from '@/lib/types';

export function getItemsToOrder(checklist: ChecklistItem[]): ChecklistItem[] {
  return checklist.filter(i => !i.checked);
}

export function buildRecipeHookText(checklist: ChecklistItem[]): string {
  const missingCount = getItemsToOrder(checklist).length;
  if (missingCount === 0) return "Your kitchen is fully stocked for this. Time to cook.";
  if (missingCount === 1) return "Almost there. Just one thing standing between you and this dish.";
  if (missingCount <= 3) return "You're 80% ready. Here's what's missing.";
  return "A few key ingredients away. Let's get them.";
}

export function buildMissingSummaryText(items: ChecklistItem[]): string {
  const names = items.map(i => i.name);
  if (!names.length) return 'Nothing — you have everything';
  return names.length > 3 ? `${names.slice(0, 3).join(', ')} + ${names.length - 3} more` : names.join(', ');
}
```
Direct ports of `templates/index.html:3499-3505, 3751-3767, 3755-3759` (note: `escapeHtml` calls in the original are dropped since React auto-escapes text content — these functions just return plain strings for React to render as text nodes, not `dangerouslySetInnerHTML`).

- [ ] **Step 2: `IngredientChecklistCard.tsx` — THE scroll-container fix**

Port markup structure from `templates/index.html:3264-3272` and CSS from lines 583-664 **exactly as-is** (this is the file's own already-correct implementation of the requested fix, not a rewrite):

```css
/* frontend/components/results/IngredientChecklistCard.module.css */
.rowsWrap { position: relative; }
.rows {
  display: flex; flex-direction: column;
  max-height: 46vh;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: thin;
  scrollbar-color: var(--text-muted) transparent;
}
@media (min-width: 481px) { .rows { max-height: 52vh; } }
.rows::-webkit-scrollbar { width: 6px; }
.rows::-webkit-scrollbar-track { background: transparent; }
.rows::-webkit-scrollbar-thumb { background: var(--border); border-radius: 999px; }
.rows::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
.rowsFade {
  position: absolute; left: 0; right: 0; bottom: 0; height: 36px;
  background: linear-gradient(to bottom, rgba(0,0,0,0), var(--bg-card));
  pointer-events: none; opacity: 0; transition: opacity .2s ease;
}
.hasMoreBelow .rowsFade { opacity: 1; }
```

Structural confirmation that satisfies the spec's requirement: `.rows` (the actual `overflow-y: auto` element) is a leaf inside the checklist card, which itself lives inside `IngredientChecklistCard` — a sibling of `ResultTabBar`/`StickySummaryBar` (Task 7, which live in `#resultStickyHeader`, `position: sticky`) rather than a parent or child of them. Confirm this nesting is preserved in `page.tsx` (Task 14): the sticky header group and this card must be **siblings** under the same scrolling ancestor (the page body), not one inside the other.

Implement the fade-visibility logic with a `ResizeObserver` + scroll listener exactly like `setupRecipeRowsFade()`/`updateRecipeRowsFade()` (lines 3291-3306), as a `useEffect`:

```tsx
const rowsRef = useRef<HTMLDivElement>(null);
const [hasMoreBelow, setHasMoreBelow] = useState(false);

useEffect(() => {
  const el = rowsRef.current;
  if (!el) return;
  const update = () => setHasMoreBelow(el.scrollTop + el.clientHeight < el.scrollHeight - 1);
  update();
  el.addEventListener('scroll', update);
  const ro = new ResizeObserver(update);
  ro.observe(el);
  return () => { el.removeEventListener('scroll', update); ro.disconnect(); };
}, [checklist.length]); // re-measure when the row count changes, matching updateRecipeRowsFade() being re-run after toggleRecipeItem()
```

Render stats line (`buildRecipeStatsHtml`, lines 3507-3511 — port as JSX with the same have/total/toOrder numbers, including the count-up animation from `animateStatNumbers()`, lines 3681-3694, implemented as a small `useEffect`-driven `requestAnimationFrame` loop per stat number on mount/value-change), hook line, and rows (`buildRecipeRowsHtml`, lines 3697-3723 — one row per checklist item with checked/staple state classes, tag logic exactly as ported: "in fridge" tag if `checked && foundInFridge`, "Staple" tag if `checked && isStaple`, "Will be ordered" if `!checked && isStaple`). Row `onClick` calls `toggleChecklistItem(index)` (from `useScanStream`, Task 3).

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run dev` with mock checklist data of two sizes: 4 items (fits without scrolling) and 20 items (e.g. simulate a Dal Makhani-sized list).
Expected: the 4-item list shows no scrollbar and no bottom fade; the 20-item list scrolls internally within `max-height: 46vh`/`52vh`, shows the themed thin scrollbar, shows the bottom fade only while there's more content below, and the fade disappears exactly at the bottom of the scroll. Confirm the sticky header (mock `ResultTabBar`) stays pinned and does NOT scroll with the list.

- [ ] **Step 4: Commit**

```bash
git add frontend/hooks/useRecipeChecklist.ts frontend/components/results/IngredientChecklistCard.tsx
git commit -m "feat: port ingredient checklist with internally-scrollable container"
```

---

## Task 10: Choice card, order bottom sheet, top-up cards

**Files:**
- Create: `frontend/lib/foodEmoji.ts`
- Create: `frontend/components/results/ChoiceCard.tsx`
- Create: `frontend/components/results/OrderBottomSheet.tsx`
- Create: `frontend/components/results/TopUpCard.tsx`

**Interfaces:**
- Consumes: `getItemsToOrder`/`buildMissingSummaryText` (Task 9), `getMissingIngredientDefaults` (Task 3's `lib/quantity.ts`), `placeOrder` (Task 3)
- Produces: presentational components consumed by `page.tsx` (Task 14).

- [ ] **Step 1: `lib/foodEmoji.ts`**

Port `FOOD_EMOJI_MAP` (lines 3038-3113), `simplifyIngredientName()` (lines 2993-3003), `getEmojiForIngredient()` (lines 3118-3145) verbatim — pure data + string logic, no DOM.

- [ ] **Step 2: `ChoiceCard.tsx`**

Port `templates/index.html:3789-3831` and CSS (lines 787-849, incl. the `::before` spotlight-glow effect at lines 805-816 and the "Powered by Swiggy" attribution at lines 841-849). Props: `{ recommendedMeal: string; reasoning: string; itemsToOrder: ChecklistItem[]; onOrderGroceries: () => void; onOrderDish: () => void }`.

Reasoning display logic ported from `isInternalReasoning()`/`firstSentence()` (lines 3777-3787): hide the reasoning subtitle entirely if it's empty or contains any of `['fallback', 'local fallback', 'enable the live model', 'temporary']` (case-insensitive), otherwise show only the first sentence.

Spotlight-follows-cursor effect: port as a `onMouseMove`/`onTouchMove` handler on each button computing `--spot-x`/`--spot-y` CSS custom properties via `style` prop (React equivalent of the old `document.addEventListener('mousemove', ...)` delegation at lines 2170-2186 — scoping it per-button via React event handlers is simpler than global delegation and behaviorally identical since the old code's `updateChoiceSpotlight` already iterated per-button anyway).

- [ ] **Step 3: `OrderBottomSheet.tsx`**

Port `templates/index.html:2089-2115` and CSS (lines 856-951). Props: `{ open: boolean; itemsToOrder: ChecklistItem[]; topUpSuggestions: TopUpSuggestion[]; onClose: () => void; onConfirm: () => void }`.

Render order-sheet item rows via `getMissingIngredientDefaults()` (Task 3's `lib/quantity.ts`) exactly as `renderOrderSheetItems()` does (lines 3947-3956). Render up to 5 `TopUpCard`s (Step 4 below). Port open/close animation (`translateY`/opacity transitions, lines 3958-3971, 3978-3984) as CSS transitions driven by the `open` prop plus a brief `useState`-delayed unmount for the closing transition. Port swipe-down-to-dismiss (lines 3994-4001) via `onTouchStart`/`onTouchEnd` handlers computing `clientY` delta > 80px.

- [ ] **Step 4: `TopUpCard.tsx`**

Port `templates/index.html:3927-3943, 928-951` (card markup/CSS). Props: `{ item: TopUpSuggestion }`. On mount, fetch `/api/ingredient-image?name=${simplifyIngredientName(item.name)}` (mirrors `loadTopUpImage()`, lines 3010-3036) and, if found, preload via a throwaway `Image()` before swapping the visible `<img src>` — show `getEmojiForIngredient(item.name)` as the permanent fallback underneath (`opacity` cross-fade on the real image once/if it loads, same as the original).

- [ ] **Step 5: Verify**

Run: `cd frontend && npm run dev` with mock checklist/top-up data.
Expected: choice card shows correct missing-items summary text and hides the reasoning line for internal-fallback-flavored text; spotlight glow follows the cursor over each button; tapping "Order missing items" opens the bottom sheet with the right item list and up to 5 top-up cards (photos load in, falling back to emoji on failure — test by temporarily breaking the Unsplash key); swipe-down and backdrop-tap both close the sheet.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/foodEmoji.ts frontend/components/results/ChoiceCard.tsx frontend/components/results/OrderBottomSheet.tsx frontend/components/results/TopUpCard.tsx
git commit -m "feat: port choice card, order bottom sheet, and top-up cards"
```

---

## Task 11: Order result states (cook / placed / auth / error) + Toast

**Files:**
- Create: `frontend/components/results/OrderResultCard.tsx`
- Create: `frontend/components/results/Toast.tsx`
- Create: `frontend/hooks/useToast.ts`

**Interfaces:**
- Consumes: `state.orderResult`, `state.scanError` from `useScanStream` (Task 3)
- Produces: presentational component + `useToast(): { message: string | null; show: (msg: string) => void }` — the latter consumed by `ResultTabBar`'s locked-tab click (Task 7) and by `resetToLanding`-style flows in `page.tsx` (Task 14).

- [ ] **Step 1: `useToast.ts`**

```ts
'use client';
import { useState, useCallback, useRef } from 'react';

export function useToast() {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  const show = useCallback((msg: string) => {
    setMessage(msg);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 3000);
  }, []);

  return { message, show };
}
```
Port of `showToast()` (lines 3170-3176).

- [ ] **Step 2: `Toast.tsx`**

Port `templates/index.html:2077` and CSS (lines 1670-1677). Props: `{ message: string | null }` — visible (via CSS class) whenever `message` is non-null.

- [ ] **Step 3: `OrderResultCard.tsx`**

Port the four terminal states from `handleEvent()`'s `cook_confirmed`/`step3`/`error`/`auth_required` branches (lines 4637-4714) and their CSS (`.cook-card` lines 981-985, `.order-card`/`.order-row` etc. lines 968-979, `.error-card` lines 987-1004, `.auth-card`/`.auth-cta` lines 953-966). Props:
```ts
{ result: ScanState['orderResult']; resultsAlreadyShown: boolean; onRetry: () => void }
```
- `cook_confirmed` → "You're all set!" cook-card (lines 4637-4646)
- `order_placed` → order-confirmed card with order ID, platform, items (comma-joined), ETA (lines 4653-4664)
- `cook_no_order` (the `step3`/`decision==='cook'`/`!placed` branch, lines 4665-4671) → "Time to cook!" cook-card
- `error` → render the **full scan-failed card** (`.scan-state-card` with retry button, lines 4687-4692) when `!resultsAlreadyShown`, or the **inline error-card** (lines 4686) when `resultsAlreadyShown` — this replicates the branch at line 4684 exactly, with `resultsAlreadyShown` passed down from `page.tsx`'s knowledge of `state.phase`.
- `auth_required` → the Swiggy-connect card with `<a href="/auth/login">` (lines 4702-4708) — this is a real link (not a fetch), so it performs the full OAuth redirect exactly as the original.

- [ ] **Step 4: Verify**

Run: `cd frontend && npm run dev` cycling through all five `result` prop values via a temporary debug control.
Expected: each state renders pixel-equivalent to the original; the error state correctly switches between full-card and inline-card based on `resultsAlreadyShown`; the auth-required card's link navigates to `/auth/login` (verify it 302s toward `mcp.swiggy.com` — can confirm without completing real OAuth).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/results/OrderResultCard.tsx frontend/components/results/Toast.tsx frontend/hooks/useToast.ts
git commit -m "feat: port order result states (cook/placed/auth/error) and toast"
```

---

## Task 12: Recipe tab — YouTube carousel + steps

**Files:**
- Create: `frontend/hooks/useYoutubeVideos.ts`
- Create: `frontend/components/results/YoutubeCarousel.tsx`
- Create: `frontend/components/results/RecipeStepsSection.tsx`
- Create: `frontend/components/results/MealSuggestionsSection.tsx`

**Interfaces:**
- Produces: `useYoutubeVideos(): { fetch: (dishName: string) => Promise<{ videos: Video[]; first_thumbnail: string }> }` (module-level cache keyed by dish name, shared with `DishHeroSection` from Task 8 by passing `fetch(dishName).then(d => d.first_thumbnail)` as the `fetchYoutubeFirstThumbnail` callback).

- [ ] **Step 1: `useYoutubeVideos.ts`**

```ts
'use client';
import { useRef, useCallback } from 'react';

interface YoutubeVideo { id: string; title: string; channel: string; thumbnail: string; embed_url: string; }
interface YoutubeData { videos: YoutubeVideo[]; first_thumbnail: string; }

export function useYoutubeVideos() {
  const cache = useRef<{ dish: string; data: YoutubeData } | null>(null);

  const fetchVideos = useCallback(async (dishName: string): Promise<YoutubeData> => {
    if (cache.current?.dish === dishName) return cache.current.data;
    try {
      const res = await fetch(`/api/youtube?dish=${encodeURIComponent(dishName)}`);
      const data: YoutubeData = await res.json();
      cache.current = { dish: dishName, data };
      return data;
    } catch {
      return { videos: [], first_thumbnail: '' };
    }
  }, []);

  return { fetchVideos };
}
```
Port of `fetchYoutubeVideos()` caching (lines 3475-3489). **Instantiate this hook once at the `page.tsx` level (Task 14) and pass it down to both `DishHeroSection` and `YoutubeCarousel`** so they genuinely share one cache/one API call, matching the original's shared `cachedYoutubeDish`/`cachedYoutubeData` module-level variables.

- [ ] **Step 2: `YoutubeCarousel.tsx`**

Port `templates/index.html:3378-3448` and CSS (lines 691-748). Props: `{ dishName: string; fetchVideos: (dish: string) => Promise<YoutubeData> }`. Fetch on mount/`dishName` change; render empty-state (`Youtube` lucide icon + "No video found for this dish") if zero videos, else the main `<iframe>` player + up to 4 thumbnail cards. `switchYouTubeVideo()` (lines 3428-3448) becomes local `activeIndex` state driving the iframe `src` (append `&autoplay=1`) and the "PLAYING" badge's position.

- [ ] **Step 3: `RecipeStepsSection.tsx`**

Port `templates/index.html:3355-3372, 3491-3497` and CSS (lines 666-689). Props: `{ steps: string[] }`. Local `expanded` state (default `false`, matching `recipeStepsExpanded` starting `false` at line 3205) toggled by the header button, driving `max-height`/rotation CSS transitions exactly as the original (`.recipe-steps-list.collapsed`).

- [ ] **Step 4: `MealSuggestionsSection.tsx`**

Port `templates/index.html:2045-2048, 4569-4586` and CSS (lines 762-786). Props: `{ suggestions: MealSuggestion[]; recommendedMeal: string | null }`. Only rendered (by `page.tsx`, Task 14) when `suggestions.length > 1`, matching `mealSuggestionsSection.classList.toggle('hidden', ev.suggestions.length <= 1)` (line 4585).

- [ ] **Step 5: Verify**

Run: `cd frontend && npm run dev` with mock YouTube API data (or point at a real `localhost:8000` if `YOUTUBE_API_KEY` is set).
Expected: carousel shows main player + up to 4 thumbnails, clicking a thumbnail swaps the iframe `src` with `autoplay=1` and moves the "PLAYING" badge; recipe steps expand/collapse smoothly; meal suggestions grid only appears with 2+ suggestions.

- [ ] **Step 6: Commit**

```bash
git add frontend/hooks/useYoutubeVideos.ts frontend/components/results/YoutubeCarousel.tsx frontend/components/results/RecipeStepsSection.tsx frontend/components/results/MealSuggestionsSection.tsx
git commit -m "feat: port YouTube carousel, recipe steps, and meal suggestions"
```

---

## Task 13: `page.tsx` — wire everything together

This is the task that replicates the old file's `startScan()`/`resetToLanding()`/`handleEvent()` orchestration (the parts not already pushed into hooks) as one top-level component's render logic + effects.

**Files:**
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: every hook and component from Tasks 1–12.
- Produces: the full working app.

- [ ] **Step 1: Compose state**

```tsx
'use client';
import { useState, useCallback } from 'react';
import { useScanStream } from '@/hooks/useScanStream';
import { usePhotoUpload } from '@/hooks/usePhotoUpload';
import { useYoutubeVideos } from '@/hooks/useYoutubeVideos';
import { useToast } from '@/hooks/useToast';
import { getItemsToOrder } from '@/hooks/useRecipeChecklist';
// ...component imports

export default function Page() {
  const [targetDish, setTargetDish] = useState('');
  const [servings, setServings] = useState(2);
  const [tab, setTab] = useState<'order' | 'recipe'>('order');
  const [photoDetectionRevealed, setPhotoDetectionRevealed] = useState(false);
  const [orderSheetOpen, setOrderSheetOpen] = useState(false);
  const [lightboxOpen, setLightboxOpen] = useState(false);

  const photos = usePhotoUpload();
  const scan = useScanStream();
  const youtube = useYoutubeVideos();
  const toast = useToast();

  const heroPhotoUrl = photos.thumbnailUrls[0] ?? null; // used both for PhotoScanScreen and, once revealed, FridgeSummaryHeader's thumb

  const handleGetRecipe = useCallback(() => {
    setTab('order');
    setPhotoDetectionRevealed(false);
    if (photos.photos.length > 0) {
      scan.startScan('photo', { files: photos.photos, targetDish, servings });
    } else {
      scan.startScan('recipe', { targetDish, servings });
    }
  }, [photos.photos, targetDish, servings, scan]);

  const handleRevealComplete = useCallback(() => setPhotoDetectionRevealed(true), []);

  const handleResetToLanding = useCallback(() => {
    scan.reset();
    photos.clear();
    setTab('order');
  }, [scan, photos]);

  // ...
}
```

- [ ] **Step 2: Phase-driven top-level render**

```tsx
const showLanding = scan.state.phase === 'idle';
const showLoadingOverlay = scan.state.phase === 'loading';
const showPhotoScan = scan.state.phase === 'photo-scanning' && !photoDetectionRevealed;
const showResults = scan.state.phase === 'results' || (scan.state.phase === 'photo-scanning' && photoDetectionRevealed);

return (
  <div className="page">
    <AppHeader />
    {showLanding && (
      <Landing
        targetDish={targetDish} onTargetDishChange={setTargetDish}
        servings={servings} onServingsChange={setServings}
        photos={photos}
        onGetRecipe={handleGetRecipe}
        submitState={scan.state.phase !== 'idle' ? 'loading' : 'ready'}
      />
    )}
    <LoadingOverlay
      visible={showLoadingOverlay}
      hasPhoto={scan.state.hasPhoto}
      headlineText={scan.state.hasPhoto ? 'Reading your fridge' : `Looking up ${targetDish}`}
    />
    <PhotoScanScreen
      visible={scan.state.phase === 'photo-scanning'}
      photoUrl={heroPhotoUrl}
      thumbUrls={photos.thumbnailUrls}
      detectedIngredients={scan.state.detectedIngredients.length ? scan.state.detectedIngredients : null}
      onRevealComplete={handleRevealComplete}
      onRetry={handleGetRecipe}
    />
    {showResults && (
      <Results
        state={scan.state}
        tab={tab} onTabChange={setTab}
        onLockedTabClick={() => toast.show('Still loading your recipe...')}
        heroPhotoUrl={heroPhotoUrl}
        lightboxOpen={lightboxOpen} onOpenLightbox={() => setLightboxOpen(true)} onCloseLightbox={() => setLightboxOpen(false)}
        onToggleChecklistItem={scan.toggleChecklistItem}
        onOrderGroceries={() => setOrderSheetOpen(true)}
        onOrderDish={() => scan.placeOrder('order_dish', scan.state.recommendedMeal ?? '', [])}
        orderSheetOpen={orderSheetOpen}
        onCloseOrderSheet={() => setOrderSheetOpen(false)}
        onConfirmOrderSheet={() => { setOrderSheetOpen(false); scan.placeOrder('order_groceries', scan.state.recommendedMeal ?? '', getItemsToOrder(scan.state.checklist).map(i => i.name)); }}
        onRetry={handleResetToLanding}
        fetchYoutubeVideos={youtube.fetchVideos}
      />
    )}
    <Toast message={toast.message} />
  </div>
);
```

This mirrors, at the composition level, the phase transitions the old file drove imperatively: `startScan()` hiding landing + showing loading (lines 4033-4041), `step1` handing off to either the photo-scan reveal or immediate results (lines 4543-4549), `transitionToResults()`'s reveal handoff (Task 7's simplified crossfade), and `complete`/`error`/`auth_required` all converging on `revealResultsSection()` (the `showResults` boolean here, matching the safety-net idempotency of the original — lines 4614-4624, 4694-4695, 4710-4711).

- [ ] **Step 3: Fold in the "meal cards only with 2+ suggestions" and "checklist section empty when no recipe_ingredients" conditionals**

Directly translate lines 3219-3223 (empty `recipe_ingredients` → no checklist rendered, no crash) and line 4585 (`suggestions.length <= 1` → no meal cards section) as plain `{condition && <Component/>}` guards inside the `Results` sub-component.

- [ ] **Step 4: Verify — build check**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: clean TypeScript compile and successful production build with no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/page.tsx
git commit -m "feat: wire up full app orchestration in page.tsx"
```

---

## Task 14: End-to-end manual verification

No new files — this task is the walkthrough the user explicitly asked for instead of unit tests, run against the real backend.

- [ ] **Step 1: Start the backend**

Run (from repo root, in a separate terminal): `uvicorn app:app --host 0.0.0.0 --port 8000 --reload`
Confirm `.env` has whatever subset of `GOOGLE_API_KEY`/`YOUTUBE_API_KEY`/`UNSPLASH_ACCESS_KEY`/`SWIGGY_CLIENT_ID` is available; note in the final report which integrations were actually exercised live vs. degraded to their graceful-fallback path (empty video list, placeholder hero image, etc.) due to a missing key.

- [ ] **Step 2: Start the frontend**

Run: `cd frontend && npm run dev` (defaults to `localhost:3000`, proxying to `:8000` per `next.config.js`).

- [ ] **Step 3: Walk the full flow and record results**

Exercise, in order, and note pass/fail + anything only checkable visually:
1. Landing screen loads; theme toggle switches instantly with no flash; typing a partial dish name shows filtered, keyboard-navigable autocomplete; a Popular Right Now card fills the input.
2. Servings selector changes the active pill.
3. Direct dish entry (no photo) → Get Recipe → loading overlay with staged checklist → results appear.
4. Photo scan: attach up to 3 photos (thumbnail strip + "+" appears, caps at 3) → Get Recipe → photo-scan screen with scan-line sweep → detected items stagger in → handoff to results with fridge thumbnail visible in the results header.
5. Order tab: sticky summary bar text, fridge chips dropdown (open/close, matched-vs-other split if applicable), fridge photo lightbox, ingredient checklist scroll behavior on both a short list and a long one (verify internal scroll + fade, sticky header stays put), staple uncheck-to-order behavior, Instamart/Swiggy choice cards with "Powered by Swiggy" text, order bottom sheet open/close/swipe-dismiss with top-up cards.
6. Recipe tab: unlocks (dot changes from pulsing to static) once `awaiting_user_choice` fires; YouTube carousel plays/swaps videos; "How to make it" steps expand/collapse.
7. Dish hero image: confirm via Network tab that `/api/dish-image` (Unsplash) is tried first, `themealdb.com` second, `/api/youtube` third, placeholder last.
8. Error path: kill the backend mid-scan, confirm the API-error card + retry button appears and retry actually resubmits.
9. Swiggy auth: if `SWIGGY_CLIENT_ID` isn't configured for a real test account, explicitly report this as **not verified live** — confirm only that clicking "Connect with Swiggy" correctly redirects to `mcp.swiggy.com/auth/authorize` with a PKCE challenge, without completing the full round trip.

- [ ] **Step 4: Write up findings**

Report back (this is the deliverable of this task, not a commit): folder structure recap, run instructions for both servers, a 1:1-ported vs. re-architected list (the SSE hook, the checklist-scroll fix already being correct in source, the FLIP-clone→crossfade simplification from Task 7, the Smart Cart / progress-step dead-code exclusions), and exactly what was/wasn't verified live per Step 3.

---

## Self-Review Notes

- **Spec coverage:** Landing (Task 5), photo scan (Task 6), results shell/sticky/tabs (Task 7), dish hero waterfall fix (Task 8), scrollable checklist fix (Task 9), order tab choice/sheet/top-up (Task 10), order result states (Task 11), recipe tab (Task 12), SSE consumption (Task 3), dark/light mode (Task 1), animations (ported per-component alongside their markup throughout), accessibility (44px targets and focus rings are already plain CSS in the ported `globals.css`/component CSS — no separate task needed since nothing about the React port changes hit-target sizing or `:focus-visible` behavior; keyboard nav on autocomplete is explicit in Task 5 Step 4). All covered.
- **Placeholder scan:** every code block above is complete, runnable code or a named exact line range to port — no "TODO"/"add validation" left unfilled.
- **Type consistency:** `ChecklistItem`, `ScanEvent`, `ScanState`, `TopUpSuggestion`, `MealSuggestion`, `DetectedIngredient` are defined once in `lib/types.ts`/Task 3 and reused verbatim by name in every later task.
