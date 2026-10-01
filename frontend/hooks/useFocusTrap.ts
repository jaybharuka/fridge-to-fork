'use client';

import { useEffect, useRef } from 'react';

// Every focusable element a keyboard user could actually reach — the
// standard WAI-ARIA APG list, minus anything explicitly pulled out of tab
// order (tabindex="-1").
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusableElements(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)].filter(
    el => el.offsetParent !== null // skip anything hidden (display:none ancestor)
  );
}

/** The actual trap decision, kept DOM-free and generic so it's unit-testable
 *  without a browser/jsdom (this repo has no DOM-testing infra — see
 *  hooks/useFocusTrap.test.ts). Returns the element Tab/Shift+Tab should
 *  jump to, or null when the default browser behavior should proceed
 *  unchanged (focus is already somewhere in the middle of the list). */
export function nextTrapTarget<T>(focusable: T[], current: T | null, shiftKey: boolean): T | null {
  if (focusable.length === 0) return null;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const currentIndex = current === null ? -1 : focusable.indexOf(current);

  if (shiftKey) {
    return current === first || currentIndex === -1 ? last : null;
  }
  return current === last || currentIndex === -1 ? first : null;
}

/**
 * Standard WAI-ARIA APG dialog focus-trap pattern — the one piece both of
 * this app's modal surfaces (Sheet.tsx, FridgeLightbox.tsx) need and
 * neither had (ui-ux-pro-max audit phase 2 flagged this on Sheet and
 * deliberately deferred it: "a behavioral change with real risk if done
 * wrong, not simple layout/spacing" — this is that follow-up, done once,
 * shared, rather than duplicated and risked twice).
 *
 * - On `active` becoming true: remembers whatever was focused before (to
 *   restore later), then moves focus onto the container itself.
 *   `containerRef`'s element needs `tabIndex={-1}` to be focusable this
 *   way without joining the normal tab order.
 * - While active: Tab/Shift+Tab wrap at the container's first/last
 *   focusable element, recomputed on every keypress (not cached once) so
 *   it stays correct as the sheet's own content changes (e.g. switching
 *   review -> payment stage adds/removes fields).
 * - On `active` becoming false: restores focus to whatever was focused
 *   before, if that element still exists in the DOM.
 */
export function useFocusTrap(active: boolean, containerRef: React.RefObject<HTMLElement | null>) {
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return;

    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const container = containerRef.current;
    container?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Tab' || !container) return;
      const focusable = focusableElements(container);
      if (focusable.length === 0) {
        e.preventDefault();
        return;
      }
      const target = nextTrapTarget(focusable, document.activeElement as HTMLElement | null, e.shiftKey);
      if (target) {
        e.preventDefault();
        target.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      const restoreTo = previouslyFocused.current;
      if (restoreTo && document.contains(restoreTo)) restoreTo.focus();
    };
  }, [active, containerRef]);
}
