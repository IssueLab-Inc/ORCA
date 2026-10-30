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

**The switch:** `SIGHTLINE_CONNECTED_MOVES` is `carry` (slice 2's default), `refuse`, or `off`, which gives moves as
before joints were known.

**Measured:**

- Northbank: every one of the 335 MEP segments is joined at an end, so none moves whole without slice 2.
- The answer key is still 3/3 first try at Rev04 heights, and Muse stopped proposing whole moves of joined runs.
- The cell's #22 gets only routes (both keep the pipe's ends on its bends).
- Joints for all 40 flow parts of the cell take 3.8 s, mostly the first triangulation of each part.

## Slice 2: moves that carry fittings and stretch segments (Oct 30)

`SIGHTLINE_CONNECTED_MOVES` is now `carry` by default.

**The walk** (`plan_move`): each element ends up translated, stretched at one face, or where it is, and both sides of
every joint must move alike. It goes out from what was asked to move, one joint at a time:

| What is beyond the joint | What happens |
|---|---|
| equipment, a terminal, a filter, structure, or anything kept fixed (`Pset_SightlineConstraints.KeepFixed`, or a group the requirements may not edit) | refused, naming it |
| a fitting or an in-line valve | taken along, and the walk continues from it |
| a straight segment joined by a cap, when the move runs along it (less than 0.5 mm across, absolute: 1° would leave 4 mm at 250 mm) | stretched at that end by the along part; refused when it would be shorter than 50 mm ("it can lose at most …") |
| a rectangular segment joined end-on by its side (80% of the face covered: a ladder bend sitting on its riser), when the move runs along the side's normal | grows to that side |
| anything joined to a segment's side that does not cover it | a branch, refused ("it branches off") |
| any other straight segment | taken along |
| a segment reached at a second face | moves whole |
| more than `SIGHTLINE_CARRY_MAX` (12) parts taken along | refused |

No extra slope, gravity or cycle rules are needed: taking along only translates, and stretching moves a face along the
segment's own axis.

**`edits.stretch(scene, gid, face, by_m, normal)`:**

- **Cap:** changes the extrusion's depth (and its start, with a new placement, when the start moves).
- **Side:** for a centred rectangular profile, writes a new profile and placement.
- **Ports** at that face shift by the same amount, keeping their rotation.
- **Refused:** a body shared with other elements, or a piece left under 50 mm.

`apply_move` translates, then stretches.

**Checking** (`trial_move` / `check_applied`):

- What moves is checked against everything except what the move changes and what that is joined to (those joints
  hold).
- A stretched segment's contacts count only when new or worse than before (`baseline`, out to 100 mm), so the riser
  keeps its gland plate.
- `check_joints` proves every joint still meets: ports within 2 mm, STEP parts still face to face. A broken joint is a
  `joint` hit; on keep it raises, which undoes the edit.

**The fix stays a "move"**, so requirements, ranking, the PDF and the BCF need nothing new. What it carries:

- `moved`: what is translated.
- `preview`: the stretched segments as they would be.
- `before`: everything it changes.
- `edit`:
  - `summary`: "move north 250 mm; takes 'bend 2' and 'bend 3' along; 'segment 2' and 'segment 4' 250 mm shorter";
  - `key`;
  - `run`, `carried`, `stretched`, `joints`.

**Keeping it:**

- Every keep goes through `plans.apply`, which tries the move again first (`plans.recheck`, as for every kind). An
  option whose `edit.key` differs from the fresh trial's is refused (409): the move would now take other parts along
  or stretch them differently from the one that was checked and shown.
- `plans.KEEP["move"]` → `Workspace.apply(moved, delta, expect=edit)` plans it again on the server and refuses a
  changed key too: "the model changed since this move was checked".
- `changed` lists the stretched segments, so accept in place patches them.
- **The page:**
  - every fix is accepted through `/fix/apply` with its clash pair;
  - the viewer translates `moved` and draws the stretched pieces;
  - the manual move previews what it takes along.

**Elsewhere:**

- Combined steps plan each move and store their stretches. A step that would change what another step changes is
  refused.
- `verify_together` reports two plan items that change the same element as a conflict.
- Muse reads, per joined side, which of the six directions keep the joints, what goes along, how far a shortening
  can go, and why the others can't (`describe`, dry plans at 100 mm).

**Measured:**

- **Cell (`evals/step_cell.py` passes):**
  - C2's ladder lifted 150 mm moves 4 parts. The riser from EP-301 is 150 mm taller with its foot still on the
    gland plate, and the STEP export matches.
  - C6 as a move (segment 3 north 250 mm) keeps its joints (2 bends along, 2 segments shorter) but hits the ES-2
    emergency stop, so the route stays the fix.
- **In the browser on #61** (ladder through post W5): Muse offered "move up 100 mm; takes … flat bend 2, run 1,
  vertical bend 1 along; riser 100 mm longer", verified, and it was accepted in place with no file download.
- **Northbank (`evals/joints.py`):** of 1,992 dry plans (332 straight runs × 6 directions), 195 keep their joints.
  The rest are refused at equipment or terminals (988), for taking more than 12 parts along (476), for leaving a
  segment too short (309), or at a branch (24). The median plan takes 16 ms. #042 raised 400 mm is refused (more than
  12 parts along).
- **Answer key:** 3/3 first try at Rev04 heights.

**Known limits:**

- A STEP prototype used by several components would change for all of them when one is stretched. The same is already
  true of offsets and trims; the cell's STEP has none.
- Joints across files (a service on structure) are not modelled.

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
