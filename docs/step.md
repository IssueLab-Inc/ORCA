# STEP models

Machine builders work in STEP (AP203/AP214/AP242). Sightline checks and edits IFC, so a STEP file is converted when it
opens, checked like any model, and written back as STEP with the fixes. Code: `server/sightline/step.py`.

## Conversion

- **Read** with OpenCASCADE's Python bindings (`cadquery-ocp`, the same 8.0 the cell's generator writes with):
  - `STEPCAFControl_Reader`, names and colours on;
  - walk the assembly tree from its free shapes, composing component locations;
  - each leaf is one part: name, the group path (the assemblies above it), its component label path, colour and alpha.
  - Units come from `xstep.cascade.unit` (mm by default) and become metres.
- **Mesh** each part with `BRepMesh_IncrementalMesh`: at most 0.5 mm deflection, finer for small parts, 0.35 rad.
- **Write IFC4:**
  - one element per part, with an `IfcTriangulatedFaceSet` body placed at the part's box minimum (so a move is one
    placement edit);
  - its STEP name, and a style with its colour and transparency;
  - pset `Sightline_STEP` (Group, Label, Source);
  - GlobalIds come from the file's hash and the label path, so the same STEP converts to the same ids;
  - STEP groups become `IfcGroup`s, not assemblies: detection treats an assembly's parts as meant to meet, and a
    machine's top groups (Guarding) hold parts that must not clash.
- **Classes:** STEP carries none. One call to the titles' model per 200 parts (`domain_packs/step_classes.md`) picks a
  class and type from each part's name and group, from an allowed list. Without a model, every part is a proxy named
  for its group.
- **Cache:** conversions are cached by the file's hash. The demo ships its conversion in `samples/step-cache`.
- **Limits:** `SIGHTLINE_STEP_MAX_PARTS` (20,000) and `SIGHTLINE_STEP_MAX_TRIANGLES` (5 M).

## Fixes and export

- **Moves only:** STEP parts are triangulated, so offsets and trims (which need extruded profiles) do not apply.
- **Runs without ports:** a STEP part has no ports, so `IfcScene.connected_run` takes the parts of the same STEP group
  that touch it, transitively (`step_run`). A cable ladder moves as one; a fence post moves alone.
- **Export:** each part's move is its placement now minus its origin in the manifest (`Workspace.export`).
  - `step.export` reopens the original STEP and sets each moved component's location to parent⁻¹ · T · parent · old.
  - It writes `<name>.sightline.step` with names and colours, next to the edited IFC (a zip).

## Upload

- `POST /api/models/upload`: one to eight `.ifc`, `.step` or `.stp` files, opened together.
- Caps: `SIGHTLINE_MODEL_UPLOAD_MAX_MB` (default as report uploads, 150 on the demo) and
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
- **In the browser:** Muse Spark proposed "Raise tray 150 mm over post top" (Rev B's fix) and it was verified. Export
  gave the STEP and the IFC.

## Not in this version

- Placing a STEP machine inside a building model (STEP has no world position).
- Offsets and trims on STEP parts.
- Keeping exact B-rep for depth: depth comes from the mesh, within the deflection.
