# Bigger uploads

Your own models (Models › Upload models, or the landing page's **Use your own models**): IFC or STEP, up to eight
files that share coordinates. Until Oct 29 the cap was 150 MB and had never been tried above about 5 MB. This page is
what a big model costs and how the upload copes. Code: `app._receive_models`, `app.upload_models_stream`,
`IfcScene.bounds`, `Workspace.open_paths`, `web/src/uploads.ts`, `api.uploadModelsStream`.

## The way in

1. **The page checks first** (`uploads.uploadRefusal`): the cap comes from the server (`GET /api/models`:
   `model_upload_max_mb`, `model_upload_max_files`), and every place that states it reads it from there.
2. **Packed in the browser**: each file over 1 MB is gzipped with `CompressionStream` and sent as `<name>.gz`
   (Northbank's MEP and Architecture files pack 5.7x and 5.5x, the eval's synthetic models 4.6x).
3. **Sent with `XMLHttpRequest`**, so the page shows upload progress ("Uploading 45% (230 of 510 MB)"). A 409
   `requirements_unknown` (the server restarted and forgot the requirements' id) registers the file again and sends
   the same form once more, as every other call does (`reRegister` in `api.ts`).
4. **The server refuses early**, before reading the body: 411 without a Content-Length (a chunked body would be
   spooled whole to disk before any check; browsers always send one), 413 when the length alone is over the cap. It
   unpacks `.gz` parts to disk off the event loop (`app._unpack`, in a thread), at most 1 MiB out of the gunzip per
   step, and counts the cap (`SIGHTLINE_MODEL_UPLOAD_MAX_MB`) on the unpacked size as it goes: a 522 kB archive of 512
   MiB of zeros is refused in about a second with a few MB of memory. An archive cut short is refused, never written
   as if whole.
5. **Opening is streamed** (`POST /api/models/upload/stream`, NDJSON): `received`, the STEP conversion's events,
   `opening`, `boxes` (elements measured, every 500), a `tick` every 5 s so no proxy times out an idle connection, then
   `done` or `error`. Refusals before the files are in stay plain HTTP errors. `POST /api/models/upload` is kept
   (one JSON answer).
6. **Drawn from the visitor's own file**: an uploaded IFC is parsed from the `File` in the browser, not downloaded
   back; only a STEP comes back (converted).

## Measuring elements

Every element's box is measured once when a model opens (`IfcScene.bounds`). Two changes made that affordable:
- **Meshes through CGAL.** OpenCASCADE takes 20-30 ms per triangulated element (it sews the triangles into shells);
  IfcOpenShell's `hybrid-cgal-simple-opencascade` kernel reads them in about 1 ms with the same vertices. Only
  elements whose bodies are all `IfcTriangulatedFaceSet` / `IfcPolygonalFaceSet` (and that have no openings) use it;
  everything else keeps the default kernel, so the boxes, their order and Northbank's 464 detected clashes are
  identical to before (checked).
- **In batches of 2,000.** An IfcOpenShell iterator holds what it made until it is dropped: the 150 MB model in one
  iterator went past 4.7 GB; in batches it peaks at 1.4 GB.
- Threads come from the CPUs the process may use (`os.sched_getaffinity`), not the host's count.

## Holding them

- **A byte budget** (`SIGHTLINE_SCENE_BUDGET_MB`) as well as the count (`SIGHTLINE_MAX_SCENES`): the IFC bytes of the
  open scenes, oldest dropped first (never the one just opened, never one an agent link holds unless all are). Room
  is made before a new scene is read, by its size (`Workspace._evict`): an opening model peaks on top of what is
  held, so the old ones go first, not after.
- **Wider fixes** copy the open models two or three times, so they are offered up to `SIGHTLINE_WIDER_FIX_MAX_MB`
  (100 by default); Propose fixes works at any size.
- Written models and exports older than an hour are deleted.
- **Adding to an open scene** ([add-and-remove-models.md](add-and-remove-models.md), Nov 1). An upload added to a scene
  is one model upload and passes the same caps; its folder joins the scene's (`Workspace._roots` holds a list, one
  folder per opening or adding, all deleted with the scene). The byte budget then bounds one scene too: adding what
  would put it alone past `SIGHTLINE_SCENE_BUDGET_MB` is refused, since a scene grown upload by upload is not held by
  the upload cap. Only the new files' boxes are measured (`IfcScene.add_files`). A model taken out is deleted from its
  folder at once, and a folder that holds none of the scene's files any more goes with it.

## Measured, and the cap

`evals/big_models.py` and `big_models_browser.cjs` (synthetic IFC4, a realistic mix; `evals/README.md` "Big models"):
150 MB opens through the page in about two minutes (1.4 GB on the server), 250 MB in about three, 500 MB in about
eight (2.8 GB). Following the plan's rule (the largest size that opens in about two minutes), **the demo's cap stays
150 MB**, now measured rather than assumed (before these changes a 150 MB model's boxes alone would have peaked at
4.8 GB, past the container's 4 GB). Any deployment can raise `SIGHTLINE_MODEL_UPLOAD_MAX_MB`; the page reads it.

What blocks 500 MB: the server's boxes (about 1 ms an element on 4 CPUs) and drawing in the browser (web-ifc on the
main thread, about 3 minutes, the page frozen). Next: parse in a Web Worker, and measure boxes without triangulating.

Modal (`deploy/modal_app.py`): `SIGHTLINE_MODEL_UPLOAD_MAX_MB` 150, `SIGHTLINE_SCENE_BUDGET_MB` 300 (two of the
biggest uploads held, about 2.5 GB, inside the 4 GB container), memory and CPUs unchanged.
