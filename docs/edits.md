# Edits: the kinds of fix ORCA can make

Every fix ORCA offers is an edit to the real IFC elements, tried in a transaction, checked by geometry and undone
before anyone sees it. This page is the design of the kinds of fix and how a new one is added. Code:
`server/sightline/edits.py` (the geometry), `agent.py` (trying ideas), `plans.py` (several fixes at once), and
`web/src/fixKinds.ts` (how the page describes them).

## Kinds

| Kind | What it does | Since |
|---|---|---|
| `move` | Moves a straight run by a vector, keeping its joints: fittings and valves beyond it go along, a segment the move runs along gets longer or shorter; refused when a joint can't be kept (`docs/connections.md`) | Oct 27 |
| `offset` | Splits a straight segment either side of an obstacle and takes the middle up or down (or sideways), with bends | Oct 27 |
| `trim` | Cuts a slender member's end back to butt another's face | Oct 27 |
| `route` | Holds stretches of a straight segment at offsets (up and/or sideways) in up to 3 steps, with bends | Oct 29 |
| `resize` | Makes a stretch of a rectangular duct or tray flatter (one face level, wider to carry the same), with transitions | Oct 29 |
| `penetration` | Asks for an opening where a straight service crosses a wall or slab: a provision for void always, the opening cut when the host's team allows edits | Oct 29 |

## One registry (Oct 29)

Each kind is registered in one place per layer, so a new kind is added by registering it, and a kind nobody
registered is refused instead of being tried as a move (before, anything Muse called by another name was moved by
its `delta_m`):

- **Trying an idea:** `agent.TRIES[kind]` → `(scene, candidate, target, other, clearance, on_trial, others=)` →
  `(Attempt, Option or None)`. `agent.PARAMS[kind]` names the candidate fields that describe it (carried into a
  recommendation, which is never tried).
- **A plan's joint check:** `plans.IN_TRIAL[kind]` applies it inside the plan's trial and says what to check;
  `plans.EXTRA_FILES[kind]` names files it changes beyond its moved elements'.
- **Keeping it:** `plans.KEEP[kind]`, behind `plans.apply`, which the plan, the MCP `apply_fix` and the page's
  `POST /api/scenes/{sid}/fix/apply` all use. That endpoint drops the page's meshes; `plans.apply` tries the fix again
  first (`plans.CANDIDATE[kind]` turns the option back into Muse's parameters for `agent.TRIES`, with the clearance and
  requirements of the clash it names in `pair`), refuses it with a 409 when it no longer passes, and keeps every
  option or none (Oct 30).
- **Sizing it against the requirements:** `requirements.SIZED` and `change_size` (how far any part goes; a lateral
  offset used to measure 0 mm).
- **The page:** `fixKinds.ts`: the name, the edit in a few words, the clearance line, which pieces to frame, who must
  review it. The newer kinds carry the server's own `edit.summary`, so the page says what Muse was told.

An option of a newer kind carries `edit` (its parameters, a `summary` and a `key` that tells two fixes apart) and
`review` (who must review it before it is built, when geometry alone cannot say it works).

## Ranking

Plain geometry fixes (move, offset, trim, route) rank before a resize (it changes how a service performs), and a
resize before a penetration (another team builds it): `agent.TIERS`; an opening in a wall or slab before one in
anything else. Then comfortable clearance, the smallest change,
the most clearance. A round that verified only a resize or a penetration does not end the search: Muse gets one more
round to find a plain fix.

## Several obstacles

A plan merges pairs that share a movable element into one item (`plans.merge_shared`). The agent now gets those other
obstacles as `Clash.others`: they are placed along the run in the text Muse reads, and a split run's shortened end
pieces are checked against all of them, not only the first (before, an offset could pass while its end still ran
through the second obstacle). Failed attempts also tell Muse where the worst hits are (`Attempt.where`).

## Route (Oct 29)

A local offset lifts or drops one stretch of a run. A route generalises it for the cases an offset cannot reach: the
room is only beside the obstacle (a column, a post), or one run meets obstacles that need different detours.

**The shape Muse proposes** (`domain_packs/construction.md`):

```json
{"kind": "route", "move": "A",
 "steps": [{"from_m": 1.75, "to_m": 2.55, "up_m": 0, "side_m": 0.2},
           {"from_m": 4.25, "to_m": 5.05, "up_m": 0, "side_m": 0.2}]}
```

