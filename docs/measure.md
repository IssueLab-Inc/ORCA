# ORCA measure: design

Owner request, Oct 30, after the drawing views went live ([docs/views.md](views.md)): the measure tool worked only in
the 3D view, took one measurement at a time and snapped to nothing. And the rail at the stage's left mixed tools that act
on every view with tools that act only on the 3D view, which in Two or Quad sits over the plan, not the 3D pane.

It is new work, written for ORCA during the event.

## What it does

- **One tool, every view.** M (or the ruler on the rail) turns measuring on in every pane. A click sets the first
  point and a second click the second; the next click starts another measurement. While the second point is open, a
  rubber band runs from the first point to the pointer with its length. Esc drops an open first point, then turns the
  tool off.
- **In the 3D view** a measurement is the true distance between two points on the model, with its components along the
  IFC axes (Δx · Δy · Δz).
- **In a drawing** both points lie on the drawing's own plane, so a measurement reads as on a printed drawing: a plan
  measures horizontally (on its cut plane), a section in its plane, an elevation along the façade and up. A point can
  be on the model or on empty paper. The measurement belongs to that pane and is drawn there with tick marks at its
  ends, as a drawing's dimensions are.
- **Where they show:** the 3D view shows every measurement (each is a real pair of points in the model); a drawing
  shows the ones taken in it. They show while the tool is on; turned off they are kept for this visit and come back
  when it is on again. Opening other models clears them. Captures never include them; the Screenshot does.
- **Snapping** (on by default; the panel's toggle or N): to an end (a corner, an edge's end), then a midpoint, then the
  nearest point on an edge, within about 12 px (8 px for an edge). In a drawing that cuts, the cut outline counts too:
  a wall cut by a plan snaps at its cut corners and along its cut faces, where no model edge runs. A glyph under the
  pointer says what it found, as CAD does: a square for an end, a triangle for a midpoint, a cross for an edge, a dot
  for a plain surface point. Snap off, the point is what the pointer is over (a drawing: on its plane). The candidates
  are the element under the pointer, and when that gives no snap, the elements under four points 10 px round it.
- **The Measure panel** (while the tool is on, beside the rail): the snap toggle, what to click next, and the list:
  `M1 · 1 234 mm · Level 02 · Plan`. Each row copies itself or is deleted; Copy all and Clear all below. A copied line
  carries everything a coordinator pastes into an issue:

  ```
  M1  1234 mm  (Δx 1000 · Δy 700 · Δz 0)  Level 02 · Plan  from (12.345, 3.210, 7.058) to (13.345, 3.910, 7.058) m
  ```

  Coordinates are the model's (IFC axes, metres).

## The rail: what acts on every view, and what only on 3D

| Acts on | Tools |
|---|---|
| Every view (the stage's left) | Go to the clash, Measure, Views (layout, what drawings show, Fly to clash), Visibility (models, levels, classes, hidden for now), Screenshot |
| The 3D view only (in the 3D pane) | Modes (Shaded, X-ray, Context, Isolate), Visual style, Section box, Outlines, Connections, Home, Camera (standard views, projection, back and forward, Home), Saved views |

- **Single** (or the 3D pane maximised): one rail at the stage's left as before, the 3D groups first.
- **Two and Quad:** the 3D groups move into the 3D pane, under its header; the rest stay at the stage's left. A drawing
  maximised hides the 3D groups. In a short 3D pane the groups fold: the four modes into one Mode menu, then the
  tools and the camera into one menu each.
- **Fly to clash** moves to the Views menu: it decides what every view does when a clash is picked.

## How it works

- `web/src/viewer/measure.ts` holds the pure parts: where a plane cuts triangles (`cutSegments`), joining a cut's
  collinear pieces into the outline's straight runs (`mergeRuns`, so a face split into two triangles has one midpoint,
  not two), clipping an edge to a view's planes (`clipSegment`), choosing the snap (`pickSnap`), and the text
  (`measureText`, `copyText`).
- The viewer owns the measurements (`Viewer.measurements`, `measureHover`, `measureClick`, `measureCancel`,
  `removeMeasurement`, `clearMeasurements`, `setMeasuring`, `setSnap`) and draws them, the rubber band and the snap
  glyph on one 2D canvas over the stage, again only when something on it changed. The old 3D measure (spheres, a line
  and one label) goes.
- Candidates: an element's feature edges (`EdgesGeometry` at the crease angle, 40° since Nov 1, already cached for
  outlines), in world space: a curve's facets are not edges. In a
  drawing they are clipped to its planes and laid onto its plane; where it cuts, the element's triangles are cut by
  that plane and joined into runs. Both are cached per element and placement while the pointer moves.
- In the 3D view an edge point is the closest point between the pointer's ray and the edge (exact in perspective); in a
  drawing it is measured on the plane (orthographic, so exact too).
- `App` shows the panel (`MeasurePanel.tsx`), routes clicks and pointer moves to the viewer while measuring (one
  snap per frame), and copies with the Clipboard API (a hidden text area where it is not allowed).

## Tests and checks

- `web/tests/measure.test.mjs`: a box cut by a plane gives its four sides, joined into runs; clipping; the snap order
  (end, midpoint, edge, none) and tolerances; the text and the copied line.
- Browser (Northbank, Quad): measure in 3D, in a plan (a wall's cut corner to a column's), in a section and an
  elevation; snap on and off; several measurements, delete one, clear all, copy; captures unchanged; the rails in
  Single, Two and Quad, a maximised drawing, a short window.
