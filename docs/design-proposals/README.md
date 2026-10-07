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


# Landing page, 2026-10 (direction A chosen)

The landing page read as one form: dish box, servings, a big orange Get Recipe, then a smaller Scan Fridge. A first-time user
could not tell that the dish and the fridge photo are independent and both optional, and Scan Fridge only added a photo (the scan
started from Get Recipe, which was labelled for the dish route). Pressing Get Recipe with nothing entered also ran a plan on an
empty fridge and returned generic dishes.

- `landing-options.html` is the mockup page for the three options considered, using the app's real tokens (A: "or" divider and
  grouped routes, B: fridge leads, C: choice tiles). Open it with `?theme=dark|light&opt=cur|A|B|C|w320`.
- `landing-options-*.jpg` are its renders (current layout and each option, dark and light at 390px, plus the 320px comparison).
- `landing-built-390-*.jpg` and `landing-built-320-*.jpg` are the shipped result in the four input states (nothing, dish only,
  fridge photo only, both), dark and light.

A was chosen because it fixes all of it with the least change: two labelled, optional routes joined by "or", a fridge card that
states the outcome, servings next to the button, and one button whose label follows the input ("Get recipe", "Find dishes from
my fridge", "Get recipe using my fridge"). B puts the fridge first at the cost of burying the dish route; C is the clearest but
costs an extra tap and more state.

The costs: "Popular right now" now starts about 180px lower (828px against 646px at 390 wide, 859px against 679px at 320), so it
takes one swipe to reach. The main button is disabled, with a line saying why, until there is a dish or a photo. A whitespace-only
dish counts as empty, and the dish is trimmed before it is sent. Enter in the dish box does not submit (it never did).