- Offsets are on the run's own axes (`edits.run_frame`): **up** is world Z made square to the run; **side** is
  cross(up, run), to the left of its direction seen from above (the text names its compass direction).
- A step holds a stretch at a constant offset. Between steps the run returns to its line; steps that share a boundary
  change straight from one offset to the next. Up to 3 steps.
- **Each change is one axis at a time**, so "up, then sideways" is two steps sharing a boundary. A change on both axes is
  refused with how to say it instead.
- A single step straight up or down is an offset and is tried (and kept) as one.

**Geometry** (`edits.apply_route`):
- The steps become transitions (where the offset changes). Each transition is a 90° bend, a riser and a bend, with
  `bend_radius` on its own jump and the profile size in its own plane (up changes use the vertical size, sideways
  changes the horizontal one); legs along the run keep the 50 mm minimum, and square corners (no fitting class, or a
  bend that would fold) apply to the whole route.
- The pieces are chained by `_build_chain`, the same code the offset uses (moved out of `apply_offset` unchanged): the
  element keeps its first piece and GlobalId, copies share its profile, bends are new fittings, ports are chained and
  the far connection handed on. A one-step route builds exactly the offset's pieces (a test compares the meshes).
- **Slopes:** runs up to 15° are accepted; the profile must be upright against the run's own up. Pieces along the run
  keep its fall. Vertical runs are refused.
- **Drainage:** a gravity pipe (its system is drainage, sewage, storm, rain or waste water, or its names say so) may
  only step sideways, and only when level: stepping it up or down would trap what it carries.

**Checking:** as the offset: the new pieces against everything, the shortened ends against the obstacle (and a plan's
other obstacles).

**What Muse is told** (`agent._room_text`, `edits.free_bands`): for each obstacle along the run, the side offsets (and,
when the obstacle has no opening, the up offsets) at which the run's profile, with the clearance all round, passes that
stretch clear of everything, not only the obstacle. Rays run along the stretch round the profile's outline (every
30 mm) and at its centre; a ray inside a solid counts as blocked (its middle in an element's box); a band counts only if
the run can reach it square from its line at both ends of the stretch. Only triangles that reach the stretch are kept, binned by where they sit
across the run so each ray tests its own cell (a mesh is triangulated with CGAL); past 200,000 triangles the room is
not told. It is worked out once per proposal, not every round. A dense 28,800-triangle mesh beside a run: 52 s
before, 0.6 s now, with the same bands on every fixture and cell case. On the cell's C6: beside column C3, side offsets
+0.20 to +0.29 m (between the column and the fence); past both columns at once, none (ES-2 is between them). For a single
proposal on a report clash, the moving element's other clashes within 3 m of where the pair meet are named too
(`Workspace._nearby`, per side: each element hears of its own): a route may clear them together, but only the asked
clash is required (never the fixed side's: a girder's other services are their own clashes).

**Demo case:** the cell's C6 (demo-models repo): PL-302 runs along the plant's south wall through columns C3 and C4.
Offsets over or under fail (the columns run full height), a whole-run move or one long detour hits the ES-2 emergency
stop between them; a detour of 200 mm round each column clears with 33 mm to spare.

**Not yet:** 45° pieces, falling drainage, and routes in the wider-fix planner. (Diagonal "rolling" changes are
done, for round pipes only.)

## Penetration (Oct 29)

Services cross walls and floors all the time; what they need is an opening, and someone else builds it. A
penetration asks for one instead of moving the service.

**When** (`edits.penetration`, `not_penetrable`): a straight service (an extruded segment, any direction, so a riser
through a slab too) crosses a host whose body is extrusions. Which hosts may take one is `hosts.decide`'s call (next
section; on Oct 29 at first walls and slabs only). Refused by geometry: a crossing that runs more than 1 m inside the
host (along it, not through it), one the service doesn't reach or pass through, a service that stops inside the host (it runs into the wall:
move or shorten it), and an opening the host would not
surround by 50 mm (a hole at its edge is a notch).

