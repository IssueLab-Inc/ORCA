# Adding and removing models in an open scene

**Status:** approved by the owner (Nov 1), to go in before the Nov 3 freeze. The plan is
[add-and-remove-models-plan.md](add-and-remove-models-plan.md). Slice 1 (the server) is built (Nov 1); slice 2 (the
page and viewer) is next.

Owner decisions (Nov 1, after "we are unable to add/append a new model once we have opened one"):

- **Add and remove**, together in this feature.
- After adding, **check again at once**, as opening does.
- **No mixing of STEP and IFC.** IFC joins an IFC scene and STEP joins a STEP scene; machines inside buildings stay
  "Later" (Oct 31). The refusal says so in words.
- **Removing a model that holds kept edits is allowed**, with a warning that names what goes and suggests exporting
  first.
- **In now**, before the freeze.
- **Spec first.** This page, then the plan, then the build on `feature/` branches, one PR per slice.

## Today

Every way of opening models builds a new scene from exactly the files chosen: the samples picker (`POST
/api/scenes`), **Upload models** (`POST /api/models/upload/stream`) and the demos. The page's `open()` first ends all
work ("The models were opened again") and drops the scene's edits, fixes, checks and triage. Nothing adds a file to a
scene, and nothing takes one away: to check Structure against MEP and then Architecture too, a person opens all three
again and loses what they did.

## What the person can do

- **Add.** With a scene open, the Open menu offers **Add to the open models**: the samples not open yet, and
  **Upload models…** (IFC or STEP, the same caps as an upload). **Open instead** keeps today's behaviour, which
  replaces the scene.
  - The new file draws beside the others, at the same origin.
  - Then every kept check runs again (one detection run, as **Run all again** is). The list gains the new model's
    clashes, and #N numbering carries on.
  - Fixes, hand edits, triage readings and kept checks stay. Readings follow unchanged clashes, as they do now, so
    only new clashes are left for **Triage N unread**.
- **Remove.** Each model in the toolbar's model list gets a remove button. It asks first, saying what goes with the
  model, for example: "Remove Northbank-Structure? Its 2 kept edits and the 118 clashes with it go too. Export first
  to keep the edits."
  - The file leaves the scene and the viewer.
  - Clashes with any of its elements leave every kept check and the list. Nothing is detected again: removing a
    model cannot make a clash.
  - Edits in the other models stay, including fixes made for clashes with the removed model.
- **While ORCA works**, a proposal, plan, triage or detection running, Add and Remove wait: "Wait for the proposal
  to finish".

## Refusals, in words

| Case | Answer |
|---|---|
| A STEP file into an IFC scene, or the reverse | "A STEP machine can't join building models yet: open it on its own." (or the reverse) |
| A file whose name is already open | "Northbank-MEP.ifc is already open." |
| Over the scene budget (`SIGHTLINE_SCENE_BUDGET_MB`) | "With these the open models would be 340 MB, over this server's 300 MB for one set: open fewer models together." (Opening had no refusal: the budget only evicted older scenes. Adding evicts them too, and refuses when this scene alone would pass it, since a scene grown upload by upload is not held by the upload cap.) |
| Over the upload allowance or size cap | today's upload refusals; adding samples is free |
| Removing the only model | "This is the only model: open others instead." |
| Removing by a stale position (another tab changed the list) | 409: "The models changed: reload them." |

## Server

**`IfcScene`** (`scene.py`)

- `add_files(paths) -> list[int]` opens and appends to `paths`, `models` and `unit_scales`.
  - When boxes are cached, it measures only the new files' elements (with progress), not the whole federation.
  - `index_of` walks the models live, so it needs no change.
- `remove_file(index)` drops the file and its elements' boxes. In `_edited` it drops `index` and shifts the indexes
  after it down.
- Both bump `revision` and a new `layout` counter. `history` (revision, files changed) only holds within one layout:
  a page that missed a layout change reloads the files instead of patching by index.

**`Workspace`** (`service.py`)

- `add_models(scene_id, paths, root=None, classify_with=None, on_event=...)`:
  - checks the refusals;
  - converts STEP as `open_paths` does;
  - extends `names`, `sizes` and `sources` (new indexes start at the old count);
  - keeps every upload folder (`_roots` becomes a list per scene, all deleted with it);
  - calls `scene.add_files`;
  - clears what depends on the file set: `_stays`, report matches (`match`), pattern readings, detection tests.
