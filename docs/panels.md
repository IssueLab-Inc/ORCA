# ORCA panels: docking, floating and pop-out windows

The desktop's panels can be docked, collapsed, floated and opened in a window of their own, so the model, and the
plans, sections and elevations beside it ([views.md](views.md)), get the room they need. Phones and tablets keep their
layouts ([mobile.md](mobile.md)).

It is new work, written for ORCA during the event. No code from other products.

## Decisions (owner, Oct 30)

- **A real docking library**, not a home-made float: [dockview](https://github.com/dockview/dockview) 8.5.1 (MIT).
- **Only its free core.** Its paid package (`dockview-enterprise`: auto-hide side bars, layout undo, snapping
  guides, pinned tabs) is never added: the public repo must build for anyone, the same reason Telerik and Blazor were
  turned down. A web test fails if the dependency or one of those options appears.
- **Pinned:** `dockview-react` 8.5.1 exactly, and `overrides` holds `dockview` and `dockview-core` at 8.5.1 too (newer
  releases came almost daily and were under two weeks old).
- **Before the Nov 3 freeze, looking like today.** The default layout is the classic one as panels, so the tour, the
  golden path and the demo pictures still read the same.
- **Pop-out windows in the first version.**

## What there is

| Panel | Holds | Default place |
|---|---|---|
| Model | The stage: the canvas, PR 49's view panes, the rail, the element card, the pilot pill, toasts | the middle; never moves, floats or pops out |
| Coordination | The left pane: the clash list and Insights (their own tabs), or the check's set-up card | left side bar |
| Clash | The Clash tab's body | right side bar |
| Plan | `PlanPanel` or `ContextPlan` | right side bar (tab) |
| Chat | `ChatPanel` | right side bar (tab) |
| Activity | The agent's activity table | bottom side bar |
| Properties | The selected element's card and everything its model says about it (below) | floating at the model's top right, opened by the first selection |

- **Side bars** (dockview's edge groups) hold their tabs along the top while open, as the classic panes did. The
  button at the end of the tabs collapses a bar to a strip of its tabs down its outer edge (the bottom one to a strip
  along the bottom); a click on a tab in the strip opens it again. A click on an open bar's active tab never closes it
  (dockview would): the tour clicks tabs, and a tab should never hide the panel it names.
- **Floating:** the second button (or Float on a tab's right-click menu) floats the panel at the model's top right;
  drag it by its tabs, resize it from its edges, drop a tab anywhere to dock it again.
- **Pop out:** the third button (or Open in New Window) moves the panel into a window of its own, for a second
  screen. Closing that window puts the panel back.
- **Put it back** (a button, and on the right-click menu) returns a floating, popped-out or moved panel to its side
  bar, in its place among the tabs.
- **Close** is on the right-click menu. **Panels and layout** (the header's layout button) shows any panel, closed
  or not, resets the layout, and switches to the **Classic layout** (the fixed panes of before, `sightline.dock.classic`).
- The layout is kept in this browser (`sightline.dock.v1`, dockview's `toJSON`, saved a moment after each change and
  after a collapse). A layout that can't be ORCA's (another version, a panel it doesn't have, the model anywhere but the
  middle) gives way to the default. Pop-out windows come back docked after a reload: a browser opens a window only on
  a click.

## Properties

A click on any element selects it (blue in every view). In a see-through view with a clash in focus, a click that
meets nothing in focus selects the faded element behind (`pickAt` with `ghosts`), so context is never out of reach.

- **On a desktop** the selection opens the Properties panel, floating where the old card was; drag it, dock it in a
  side bar or beside the model, or open it in its own window, and later selections fill it wherever it is. Its ✕
  closes it; Esc clears the selection (the panel then says to click an element).
- **Classic layout, tablets and phones** keep the card over the model, with an **All properties** section.
- **What it shows:** the card as before (class, name, GlobalId, tag, level, file, links, Set as A / B, Zoom, Hide,
  Isolate, Section box, Hide / Isolate the class), then the element's type, materials, size (mm, from the scene's
  box), attributes, every property set (with what its type gives it) and every quantity set in SI with its unit. A
  filter narrows the rows; a click on a value copies it.
- **From the server:** `GET /api/scenes/{sid}/elements/{gid}/properties` (`properties.py`), read from the scene as it is
  now, so a kept fix's new pieces have theirs. The demo models carry their own notes in a property set named for the
  tool that generated them: it shows as **Model data**, without the scripting note on the clash host (it says the
  answer key was planted).

## How it works

**App keeps its state; the dock only moves elements.** `App.tsx` owns about a hundred pieces of state and draws every
panel itself. Rather than split it into components that take all of that as props, each panel's content is drawn
into a **slot** (`dock.tsx`, `usePanelSlots`): one detached element per panel, made once for the page's life, that
`App` portals into (`inSlot`). The dock's panel component is a few lines that put the slot into its own element
(`SlotHost`). A panel moving, floating, popping out or being re-created by dockview only moves the slot, so nothing
`App` draws is remounted: the chat keeps its history and a running proposal keeps streaming into the Clash panel
wherever it is (checked: floated, proposed, put back mid-run, accepted).

**The classic layout uses the same slots.** On a phone, a tablet, the landing, or with the Classic layout switch on,
`App` renders the old grid and places the slots with `SlotHost` as well. There the slot and its host are
`display: contents`, so what they hold is a grid item exactly as before and the classic CSS (sheet, drawer, resizers)
did not change. Crossing 1100 px moves slots between the dock and the grid; nothing remounts.

**The right-hand tab.** `tab` is still `App`'s. `setTab` also asks the dock to show that panel (`DockHandle.show`:
reopen a closed panel at home, open its collapsed bar, bring its window forward). A click on a dock tab is the user
choosing it: Clash, Plan and Chat run their classic tab handlers (`showClashTab`, `showPlanTab`, `showChatTab`), so the
viewer follows as before. Whatever else brings one of the three to the front (a restored layout, closing its
neighbour, a drag, Put it back) updates `tab` too (`onShown`, from dockview's active panel). In the dock every panel draws its content whatever `tab` says; Clash and Chat can both be on
screen. The dock tabs show what the classic tabs did (the option count, the plan's spinner) and carry the tour's
`data-tour` names.

**Panels behind another tab stay in the page,** hidden (dockview's `renderer: "always"`), so the tour finds what it
points at and its `reveal` shows the panel it is in. When the tour starts, closed panels open again, panels in their
own windows come back and collapsed bars open (`DockHandle.gather`): the tour reads the main page.

**Scroll.** Moving an element resets its scrollers. Each slot remembers where its scrollers were (a capture-phase
scroll listener, ignoring a squeezed scroller) and puts them back after a move or when its bar opens again.

**Pop-out windows.** dockview opens `/popout.html` (`web/public/popout.html`, served by Vite and by the server's static
mount) and copies the page's styles into it. React's listeners sit on the slot, so clicks work there. What was bound to
the main window now isn't: `App`'s keys listen on every pop-out window too, each window gets its own `Tooltips` layer
(`doc` prop), `Popover` listens on its own document, the clash list finds its rows in its own document, and hands-free
voice stops when the chat's own window is put away. Dialogs (the image, the report, requirements) still open in the
main window.

## Found on the way

- **A floating panel over the model left a hole below it** in headless Chromium: an opaque scrolling panel culled the
  WebGL canvas under it by its whole content height, so the stage background showed through. Docked slots and the
  panes in them draw no background of their own (dockview's group paints the panel). Seen and fixed Oct 30.
- **StrictMode** runs an effect's cleanup and the effect again at once; the dock's subscriptions are let go only when
  `DockHost` really unmounts, and then only the handle it published (`onGone`), with its pop-out windows.
- **From the review (Oct 30):** a floating or pop-out window split into several groups is saved as a grid, not a group
  (`windowViews`), so a reload kept it and a pop-out's panels all go home; `fromJSON` brings the model's lock back as
  plain `true`, so it is set again; a new `components` object on each render made dockview lay out again several times a
  second while an agent worked; a tab's padding was outside the part that sees clicks; the scroll memory let go of
  scrollers React removed only on a move.

## Not done (later)

- Plan, section and elevation views as panels of their own: they share one canvas (views.md), so it would take a canvas
  behind the whole dock. They stay inside the Model panel with their own Single / Two / Quad.
- Restoring pop-out windows after a reload (browsers block it).
- Docking on tablets.

## Tests and checks

- `server/tests/test_properties.py` (5) and `web/tests/properties.test.mjs` (4): what the panel reads and shows.
- `web/tests/dock.test.mjs` (9): every panel has a home, which saved layouts load (a window split in several groups
  too), the widths the classic panes and the side bars share, what was popped out goes back to its bar, storage and
  versions, what showing a panel takes, and the free-core-only rule.
- Browser (Playwright, Northbank, 1440×900): the default layout; float, collapse, reopen, tab clicks; pop out Chat
  (styles, typing, a tooltip, M from the window reaching the page), close the window, pop out again; reload with a
  popped-out, a floating and a collapsed panel; Reset; Classic; the tour bringing panels home; #1 proposed with the
  Clash panel floating, put back mid-run, accepted; tablet (1024) and phone (390) unchanged, no sideways scroll.