**The opening:** the service's section plus the clearance and 5 mm all round (tessellated circles, site tolerance),
rounded up to 10 mm, round or rectangular like the service and square to it. Its depth comes from rays along the
service round the opening's outline (every 30 mm) from both sides of the host: the host's whole depth and 10 mm proud
of each face. The cell's air main (DN50, 60 mm) through the 200 mm west wall: Ø130 mm, 220 mm deep.

**Written** (`edits.apply_penetration`):
- **Always** a provision for void in the service's model: an `IfcBuildingElementProxy`, PredefinedType
  PROVISIONFORVOID (IFC2X3: ObjectType "ProvisionForVoid"), in the service's storey, with `Pset_ProvisionForVoid`
  (Shape, Diameter or Width/Height, Depth, System) and a see-through orange style, so the page draws it in the glass
  batch. From STEP it carries the service's `ORCA_STEP` label.
- **When cut** an `IfcOpeningElement` with the same solid in the host's model, voiding it (`feature.add_feature`), and
  the host's box refreshed.
- A provision for void is never physical (`scene.not_physical`): no box, never in `products()`, so detection, checks,
  root causes and requirements never see it.
- **One request:** the provision carries `ORCA_Provision` (Service, Host). Asking again reuses it (`provision_for`);
  while the host still may not be cut, a new proposal is told the opening was already requested and refuses it.

