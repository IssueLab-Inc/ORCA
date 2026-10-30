# ORCA views: design

Two things ORCA's viewer cannot do today. Once a clash is picked there is no plain model to move around in: the view
is about that clash until another is picked. And there is one view, where coordinators read a clash the way a designer
drew it: in plan at its level, and in section through it.

This design does both. **The camera and the clash are independent:** navigate anywhere in the model with CAD-style
standard views, view cube, visual styles and visibility, with or without a clash picked, and a picked clash stays drawn
in every open view wherever it looks. **Plans, sections and elevations sit next to the 3D view, up to four at once**,
drawn like a CAD drawing (paper, linework, cut faces filled, grids and levels), and **live**: nothing is generated. Each
view is another camera over the same GPU buffers the 3D view uses. A picked pair, a trial the agent is checking, a
before/after preview and an accepted fix show in every view in the same frame.

It is new work, written for ORCA during the event. No code from other products.

## Decisions (owner, Oct 29 and 30)

- **Up to four views.** Layouts: Single, Two, Quad.
- **A toggle** decides whether drawing views follow the 3D view's Near it / Only it (today's Context / Isolate), or
  always show the full model.
- **Clip planes are the user's to set**, in plans (cut plane and bottom) and in sections (the line, far clip and crop),
  by typing a value or dragging it in another view (View range and clip planes, below).
- **Navigate anywhere, with or without a clash** (Oct 30): leaving a clash is one key or one click, the model can be
  navigated, styled and filtered with or without one, and a picked clash shows in every open view wherever each looks.
- **CAD-style 3D** (Oct 30): standard views and a view cube, perspective or orthographic, visual styles, visibility by
  model, class and level, hide and isolate.
- This document first, then a branch per slice (`feature/…`) and a PR.

## What the viewer has now (Oct 30)

- `web/src/viewer/Viewer.ts`: one `WebGLRenderer` (`preserveDrawingBuffer`), one perspective camera, `OrbitControls`
  on the canvas. One `BatchedMesh` per file (plus `glass` for see-through elements); the pair in focus is drawn as its
  own meshes over the batch buffers (`focusLayer`), with outlines through everything. Modes Shaded / X-ray / Context /
  Isolate set per-instance visibility and colour **on the batch**, so they apply to anything that draws it. Section box
  = six clipping planes shared by every material (`this.clipping`). Presets Top / Front / Right / Iso are perspective.
- Captures (`captureClash`, `thumbClash`, `capture`, `captureBuilt` for Show it built, `snapshot`) render with the 3D
  camera into the whole canvas and crop its centre square.
- A kept fix is swapped into the batches in place (`Viewer.patch`, `viewer/patch.ts`), not reloaded.
- Without a clash there is little to do: no way to leave one once picked, X-ray / Context / Isolate and the section box
  need one, nothing selected is highlighted, orbit turns about a target rather than what is under the pointer.
