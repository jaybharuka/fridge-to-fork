# UI defaults for Fridge to Fork

Use this when briefing design work. Each rule was checked against the cited source; rules with no real backing were dropped (see the end).

**The app:** mobile first, one 480px column with 20px gutters, designed at 320px and 390px wide. Light is `:root`, dark is `[data-theme="dark"]`, and the theme follows the OS setting until the user toggles it. Rubik for headings (600 to 800), Nunito Sans for body (14px, line height 1.5). Colour comes from `--bg`, `--bg-secondary`, `--bg-card`, `--border`, `--text-primary`, `--text-secondary`, `--text-muted` and the orange accent `--orange` (#FC8019), `--orange-dark`, `--orange-light`. Spacing is `--space-1` to `--space-12` (4 to 48px), type is `--text-xs` to `--text-4xl`.

## Contrast
- Text needs 4.5:1 against the surface it sits on (page, card or secondary grey); large text (24px, or 18.66px bold) needs 3:1. Placeholder text counts. Disabled controls and logos are exempt. Do not round: 4.499 fails. [WCAG 1.4.3]
- Anything that identifies a control or carries meaning (icon, field border, checkbox, focus ring) needs 3:1 against its neighbour. Disabled controls are exempt. [WCAG 1.4.11]
- Never signal state by colour alone: add text or an icon. [WCAG 1.4.1]
- For this app: #FC8019 is strong on dark (6.5 to 7.5:1) but only 2.55:1 on light, and white text on it is also 2.55:1. On orange fills use #1A1A1A text (6.8:1) or a fill near #B85D12 with white text. Orange text on light needs about #AE5811 or darker.
- Shipped values (light / dark): `--text-muted` #707070 / #888888 (4.7 to 5.4:1 on page, card and grey); `--success-text` #1B7A43 / #2ECC71 and `--red-text` #C41E1E / #FF8F8F for status text (use these, never `--success` or `--red`, as text colours); `--border-control` #8E8E8E / #6E6E6E for input borders (3:1 or more); `--focus-ring` #D46C15 / #FC8019. Orange fills and orange text are unchanged until a choice is made in `docs/design-proposals/orange-contrast.md`.
- Check every new colour pair in both themes before it ships.

## Touch targets
- Aim for 44 by 44 CSS px on every tappable control. [Apple HIG default 44pt; WCAG 2.5.5, level AAA]
- Never below 24 by 24 CSS px. [WCAG 2.5.8, level AA; Apple's smallest control is 28pt]
- The visible control can be smaller than the hit area: Material draws a 40px button with a 48px touch area. Do the same with padding or a pseudo-element. [material-web touch-target]
- Links inside a sentence are exempt. [WCAG 2.5.8]

## Type and layout
- Smallest text is 11px. [Apple HIG minimum 11pt; WCAG sets no minimum]
- Content must work at 320px wide with no sideways scroll. [WCAG 1.4.10]
- Never lock zoom or fix the height of a text container; text must grow to 200%, and layouts must survive user line height 1.5, letter spacing 0.12em and word spacing 0.16em. [Apple HIG 200%; WCAG 1.4.12]
- Lines of 80 characters or fewer, paragraph line height 1.5. Tighter is fine on large headings (the 1.15 to 1.25 now used on 22 to 36px titles). [WCAG 1.4.8, level AAA]

## States
- Every control shows a keyboard focus ring. [WCAG 2.4.7, level AA] A solid 2px outline is the simplest way to meet 2.4.13, and it must have 3:1 against the surface behind it (the orange ring does on dark; on light the ring is `--focus-ring`, #D46C15, 3.5:1 on white). Never set `outline: none` without an equally visible replacement. [WCAG 2.4.13, 1.4.11]
- Put hover effects inside `@media (hover: hover)` so touch screens never get a stuck hover. [MDN hover]
- For hover and press feedback, Material uses an overlay: 8% for hover, 12% for focus and pressed. A reference value, not a requirement. [material-web md-sys-state]
- Disabled: about 38% opacity for content and 12% for a filled container, and the control should really be disabled, not just dimmed. [material-web md-comp-filled-button]

## Motion
- Small state changes 100 to 200ms, sheets and panels 250 to 400ms. Keep normal UI under 500ms (a house limit; Material allows up to 1000ms for full-screen moves). Linear progress bars are the exception. [Material 3 duration tokens]
- Standard easing `cubic-bezier(0.2, 0, 0, 1)`, entering elements `(0, 0, 0, 1)`, leaving ones `(0.3, 0, 1, 1)`. The older `(0.4, 0, 0.2, 1)` used here is Material's legacy curve and is fine. [material-web md-sys-motion]
- Under `prefers-reduced-motion: reduce`, remove, shorten or replace non-essential motion, including smooth scrolling in CSS and in `scrollIntoView`. [WCAG 2.3.3, level AAA; MDN prefers-reduced-motion]

## Dropped (no real backing)
Card radius of 8px at most (this app uses 14 to 24px), an 8% hover lightness change, avoiding pure white on dark, the letter-spacing by size table, 65ch line length, a 10px text minimum, a 16px icon minimum, icon stroke weights, and everything about Pencil.dev, `.pen` files, scaffolds and sidebar layouts.

Sources: WCAG 2.2 Understanding pages 1.4.1, 1.4.3, 1.4.8, 1.4.10, 1.4.11, 1.4.12, 2.3.3, 2.4.7, 2.4.13, 2.5.5, 2.5.8 (w3.org/WAI/WCAG22/Understanding); Apple Human Interface Guidelines, Accessibility; Material Web token and touch-target source (github.com/material-components/material-web); MDN `prefers-reduced-motion` and `hover`.

Some rules were adapted from PencilPlaybook (MIT, stevembarclay/pencilplaybook) after verification.
