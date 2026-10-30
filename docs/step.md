# STEP models

Machine builders work in STEP (AP203/AP214/AP242). ORCA checks and edits IFC, so a STEP file is converted when it
opens, checked like any model, and written back as STEP with the fixes. Code: `server/sightline/step.py`.

## Conversion

- **Read** with OpenCASCADE's Python bindings (`cadquery-ocp`, the same 8.0 the cell's generator writes with):
  - `STEPCAFControl_Reader`, names and colours on;
  - walk the assembly tree from its free shapes, composing component locations;
  - each leaf is one part: name, the group path (the assemblies above it), its component label path, colour and alpha.
  - Units come from `xstep.cascade.unit` (mm by default) and become metres.
- **Mesh** each part with `BRepMesh_IncrementalMesh`: at most 0.5 mm deflection, finer for small parts, 0.35 rad.
- **Exact bars and rods:** `_prism` recognises a solid that is a plain cylinder (one cylindrical face, two flat caps)
  or a box (six planes in three perpendicular pairs, volume checked). These are written as `IfcExtrudedAreaSolid`
  (circle or rectangle profile along the long axis), exactly as an IFC generator would, so offsets and trims work on
  them. The cell: 97 exact parts (pipes, rails, posts, ladder runs, plates), 47 meshes (bends, robot, drums).
- **Write IFC4:**
  - one element per part, placed at the part's box minimum (so a move is one placement edit); exact parts get the
    extrusion, the rest an `IfcTriangulatedFaceSet`;
  - its STEP name, and a style with its colour and transparency;
  - pset `ORCA_STEP` (Group, Label, Source);
  - GlobalIds come from the file's hash and the label path, so the same STEP converts to the same ids;
  - STEP groups become `IfcGroup`s, not assemblies: detection treats an assembly's parts as meant to meet, and a
    machine's top groups (Guarding) hold parts that must not clash.
- **Classes:** STEP carries none. One call to the titles' model per 200 parts (`domain_packs/step_classes.md`) picks a
  class and type from each part's name and group, from an allowed list. Without a model, every part is a proxy named
  for its group.
- **Cache:** conversions are cached by the file's hash. The demo ships its conversion in `samples/step-cache`.
- **Limits:** `SIGHTLINE_STEP_MAX_PARTS` (20,000) and `SIGHTLINE_STEP_MAX_TRIANGLES` (5 M).

## Fixes and export

- **Moves, offsets and trims:** exact parts take all three; meshed parts move only.
- **Bends on STEP parts:** an offset's bend fittings carry the segment's `ORCA_STEP` pset, so they export into
  its group.
- **Runs without ports:** a STEP part has no ports, so `IfcScene.connected_run` takes the parts of the same STEP group
  that touch it, transitively (`step_run`). A cable ladder moves as one; a fence post moves alone.
- **Joints without ports (Oct 30, `docs/connections.md`):** flow parts of one group that meet face to face are joined
  (a pipe's cap against its bend's face, a valve hanging off a main's side). A move of a flow part keeps those joints:
  the bends beyond it go along and a prism the move runs along gets longer or shorter (the cell's ladder riser grows
  taller on its panel), exported as a replaced prism; a part that is not a flow element still moves with the parts of
  its group it touches, but never pulls flow parts along. A prototype instanced by several components would change for
  all of them (as for offsets and trims).
- **Export:** `service.step_changes` sorts each edited element (`Workspace.export`):
  - **move:** an exact part whose extrusion still matches its manifest `prism`, or a mesh; the delta is its placement
    now minus its origin. `step.export` sets the component's location to parent⁻¹ · T · parent · old.
  - **replace:** an exact part whose extrusion changed (an offset's first piece, a trimmed rail). Its prototype shape
    is rebuilt (`BRepPrimAPI_MakeCylinder` / `MakeBox`, in the component's own frame).
  - **add:** a new element carrying a part's `ORCA_STEP` label (offset middles, risers, bends) becomes a new part
    in that part's group, with its name and colour: an exact prism, or a sewn solid from its triangles.
  - Shapes are placed with `BRepBuilderAPI_Transform`, never `.Moved()`: a located shape loses its name and colour on
    write.
  - It writes `<name>.orca.step` with names and colours, next to the edited IFC (a zip).
- **Fix together on one part:** clashes that share a movable element (a pipe through two rails) become one job
  (`plans.merge_shared`): one agent, told about every obstacle. A shared fixed element (a girder hit by three
  services) is not merged.
- **Trims never cut guarding or structure for a service:** `agent._try_trim` refuses to trim a fixed element when the
  other side can move, so a post is never cut down to let a cable tray pass.

## Upload

- `POST /api/models/upload` (or `/upload/stream`, with progress): one to eight `.ifc`, `.step` or `.stp` files, each as
  is or gzipped by the page, opened together ([uploads.md](uploads.md)).
- Caps: `SIGHTLINE_MODEL_UPLOAD_MAX_MB` (default as report uploads, 150 on the demo; on the unpacked size) and
  `SIGHTLINE_MODEL_UPLOADS_PER_HOUR/DAY` (10/200 on the demo, none for the owner).
- An upload lives in its scene's temporary folder, deleted when the scene is dropped.
- UI: Models › Upload models (IFC or STEP)…

## Measured (Oct 28, `evals/step_cell.py`, `evals/runs/2026-10-28-cell-step/`)

| | Rev A | Rev B |
|---|---|---|
| Parts converted | 144 of 144 | 152 of 152 |
| Classes the model picked that match the generator's own | 144 of 144 | 152 of 152 |
| First opening (with the class call) / from the cache | 36 s / 1.3 s | 37 s / 1.6 s |
| Detection | 107 clashes in 1.3 s: 13 of 13 planted pairs, 94 by design, 0 unexpected | 92, 0 planted, 0 unexpected |

- **C2:** the CT-301 cable ladder through fence post W5. Its run is the 5 ladder parts.
  - +150 mm clears it.
  - The exported STEP re-reads with exactly those 5 parts 150 mm higher and the other 139 unchanged.
- **C1:** Fix together on the air pipe's two clashes gives one job and a verified fix (an offset 150 mm down past
  both rails in the recorded run; a move in another); the exported air line goes from 7 to 15 parts.
- **C3:** the fence top rail S5-SE trimmed 40 mm back to post SE's face; the exported rail is 40 mm shorter.
- **In the browser:** Muse Spark proposed "Raise tray 150 mm over post top" (Rev B's fix) and it was verified. Export
  gave the STEP and the IFC.
- **Tour:** the landing's cell card has **Take the cell tour** (12 steps: open, triage, the ladder move, the pipe fixed
  together, export), with recorded runs in `web/public/tour/cell-*.json`. The header's Tour picks it when the cell is
  open.

## Not in this version

- Placing a STEP machine inside a building model (STEP has no world position).
- Offsets and trims on meshed STEP parts (tubes, bends, castings).
- Keeping exact B-rep for depth: depth comes from the mesh, within the deflection.
