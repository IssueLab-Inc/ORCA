# ORCA on phones and tablets: design

ORCA was built for a desktop: three columns (clash list 310 px, the model, the fix panel 380 px), picking by double
click, icon buttons that explain themselves only in hover tooltips. On a phone that was unusable (Oct 29, owner). This
is how it works on small and touch screens now, without changing the desktop. Owner decisions (Oct 29): the model
stays on screen with a **bottom sheet** over it, and **every feature stays reachable**, adapted rather than cut.

## Rules every screen follows

1. One obvious next step on screen: the sheet's peek line carries it (Open, Check, Propose fixes, Accept, Next clash).
2. Nothing only behind hover, double click or a key: every action has a visible, named control. Long press and
   double tap are shortcuts.
3. The model never disappears: the sheet stops at half the screen while the model is the point.
4. The sheet follows what happens; moving it by hand wins until the next thing happens.
5. The same words as the desktop, in the same order as the work.
6. Targets a finger can hit: 44 px (36 for small buttons) on any touch screen.

## Layouts (`web/src/layout.ts`, CSS "Responsive" at the end of `index.css`)

| Width | Layout |
|---|---|
| > 1100 px | Desktop, as before. Checked box for box against `main` at 1280, 1440 and 1920 px. |
| 761–1100 px | **Tablet** (`.app.tablet`): the model and the fix panel. The clash list is a drawer from the left (header **Clashes**, with the count); a scrim or picking a clash closes it. Report and Export stay in the header; the rest is in **Menu**. |
| ≤ 760 px | **Phone** (`.app.phone`): header (logo, fixed count, **Menu**), the model full width, the sheet. |

`useLayout()` picks the layout from the window width; `(pointer: coarse)` sets touch sizes on its own, so an iPad in
landscape (desktop width or tablet) still gets finger-sized targets. Heights use `100dvh`, and the header, sheet,
menus and dialogs keep clear of the notch and home bar (`viewport-fit=cover`, `env(safe-area-inset-*)`).

## The phone's sheet (`web/src/Sheet.tsx`)

- **Bar:** a handle, the peek line (what is happening now and one button), and the tabs **Clashes · Fix · Plan · Chat**
  with their counts. The panes under it are App's own left and right panes, re-placed by CSS: nothing remounts when the
  sheet moves, the layout changes or the phone turns (chat history, scroll positions and the viewer stay).
- **Heights:** peek (the bar only), half (55% of the screen; the model keeps the rest), full (up to the header; the
  model stays at its half size behind it). Drag the bar, flick it (one step its way), or tap the handle
  (peek → half → full → peek); arrow keys on the handle.
- **Follows activity** (`follow()` in layout.ts, one effect in App.tsx next to `viewPlan`): a report or the models open
  → Clashes at half; a clash picked → Fix at half; a proposal or plan starts → peek, so the pilot's drive is in view; the
  result → back to half, scrolled to the options. Chat keeps its tab when it selects a clash.
- **Peek line:** progress while Muse works, "1 · Offset duct up 400 mm…" with **Accept** once an option is chosen,
  "#1 fixed" with **Next clash** after, "#1 …" with **Propose fixes** when a clash is picked, Check for clashes when
  models are open with no report.

## Room for the list

The left pane over a report has two tabs, so the list never sits under three tall cards: **Clashes** (title and
test count, Triage folded to one line, the search with its filters, then the list scrolling on its own) and
**Insights** (the impact line, the run's summary with Detect again and coverage, root causes and patterns). Insights'
filter and tick buttons switch back to Clashes. On a phone the title row is hidden and the sheet's status line gives
way at full height when it has no button: an iPhone 13 at full shows 6 clashes (was 1).

## Touch

- **Picking A and B:** tap an element: its card (docked above the sheet) has **Set as A** / **Set as B**, and says what
  to do next ("A set. Now pick element B"). A long press (half a second, finger still) picks A then B like a double
  click. Hints say tap, not double-click.
- **Viewer tools:** the rail becomes **Tools** (a sheet with the view modes as labelled cards, section box, outlines,
  measure, show connections, screenshot, standard views, models shown, **Filters by property**), **Go to clash** and
  Fit. Filters open as a sheet over the model (no dock on a phone or tablet), and the colour key sits above the bottom
  sheet ([filters.md](filters.md)).
- **Tooltips:** press and hold any control with a tip to read it without doing it; a tap on an informational element
  (`data-tip-tap`: info icons, chips, requirements cells) shows its tip for a few seconds.
- **Popovers** open as sheets from the bottom with their name and a close button; they close on `pointerdown` outside.
  On a phone the sheet is rendered into the page's body, or a popover in the viewer's rail would sit under the page's
  bottom sheet.
- **Dialogs** (How it works, Requirements, Report, Connect an agent) go full screen with the title and Close pinned.
  The requirements matrix becomes a list per group ("vs MEP: Clearance 50 mm"), the detection coverage and agent
  activity tables become rows, the team table stacks. The lightbox swipes between views.
- Inputs are 16 px on a phone (iOS zooms into smaller fields). iOS cannot pick a folder, so "Upload an export folder"
  is left out there; XML files still upload.

## Tour

The tour finds the control that shows (a phone has some twice: the sheet's tabs and the pane's own), and when it is
hidden it asks App to open what hides it (`TourActions.reveal`: the sheet's tab, the drawer, the header menu). On a
phone its card spans the width above or below the control, and its copy says tap instead of click.

## Checked (Oct 29)

Playwright with device profiles (iPhone 13, iPhone SE, Pixel 7, iPad Mini portrait and landscape, desktop): no page
scrolls sideways in any state; every visible control is at least 40 px (20 px checkboxes) on touch profiles and has a
name; on iPhone 13 and Pixel 7, by touch, Open the Northbank demo → #1 → Propose fixes (live Muse Spark: "Offset duct up
400 mm through girder opening", verified) → Accept → "1 fixed" → Next clash. The machine cell opens and its clashes
select on a phone; the tour runs its first 14 steps on a phone. Recognition of real speech on a phone is still
untested here, as before.
