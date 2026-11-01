# Plan: adding and removing models in an open scene

Spec (the what and why, owner-approved Nov 1): [add-and-remove-models.md](add-and-remove-models.md). This page is the
how, for a session that has not seen the planning conversation. It ends with a progress ledger: update it after every
task.

There are two slices, each its own branch and PR:

1. **Server:** `feature/add-remove-models-server`.
2. **Page and viewer:** `feature/add-remove-models-page`, from `main` once slice 1 is merged (or stacked on it, if
   the owner says so).

## Global constraints (read first)

- **Rules:** `AGENTS.md` and `CLAUDE.md`.
  - No superpowers skills, and plans live in `docs/`.
  - Never implement on `main`. Merge only on the owner's word.
  - A core change updates its `docs/architecture/` doc in the same PR. `server/tests/test_docs_map.py` fails on a
    route missing from doc 10.
- **Commits:**
  - This checkout has **no repo-level `user.email`**, and the global one is personal. Always commit with
    `git -c user.name="Dodzi Agbenorku" -c user.email="50728220+dodzikojo@users.noreply.github.com" commit …`.
  - No co-author or session trailers.
  - PR bodies end with the "Generated with Claude Code" line, as earlier PRs do.
- **The checkout is shared, so work in a worktree.** Other sessions work in `C:\Users\dodzi\source\repos\ORCA` at the
  same time. Never switch branches there.
  - Make a sibling worktree for each slice: `git worktree add ../ORCA-add-models feature/add-remove-models-server`.
  - Link `web/node_modules` with a junction (`cmd /c mklink /J web\node_modules
    ..\ORCA\web\node_modules`) and copy `web/public/wasm`.
  - When the worktree is done, unlink the junction (`cmd /c rmdir web\node_modules`) before
    `git worktree remove`.
  - Stage only your files. `voicebench/` is not ours.
- **Freeze, Nov 3:** keep to the spec. Anything else goes in its "Not in this slice" list.
- **Known failures on `main`:**
  - `test_detect.py`: two clash-point tests;
  - `test_document.py`: two tests that need GTK, not installed here;
  - `test_voice_live.py` fails under load and passes alone.
- **Web trap:** a new import in `web/src/App.tsx` goes in both stub lists (`web/tests/app-host.mjs` and
  `app-replacement.test.mjs`). That test transform can't read `for (const [a, b] of …)` in App.
- **Windows:** PowerShell 5.1 (no `&&`). Application Control may block a fresh binary: run it again.
- **Runtime checks:**
  - Build first (`cd web && npm run build`). The server serves `web/dist`:
    `cd server && uv run --locked uvicorn sightline.app:app --host 127.0.0.1 --port 8023`.
  - Ports 8000 and 8010 are other sessions' servers. The shared Playwright browser may be busy: use
    `playwright-core` from a scratch folder, with `executablePath`
    `C:/Users/dodzi/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe` and args
    `--use-gl=swiftshader --enable-webgl --ignore-gpu-blocklist`.
  - Selectors that worked:
    - the "Open the Northbank demo" button;
    - `input[type=file][accept=".ifc,.step,.stp"]` (`setInputFiles`);
    - `button.clash-main`: click at `{position: {x: 12, y: 10}}`, because the row's action icons cover its middle;
    - `button.card-body.option`: check `aria-pressed` before clicking, since a click toggles;
    - the triage card: `section[data-tour=triage]`.

## What the code holds (anchors at `bba613c`; line numbers drift)

**Opening today**

- `app.py`:
  - `open_scene`, `POST /api/scenes` (~430);
  - `_receive_models` (~480): caps, unpacking and the upload folder;
  - `upload_models_stream` (~546): its events and how errors are answered.
- `service.Workspace.open_paths` (~124):
  - STEP conversion into `sources[i] = {"step", "manifest"}`;
  - `names`, `sizes`;
  - `_roots[scene_id] = root` (one folder per scene);
  - `_evict` (~165): the scene budget and `MAX_SCENES`.
- The page's `App.open()` (~1238):
  - `api.uploadModelsStream` or `api.open`;
  - the bytes of each file: an upload is parsed from the visitor's own `File`, a STEP is fetched converted, a
    sample is fetched;
  - `viewer.load`;
  - then it sets `modelNames`, `stepFiles`, `sceneFiles` and `sceneUploaded` (~1284–1291).
  - `openDemo` then runs detection.

**Keyed by file position, so a removal must remap all of it**

- **Server:**
  - `IfcScene._edited` (set of indexes), `IfcScene.history` ([(revision, [indexes])]);
  - `Workspace.sources[sid][i]`, `names[sid]`, `sizes[sid]`;
  - `journal.Entry._tx`, `_models`, `_tail` (index →);
  - `GET /api/scenes/{sid}/files/{index}`;
  - `IfcScene.write_edited`, and the STEP export through `sources[i]`.
