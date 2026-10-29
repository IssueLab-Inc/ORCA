# Show it built (draft plan)

**Status (Oct 29):** draft, not built. S0 (below) passed on ORCA's own captures. The new kinds' previews come from the
Advanced IFC edits (a penetration must be drawn with its opening before it can be pictured); the rest doesn't depend
on that work.

A button on a fix that turns ORCA's own view of it into a realistic picture of what will be built, for people who
don't read BIM views: clients, site teams, the demo video. Muse Image (`muse-image-1.0`) draws it. The picture must
keep to the model's context: same elements, same places, same shapes. That is the whole job, and the reason for the
checks below.

## Rules

1. **No geometry, no picture.** Only for a fix that exists as geometry: a verified option, an accepted fix, or a
   verified option that needs approval. Never for a recommendation or advice.
2. **Muse Image restyles ORCA's view; it never designs.** Where anything goes comes from the model.
3. **Every picture is checked against the model before anyone sees it.** A picture that fails is never shown.
4. **The model's own view stays beside it,** and the picture is labelled "Illustration by Muse Image from ORCA's
   model view. The model is the record." What the view leaves out is said too ("ceiling and slab above cut away").
5. **Never the BCF snapshot and never in the export.** The BCF viewpoint keeps the true capture
   (`document.py` takes `after_img`).

