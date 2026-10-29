# Edits: the kinds of fix ORCA can make

Every fix ORCA offers is an edit to the real IFC elements, tried in a transaction, checked by geometry and undone
before anyone sees it. This page is the design of the kinds of fix and how a new one is added. Code:
`server/sightline/edits.py` (the geometry), `agent.py` (trying ideas), `plans.py` (several fixes at once), and
`web/src/fixKinds.ts` (how the page describes them).

## Kinds

| Kind | What it does | Since |
|---|---|---|
| `move` | Moves a straight run (the element and what it is joined to) by a vector | Oct 27 |
| `offset` | Splits a straight segment either side of an obstacle and takes the middle up or down (or sideways), with bends | Oct 27 |
| `trim` | Cuts a slender member's end back to butt another's face | Oct 27 |
| `route` | Holds stretches of a straight segment at offsets (up and/or sideways) in up to 3 steps, with bends | Oct 29 |

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
  `POST /api/scenes/{sid}/fix/apply` all use. That endpoint drops the page's meshes and works out anything that
  depends on the requirements again on the server.
- **Sizing it against the requirements:** `requirements.SIZED` and `change_size` (how far any part goes; a lateral
  offset used to measure 0 mm).
- **The page:** `fixKinds.ts`: the name, the edit in a few words, the clearance line, which pieces to frame, who must
  review it. The newer kinds carry the server's own `edit.summary`, so the page says what Muse was told.

An option of a newer kind carries `edit` (its parameters, a `summary` and a `key` that tells two fixes apart) and
`review` (who must review it before it is built, when geometry alone cannot say it works).

## Ranking

Plain geometry fixes (move, offset, trim, route) rank before a resize (it changes how a service performs), and a
resize before a penetration (another team builds it): `agent.TIERS`. Then comfortable clearance, the smallest change,
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
the run can reach it square from its line at both ends of the stretch. On the cell's C6: beside column C3, side offsets
+0.20 to +0.29 m (between the column and the fence); past both columns at once, none (ES-2 is between them). For a single
proposal on a report clash, the moving element's other clashes within 3 m are named too (`Workspace._nearby`): a route
may clear them together, but only the asked clash is required (never the fixed side's: a girder's other services are
their own clashes).

**Demo case:** the cell's C6 (demo-models repo): PL-302 runs along the plant's south wall through columns C3 and C4.
Offsets over or under fail (the columns run full height), a whole-run move or one long detour hits the ES-2 emergency
stop between them; a detour of 200 mm round each column clears with 33 mm to spare.

**Not yet:** 45° pieces, falling drainage, diagonal ("rolling") changes, and routes in the wider-fix planner.

## Keeping a fix: the model updates in place (Oct 29)

Accepting a fix used to download the whole file it changed (and the server wrote the whole IFC out for that download)
and re-parse it in the browser. Now every way of keeping a fix answers with what changed:

- **Server:** each apply reports `changed` (the moved run, a split run's pieces, a trimmed member, a plan's or wider
  fix's edits), and the endpoints, the MCP `apply_fix` / `apply_plan` and the agent link's `applied` event add
  `Workspace.patch`: `scene_id`, `revision_before`, `revision`, and `meshes`, the changed and new elements' triangles
  taken after every edit of the request (`edits.meshes(render=True)`: unwelded, with normals, the style's colour and
  opacity, and the element's file). No meshes when one will not triangulate or there are more than 500,000 vertices.
- **Page:** `applyToViewer` (App.tsx) patches when the reply has meshes for this scene and the page's model is at
  `revision_before` (from opening: `revision` in the open, upload and scene-info replies); otherwise it reloads the
  changed files as before. Either way it then knows the new revision.
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
