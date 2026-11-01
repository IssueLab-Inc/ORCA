# Manual edits and the edit log: design

Owner request, Nov 1: edit model objects by hand (or by asking Muse) and keep a record of every edit, so the reports,
Muse and agents know what changed, not only the geometry. It is new work, written for ORCA during the event.

## Owner decisions (Nov 1)

1. The whole basic toolset, the edit log and Muse on both, before the freeze.
2. A hand edit that creates a clash can be kept, behind an explicit **Keep with N clashes**. It is never called
   verified, and the clash joins the clash list (the kept checks run again).
3. The coordination requirements bind hand edits as they bind fixes. ORCA's own hard rules (never cut a transfer
   girder, a column, glazing) **warn** instead of block, and the warning is kept in the log with who must review it.
4. "Cut" means split an object into pieces, and optionally take a section out of it.
5. A person's own "keep it", typed or spoken, keeps an edit Muse checked; so does the Keep button. Muse never keeps on
   its own. MCP agents get `apply_edit` beside `apply_fix`.
6. Accept Muse's fix, then adjust it by hand: the log ties the hand edit to that clash and that fix, and the report
   shows both, in order.

**Second round (Nov 1, after the owner's testing: "too many restrictions on the editing features").**

7. An edit that cannot keep a port joint is allowed behind a confirm, **Keep with 1 open joint**, logged with a services
   review. ORCA keeps the joint instead (the joined segment stretches with it) only when joined parts are carried
   (decision 10).
8. Pushing an I, U, C, L or T section's outer side changes the section, with a structure review warning.
9. Bodies that are not plain extrusions are split, have a section taken out and are clipped with half-space clips.
   Plain extrusions keep their exact path. People may leave 5 mm of a length or a width (`manual.MIN_HAND_M`); the fix
   agent keeps its 50 mm (`edits.MIN_PIECE_M`), and its paths are unchanged.

**Third round (Nov 1, owner: "when we are extending a face, it's pulling everything").**

10. **This face or element only, by default.** Push/pull, align and move change the face or element picked and nothing
    else; a joint they leave open is listed under `joints` and kept only through **Keep with N open joints**. Taking
    joined parts along is a choice (`carry: true`; the Edit tool's **Take joined parts along**, off by default): a
    straight segment joined to a pushed cap follows it, a move takes its run and fittings (`connections.plan_move`), a
    STEP part its touching group. The element's own openings still grow with a pushed face: they belong to it. The old
    opt-out `alone` is still read (it never carries). The fix agent's moves are unchanged: they carry
    (`SIGHTLINE_CONNECTED_MOVES`). The wider program this starts is [editing-parity.md](editing-parity.md).
    A shape or section its type gives becomes the element's own when edited; **Apply to the type** (`scope: "type"`,
    push/pull and align only, off by default and again for each element) changes the type instead, for every element
    of it, each checked ([editing-parity.md](editing-parity.md), "Apply to the type").

## The edit log (`server/sightline/journal.py`)

Every kept edit is one entry, whoever made it:

| Source | Kept by |
|---|---|
| `fix` | an accepted option (`plans.apply`, from the page) |
| `plan` | an accepted plan of several fixes |
| `agent` | an MCP agent (`apply_fix`, `apply_plan`, `apply_edit`) |
| `wider` | an accepted wider fix (`context_planner.accept`) |
| `you` | a hand edit with the Edit tool |
| `muse` | a hand edit Muse checked and the person said to keep, in chat or by voice |

An entry holds what it changed, made and removed (with each element's class and name, so a removed one still has a
name), the files, the revision, the clashes it is for (`clashes`: the clash id when the page or agent knows it, and
the pair), the entries it **follows**, what its check found, its warnings, and its state (kept or undone).

**Follows.** The log keeps a lineage: which entries changed or made each element. A hand edit on an element an
earlier entry changed or made follows that entry and carries its clashes. Editing the middle piece an offset made (a
GlobalId the fix created) finds the fix and its clash with no clash selected. `made_from(gid)` walks the other way:
an element and everything made from it, so a clash can be measured again after its fix split the element.

**How it records.** `Journal.record(scene, source, kind)` wraps the code that keeps an edit. Every keep already makes
one IfcOpenShell transaction per file it changes (`edits.kept_files`); when the block ends, the new transactions on
each file (by identity, empty ones dropped), the boxes that changed (they are replaced when they change, never edited
in place) and the elements made or removed become the entry. Nothing is recorded when the block raises or changes
nothing. A wider fix replaces the scene's state with a private copy: its entry keeps the state before and after.

**Undo and redo.** Undo takes the newest kept entry only ("Undo to here" repeats it). Each file's history must end in
exactly that entry's transactions; otherwise an edit was kept outside the log since, and undo refuses. It rolls them
back, takes them off the file's redo list (a trial since would otherwise come back with them), puts the boxes and the
edited files back, and moves the revision forward (caches are keyed on it). Redo commits the same transactions again.
A wider fix is undone by putting its state back. Measured on the run fixture: an offset undone and redone in place,
its eight new pieces gone and back, the revision 1 → 2 → 3.

**Two traps found on the way.**
- A trial move (`IfcScene.translate` there and back) outside a transaction left the file's history pointing at
  placements it had replaced: the next undo raised `UndoSystemError`. Trial moves now run inside `edits.scratch`, a
  transaction that is always undone (`agent._try_move`, `Workspace.verify_move`).
- `file.redo()` cannot be used: every trial ends its transaction and undoes it, which leaves the trial on the file's
  redo list. The log holds its own transactions and commits them itself. Each file keeps 1,024 transactions
  (`scene.HISTORY_SIZE`; IfcOpenShell's default of 64 would drop old kept edits as trials come and go).

## Faces (`server/sightline/faces.py`)

ORCA edits parameters where it can: a pick (a point and a normal on the element's triangles) is resolved to a face of
one solid of the body (`edits.solids`: each item of the Body, under any clips: an extrusion along its own axis, a mesh,
or other), and pushing that face changes one number in the IFC, or, on a mesh, moves that face's corners.

| Face | Where | Push/pull changes | Also |
|---|---|---|---|
| `cap:start`, `cap:end` | an extrusion's ends: a beam's or duct's ends, a wall's two big faces, a slab's top and bottom | its depth (`edits.stretch`) | align, clip, void |
| `side:±x`, `side:±y` | a rectangle profile's sides (turned in its plane too: its own axes), and an I, U, C, L or T section's outer sides | its width; a section's overall width or depth, the opposite side held, refused when its flanges or web would not fit (`edits.stretch(sections=True)`) | align, clip, void |
| `radial` | a circle profile's round face (its normal where it was picked) | its radius (`edits.stretch_radius`) | align, clip |
| `flank` | an I, U, C, L or T section's inner faces ("inner faces": the web, the flanges inside), or a side of a profile ORCA does not size | nothing | align by moving, clip, void |
| `edge:k` | one straight edge of an outline: a wall drawn as its elevation (its ends and top), a slab's edges | that edge, the edges either side running on to meet it (`edits.offset_edge`) | align, clip, void |
| `plane:j` | a mesh's flat face (`IfcTriangulatedFaceSet`, `IfcPolygonalFaceSet`, `IfcFacetedBrep`): its triangles joined through shared corners within 1° and 1 mm (`edits.mesh_patches`); listed when at least 3% of its area, the 12 biggest | its corners along its normal, the faces round it stretching; ports on it go along; refused on a curved surface or past its other side (`edits.push_mesh_face`) | align, clip, void |
| `clip:j` | a clip's plane (a clipped end); the end it cut away is gone from the list | the plane along its normal: less or more taken away (`edits.move_clip`) | align, clip, void |

A body of several solids (a fitting's pieces, a door's frame and leaf, a desk) lists each solid's faces, their ids
prefixed with its place in the body (`i1:cap:end`, `faces.split_id`); a body of one solid keeps plain ids. A pick finds
the solid it is on (`faces.resolve`: the nearest solid's box, then its face). Each face is named in words from its world
normal and the element's box: "top" and "bottom", else a compass direction and "end" (along its longest size), "face" (a
plate's or wall's big face) or "side"; repeated names are numbered. Muse can say "the east end" (`faces.by_name`; a partial name several faces fit, "end", is refused with the candidates, never
the first of them). A body drawn
from its type (a mapped shape) reads as the solids it draws, so its faces push and pull: the edit first makes it the
element's own copy (`edits.unmap`), the type and its other elements unchanged. A body ORCA cannot read (a swept disk, a
scaled map) can still be moved, aligned by moving and clipped.

**Faces only a pick places.** A section's inner faces, a mesh's face found by a pick, a round side and a face ORCA does
not edit have no plane a name can give: the page sends their pick (`viewer/edit.faceRef`), an op keeps it in its params
(`manual.spec`) so its check and its keep read the same face, and by name they are refused ("need a pick"). A listed mesh
face by name is placed by its own middle. Muse gets the chosen face's pick in the chat context (`selected.pick`; `face:
"selected"`).

Measured on Northbank (1,732 physical elements with a body), Nov 1: before this round, 1,324 had a face to push (408
fittings, terminals, doors, windows, furniture and meshes had none; beams and columns only their ends). Now **all 1,732
do**, listing every face of the three models in 1.6 s: 6,060 sides, 4,408 caps, 836 outline edges, 556 round sides,
548 mesh faces, 119 inner faces. Of the MEP model's mesh faces, 312 push cleanly; the rest are joined ends (below).
Checks on real elements: a 600 x 600 supply diffuser's side, a sliding door's bottom, a UB 457 beam's flange (with the
section warning) all check in 0.1–0.7 s.

## The edits (`server/sightline/manual.py`)

| Op | What it does | Requirements | ORCA's rules (warnings) |
|---|---|---|---|
| `push_pull` | A face out (+) or in (−) by metres. A thicker wall takes the openings through the pushed face with it, however it is drawn (an elevation's cap, a plan rectangle's side, a plan outline's edge): an opening is through the face when its far side on that side is at the face's plane or stands up to 200 mm proud of it, measured before the push, so a beam's web openings stay as they are when its end is pushed, and a slab's soffit recess when its top is. A duct's or pipe's side or radius pushed where it is joined: on its own, a warning that its end no longer matches what it joins; with `carry`, a transition back to the old size at each joined end (`edits.add_transitions`). A face joined to another element by a port: the joint is left open (`system.disconnect_port`, so the other element is checked as any other) and the check lists it under `joints`. With `carry`, when that element is a straight segment on the face's axis joined at its end, it stretches too (shorter when the face goes out) and the joint moves and holds; any other joint is still left open. Each such opening grows on that face (drawn through the wall or across it); a wall end pulled in past an opening is refused, naming it. A shared body gets its own copy first (`edits.make_unique`, styles kept; a type's mapped shape becomes its own copy, `edits.unmap`) | as a resize: "may only be moved whole" refuses it, the largest move applies; what stretches with it is gated too | structure (a building's column, beam, slab, footing or pile, never a machine's part: `hosts.structural`; a transfer element names what stands on it: `hosts.transfer`); a section changed (`section`); a pipe's radius asks the services designer; an open joint asks services |
| `align` | One face flush with another (or a gap off it), by stretching it or by moving the element. Parallel faces: `t = ((pB − pA)·nB)/(nA·nB) − gap`. Faces up to 80° apart meet at the first corner of A (its corners from its solid's mesh, `faces.patch_vertices`): faces turned to each other end on B's outer side, faces turned the same way (level with) stay on the side A is on (`manual._first_contact`); the check offers **Clip it flush** (`offer`). Past 80° it says to clip instead. The target is a face of another element (by name or pick), a bare point and normal, or a **point** with no normal (a corner, an edge's midpoint or a point on an edge, snapped as a measure snaps: `snap` end, mid, edge): A's plane goes through it, the gap short of it. A face target is meant to be touched, so its clearance is waived | as push/pull or move | as those |
| `move` | The element only, by a vector or from one snapped point to another; every joint it has is left open, under `joints`. With `carry`, the element and the straight run it is in, joints kept (`connections.plan_move`), and each wall whose end is path-joined to it has that end pushed along its own axis to meet it again (`manual._retrims`); a level straight it goes square to, joined at its far end too, is re-fitted with a pair of bends at the joined end instead of taken along (`connections.plan_move(refit=True)`, `edits.apply_jog`); when they cannot be, the check offers **Move it on its own** (the op without `carry`) | as a move | structure; open joints → services |
| `void` | A rectangular or round opening on any face with a plane (a cap, a side, an inner face, an outline edge, a mesh face, a clip's plane), centred where it was clicked (on the face's plane), across the face and up it (`edits.face_axes`). Through: rays from just inside each point of its outline find where it comes out (the deepest, refused past 1 m), plus 10 mm proud of each face; when no ray comes out, as deep as the element is behind the face (its mesh), refused past 1 m; or a recess to a given depth. An `IfcOpeningElement` (OPENING or RECESS) voiding the element (`edits.cut_void`, reusing the penetration's void builders) | a cut: only where the group may be edited in any way (`requirements.can_cut`) | ORCA's hard rules for hosts (`hosts.hard_rule`: a transfer element, a column, glazing…) and structure; an outline within 50 mm of the face's edge is "a notch more than a hole" |
| `cut_by` | Cut an element where another one is, with a gap all round: an opening shaped as the cutter grown by the gap (`edits.cut_by_shape`). Exact for extrusions (a rectangle +2 gaps, a circle +1, an outline offset by `edits._grown`, an I, U or L section as its bounding rectangle, the depth +2 gaps), in the cut element's file and units; any other cutter (a fitting's mesh) is welded and pushed out along its vertex normals, and the warning says the gap is approximate. Refused when the cutter does not reach it | a cut | as a void |

| `split` | One element becomes two where the plane square to its long axis passes through the point clicked (snapped like a measure). Along a run with ports (a duct, a pipe): `edits._build_chain` with two straights, the ports chained across the cut. Along a member without ports (a beam, a transom long along its profile): a copy, then each trimmed to its side (`edits.apply_trim`). Across an outline (a wall drawn as its elevation, a slab): the outline clipped to each side of the line (Sutherland–Hodgman). The element keeps the first piece and its GlobalId; the second is a copy named "… (part 2)" (`root.copy_class`: type, properties, container, systems; the openings it duplicated are dropped). Each opening goes to the piece that holds it; a piece under 5 mm is refused. **Any other body, or where that exact path refuses** (a cut through an opening, an outline with holes): split by clips (`edits.split_by_clip`), square to its long axis (`edits.long_axis`: its extrusion's, else the axis of its placement it is longest along): the element is clipped beyond the plane, a copy (its class, properties and openings, its own deep copy of the body) before it; the copy's ports are dropped, so its joints stay with the first piece (said so), and what fills an opening stays with the first piece (said so) | any edit: "may only be moved whole" refuses it | structure; clipped; joints with the first piece → services; fillings → design |
| `remove_section` | Split at the first point and at the second, then remove the middle with what it held (`edits.remove_product_with`); the rest keeps its place and is named "… (part 2)". By clips, both cuts are square to the whole's axis. A run's two new ends are left open, said so for the services designer | any edit | structure; open ends → services |
| `delete` | The element, with its openings and what fills them, the parts it aggregates and its ports (`edits.remove_product_with`); its boxes forgotten (`IfcScene.forget`). The log keeps the names of everything removed, so undo and the report can say what came back | any edit | structure; what fills its openings; peers left with an open end; elements standing on it |
| `clip` | Cut the element's material beyond another element's face (any angle, with a gap): an `IfcBooleanClippingResult` with a half-space (`geometry.clip_solid`) round every solid of its Body that the plane crosses, meshes too (a solid wholly beyond is dropped), the Body's type "Clipping" (`edits._clip_items`). Any face picks the element. Refused when the plane misses it or leaves less than 5 mm. A clipped element still has faces: each clip's plane is a face (`clip:j`) that pushes and pulls, the end it cut away is gone, and its other end pushes and pulls as before | as a trim (`trims`) | structure |
| `offset` | A section of a level duct, pipe or tray between two points along it (`from`, `to`) taken up, down or sideways square to its run (`toward`: up, down, a compass word, or a direction; `by_m`), with 90° bend fittings either side, or (`bend_deg` 45, the tool's **45°**) up a slope with 45° bends either end: the fix kind's own geometry (`edits.apply_offset`, its `lateral_m` for sideways), so its ports chain through the pieces and the far joint is handed on. Refused along the run, off a level run, or for anything but a flow segment ([editing-parity.md](editing-parity.md), Tier 2) | as an offset | structure |
| `join` | Two straight segments' nearest free ends (`edits.join_plan`, `join_segments`): on one line, the first stretched to the second; square to each other in one plane, both brought to the corner less a bend radius (one section depth) and a 90° bend fitting between, its ports placed and joined to both. Refused for other angles, different kinds or sizes (a transition is needed), an end already joined, or an end within a bend's radius of the corner | as a resize | structure |
| `disconnect` | One of the element's port joints left open (`system.disconnect_port`): the one to `from`, else nearest `at`, else its only one. Listed under `joints`, kept only as **Keep with 1 open joint**: how a run is split at a fitting | any edit | open joint → services |

Measured on the fixture: a 400 x 300 mm opening through the wall lands at x 2.8–3.2, z 1.35–1.65 and comes 10 mm out of
both faces; the wall pushed into the column and then cut round it with a 20 mm gap clears the clash at exactly 20 mm.

Each op is resolved first (`resolve`: which face, how far, in words: "east end of wall 'W1' pushed 500 mm out"), gated by
the requirements (`gate`), then made in a trial (`edits.trial_files`) and checked (`verify.check` on what it changed and
made, against everything): what it **clears** (collisions there before and gone), what it hits **new**, and what it hits
**worse** (2 mm deeper than before, the rule trims use). New or worse collisions are its clashes; shortfalls of clearance
are counted apart. A refusal is not an error: the check says `blocked` and why.

The trial is also read for **consistency** (`consistency.py`, [editing-parity.md](editing-parity.md)): what the model
says besides the shape (a layered element's layers, a profile set's section, an `Axis`, a path join, a type's maps,
base quantities), before and after. Every hand edit first brings that data along with the body (`parametric.py`: the
layer on the pushed face, the new section as the material profile, the axis, the quantities, a split's join; a shared
set or a type's shape copied for the element alone), so the check refuses only what still disagrees, in words with the
numbers (under `consistency`). Only what the edit makes worse counts.

**Keeping** (`manual.apply`, `POST /edit/apply`) never trusts the page: the edit is checked again on the server, refused
(409) when the requirements forbid it, the model changed since its check (`key`: a hash of the op, the revision and the
requirements), or it would make more clashes than the person accepted (`accept_clashes`, "Keep with N clashes") or
leave more joints open than they accepted (`accept_joints`, "Keep with 1 clash · 1 open joint"). Then it
is made for good inside `journal.record` and `edits.kept_files`, the files marked edited, the revision bumped. When the
edit names a clash (the one on screen, and only when the edit touches its elements or what a fix made of them) or
follows a fix, the clash is measured again over its elements and everything a
fix made from them (`made_from`, one index for all the pairs: `detect.measure_pairs`), and the entry says whether it is
still resolved; a hand edit that resolves the clash on screen marks it fixed. Undo and redo measure each of the entry's
clashes again the same way (`manual.clash_states`) and the page opens or marks fixed from that, for a fix and a hand edit
alike. Kept with clashes, the page runs the kept checks again, so the new clash joins the list: that run is not a
detection run's charge but has its own cap, three times larger (`app.edit_rerun_limit`).

Measured on Northbank: a check takes about 1.1 s (a wall end pushed 200 mm into the curtain wall: four transoms and
panels hit); clash #1's duct made 50 mm deeper reads "Makes 1 clash: girder −350 mm" and keeps only as "Keep with 1
clash". The answer key still passes 3/3 first try at Rev04's heights after the trial moves moved into `edits.scratch`.

On the run fixture: the supply main's east end pushed 300 mm makes it 6.3 m and leaves its end segment as it was, the
joint open (kept only with "keep it with 1 open joint"); carried, the end segment becomes 0.7 m, still joined at
x = 6.3. Pulled in 200 mm it leaves the joint open, refused until "keep it with 1 open joint", and undone the joint is
back.

## Muse, voice and agents

- **Chat** (`chat.py`): `list_faces` (an element's faces by name, or "selected"), `edit_check` (any op; the page previews
  it in the Edit tool with its own Keep: ui `edit_preview`), `edit_keep`, `undo_edit` and `list_edits`. The chat's
  [context] line now says what the user has selected (and the Edit tool's chosen face) and the last three edits kept.
  `face: "selected"`, or the chosen face's name, sends that face's pick (`Chat._chosen_face`).
- **Only the person keeps** (`chat.consents`): `edit_keep` keeps the edit Muse checked last for this conversation, only
  when the person's own message in this turn says so ("keep it", "apply it", "do it", "yes", "go ahead"; a bare "keep"
  is not consent, since "keep 25 mm clear" means maintain; refused when it also says don't, cancel, stop, wait, or
  starts with no), and never in the turn Muse checked it unless "keep it" is all they said: the person sees the preview
  first. An edit that makes clashes needs `accept_clashes` and the person to keep it *with* them (`chat.accepts`: "keep it
  with the clash", not "keep it if it makes no clashes"); one that leaves a joint open likewise ("keep it with the open
  joint"). `undo_edit` needs "undo", "revert", "take it back" or "put it back", with no refusal anywhere in the
  message ("don't revert it" undoes nothing; "go back" is navigation). Reviewed on PR IssueLab-Inc/ORCA#92. The
  prompt (`domain_packs/chat.md`) says the same: never on Muse's own initiative. A kept edit is logged as `muse`.
- **Voice** is chat with the words spoken (`voice_live.py` only transcribes), so "make this beam 200 mm longer at the
  east end" and then "keep it" work by voice.
- **The fix agent** hears about edits already made to a clash's elements (`Workspace._with_edits`, in the clash's notes
  that `_describe` reads): kept ones to build on, undone ones not to propose again. Nothing is added when there are none.
- **MCP** (`mcp_server.py`): `list_faces`, `check_edit`, `apply_edit` (`accept_clashes` and `accept_joints` only when
  the person asked),
  `list_edits`, `undo_edit`, `redo_edit`. Keeps are logged as `agent` with the link; the page follows (`edit_kept`,
  `edit_stepped` with the patch).

## Reports, BCF and export

- **The report** (`document.py`; the page's PDF and MCP's `generate_report` both read the log, through
  `app._build_document`): each clash's page gets **What was done**, its entries in order (who, when, what, the check
  in words, warnings with who reviews, "after E1" for a follow-up), its state ("Fix applied", "Edited by hand", "Fix
  applied, then edited by hand", then "still resolved" or "clash back (−12 mm)", from the entry's re-measure) and the
  picture the page took after the last edit ("After the edits"). A clash with entries and no evidence from the page
  still gets its page, so a fix an agent kept is reported. Muse's explanation reads the same timeline (`_facts`). The
  actions table says the state. **Changes to the model**, after the summary, lists every kept entry with its clash
  numbers, its check and its reviews (a per-team or per-model report lists the entries for its clashes).
- **BCF**: each clash topic gets a comment per entry ("ORCA edit log"); a hand edit no clash page holds that someone
  must review (warnings, or kept with clashes) gets a Request topic of its own, its elements selected.
- **Export** (`Workspace.export`): every element a kept entry changed or made carries `ORCA_Edit` (EntryIds, Ops,
  Summary, Source, When, Clashes) in the written IFC. It is written inside `edits.scratch` around the write, so the
  live models, and the log's undo, never hold it. A zip (several files, or STEP and IFC) also holds `orca-edits.json`
  and `orca-edits.csv`; a single file stays a bare IFC. STEP: a part a hand edit deleted is taken out of its assembly,
  its own shape with it once nothing uses it (`step.export(remove=)`, `service.step_removed`), a box whose side or a
  cylinder whose radius was pushed is written with its new profile, and a part a kept hand edit reshaped otherwise (a
  mesh face pushed, a clip, a cut: `service.reshaped`) is written as its shape now. IfcOwnerHistory is left as it was.

## On the page

- **The Edit tool** (`web/src/EditTool.tsx`, **P** or the rail's Edit button; measuring and editing take turns): a panel
  beside the rail with the palette (push/pull, align, move, void, cut by shape, split, remove a section, clip, offset,
  join, disconnect, delete; inside the tool their keys are P, A, T, O, K, B, R, J, F, N, X and D). An offset takes where
  it starts and where it ends on the run, then Up, Down or a compass side (`offsetWays`) and how far; a join takes one
  segment, then the other; a disconnect, the element near the joint. A point clicked for a split, a section or an
  offset snaps as a measure does, but only to the element picked (a snap further than 0.3 m from the pick, on the
  context drawn see-through around a clash, is ignored); the forms leave numbers to the server (`noValidate`: a 400 mm
  offset is not "invalid" for a 10 mm step). The face under the pointer is lit faintly; a click chooses
  it (the server names it: "top of duct segment 'Supply air main L02 600x300' · 0.300 m") and lights it orange with an
  arrow. Drag the face (5 mm steps, Shift for 1 mm) or type how far: the element stretches live, as one instance matrix
  (`viewer/edit.ts`, `pushMatrix`), every drawing of it with it (a clash pair is drawn by the focus layer: its focus mesh,
  edges, selection and lit face take the matrix, `Viewer.syncDrawings`), the distance at the arrow's tip ("+150 mm");
  a check's drawing goes once, when the drag starts (`EditDrag.onStart`). On release the server checks it and draws what
  it would really be, green when clear, amber with clashes. Align takes the face to move, then the target (lit green, or
  a snapped corner, edge midpoint or edge point), a gap and stretch-or-move, and previews at once from the two picks
  (`alignDistance`, `pointDistance`) before the server's check replaces it; move takes a vector or two snapped points.
  Keep, or **Keep with N clashes** / **Keep with 1 clash · 1 open joint** (`keepLabel`); a check's offer is a button
  (**Clip it flush**, **Move it on its own**, which also turns carrying off). **Take joined parts along** (push/pull,
  align and move; off by default, remembered for the visit in `sessionStorage` `orca.edit.carry`) sends `carry`;
  **Apply to the type** (push/pull and align; off by default and again for each element) sends `scope: "type"`. Each
  shows only where it does something: the face picked says how many parts are joined to the element and which type an
  edit there would change, with how many others (`choices`; "Apply to type FT-BOX · 1 other"). A check reads as the
  edit, then each thing it brings along on its own line (`effects`), then **Also changes N other elements**, by why,
  a few names each (`also`, `alsoGroups`: same type, a joined wall's end, taken along, re-fitted, new part), with
  **Show them** to frame them all before keeping it. A Properties panel floating over the model closes when the Edit
  tool opens (one docked in a side bar stays). Esc steps back one thing at a time.
- **No dead ends**: a face the tool cannot take is still chosen and lit; the panel says why and offers the tools it does
  take as buttons ("Align it", "Move it", "Cut a void"), keeping the face across the change of tool.
- **The Edits panel** (`web/src/EditPanel.tsx`, a tab in the right side bar beside Clash, Plan and Chat): the log,
  newest first. Each row says who kept it, when, its clashes, "after E1" when it follows a fix, what its check found and
  any warning with its reviewer; a click frames it. An undone entry says **Undone** in its header and hides its stale
  clash state; **Redo** sits at the foot of the entry next to redo, **Undo to here** at the foot of each kept entry below
  the newest. Undo, Redo and the log as CSV head the panel. It comes into its bar, behind the tab in front, the first
  time something is kept.
- **Ctrl+Z** undoes the newest kept edit, **Ctrl+Shift+Z** or **Ctrl+Y** redoes it (not while typing). A fix undone
  leaves its clash open again.
- **Removed elements** (undo of what a fix made, a delete) leave the viewer's batches in place (`patch.removeElements`).

## Icons

The edit tools' icons (`web/src/editIcons.tsx`) act out what each tool does (an offset's middle lifts over, a join's ends
close in round a bend, a disconnected joint parts): they play once on hover or focus and loop gently while their tool is
on. Motion follows the brand's rules (`docs/brand-assets.md`): checking plays only while a
check really runs, Keep settles once only after the server kept the edit. Under reduced motion they hold still.
