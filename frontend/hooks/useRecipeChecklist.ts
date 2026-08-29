import type { ChecklistItem } from '@/lib/types';

// Direct ports of templates/index.html:3482-3488 (buildRecipeHookText),
// 3720-3724 (toggleRecipeItem's "missing" filter, generalized here as
// getItemsToOrder for reuse by ChoiceCard/OrderBottomSheet, Task 10).
// escapeHtml calls in the original are dropped since React auto-escapes
// text content — these functions return plain strings for React to render
// as text nodes, not dangerouslySetInnerHTML.

export function getItemsToOrder(checklist: ChecklistItem[]): ChecklistItem[] {
  return checklist.filter(i => !i.checked);
}

export function buildRecipeHookText(checklist: ChecklistItem[]): string {
  const missingCount = getItemsToOrder(checklist).length;
  if (missingCount === 0) return 'Your kitchen is fully stocked for this. Time to cook.';
  if (missingCount === 1) return 'Almost there. Just one thing standing between you and this dish.';
  if (missingCount <= 3) return "You're 80% ready. Here's what's missing.";
  return "A few key ingredients away. Let's get them.";
}

export function buildMissingSummaryText(items: ChecklistItem[]): string {
  const names = items.map(i => i.name);
  if (!names.length) return 'Nothing — you have everything';
  return names.length > 3 ? `${names.slice(0, 3).join(', ')} + ${names.length - 3} more` : names.join(', ');
}