Decided (owner, Oct 29): the fix after only (ORCA's own before and after views are already there); a clean
presentation render, not a site photo.

## What Muse Image can't do (Oct 29, Navisworks pictures of #042)

| Asked for | Result |
|---|---|
| The fix, drawn on view A, on view B, and with reasoning on A + C | 3/3 wrong: girder redrawn, duct never through the opening |
| A redline drawn on top, "change nothing" | Redrew the picture underneath anyway |
| A photo of the fixed ceiling | A different building |
| A dimensioned RFI sketch from given numbers | Wrong numbers |
| A restyle: same geometry, real materials | Layout kept, small drift, 11.5 s |

Facts: $0.01 an image, 11–35 s, about 1600 px square back for a 1024 px input (`size` sets only the aspect ratio), up
to 10 reference images. `mask` and `input_fidelity` are refused (400), so there is no strength setting: keeping to
the model comes from the inputs, the prompt and the check.

## S0: restyling ORCA's own views (Oct 29)

Code: `spikes/built/` (`fixes.py`, `capture.cjs`, `s0.py`) and the capture page `web/spikes/built.ts`, which drives
ORCA's real `Viewer`. Pictures and scores stay out of git (`OUT_DIR`).

**Cases:** six fixes Muse Spark proposed and verified, then accepted through the API: Northbank's duct, tray and
cold-water offsets through the girder (+400, +250, +280 mm: Rev04's heights), the Clash7 transom trim, and on the cell
the CT-301 ladder offset over post W5 and the PL-301 air-pipe offset under the conveyor rail. 13–32 s each.

### The view

- **A fix in a ceiling void can't be seen in a solid model.** With the context solid, Northbank's duct showed 0% from
  every one of 12 directions, the cold-water main 13% and the tray 36%: slab above, ceiling below, walls around.
- **So the view is a cutaway, chosen by the page.** Of 12 directions (above, low, below × four quarters), the one that
  shows the most of the changed pieces for the least taken away. Each step takes away the element hiding the most of
  the fix for what it costs: ceilings, lights, grilles, furniture, slabs and glazing cost 1, walls 2, services,
  structure and machine parts 6; never the pair or what the fix passes through. A slab, roof or ceiling taken away
  above the fix becomes the section's top (its underside), one below its bottom, so the floor above and its furniture
  go with it, cleanly cut. Looking up costs a little more than looking down.
- **Frame the change, not the run:** an offset's first and last pieces are the rest of the run (metres), so the view
  frames the pieces between, as the agent checks `pieces[1:-1]`. Framing the pair's boxes made the girder fixes a
  speck.
- **Zones aren't built:** see-through elements under 0.2 opacity (a robot's restricted space, a door's working space)
  are hidden; glazing and mesh guards (0.3–0.5) stay.
- Result: 61–98% of each fix in view, with at most one element taken away beyond the section.

### The pictures

Two images per call: the **look** (true colours, solid, everything within 3 m, the cutaway) and the **lines**
(element boundaries and creases from the ids and normals passes, black on white). Six cases each:

| Variant | Kept to the model (the check below: one judge call for the first three rows, any-of-three for the last) |
|---|---|
| Look only | 1 of 6: invented a support, a back panel, a hollow duct bend, a plinth |
| Look + lines | 5 of 6 |
| Look + lines + what the objects are ("a ceiling void", names) | 3 of 6: added a ceiling with lights, a cable tray with cables, fence panels |
| **Look + lines, second prompt** (no "cut" wording, background kept, "no extra pipes, rods, hangers…") | **7 of 12** on the images endpoint, **5 of 6** through Responses with reasoning high, by eye on zoomed crops (the judges' first count, 9 and 6, missed a round column, a dropped block and an opened bend) |

14.5–33 s a picture (median 23 s), the same on both endpoints. Telling Muse Image what things are invites it to add
what such places usually have, so the prompt names nothing; it reads the materials well from the look alone
(galvanised duct, painted steel, copper and plastic pipe, concrete).

**Weak spot: see-through parts.** On the ladder, one picture dropped the mesh-guard walls (drawn at 0.4 opacity in
the look) and shrank another. To try in the build: draw physical see-through parts more opaque in the look.

### The check

1. **Pixels (instant):** edges of the picture against edges of ORCA's own render, at 256 px after a blur (so concrete
   and galvanising texture drops out): F-score ≥ 0.55, and no tile of an 8 × 8 grid more than 45% covered by edges
   that are near neither the render's nor the model's lines (an added object). Faithful restyles: F 0.65–0.95, worst
   tile ≤ 0.34. This alone rejects 6 of the known-bad pictures (other scenes, redesigns) and no good one.
2. **A judge:** image 1 the look, image 2 the picture; list the objects in image 1, then go over image 2 region by
   region and record anything added, removed, moved, reshaped or resized, with a size; verdict faithful, minor
   differences or unfaithful, and unfaithful fails the picture (`s0.JUDGE_SYSTEM`).

**Which judge** (`spikes/built/judges.py`): Muse Spark (reasoning high) and Muse Wonder (low, medium), three runs each
on the same 31 pictures. The labels: 14 known bad (six "improve this design", three with facts, four look-only, the
ladder without its mesh guards), and five restyles that passed Spark and the thumbnail look but not a zoomed crop
(two air-pipe pictures drew a flat rectangular column round, a third dropped a block under the slab; two duct-view
pictures drew the tray's closed bend fitting as an open channel). 19 bad, 12 faithful.

| Pixel gate plus | Bad rejected | Faithful passed | Time | Cost a check |
|---|---|---|---|---|
| Spark high, 1 call | 13/19 | 10/12 | median 42 s, 94 s max | contributor tier |
| Spark high, any of 3 | 14/19 | 10/12 | ~60–90 s (parallel) | contributor tier |
| Wonder low, 1 call | 16/19 | 9/12 | median 23 s, 47 s max | $0.044 |
| **Wonder medium, 1 call** | **18/19** | **8/12** | median 32 s, 81 s max | $0.059 |
| Wonder medium, majority of 3 | 17/19 | 9/12 | | $0.18 |
| Wonder medium, any of 3 | 18/19 | 6/12 | | $0.18 |

- **Spark misses shape changes.** It passed all five pictures found on zoom, every run.
- **Wonder catches them, and is steady where Spark wasn't:** the ladder's missing mesh guards in 6 of 6 runs (Spark 1
  of 3). It misses the duct view's opened bend in one of the two pictures (debatable: a real tray bend is open).
- **Wonder misreads one model view, every time:** the cold-water views have two openings side by side in the girder
  web (the outline pass shows both); Wonder read one wide slot in all 18 of its runs on them, and rejected all three
  faithful pictures. That case would never get a picture.
- **The outline drawing as image 3 fixes that misread and loses others** (11 hard pictures, two runs, medium,
  $0.071 a call): the cold-water pictures 6 of 6 faithful, but the round column in one air-pipe picture and the opened
  bend in one duct picture passed both runs.

A false reject costs a retry or, at worst, no picture (the true view still shows); a false accept puts a wrong
picture beside the model. So the judge is **Muse Wonder, medium, one call per picture, without the outline**. Spent on
this: $11.25 for 211 Wonder calls.

**Not run:** radius 2 and 5 m (3 m throughout); a penetration (needs the edits work); Wonder at high effort. The
faithful labels are by eye on zoomed crops for every disputed picture, at thumbnail size for the rest. The capture
took up to 77 s in headless Chromium on software GL, mostly fetching classes one by one; in the app the classes come
with the scene and the GPU draws the passes.

## Design after S0

### Capture (browser)

`Viewer.captureBuilt(fix)` in one task, the view put back (like `posed`): the cutaway viewpoint above, then the look
(1024 px), ids, normals and the fix's own pieces. Classes for the cut costs come from the server with the scene
(`describe` today is one call per element). The page sends look, lines (or ids and normals, and the server draws the
lines), the legend and what was taken away.

### Generate and check (server)

- `server/sightline/built.py`: two pictures at once through Responses (`image_generation`, `reasoning_strength`
  high), so one usually passes without a second round; each through the pixel gate, then one Muse Wonder judge
  (medium) each, in parallel. The first that passes is shown; with none, one more pair with the judge's differences in
  the prompt ("don't drop the mesh guard panels on the right"), then "Muse Image couldn't keep to the model here" and
  the true view only.
- About a minute to a checked picture (23 s to draw, median 32 s to judge, 81 s at worst); the panel streams the
  stages.
- Cost: $0.14 a click ($0.02 in pictures, $0.12 in judging), $0.28 with the second pair. Wonder has no contributor
  tier, so built views share the escalation's daily spend limit (`docs/escalation.md`), and the owner's caps apply.
  Without Wonder (off, or over the limit): Muse Spark, any of three calls, with the label saying the check was the
  lighter one. Cached by a hash of the look, lines and prompt version, so the PDF, replays and the tour reuse a
  picture.
- Not offered for trims and cleanups: a 30 mm cut-back is invisible at the scale of the view (the transom).

### API and UI

- `POST /api/scenes/{sid}/built/stream` (NDJSON through `_ndjson`): `{look, lines | ids + normals, fix_mask, legend,
  cut, fix: {kind, moved, edit}, report_id?, clash_id?}`. Events: drawing, gate `{f, tile}`, judging `{verdicts}`,
  retry `{why}`, done `{image_url, scores, cut}`, failed `{why}`. Caps `SIGHTLINE_BUILT_PER_HOUR` / `_PER_DAY`; the
  owner has none.
- **Clash panel** (an option, or an accepted fix): **Show it built** → the picture, a wipe slider against ORCA's view
  and a "Lines from the model" overlay, so anyone can see it matches; what was cut away and the check's verdicts in
  a tooltip. `web/src/BuiltView.tsx`.
- **PDF:** on the fix page, beside "The model as it is" and "With the fix", a third picture "As it could look built
  (illustration)" when one was made; the report's evidence gains `built_img`. The BCF snapshot stays the true
  capture.
- Plan panel, per fix. Chat: `show_it_built`. MCP later. The phone's Fix sheet.

## Plan

Branch `feature/show-it-built`, one PR.

1. `Viewer.captureBuilt` from `web/spikes/built.ts` (cutaway, zones, framing), classes with the scene.
2. `built.py` (prompt, Responses call, pixel gate, judges, retry, cache), the endpoint, caps. Tests: the gate rejects
   synthetic bad pictures (an object pasted in, one moved, another scene) and passes the look against itself; the
   judge rule with a scripted model; never offered without geometry or for a trim; the BCF snapshot stays the true
   capture; caps; cache.
3. UI in the clash panel and the plan panel; the phone's Fix sheet.
4. The PDF's third picture.
5. Chat tool; a tour step only as a recorded run.
6. Runtime check in the browser on Northbank and the cell, then on Modal. README picture only from a real run.

## Open questions

1. PDF built views: opt-in per report, or automatic for accepted fixes?
2. Is $0.14–0.28 a click acceptable for the public demo, or should built views be owner-only or capped low?
3. The cold-water misread: try the ids pass (one colour per element) as image 3 instead of the outline, or accept
   that some views never get a picture.
