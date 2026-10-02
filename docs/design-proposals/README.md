# Header redesign, 2026-10 (direction C chosen)

The results-screen top bar was redesigned from four identical icon circles (status chip, Instamart orders, Food orders,
theme toggle, with the wordmark hidden on phones) to: back chevron | centred brand lockup | one account menu.

- `header-options.html` is the mockup page for the three options considered, using the app's real tokens
  (A: refined bar, B: branded lockup with a grouped tool pill, C: centred brand with one account menu).
- `header-options-1-current-and-A.png` and `header-options-2-B-and-C.png` are its renders (dark and light, 390px).
- `built-390.png` and `built-320.png` are the shipped result (dark and light, menu open) at two phone widths.

C was chosen for its calmer resting state; the cost is one extra tap to reach orders or the theme switch.
The first build hid the menu's top rows behind the sticky summary bar; fixed by raising the header's z-index to 250
(above the summary bar at 200, below sheets at 500 and the lightbox at 999).