- **Web:**
  - `Viewer.models[i]`, `Viewer.names`, `Viewer.hiddenModels` (Set), `Viewer.replace(i)`;
  - App `tool.hiddenModels` (number[]), `sceneFiles`, `stepFiles`, `modelNames`;
  - `SavedSession.files`;
  - the reload after a kept fix (App ~2269, `viewer.replace(i, …)`);
  - `sceneRevision` and patching from `history`.

**Keyed by name, so it survives a removal:** detection test ids (`pair:A.ifc|B.ifc`) and `ReportElement.file`.

**Caches that depend on the scene's set of files** (clear them on add and on remove):

- `Workspace._matches` (report ↔ scene);
- `_patterns`;
- `_stays`;
- last tries, keyed by `_stamp` (~370);
- detection tests (`detect_tests`).

**Other anchors**

- **Kept checks:** `checks.Register` (~95): `checks` (key → `Check`); `union()` (~230) builds the list;
  `keep_reading` and `carried` hold the readings.
- **`IfcScene`:**
  - `index_of` walks the models live;
  - the only cache is `_bounds` (`bounds()` ~201, `refresh_bounds` ~249);
  - `clone()` copies `_edited` and `history` (~147).
- **Viewer:** `load()` (~275) replaces every file. `replace(index)` (~320) parses at `origin()`: copy that for `add`.
- **The toolbar's model list:** `ViewerToolbar.tsx` ~273, one checkbox per model, `onModel(i, visible)`.
- **Checking again after adding:** `runDetect(null, sid, { all: true })` calls `Workspace.detect_all`, one detection
  run.
- **Uploaded scenes:** `sceneUploaded` makes reopening after a restart ask for the files again. A sample scene with
  an upload added is an uploaded scene from then on.

## Slice 1: server

Work test-first: write the failing test, run it red, implement, run it green.