- `remove_model(scene_id, index, name)`:
  - refuses a stale `name` or the only model;
  - shifts `names`, `sizes` and `sources` down;
  - deletes the file from its upload folder;
  - calls `scene.remove_file`.
  - **Checks:** `checks.Register.drop_file(name)` takes the clashes with that file's elements out of every kept check
    and the union list.
  - **Edit log** (`journal.py`): an entry that changed the removed file can no longer be undone, because its
    transactions were on that model. It stays in the log, marked `model_removed`, and is never undone or redone. Its
    `_tx`, `_models` and `_tail` keys are remapped.
  - Clears the same caches as adding.

**Routes** (`app.py`; each answers with `files`, `step`, `revision` and `layout`)

| Route | Does | Cost |
|---|---|---|
| `POST /api/scenes/{scene_id}/models` `{"samples": [...]}` | adds sample models | free, like opening samples |
| `POST /api/scenes/{scene_id}/models/upload/stream` (multipart) | adds uploaded models; the same events as `/api/models/upload/stream` | one model upload (`SIGHTLINE_MODEL_UPLOADS_PER_HOUR/DAY`), the size cap |
| `DELETE /api/scenes/{scene_id}/models/{index}?name=` | removes one; also answers `removed: {clashes, edits}` and the report listing what is left | free |

`GET /api/scenes/{scene_id}` adds `layout`. Chat and MCP tools are not in this slice.

## Page and viewer

- **`Viewer`** (`viewer/Viewer.ts`):
  - `add(files, names)` parses at `origin()` (as `replace` does), adopts the files and appends them; the views are
    configured again.
  - `remove(index)` disposes its batches, splices `models` and `names`, remaps `hiddenModels`, and clears measures,
    hover and the focus cache that referred to it.
- **App:**
  - `addModels(source)`: the add route; parse uploads locally (as `open` does) or fetch samples; `viewer.add`; update
    `sceneFiles`, `stepFiles`, `modelNames` and the saved session; then run every kept check again.
  - `removeModel(i)`: confirm; the delete route; `viewer.remove`; the report from the answer; drop `fixes` and the
    selection for clashes that went; remap the toolbar's `hiddenModels`.
  - Neither goes through `open()`.
  - A page that sees a `layout` it does not know (another tab, an agent) reloads the files, as it does after a
    restart.
- **Reopen after a restart** already uses `sceneFiles`, so it gets the current list.
- **Trap:** a new import in `App.tsx` goes in both test stub lists (`web/tests/app-host.mjs`,
  `app-replacement.test.mjs`).

## Tests

- **Server:**
  - `IfcScene.add_files` and `remove_file`: boxes, `index_of` and `_edited` remapped.
  - `Workspace` refusals: mixing, a name already open, the budget, the only model, a stale name.
  - Adding Architecture to Northbank Structure + MEP: the Architecture pairs' clashes appear after the check runs
    again, numbering carries on, and earlier readings are carried.
  - Removing Structure: its clashes leave every kept check; a hand edit in MEP stays; an entry that changed
    Structure is marked and not undoable; export writes the files left.
  - Routes: the upload allowance is charged on add; the 409 guard.
- **Web:** `Viewer.remove` remaps `hiddenModels`; App's stub lists updated.
- **Runtime, in a browser:**
  - Open Northbank Structure + MEP, propose and keep #042's fix.
  - Add Architecture: the list grows and #042 stays fixed.
  - Remove Architecture: the list shrinks and the fix stays.
  - Export, and confirm the IFC carries the edit.
  - Then STEP into IFC: refused in words.

## Docs to update in the same PR

`docs/architecture/` 01 (journeys), 03 (flows), 05 (the scene's file list, `layout`), 10 (routes), 12 (App), 13
(`Viewer.add`/`remove`), 14 (files in), 16 (caps), 22 (build log); [docs/uploads.md](uploads.md);
[docs/detection.md](detection.md) ("Kept checks"); [docs/manual-edits.md](manual-edits.md) (entries in a removed model).

## Not in this slice

- STEP and IFC together.
- Chat and MCP tools to add or remove (`open_models` is unchanged).
- Replacing one model with a new revision of itself.
- Moving or aligning a model whose coordinates do not match.

## Decided

1. **Removing a model that holds kept edits:** allowed, with the warning (Nov 1).
2. **The freeze (Nov 3):** in before it (Nov 1). It touches opening, which every demo starts with, so the demo
   cards and both tours are part of the runtime check.
