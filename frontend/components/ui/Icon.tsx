import type { LucideIcon as LucideIconType } from 'lucide-react';

export type IconSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';

interface IconProps {
  /** The lucide-react icon component itself (e.g. `icon={ShoppingCart}`), not a rendered element. */
  icon: LucideIconType;
  size?: IconSize;
  className?: string;
  /** Set when the icon carries meaning on its own (no adjacent label text) — omit for a purely decorative icon. */
  'aria-label'?: string;
}

const SIZE_VAR: Record<IconSize, string> = {
  xs: 'var(--icon-xs)',
  sm: 'var(--icon-sm)',
  md: 'var(--icon-md)',
  lg: 'var(--icon-lg)',
  xl: 'var(--icon-xl)',
};

/** The one way to size a lucide icon in this app. Icon audit (2026-09) found lucide's own `size` prop and every
 *  per-component CSS class (`.statusIcon`, `.bigIcon`, etc.) silently losing to globals.css's `svg.lucide {
 *  width:1em }` — both lose the cascade to that rule, so icons actually just inherited whatever font-size happened
 *  to cascade to wherever they sat, not the size anyone wrote. Inline style is the one thing with higher specificity
 *  than that rule, so this sets size that way, from the shared --icon-* token scale (app/globals.css) rather than a
 *  one-off number, mirroring components/ui/Button + Card: one shared primitive instead of N divergent conventions. */
export function Icon({ icon: LucideIconComponent, size = 'sm', className, 'aria-label': ariaLabel }: IconProps) {
  const sizeVar = SIZE_VAR[size];
  return (
    <LucideIconComponent
      className={className}
      style={{ width: sizeVar, height: sizeVar, flexShrink: 0 }}
      aria-hidden={ariaLabel ? undefined : true}
      aria-label={ariaLabel}
    />
  );
}
