# Show it built (draft plan)

**Status (Oct 29):** draft, not built. The new kinds' previews come from the Advanced IFC edits (a penetration must be
drawn with its opening before it can be pictured); the rest doesn't depend on that work.

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
   model view. The model is the record."
5. **Never the BCF snapshot and never in the export.** The BCF viewpoint keeps the true capture
   (`document.py` takes `after_img`).

## What we measured (Oct 29)

Clash #042 (supply air main × transfer girder), on Navisworks pictures from the demo-models repo (the spike below
uses ORCA's own captures):

| Asked for | Result |
|---|---|
| The fix, drawn on view A, on view B, and with reasoning on A + C | 3/3 wrong: girder redrawn, duct never through the opening |
| A redline drawn on top, "change nothing" | Redrew the picture underneath anyway |
| A photo of the fixed ceiling | A different building |
| A dimensioned RFI sketch from given numbers | Wrong numbers |
| **A restyle: same geometry, real materials** | **Layout kept, small drift, 11.5 s** |

Facts: $0.01 an image, 11–35 s, about 1600 px square back for a 1024 px input (`size` sets only the aspect ratio), up
to 10 reference images. `mask` and `input_fidelity` are refused (400), so there is no strength setting: keeping to
the model comes from the inputs, the prompt and the check.

## Keeping to the context

The context is everything in the picture besides the fix: the obstacle, slabs, walls, other services, the machine
frame. What went wrong in the tests: invented scenes, objects moved, added or removed, openings redrawn.

### Inputs that pin it

Four passes of one camera, taken by the browser off screen in one task (like `Viewer.posed`) and framed by
`frameFix`:

- **Look** (sent): true IFC colours (the style colours already in each BatchedMesh), solid, everything within R of
  the fix (default 3 m, bounded by `Viewer.reach` for small models), the rest hidden, section box on. Not the red and
  green focus colours, which would come back as paint.
- **Lines** (sent): the same view as edges only (element boundaries, creases, depth steps), black on white. The prompt
  calls it the drawing to keep.
- **Ids** (kept): one flat colour per element, no lighting, with a legend (GlobalId, class, name, material, pixels).
  Used for the facts and the check.
- **Depth** (kept): for the check.

**Facts** for the prompt, from the server, for the largest elements in the ids pass: class, name, material
(IfcMaterial or style), predefined type, size, system; the setting (ceiling void on Level 02, a machine cell); the
fix in a few words (`edit.summary` or the move, offset or trim text). Buildings and machines get their own packs
(`domain_packs/built_construction.md`, `built_machine.md`).

**Prompt:** restyle only; keep every outline in the lines image; add, remove and move nothing; materials from the
facts; no people, no text, no labels; lighting from the pack.

### The check

On the server, after each picture (scaled to the capture's size):

- **Outlines agree:** the picture's edges against the lines pass, as an F-score within a few pixels, for the whole
  frame and for each element inside its ids mask. Catches moved or redrawn geometry.
- **Nothing new:** few edges where the ids pass is empty. Catches added objects (the photo test's vertical duct).
- **Nothing missing:** every element above a size threshold keeps its edges inside its mask.
- **The fix is there:** the changed pieces (the moved run, the offset pieces, the new opening) pass a stricter
  threshold.
- **Muse Spark compares:** look pass and picture → strict JSON `{added, removed, moved, changed_shape, fix_matches,
  notes}`. Catches what pixels miss (a duct that kept its outline but turned into a pipe).

All must pass. A failure retries with the reasons (up to two more pictures); after that the panel says "Muse Image
couldn't keep to the model here" and shows the true view only.

### Showing it

- **Clash panel** (an option, or an accepted fix): **Show it built** → the picture, a wipe slider against ORCA's view
  and a "Lines from the model" overlay, so anyone can see it matches; the check's scores in a tooltip.
- **PDF:** on the fix page, beside "The model as it is" and "With the fix", a third picture "As it could look built
  (illustration)" when one was made. The Report dialog's "Include built views" makes the missing ones (charged per
  page).
- Plan panel, per fix. Chat: `show_it_built`. MCP later.
- After only at first; before and after later.

### Cost and caps

- One click: 1–3 pictures ($0.01–0.03) and 1–3 Muse Spark checks. Caps `SIGHTLINE_BUILT_PER_HOUR` / `_PER_DAY`; the
  owner has none.
- Cached by a hash of look, lines, facts and prompt version, so replays, the tour and the PDF reuse a picture.

## Code

- `server/sightline/built.py`: prompt, the call (`/v1/images/edits`, JSON body, `images` as data URLs,
  `output_format: webp`), the check (numpy and PIL edges, ids decoding), retries, cache.
- `POST /api/scenes/{sid}/built/stream` (NDJSON through `_ndjson`): `{look, lines, ids, depth, legend, fix: {kind,
  moved, edit}, report_id?, clash_id?}`. Events: drawing, checking `{scores}`, retry `{why}`, done `{image_url,
  scores}`, failed `{why}`.
- `Viewer.captureBuilt(fixShapes)`: the four passes, the view put back. Risks: the ids pass needs a flat colour per
  element in each BatchedMesh and in the glass mesh (`setColorAt` and an unlit material); the lines pass is a
  post-process of normals, depth and ids (or done on the server from the passes).
- `web/src/BuiltView.tsx`: the picture, wipe, overlay, label and scores. The report's evidence gains `built_img`.

## S0 spike (measurement only; can run before the edits work lands)

- **Cases:** Northbank #1 duct offset, the tray and cold-water offsets, the Clash7 transom trim, the cell ladder
  +150 mm move, the cell C1 offset; a penetration once one exists.
- **Variants:** look only; look and lines; look, lines and the ids legend. Images endpoint vs Responses with high
  reasoning. R of 2, 3 and 5 m.
- **Read:** each picture by eye (keeps to the context or not, what drifted) and through the check. Today's nine wrong
  pictures go in as known bad.
- **Decide:** inputs, prompt and thresholds. Ship only if the check rejects every known-bad picture and passes at
  least 80% of the good ones. Write the numbers here.

## Plan

Branch `feature/show-it-built`, one PR.

1. S0 (`spikes/built.py`); numbers and decisions in this doc.
2. Viewer passes and `captureBuilt`.
3. `built.py`, the endpoint, caps and cache. Tests: the check rejects known-bad fixtures (small synthetic pictures:
   an object added, one moved, one missing) and passes a picture against itself; never offered without geometry;
   the BCF snapshot stays the true capture; caps; cache.
4. UI in the clash panel and the plan panel; the phone's Fix sheet.
5. The PDF's third picture.
6. Chat tool; a tour step only as a recorded run.
7. Runtime check in the browser on Northbank and the cell, then on Modal. README picture only from a real run.

## Open questions

1. Radius R, and whether the slab above is always in (a ceiling void reads better with it).
2. After only, or before and after?
3. Style: site photo, or a clean presentation render (or a toggle)?
4. PDF built views: opt-in per report, or automatic for accepted fixes?
