# Connections: what is joined to what

ORCA's fixes edit real elements, and elements are joined to each other: a pipe to its bends, a bend to the next pipe,
a duct to its tees, a door to its wall. A fix that pulls a joint apart is not a fix anyone would build. This page is the
design for knowing those joints, keeping them when a fix moves something, and showing them in the viewer. Code:
`server/sightline/connections.py`.

Owner decisions (Oct 30, after a fix moved the cell's PL-302 segment 3 off column C3 and left it apart from its bend):

- A move that cannot keep every joint is **refused with an explanation**. A verified fix always leaves the system
  connected.
- Hovering shows **direct links**, coloured by kind; Shift widens the view to the whole connected run.
- The slices land in this order:
  1. joints, with moves that break one refused;
  2. moves that carry fittings and stretch segments;
  3. hover highlight.

## Joints

A `Joint(a, b, point_m, source, end_a, end_b)` is where two elements meet so that something passes through.

- **Ports** (`source: "ports"`): two ports connected in the model (`IfcRelConnectsPorts`), read live from the model
  each time. Both directions count (`ConnectedTo` and `ConnectedFrom`). The point is the port's place.
- **Geometry** (`source: "geometry"`): only for parts converted from STEP, which have no ports. Two flow parts
  (`IfcDistributionFlowElement`) of the same file and STEP group meet face to face:
  - one part's face lies within 2 mm of the other's surface;
  - the two faces' normals are opposed (cos > 0.95);
  - the face's centre is inside a triangle of the other.

  What counts as a face:
  - A straight segment offers only its two caps, so two pipes side by side never join.
  - Any other part offers its large planar faces: triangles of one plane, at least a fifth of the largest such face.
    That means a bend's end discs or a box fitting's sides, never a bend's thin facets.

  What is never joined: stands, plates and walls (not flow elements); parts in another group; a gap over 2 mm (the
  cell's 400 V conduit ends 3 mm inside its panel). Triangles are cached per part and recomputed when its box
  changes, so joints stay right inside a trial.
- **Ends:** for a straight segment, a joint sits on its "start" or "end" cap or on its "side" (a branch: a valve hanging
  off a main, a bend sitting on a ladder riser). For anything else, the end is None.

**Classes** (`classify`):

| Class | What it covers |
|---|---|
| straight | a flow segment that is one straight extrusion |
| rigid | fittings; in-line valves, dampers and meters (IFC2X3: a flow controller of that type); segments that aren't straight |
| stays | equipment, terminals, filters, other controllers, structure, anything that is not a flow element |

**Runs** (`run`): the straight segments joined cap to cap. A run stops at anything rigid, anything that stays, and at
branches. It starts with the element asked about. A part that is not a flow element keeps what it moved with before
(`scene.connected_run`, which for a STEP part is the parts of its group it touches), but never pulls flow parts along:
a filter's stand no longer takes the air line with it. `scene.connected_run` itself is unchanged, because the
wider-fix planner relies on it.

**What the samples have:**

- **Northbank MEP:** 650 port joints.
- **Northbank Structure and Architecture:** none. Their links (aggregates, fills, contacts) are for slice 3's
  highlight.
- **The cell from STEP:** every PL-301/PL-302 pipe, bend, valve and filter, and the CT-301 ladder, joined as built.
  V-302 is a branch on the plant main's side.

## Slice 1: a move that would pull a joint apart is refused (Oct 30)

`plan_move(scene, moved, delta_m)` looks at every joint of what moves. A joint whose other side stays where it is
would come apart, so the move is refused, naming the joint:

> moving 'PL-302 compressed air DN25 segment 3' north 250 mm would pull it apart from 'PL-302 compressed air DN25
> bend 2' and 'PL-302 compressed air DN25 bend 3', joined to it, which stay where they are (split it with an offset or
> a route so its ends stay put)

Every path that moves something plans first:

- **`agent._try_move`:** the run, refused before it is tried. The attempt reads "cannot keep its joints: …". The
  pilot still shows the idea, and the joints it would break are its hits.
- **Combined fixes:** a move step is refused with the step's number.
- **Plans (`verify_together`):** a broken joint is a `joint` hit ("breaks its joint with IfcPipeFitting x2").
- **The workspace:** `Workspace.verify_move` fails without trying, giving `reason` and `joints.refused_at`.
  `Workspace.apply` raises, and `/apply` answers 422.
- **Chat and MCP `check_move`:** both give the reason.
- **The page's manual move** says "Not tried: …".

**What Muse reads:** for each side, what its run is joined to, and that a whole move would pull those joints apart,
so an offset or a route (which keep its ends) is the way. `construction.md` says joints stay joined.

**The switch:** `SIGHTLINE_CONNECTED_MOVES` is `refuse` (the default), `carry` (slice 2) or `off`, which gives moves as
before joints were known.

**Measured:**

- Northbank: every one of the 335 MEP segments is joined at an end, so none moves whole without slice 2.
- The answer key is still 3/3 first try at Rev04 heights, and Muse stopped proposing whole moves of joined runs.
- The cell's #22 gets only routes (both keep the pipe's ends on its bends).
- Joints for all 40 flow parts of the cell take 3.8 s, mostly the first triangulation of each part.

## Slice 2: moves that carry fittings and stretch segments (planned)

The walk: each element is translated, stretched at one face, or unchanged, and both sides of every joint move the same
amount. Going out from the moved run:

- **Equipment, terminals or structure:** refuse, naming it.
- **A fitting or in-line valve:** carry it along and keep walking.
- **A straight segment joined by a cap, or end-on by a side:**
  - if the move runs along it (under 0.5 mm across), stretch it by that much; refuse when it would get shorter than
    50 mm;
  - otherwise carry it.
- **A branch:** refuse.
- **More than 12 carried:** refuse.

`edits.stretch` changes a segment's extrusion depth, or a box's side, and moves the port at that face without turning
it. The option stays a "move", with `edit` listing what it carries and stretches and a mesh preview of the stretched
segments. Keeping it re-plans on the server and refuses a changed plan. The cell's C2 ladder then lifts 150 mm with
its riser 150 mm longer, foot still on the panel.

## Slice 3: see connections (planned)

- **The graph:** `GET /api/scenes/{sid}/connections` lists typed edges:
  - joint (ports or geometry);
  - assembly;
  - hosted (a door or window in its wall, an opening and its provision for void);
  - rests on;
  - contact (pairs touching within 1 mm, kept from the last check).

  Systems are listed per element.
- **On the page:**
  - hold Alt (Option on a Mac) and hover, or turn on the **Connections** toggle (L), to light an element's direct
    links by kind; Shift widens to the run;
  - on a phone, tap with the toggle on;
  - the properties card lists the links by kind;
  - the highlight never shows in captured pictures.
