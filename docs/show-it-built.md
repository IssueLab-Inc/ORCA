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
| **Look + lines, second prompt** (no "cut" wording, background kept, "no extra pipes, rods, hangers…") | **9 of 12** on the images endpoint, **6 of 6** through Responses with reasoning high |

14.5–33 s a picture (median 23 s), the same on both endpoints. Telling Muse Image what things are invites it to add
what such places usually have, so the prompt names nothing; it reads the materials well from the look alone
(galvanised duct, painted steel, copper and plastic pipe, concrete).

**Weak spot: see-through parts.** On the ladder, one picture dropped the mesh-guard walls (drawn at 0.4 opacity in
the look) and shrank another. To try in the build: draw physical see-through parts more opaque in the look.

### The check

1. **Pixels (instant):** edges of the picture against edges of ORCA's own render, at 256 px after a blur (so concrete
   and galvanising texture drops out): F-score ≥ 0.55, and no tile of an 8 × 8 grid more than 45% covered by edges
   that are near neither the render's nor the model's lines (an added object). Faithful restyles: F 0.65–0.95, worst
   tile ≤ 0.34. This alone rejects 6 of 14 known-bad pictures (other scenes, redesigns) and no good one.
2. **Muse Spark (reasoning high), three calls in parallel:** image 1 the look, image 2 the picture; list the objects in
   image 1, then go over image 2 region by region and record anything added, removed, moved, reshaped or resized, with
   a size; verdict faithful, minor differences or unfaithful. **Any unfaithful fails the picture.** One call varies on
   borderline pictures (the ladder's missing mesh guards: unfaithful in 0 of 1, 1 of 3 and 2 of 3 runs at high effort, 3
   of 3 at low), hence three.
   Median 42 s a call, 94 s at worst; low effort is faster (6–37 s) but missed the invented support 2 times in 3.

| Rule | Known-bad rejected | Faithful restyles passed |
|---|---|---|
| Pixels | 6/14 | 17/17 |
| Pixels + one judge call | 13/14 | 15/17 |
| Pixels + majority of three | 13/14 | 17/17 |
| **Pixels + any of three** | **14/14** | **15/17** |

Known-bad: six "improve this design" pictures, three with facts, four look-only and the ladder picture without its
mesh guards (eye-confirmed). The bar was every known-bad rejected and at least 80% of good ones passed: met (88%). A
false reject costs a retry, a false accept misleads, so the strict rule.

**Not run:** radius 2 and 5 m (3 m throughout); a penetration (needs the edits work); Muse Wonder as the judge. The
capture took up to 77 s in headless Chromium on software GL, mostly fetching classes one by one; in the app the classes
come with the scene and the GPU draws the passes.

## Design after S0

### Capture (browser)

`Viewer.captureBuilt(fix)` in one task, the view put back (like `posed`): the cutaway viewpoint above, then the look
(1024 px), ids, normals and the fix's own pieces. Classes for the cut costs come from the server with the scene
(`describe` today is one call per element). The page sends look, lines (or ids and normals, and the server draws the
lines), the legend and what was taken away.

### Generate and check (server)

- `server/sightline/built.py`: two pictures at once through Responses (`image_generation`, `reasoning_strength`
  high), so one usually passes without a second round; each through the pixel gate, then three Muse Spark judges in
  parallel. The first that passes is shown; with none, one more pair with the judges' differences in the prompt
  ("don't drop the mesh guard panels on the right"), then "Muse Image couldn't keep to the model here" and the true
  view only.
- About 1–1.5 minutes to a checked picture (23 s to draw, 42–94 s to judge); the panel streams the stages.
- Cost: $0.02–0.04 in pictures and 6–12 Muse Spark calls a click. Cached by a hash of the look, lines and prompt
  version, so the PDF, replays and the tour reuse a picture.
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
2. Is 1–1.5 minutes per picture acceptable, or should the judge run on Muse Wonder (untested) or at low effort with
   five calls?