**Trying it** (`agent._try_penetration`): both files in one `trial_files`, always cut, then the service is checked:
it must clear the host by the clearance (and every other element a plan's merged item is for: one opening does not
clear a second wall), and only contacts new or worse than before count elsewhere (the service
stays where it is: a valve already beside it is not this fix's). The option's clearance is the opening's gap round
the service. Muse names the service as `move`; a wall or slab named instead is taken as the host
(`penetration_sides`). The option's `moved` is the host (its geometry changes in the viewer), its `edit` names
service and host, and the preview is the provision for void and the host with its hole (the page frames the first).

**Who reviews it** (`hosts.decide`, and `hosts.default` when nothing else answers; "Which hosts" below): structure
for a slab or a load-bearing wall (`Pset_WallCommon.LoadBearing`), else architecture; a `FireRating` adds
fire-stopping to `also_needs`. Ranked below every plain geometry fix
(`TIERS`), and a round that verified only a penetration gets one more round to find one.

**What Muse is told** (`agent._penetration_text`): that the service crosses the host's full depth, the opening a
penetration asks for, who cuts and reviews it, and, when the service runs out of both faces, that a fix which stops it
crossing (a move along it) cuts it off from what it serves. Walls and slabs are no longer described as runs to split.
Prompt: `construction.md` "penetration".

**Kept** (`Workspace.apply_penetration`, behind `plans.KEEP`): sized again with the clearance the requirements ask
for. The opening is cut when there are no requirements, or the host's group may be edited in any way
(`requirements.can_cut`); otherwise only the provision for void is written, the reply says `cut: false` with
`blocked_by`, and the clash stays open: the page records the fix as requested (evidence "recommended", "Opening
requested" in the clash panel, the PDF and BCF as for a recommendation), plans and the MCP `apply_fix` /
`apply_plan` leave its clashes unmarked (`not_cut`). Under "move only" requirements a penetration is still allowed
(it only asks); under "no edits" for the service it is blocked. `meets` says whether the opening was cut.

**STEP:** export cuts the host's prism with each opening (`BRepAlgoAPI_Cut`; a boolean OCP cannot do leaves it whole,
the IFC still has the opening) and adds the provision for void as a part of the service's group, see-through orange.

**Demo case:** the cell's C7 (demo-models repo): the plant's existing compressed-air main runs through the full-height
west wall with no opening. Nothing goes round it; the opening is the fix (Rev B has a 150 mm one).

**Measured** (`evals/step_cell.py`, three runs on the cell after its other fixes): the opening offered every time
(34-42 s), kept and cut, the STEP's wall 2,655 cm³ smaller. Twice Muse also offered a whole-run move of the air
system that pulls the main out of the wall (it verifies, and as a plain fix ranks first); once after the "keeps
crossing" line was added. Geometry cannot tell that the main serves something beyond the wall; the person picks.

**Not yet:** sleeves and fire-stopping as elements, openings for several services at once, and penetrations in the
wider-fix planner.

## Which hosts (Oct 29, owner decision)

A wall or floor is opened for services all the time; a transfer girder never; a steel beam's web sometimes, within
limits; a machine panel's gland plate is made to be drilled. `server/sightline/hosts.py` decides, strictest first:

1. **Hard rules** (`hosts.hard_rule`, no model call, nothing overrides them): columns, doors, windows, curtain walls,
   piles, footings, stairs, ramps, railings, lifts; services and equipment (`IfcDistributionElement`: a pipe is never
   cut for another pipe, a motor control centre is entered through its gland plate); glazing (a plate or window whose
   name or material says glass: Northbank's opaque glass spandrels too); see-through proxies (clearance zones, a robot's
   restricted space); anything not physical; and a **transfer element**: a beam or member that a column or wall stands
   on (its foot within 5 mm of the beam's top, overlapping in plan). That last rule, not Muse, keeps the Northbank
   girder (column B3 stands on it) out of every proposal on the golden path.
2. **The requirements** (`penetrations` in `orca-requirements/1`, optional): per group, allowed / review / never, the
   largest opening and the reviewer. They win over Muse; a file without the section keeps its id. The fixes prompt
   lists them. The dialog has "Openings for services" (Muse decides / Allowed / With review / Never, size, reviewer),
   and an opening option read by Muse has **Add to requirements**. That rule is for the reading's kind of host only
   (`kind`: `hosts.profile`'s key, `kind_name` in words; `edit.host_kind`), never the whole group: a cell's gland plate
   read "allowed" must not open its base plates and guard panels, which read differently. A kind's rule beats its
   group's; the dialog lists kind rules under their group, each removable.
3. **Muse's reading of each kind of host** (`hosts.read`, `domain_packs/penetrations.md`, strict JSON, on the triage
   model): verdict (allowed, with_review, not_advised, never), reviewer, fit (annular: a clearance filled by a sleeve or
   fire-stopping; fitted: a gland or grommet), limits (largest hole for the host's depth, distance from its ends in
   depths, from its edges, the middle third of a beam's depth), conditions, reasoning. Read once per kind (class, type,
   name words, materials, thickness, standard `Pset_*Common` properties, discipline, STEP assembly), cached for the
   server's life, before a proposal's first round when a service crosses a host (`agent.penetration_pairs`). Facts are
   text only, and a project's own property sets never reach it (Northbank's demo property set holds its
   answer key). A failed reading leaves the default: walls and slabs as in 4a, nothing else. The model is resolved per
   request (`Workspace.hosts_model`: the open-weights choice and the owner's settings apply as for triage), with a 60 s
   timeout so a slow host does not hold the proposal; Muse's limits are kept only as numbers in range (`hosts.LIMITS`),
   its conditions and reasoning are capped. Pairs are found before the opening is sized, so a gland plate too narrow
   for an annular opening is still read (it may take a fitted one).

**The hole against the limits** (`hosts.check_hole`): the host's depth is its smaller size in the hole's plane (a
beam's depth for a pipe through its web), its ends those of its longer size; edges by rays from just outside the hole.
A hole that breaks a limit is refused with the numbers (when tried, and again when kept: the rules may have changed
since the option was made); a passing one carries them (`edit.numbers`: "hole 170 mm in
600 mm of host (28%)", "915 mm from its nearest end"), shown on the option card with the reading.

**Fitted openings:** the service plus 1 mm round, to the mm (a 32 mm conduit: Ø34), and the service may touch the host
(the gland seals it); in a plan's joint check too. The option's `meets` says "a fitted gland, sealed round the service
(no clearance there)", never a clearance it does not have.

**Ranking:** an opening in anything but a wall or slab ranks after one in a wall or slab (`agent.tier`).

**Muse is told** (`_penetration_text`) the reading in a sentence, or that the host may not take an opening and why
("never: It is a transfer element: UC 254x254x89 - B3 stands on it. Do not propose a penetration of B."), and when the
hole would break a limit at this point.

**Measured** (`evals/penetration_hosts.py`, 25 labelled hosts from Northbank and the cell, `penetration_hosts.csv`):
25/25 as a coordinator would say on Muse Spark, 18 kinds read in one call in 34-41 s; 7 settled by hard rules. Walls
and slabs with review by structure or architecture, an external wall by architecture, the lift pit wall not advised
(tanking), steel beams with review or not advised, base plates, stiffeners and mullions never, the gland plate allowed
and fitted, the guard panel with safety review. Readings vary run to run within those labels (a secondary beam with
review or not advised).

**Demo case:** the cell's C8 (demo-models repo): the plant's 400 V feed drops in a 32 mm conduit into EP-301 through its
top gland plate (3 mm) with no hole. The fix is a gland hole.

## Resize (Oct 29)

Where an obstacle leaves too little depth above or below a duct or tray and nothing else clears (a ceiling under it, a
slab over the beam, walls either side), the designer's answer is a flatter section for that stretch, wider so it
carries the same.

**The shape Muse proposes:** `{"kind": "resize", "move": "A", "split_m": [2.5, 3.5], "depth_m": 0.22, "keep": "bottom"}`.
ORCA works out the width (`edits.resize_size`):
- **a rectangular duct** keeps its equivalent diameter (Huebscher, `1.30 (ab)^0.625 / (a+b)^0.25`), the width to the
  next 5 mm, and is refused flatter than 4:1 ("830 x 200 mm would be 4.1:1 ... no shallower than about 205 mm");
- **a cable tray** keeps its cross-section, at least 50 mm deep;
- **refused:** pipes (their size is set by their flow), round ducts, any profile but a plain `IfcRectangleProfileDef`
  (exactly: a hollow, rounded / flat-oval or channel profile would come out as a solid rectangle), parts from STEP (no
  profile to change), sloped runs, tilted sections, split points or depths that are not finite numbers (refused before
  anything is edited), and a stretch that leaves no room for its transitions.

**Geometry** (`edits.apply_resize`): five pieces through `_build_chain`: the original shortened, a transition fitting
(`IfcDuctFitting` TRANSITION / `IfcCableCarrierFitting` REDUCER, a closed lofted `IfcTriangulatedFaceSet`, every face
at most 30° from the run: `transition_length`), the resized middle (a copy with a profile of its own, never the shared
one, shifted so the `keep` face stays level; its ports at its own centre), a transition back, and the rest. The
centreline stays put across. `_build_chain` gained straights with their own profile and transition pieces (with where
their ends' centres sit). **The new size is written on what the reviewer reads** (`_label_resize`): the middle's name
(a "600x300" in it becomes "795x240", else the size is added), its profile's name, its own copies of the original's
properties that held the old size, and an `ORCA_Resize` property set (ResizedFrom, Size, KeepLevel, Performance); the
transitions are "… transition to 795x240".

**Checking:** as an offset: the transitions and middle against everything, the ends against the obstacles.
**Review:** the services designer (`review: "services"`), with the performance line in `also_needs` ("equivalent
diameter 100% of before, 3.3:1"). Ranked after every plain geometry fix (`TIERS`), and a round that verified only a
resize gets one more round. Under the requirements a resize is sized by how far its moving face goes
(`edits.face_move`: the whole change with the bottom or top kept, half with the centre kept).

**What Muse is told** (`agent._resize_text`): when the obstacle is above or below the run, how deep the section can be
there with the clearance, keeping the far face level, how wide that makes it and what it keeps, and how much run each
transition takes. Prompt: `construction.md` "resize". Chat and MCP: `check_resize`.

**Checked:** `tests/test_resize.py` (11) on `fixtures.build_resize_fixture` (a 500 x 300 duct 50 mm into a beam with
a slab above, a ceiling below and walls either side: 735 x 220 mm bottom kept, 30 mm clear). In the browser, uploaded
through Use your own models, Muse tried a drop and a raise (both fail) and proposed "Flatten duct to 225 mm deep under
the beam" (710 x 225 mm, verified, 25 mm); accepted in place. No planted demo case.

**Not yet:** round ducts (flat oval), resizing at fittings, and keeping a pressure drop rather than an equivalent
diameter.

## Keeping a fix: the model updates in place (Oct 29)

Accepting a fix used to download the whole file it changed (and the server wrote the whole IFC out for that download)
and re-parse it in the browser. Now every way of keeping a fix answers with what changed:

- **Server:** each apply reports `changed` (the moved run, a split run's pieces, a trimmed member, a plan's or wider
  fix's edits), and the endpoints, the MCP `apply_fix` / `apply_plan` and the agent link's `applied` event add
  `Workspace.patch`: `scene_id`, `revision_before`, `revision`, and `meshes`, the changed and new elements' triangles
  taken after every edit of the request (`edits.meshes(render=True)`: unwelded, with normals, the style's colour and
  opacity, and the element's file). No meshes when one will not triangulate or there are more than 500,000 vertices.
- **Page:** `applyToViewer` (App.tsx) patches when the reply has meshes for this scene and the page's model is at
  `revision_before` (from opening: `revision` in the open, upload and scene-info replies, resume included); otherwise
  it reloads this fix's files and every file changed by an edit it missed (`history`: which files each revision
  changed, `IfcScene.bump`; all edited files when the page doesn't know its revision). Either way it then knows the new
  revision.
- **One request, one revision range:** `_with_patch` and the MCP `apply_fix` / `apply_plan` read `revision_before`,
  keep the fix and take the patch under the workspace lock, so another tab's edit never lands in between.
- **Colours:** the patch's meshes carry only the model's own styles (no IfcOpenShell class defaults), so an unstyled
  element keeps the colour the page drew it in.
- **Viewer:** `viewer/patch.ts` (`patchModel`, pure over the loaded model): an element keeps its instance and gets the
  new geometry (add, point the instance at it, then delete the old one: deleting first would delete the instance); a
  new piece gets its own instance, coloured from its mesh or the element it came from, in the see-through batch when
  its opacity says so (made when the model had none). Batches are built with spare room (`ROOM`); `makeRoom` packs
  out freed space, then grows by twice what is needed. The viewer then drops its focus cache (it shares the buffers),
  resets the scene size and redraws.
- **Measured:** the server answers an offset on Northbank in 0.23 s with 9 meshes (936 vertices); in the browser no
  file is fetched after an accept. On Northbank's 2.3 MB MEP file the headless browser is barely faster (4.0 s
  against 4.4 s after the reply, software rendering dominates); the gain is the parse of the whole file, which grows
  with its size.

## A move keeps what it stands on (Oct 30)

A moved element's contact with what carries it used to count as a clash wherever it went. The cell's fence posts move
as a run (post, base plate, M10 anchors cast 70 mm into the floor slab), so every horizontal move of a post hit the slab
by −70 mm; the C5 HMI stand touches the slab within the clearance. Muse Wonder's way through (E0, `docs/escalation.md`)
was to lift the post 100-200 mm off its slab: verified by geometry, not buildable.

- **What it stands on** (`verify.supports`, before the move): for each moved element that is not a run (ducts, pipes,
  trays and their fittings hang or are carried along their length: `IfcFlowSegment` / `IfcFlowFitting`), the elements it
  touches whose top it stands on or sits in (`verify.stands_on`: its base at that top, or no more than `EMBED_M` 300 mm
  into it, the host reaching below that base, footprints overlapping) and how far into each it sits. Never what the move
  must clear (the clash's partner and a plan item's others), so a post-against-slab clash is not "cleared" by sliding.
- **After the move** (`verify.keep_supports`): a contact with what it stood on, no deeper than before, is not a hit;
  nor is one with something like it at no greater depth (slid onto the next bay of slab). An element that stood on
  something and now stands on nothing fails ("would leave … standing on nothing"), one pushed deeper fails ("sinks
  deeper into …"), and anything else it now cuts into is a clash like any other. A passing move's clearance is measured
  to what is near it, not to what carries it.
- **Where:** single proposals (`agent._try_move`), a plan's joint check (`plans.verify_together`), and the manual and
  chat / MCP move checks when they are told what the move must clear (`Workspace.verify_move(obstacles=)`, the page's
  "Try a move yourself" sends B, `check_move(obstacle=)`); without it every contact counts, as before. Combined fixes'
  move steps keep the old rule.
- **Services are untouched:** runs stand on nothing, so Northbank's answer key and every duct, pipe and tray move are
  checked exactly as before.
- **Checked:** `tests/test_supports.py` (a post cast into a slab: slid passes with its real clearance; lifted, sunk or
  pushed into a cabinet fails; the clash partner is never a support; runs have none; a plan and a checked move agree).
  On the cell: post N3 slid 300 mm out of the robot's restricted space passes (74 mm clear); the same with a 150 mm lift
  fails as floating; the HMI 0.5 m out of the panel's working space passes.