- Every Northbank file carries its `IfcBuildingStorey`s (Foundations −1.2, Level 01 0, Level 02 +4, Level 03 +8, Roof
  +12). The grid (`IfcGrid`, axes 1–4 and A–C, polylines in the grid's placement) is only in `Northbank-Grids.ifc`,
  which the demo does not open; it also has mesh "grid line" proxies, so opening it as a model would put them into the
  check.

## Navigate the model, with or without a clash

Today a picked clash owns the view. Nothing leaves it (Esc clears the measure, the element card and the lightbox, not
the clash), Shaded greys every other element while it is picked, X-ray / Context / Isolate do nothing without one, and
the section box only goes round one. A coordinator also walks the model with no clash in mind, and looks elsewhere
with a clash still picked. So the clash and the camera become independent.

### A clash in focus, and nothing more

- **What a picked clash is now:** its pair in red and green with outlines, the marker and its number, in every open
  view, wherever each view looks. It no longer decides the style or the visibility, and it moves the camera only
  when picked (with Fly to clash on) or on F.
- **Fly to clash** (Views popover, on by default, kept per browser in `sightline.views.fly`): picking a clash flies the
  3D view to it and sets the drawing views' defaults, as today. Off: picking only highlights it in every view and the
  camera stays (Navisworks' auto-zoom off); **F** flies when wanted.
- **The camera moves only when asked:** picking a clash (Fly on), F, H, a preset or the view cube, a saved view,
  picking an option or a plan (framed on the fix, as today), and the pilot while it drives (any camera move takes over,
  as today). Background work never moves it: re-measures, titles, thumbnails, triage, a kept fix patched in
  (`Viewer.patch`).
- **Leave the clash:**
  - **Esc**, one thing at a time: the measure, then the element card, then the lightbox, then the selected element,
    then the clash;
  - or **✕** on the clash chip at the top of the 3D pane ("#1 Supply air main × transfer girder").
  - Leaving clears the pair, its marker, its stand-ins and any preview. The camera, style and visibility stay where they
    are, the list loses its highlight, and the clash panel goes back to "Pick a clash". Fixes, reviews, triage and
    requirements are untouched.
  - While ORCA works on that clash (a proposal, plan or replay), the chip says "ORCA is working on #1" and Esc does
    not leave it; navigating still takes over from the pilot, as today.

### Navigate like a CAD tool

- **Mouse:** left drag orbits **around the point under the pointer** (the pivot moves there at the press, without a
  jump; empty sky keeps the last pivot), right or middle drag pans, the wheel zooms to the cursor (as today),
  Shift + left drag pans (trackpads). Touch as today: one finger orbits, two pan and pinch.
- **Controls:** `camera-controls` (MIT, pinned) replaces `OrbitControls` for the 3D view. It has the pivot without a jump
  (`setOrbitPoint`), dolly to the cursor, orthographic cameras, smooth moves (replacing `Viewer.flight`) and fitting a
  box with padding. The Viewer keeps its own API (`flyTo`, `frameFix`, `orbit`, `onUserCamera`), so the pilot,
  captures and tour do not change. First step of the phase: a spike. If it breaks a capture or the pilot, keep
  `OrbitControls` and shift the target along the view ray for the pivot.
- **View cube** at the 3D pane's top right: click a face, edge or corner (26 directions); drag it to orbit; Home above
  it. Front looks north (from the south), Right from the east, Back from the north, Left from the west, as in the
  elevations. It turns about the current pivot and keeps the distance.
- **Perspective or orthographic** (**O**, or the cube's menu). Orthographic zooms by scale; picking works in both.
- **Presets:** 1–4 stay (Top, Front, Right, Iso); the cube has the rest, including the four isometrics.
- **Home:** H fits the whole model as today; "Set this view as Home" in the cube's menu makes H fly there instead (per
  project, `sightline.views.<project>`).
- **F frames the selection:** the selected element if one is selected, else the clash.
- **Back and forward:** each camera jump (a clash, F, H, a preset, the cube, a saved view) goes on a history; **[** and
  **]** step through it, and so do buttons in the Views popover.
- **Saved views:** "Save this view" names the camera (position, pivot, projection), style, visibility and section box;
  the Views popover lists them; per project in `localStorage`.
- **Section box anywhere:** round the clash, the selected element, what is in view (the model's box near the pivot) or
  the whole model; each face has a grip to drag, live. **S** toggles it: round the clash if there is one, else the
  selection, else what is in view.
- **Walk** (first person: W A S D, mouse look, speed from the model's size, Esc leaves): last in its phase if time
  allows, else later.

### Visual styles

How the 3D view draws everything (Revit's visual styles). **G** cycles them; **V** goes back to Shaded with everything
shown, as today.

| Style | Drawn | Notes |
|---|---|---|
| **Shaded** | lit, each element in its own colour | default; with a clash picked the rest is greyed (today's look), or own colours (toggle) |
| **Consistent colours** | unlit, own colours | disciplines read by colour, no shading |
| **Shaded with edges** | Shaded plus dark outlines on every element | the drawing views' linework pass, in 3D |
| **Hidden line** | paper white and dark lines | the drawing views' fill and linework |
| **Wireframe** | element outlines only, see-through | feature edges per model, built once on first use; moved and replaced elements draw their own, like the pair's. Measure on Northbank first: dropped if too slow |
| **X-ray** | everything see-through, the pair and the selection solid | today's X-ray (**X**), now with no clash too: services seen through the façade |

The pair, the selection, previews, trials and hits keep their colours in every style.

### Visibility

Three layers, each applying to every open view (the toggle above covers only the first, for drawing views):

1. **Round the focus:** All (default), **Near it** (**C**, within 2.5 m, `reach`-scaled) or **Only it** (**I**); pressing
   the key again goes back to All. The focus is the clash, or the selected element when no clash is picked: isolate an
   element without making it side A. Off when there is no focus, as today.
2. **Filters** (Revit's visibility / graphics, simplified): by model (as today), by class (Walls, Slabs, Beams, Ducts…,
   with counts) and by level (one level, or a range). A Visibility popover with checkboxes and Show all. The loader
   records each element's class (web-ifc `GetLineType`) and storey (`IfcRelContainedInSpatialStructure`) from the
   model it already has open. Filters are for viewing only: the check, triage and fixes never see them.
3. **Hide and isolate, for now** (Revit's temporary hide / isolate): Hide, Isolate, Hide this class, Isolate this
   class, from the element card. While any is on, the 3D pane has a cyan frame and a "3 hidden · Reset" chip. Hidden
   elements are not picked.

What wins: a hidden model, then a temporary hide or isolate, then the filters, then "round the focus". The clash pair,
a fix preview and the agent's trials always show while they are on screen.

**Selection.** A single click selects an element (as today) and now draws it in blue (`#2f8fdf`) with an outline in
every view, a colour no other role uses. Its card adds Zoom to it, Hide, Isolate, Section box round it and Show in plan
(the plan goes to its level and centres it), beside Set as A / B.

### Keys

| Key | Does | |
|---|---|---|
| 1–4, H, F | presets, fit (or Home), frame the selection or the clash | F changes: the selection first |
| X, C, I, V | X-ray, Near it, Only it, back to Shaded with all shown | as today |
| G | next visual style | new |
| O | perspective / orthographic | new |
| [ and ] | back / forward through camera jumps | new |
| Q | layout: Single, Two, Quad | new |
| S, E, M | section box, outlines, measure | as today |
| Esc | the measure, card, lightbox, selection, then the clash | longer chain |

## Views and layouts

| View | Camera | Cut | Default |
|---|---|---|---|
| **3D** | perspective, orbit (as today) | the section box (as today) | |
| **Plan** | orthographic, looking down | its view range: cut plane (above removed) and bottom (below removed) | level and cut height through the clash |
| **Section** | orthographic, looking along the section line's normal | the section plane (near side removed), far clip, crop | through the clash, along the run of the service |
| **Elevation** N / S / E / W | orthographic, from outside the model's box | far clip (off by default), crop | the side facing the section's look direction |

- **Layouts.** Single (3D, as today), Two (Plan · 3D), Quad (Plan · 3D / Section · Elevation). Each pane can show any
  view. Double-click a pane's title to maximise it; again to go back. Key **Q** cycles Single → Two → Quad.
- **Per device.** Desktop up to Quad; tablet Single or Two; phone Single only (its bottom sheet needs the room).
- **Defaults follow the clash.** Picking a clash (list, chat, tour, agent link) with Fly to clash on sets, once per
  clash:
  - plan: the storey the clash point stands in (highest level at or below it) and a cut height through the point,
    kept between 0.3 m and the storey height less 50 mm;
  - section: through the clash point, vertical, along the longer horizontal axis of the side that moves (the
    service). Raising the #042 duct through the girder then reads in profile: the girder cut, the web opening, the
    offset's risers and bends;
  - elevation: the side the section looks towards.
  A view the user changed keeps its settings until the next clash; a pinned view (pin in its header) keeps them
  across clashes.
- **Drawing views and modes (the toggle).** "Full model" (default): drawing views show every element in visible
  models, whatever the 3D mode. "Follow 3D": they hide what Near it / Only it hide. Either way the pair is red and
  green, hidden models stay hidden and an edit preview replaces what it changes.

## View range and clip planes

Every plane a drawing view clips by can be set, three ways: typed in the pane header, dragged as a line in another
view, or taken from a preset. Values are metres to the millimetre (+1.200), and a view redraws while one changes.

**Plan: view range.** Two horizontal planes, each set as a level plus an offset, so it follows that level (as in
Revit's view range, without its separate top):

| Plane | What it does | Default |
|---|---|---|
| **Cut plane** | everything above is removed; what it passes through is cut (filled, heavy outline) | level + 1.200 |
| **Bottom** | everything below is removed, not cut; off = down to the bottom of the model | the plan's level + 0.000 |

- The cut stays above the bottom (at least 10 mm apart); the header and the handles stop there.
- Presets in the header: **Floor plan** (cut +1.200, bottom +0.000), **Ceiling void** (bottom +2.400, cut 50 mm under
  the next level: beams, girders and the services between them, without the floor), **Whole storey** (cut 50 mm under
  the next level, bottom at the level), **Through the clash** (the clash default above: cut through the clash point,
  bottom at its level).
- Dragged in a section or elevation: the cut is a dashed line, the bottom a dotted one, each with a grip at the view's
  edge and its value beside it ("cut +1.200"). The plan they belong to is named on the line when several are open.
- A clash default sets only the cut (and the level); a bottom the user set stays.

**Section: line, depth and crop.** A section is a vertical plane plus the box of what it shows:

| Setting | What it does | Default |
|---|---|---|
| **Line** (position and direction) | the cut plane; the near side removed | through the clash, along the service's run |
| **Look direction** | which side is kept (flip) | the side the 3D camera is on |
| **Far clip** | everything further than this behind the line is removed, not cut; off = to the model's edge | 2.000 behind the pair (`reach`-scaled for small models) |
| **Crop width** (left, right) | the extent along the line | the pair plus 2.000 each side |
| **Crop top and bottom** | the extent up and down | lowest level − 1.000 to highest + 1.000 (the model's box with no levels) |

- In plan the section is drawn as its box: the line (heavy, with look-direction heads and the section's name), the far
  clip (dashed) and the crop sides (thin). Drag the line along its normal to move it, its end grips to turn it (Shift
  for 15° steps), the far clip line to set the depth, the sides to set the width; click a head to flip.
- In the section itself, the crop's top and bottom edges have grips. Header fields hold the same values.
- **Elevations** have a far clip and a crop the same way (far clip off by default), set in plan from the elevation
  marker's line, and in the header.

**What gets cut.** Only the cut plane (a plan's cut, a section's line) cuts: the stencil passes that fill cut faces
run with that one plane, so a column through both a plan's cut and its bottom is filled, and nothing is filled at a
bottom, far clip or crop edge. Bottom and far clip are global clipping planes for the fill and linework passes only.
A crop is a rectangle on screen in these orthographic views: the view is drawn inside it (scissor), paper outside, and
picks outside it are ignored; the crop's border is drawn as a thin line, as a crop region is on a drawing.

**The 3D section box** stays the 3D view's tool, as today. Later: "Match this view" in a plan or section header sets
the section box to its view range or its section box.

## Rendering

**One renderer, one canvas, scissored viewports.** Each frame, each pane is drawn into its own rectangle
(`setViewport` / `setScissor`). The scene, GPU buffers and per-element state are shared, so a view costs only its own
draw calls. Three.js layers keep 3D-only objects (the pair's through-wall outlines, the hit outlines, the marker,
measure, section-box helper) out of drawing views: those go on layer 1, which only the 3D camera sees.

**Cuts are global clipping planes set per view** (`renderer.clippingPlanes`), not material planes, so no material
changes. The section box (material planes) stays a 3D tool: it is lifted while a drawing view renders.

**Per-view visibility.** "Full model" needs every instance visible while a drawing view renders, and the 3D mode's
visibility back for the 3D view. `applyMode` already computes both; the viewer keeps the drawing set and swaps it in
and out around drawing views only while Isolate / Context hide something (about 2,000 `setVisibleAt` calls each way on
Northbank).

### The drawing style

A drawing view renders into its own render targets (device pixels, 4× MSAA, with a stencil buffer; the canvas itself
needs none) and is composited into its pane:

1. **Paper fill.** Batches swap to unlit materials for the pass: near-white, faintly tinted per file (structure grey,
   MEP blue, architecture warm), ignoring the batch's mode colours. The pair keeps flat red / green; previews keep
   their colours, the "before" ghost stays orange.
2. **Cut faces (poché).** The standard stencil cap, by parity, clipped by the cut plane alone (View range and clip
   planes, above): each cut solid is drawn once, both faces, colour and depth off, inverting a stencil bit, so a pixel whose bit is set lies inside a solid the cut passes through. Bits:
   1 everything else, 2 side A, 4 side B, 8 one element on both sides. Full-view quads then fill by stencil value:
   grey with a 45° hatch for 1 only, red for A, green for B, purple for both, and **amber where A and B overlap**: the
   interference shows as a filled region in plan and section. Caps write a class into the colour target's alpha.
3. **Linework.** A second pass writes normals and depth (`MeshNormalMaterial` as override). The composite shader marks a
   pixel as an edge where a neighbour's normal turns more than about 30° or its depth jumps more than a few pixels'
   worth of model: thin dark projection lines on every visible edge, silhouette and step, recomputed every frame, so
   moved and previewed elements are always right. Inside a cap there are no projection lines.
4. **Cut outline.** Where the alpha class changes within about 1.5 px, the composite draws a heavy line (black; dark
   red / green round the pair): cut lines heavier than projection lines, as on a drawing.

Elevations skip steps 2 and 4. Glass (safety zones, glazing) is drawn see-through in the fill and left out of the
linework pass.

### Annotations

Each drawing pane has a 2D canvas over it, redrawn when its view changes. Units are metres; points go through the
view's camera (three.js is Y up: server point (x, y, z) → (x, z, −y)).

- **Grids:** dash-dot centre lines, numbered bubbles at both ends. In sections and elevations, an axis that runs
  within about 25° of the look direction is drawn as a vertical line with a bubble at the top; others are left out.
- **Levels** in sections and elevations: a line across the view with a head ("Level 02 · +4.000").
- **The clash:** a revision cloud round where the pair meets (`meetingZone`) and its number (#1).
- **Linked marks:** in plan, each section's box (line with look-direction heads, far clip, crop sides), each
  elevation's marker and far clip, and the 3D camera (position and field of view); in sections and elevations, each
  plan's cut plane (dashed) and bottom (dotted) with their values.
- **Sheet furniture:** view title bottom left ("Level 01 · Floor plan · cut +1.200 · bottom +0.000"; a section's far clip), scale bar and the nearest
  standard scale ("≈ 1:100", from pixels per metre at 96 dpi), project north arrow in plans (true north is later).

## Datums from the server

`GET /api/scenes/{sid}/datums` (new module `server/sightline/datums.py`, read with IfcOpenShell, cached per scene, dropped
with it):

```json
{"levels": [{"name": "Level 02", "elevation_m": 4.0, "height_m": 4.0}],
 "grids":  [{"tag": "1", "grid": "Structural grid", "start": [-10.5, -8.5, 0.0], "end": [-10.5, 8.5, 0.0]}],
 "sources": {"grids": "Northbank-Grids.ifc"}}
```

- Metres, IFC axes. A storey's elevation is its placement's world z (the `Elevation` attribute is optional and
  sometimes relative), scaled per file. Levels are merged across files by name and elevation (to the millimetre);
  `height_m` is the gap to the next level.
- Grid axes are their polylines (`IfcGrid` U, V and W axes) through the grid's placement.
- **Grids as context.** When none of the scene's files has an `IfcGrid` and the scene was opened from samples, the server
  reads one from `<prefix>-Grids.ifc` in the samples folder, where the prefix is the files' shared name ("Northbank").
  It is read for its grid only: never added to the scene, the check or export. Uploads use their own grids.
- No grid and no levels (a machine cell): the views work without them; plans then cut at the model's mid-height, with no bottom, and the
  plan presets that need a next level are off.

## Interaction

- **Panes.** The viewer adds one transparent element per pane over the canvas. Each has its own controls: 3D orbits
  as today; drawing views pan (left or right drag) and zoom to the cursor (wheel, pinch), never rotate. Clicks still
  bubble to the stage, so App's click / double-click / long press work unchanged in every pane.
- **Picking** uses the pane under the pointer and its camera, and skips hits on the removed side of any of that view's
  clip planes and outside its crop. In
  3D the section box rules, as today. Double-click picks A then B in any view.
- **Linked handles** (View range and clip planes, above): in plan, a section's line, ends, far clip and sides, and an
  elevation's far clip; in sections and elevations, each plan's cut and bottom, and the view's own crop top and
  bottom. The view a handle belongs to redraws as it is dragged. A handle drag never pans the view it is in; Escape
  puts the value back.
- **Pane chrome** (`web/src/ViewPanes.tsx`): a header per pane with the view picker (3D, Plan per level, Section,
  Elevation N/S/E/W), and the view's clip planes: for a plan the level, cut and bottom (offset fields, a slider for the cut, the
  presets), for a section far clip and crop (fields, flip, far clip off), for an elevation far clip; pin; maximise. The rail gets a Views popover:
  layout, and the Full model / Follow 3D toggle. The rail sits at the stage's top left, so the top-left pane's header
  starts after it.
- **Camera tools.** F, H, the presets, the view cube, back / forward and saved views act on the 3D view. Fit in a
  drawing view's header frames the model there; a right-click (no drag) on a point in a drawing view offers Look here
  in 3D, which turns the 3D view to it.
- **Labels.** The marker and measure labels stay with the 3D pane, offset by its rectangle.

## What must not change

- **Clash pictures.** `captureClash`, `thumbClash`, `capture` and the report shots keep rendering with the 3D camera
  into the whole canvas at its aspect, with no global cut, whatever the layout. The guard saves viewport, scissor,
  aspect and global planes, and puts them back. Check: A/B/C pictures of #1 and list thumbnails identical, pixel for
  pixel, in Single before and after, and the same in Quad. Captures also lift the user's style, filters, temporary
  hides, projection and section box while they shoot (a hidden class must not vanish from picture B's context), and
  put them back. Show it built (`captureBuilt`) the same.
- **The golden path, tour and pilot** open in Single with Fly to clash on and work as before. The pilot's camera moves and orbit act on the
  3D view; its trials show in every view (it previews through the same calls).
- **Screenshot** saves the whole layout: the canvas plus each pane's annotation canvas.

## Cost

A drawing view with a cut costs about three passes over the visible triangles (fill, stencil, normals) plus a few
full-view quads. To keep Quad light on a laptop, drawing views redraw only when needed: their own camera moved, their
settings changed, the pane was resized, or the scene changed (a version counter bumped by `applyMode`, `setHits`,
`setMarker`, previews and loads). The 3D view renders every frame as today. Measure on Northbank before merging: frame
time while orbiting in Quad, and while the pilot plays a proposal.

## Tests and checks

- **Server:** `datums.py` on Northbank (five levels with elevations, seven grid axes from the Grids file as context, no
  grid in an upload without one) and on the cell (no levels, no grid).
- **Web (`npm test`):** pure functions in `web/src/viewer/views.ts`: layout rectangles, clash defaults (level, cut
  height, section line and box), view range limits (cut above bottom, presets with and without a next level), nearest standard scale, which grid axes a view shows and where. New App imports go in both stub
  lists (`tests/app-host.mjs`, `tests/app-replacement.test.mjs`); new Viewer imports in `tests/viewer-load.test.mjs`.
- **Web, navigation:** the Esc chain, what-wins for visibility, view cube directions, camera history, saved views
  round-tripped.
- **Browser, navigation:** pick #1, orbit away and look at Level 03: the pair still drawn there in 3D (and later in
  every view); Esc until the clash is left, camera unmoved; Fly to clash off: picking moves nothing; filters and a
  temporary hide leave #1's A/B/C pictures pixel-identical; X-ray with no clash shows the girder through the façade.
- **Browser (Playwright):** Northbank #1 in Quad: plan cut through the duct and girder with the amber interference,
  section showing the web opening, grids and levels;
  Ceiling void on Level 01 showing the girder and the three services without the floor; a section's far clip and a
  plan's bottom set by typing and by dragging, with nothing filled at either; propose and watch the trial in all views; accept; capture
  pictures unchanged. Phone profiles: Single only, no new controls.

## Phases

0. **Navigate freely (3D only, before any new view):** leaving a clash, Fly to clash, the Esc chain, the clash chip,
   selection in blue and its card actions, round-the-focus on a selection, filters by model / class / level, temporary
   hide and isolate, X-ray and Consistent colours without a clash, orbit about the point under the pointer, view cube,
   perspective / orthographic, presets, Home, back / forward, saved views, section box anywhere with grips. Walk if
   time allows.
1. **Views:** layouts, orthographic plan / section / elevation, live cuts, every clip plane set in the header
   (view range, presets, far clip, crop), panes and picking per view, the toggle,
   the datums endpoint, the capture guard.
2. **Drawing style:** fill, poché with the interference colour, linework, cut outline, grids, levels, cloud, title,
   scale, north; in 3D, Shaded with edges, Hidden line and Wireframe from the same passes.
3. **Linked:** clash defaults, the handles (section box in plan, cut and bottom in sections and elevations, crop
   edges), the 3D camera in plan, Screenshot of the layout.

Each phase is its own PR and leaves the app working.

## Later, not in the hackathon build

Per-view visibility and styles (each view its own filters); Revit's "reveal hidden"; multi-select with Shift;
Exact vector cuts (plane-triangle intersection on the CPU) for DXF / PDF sheets; dimensions; hatches by material
(the models carry no materials ORCA reads yet); Revit's separate top and view depth; plan crop regions; true north; reflected
ceiling plans; saved views and sheets.