1. **`IfcScene.add_files(paths) -> list[int]` and `remove_file(index)`, with a `layout` counter.**
   - New test file `server/tests/test_scene_models.py`, using `fixtures.build_detection_fixtures` (several files
     sharing coordinates).
   - Cases: cache the boxes; add a file, and its elements get boxes and `index_of` finds them. Remove the middle file:
     its boxes go, `_edited` is remapped (a later file's index shifts down), and `revision` and `layout` both rise.
     `clone()` carries `layout`.
2. **`Workspace.add_models(scene_id, paths, root=None, classify_with=None, on_event=…)`.**
   - Refusals, each a `ValueError` whose text the route sends as a 400: mixing STEP and IFC (look at `sources` for
     the scene's kind), a name already open, the scene budget.
   - STEP conversion as in `open_paths`. Factor the per-file part out and reuse it, don't copy it.
   - Extend `names`, `sizes` and `sources`. `_roots` becomes a list of folders per scene; update `_evict` and every
     reader (`datums.read` checks `scene_id in self._roots`).
   - Clear the caches listed above.
   - Tests: the refusals; adding a sample to a sample scene; a STEP into a STEP scene (the cell fixture, if quick).
3. **`Workspace.remove_model(scene_id, index, name)`, `checks.Register.drop_file(name)`, and the journal marking.**
   - Refuse a stale `name` (`StaleLayout`, which the route answers 409) and the only model.
   - Shift `names`, `sizes` and `sources` down. Delete an uploaded file from its folder.
   - `drop_file` takes clashes with an element of that file out of every `Check` and out of the union. Readings for
     those clashes may stay (harmless) or go.
   - The journal: an entry that changed that file is marked `model_removed`; `undo` and `redo` refuse it in words.
     Remap `_tx`, `_models` and `_tail`.
   - Test, on Northbank Structure + MEP + Architecture (`samples/`):
     1. run `detect_all`;
     2. keep a hand edit in MEP (see `tests/test_manual.py` for the call);
     3. remove Structure;
     4. no check or union lists a clash with a Structure element; the MEP edit is still in the file; an entry that
        changed Structure is marked and undo refuses it; `write_edited` writes only the remaining files.
4. **Routes.**
   - `POST /api/scenes/{scene_id}/models` `{"samples"}`.
   - `POST /api/scenes/{scene_id}/models/upload/stream`: reuse `_receive_models`, which charges the model-upload
     allowance; the same event shapes; `done` adds `layout`.
   - `DELETE /api/scenes/{scene_id}/models/{index}?name=`: `{files, step, revision, layout, removed: {clashes,
     edits}, report}`, where `report` is `checks_info`'s list.
   - `GET /api/scenes/{scene_id}` adds `layout`.
   - TestClient tests: an add charges the allowance (see `test_limits.py`); 400 refusals; the 409 guard; adding then
     `detect_all` finds the new pairs and numbering carries on (`checks` "Kept checks" behaviour).
5. **Docs, in the same PR:**
   - `docs/architecture/` 05 (the file list, `layout`), 10 (three routes, `layout`), 14 (files in), 16 (what
     adding charges), and 22 (build log);
   - [uploads.md](uploads.md) (several folders per scene), [detection.md](detection.md) ("Kept checks" after a
     removal), [manual-edits.md](manual-edits.md) (entries in a removed model).
6. **Finish:** `uv run pytest -q` (only the known failures), then commit, push, open the PR, and update the ledger.

## Slice 2: page and viewer

1. **`api.ts`:** `addModels(sceneId, samples)`, `addModelsStream(sceneId, files, onEvent)` (copy
   `uploadModelsStream`), and `removeModel(sceneId, index, name)`. Add `layout` to `OpenedScene`.
2. **The viewer:**
   - `Viewer.add(files, names, isCurrent)` parses each at `origin()`, adopts, appends, then `sceneChanged()`,
     `configureViews(false)`, `applyMode()`, and fits all so the new model shows.
   - `Viewer.remove(index)` disposes its batches, splices `models` and `names`, remaps `hiddenModels` (drop it,
     shift the higher ones down), and clears measures, hover and the focus cache.
   - Test `remove`'s remap if `web/tests/viewer-load.test.mjs` can host it; otherwise check it at runtime.
3. **App:**
   - **The Open menu**, with a scene open: "Add to the open models" (samples not open yet, plus "Upload models…" in
     add mode) and "Open instead" (today's `open()`).
   - **`addModels(source)`:** add route; bytes as `open()` gets them, for the new files only; `viewer.add`; update
     `sceneFiles`, `stepFiles`, `modelNames` and `sceneUploaded`; save the session; then `runDetect(null, sceneId,
     { all: true })`. Disabled while `busy`, a proposal, plan or triage is running, saying what to wait for.
   - **Removing:** a remove button per model in the toolbar's model list.
     - Confirm with the counts: clashes with that file from the report (`a.file` or `b.file`), and kept edits from
       the journal (`GET /api/scenes/{sid}/edits`).
     - `removeModel(i)`: the delete route; `viewer.remove(i)`; set the report from the answer; drop `fixes`, `reviewed`
       and the selection for clashes that went; remap `tool.hiddenModels`; update the file lists and the session.
   - **A `layout` the page doesn't know** (another tab, an agent): reload the files, as after a restart.
4. **Docs, in the same PR:** `docs/architecture/` 01 (journeys), 03 (a flow for adding and removing), 12 (App),
   13 (`Viewer.add` and `remove`), and 22 (build log).
5. **Checks:** `npm run build`, `npm test`, the server suite, then a runtime check in Chromium:
   1. Open Northbank Structure + MEP from the samples picker; propose on #042 and keep it.
   2. Add Architecture: it draws, the check runs again, the list grows, and #042 is still fixed.
   3. Remove Architecture: confirm the counts; the list shrinks and the fix stays.
   4. Export, and confirm the IFC carries the edit.
   5. STEP into IFC is refused in words.
   6. Both demo cards and the first steps of both tours still work.
6. **Finish:** commit, push, open the PR, and update the ledger and `CLAUDE.md`'s status (one line).

## Progress ledger

| Date | Slice / task | State | Commit | Checked |
|---|---|---|---|---|
| Nov 1 | Spec and plan | written, owner-approved | (this commit) | n/a |
| Nov 1 | 1.1 `IfcScene.add_files`, `remove_file`, `layout` | done | `88fb766` | `test_scene_models.py` (7) |
| Nov 1 | 1.2–1.3 `Workspace.add_models` / `add_samples`, `remove_model`, `Register.drop_file`, journal marking | done | `1d20c77` | +15 tests, Northbank add and remove |
| Nov 1 | 1.4 routes, `layout` on every way in and the patch, doc 10 | done | `1314f57` | +5 route tests, docs map |
| Nov 1 | 1.5 docs (04, 05, 10, 14, 15, 16, 18, 20, 22; uploads, detection, manual edits; spec status) | done | `6d27534` | docs map |
| Nov 1 | 1.6 finish | PR #104 merged on the owner's word | `75dddf8` | 895 server tests (4 known failures), 240 web tests, build, runtime on port 8023 (build log) |
| Nov 1 | 2.1 `api.ts`, 2.2 `Viewer.add` / `remove`, `sceneModels.ts` | done | `3d8c201` | `scene-models.test.mjs` (8), `viewer-load.test.mjs` (+3) |
| Nov 1 | 2.3 App: the Open menu, remove with its question, waiting, another layout reloads | done | `5542aa1` | 251 web tests, build |
| Nov 1 | 2.4 docs (01, 03, 12, 13, 18, 20, 22; spec; CLAUDE.md status) and 2.5 runtime checks | done | `0d60e14` | Chromium on port 8023: every check in the list above (build log) |
| Nov 1 | 2.6 finish | PR #106 open, awaiting the owner | `0d60e14` | 251 web tests, build, 894 server tests (known failures), runtime (build log) |
