# 21 · Glossary and naming

> **Covers:** the words used across ORCA's code, UI and docs, and the naming rules: `server/sightline/*.py` (the
> symbols named below), `web/src/api.ts` (shared types), `web/src/fixKinds.ts` (`KIND_LABEL`), `web/src/Triage.tsx`
> (`TRIAGE`), `web/src/reqFile.ts`, `web/src/About.tsx` ("Words you'll see") · **Checked against code:** 2026-10-30
> (`feature/brand-assets`, based on `0390a12`)

A newcomer to ORCA meets two vocabularies at once: the building and machine design world's (IFC, MEP, ports, provision
for void) and ORCA's own (scene, option, trial, basis, hub). This doc defines both, maps each ORCA term to the code
symbol it names, and sets out the naming rules: what users see, the internal names kept on purpose, and the wording
the product uses. For where each object's state lives see [05](05-domain-model-and-state.md); for the user's view of
each feature see [01](01-product-and-journeys.md).

## BIM and engineering terms

| Term | Meaning | Where it shows in ORCA |
|---|---|---|
| **BIM** | Building Information Modelling: a 3D model where every object knows what it is (class, properties, relations). | The landing's glossary (`About.tsx`). |
| **IFC** | Industry Foundation Classes, the open model format. ORCA reads and writes IFC4 (IFC2X3 where noted, e.g. a provision for void by ObjectType). | IfcOpenShell on the server, web-ifc in the browser ([14](14-files-in-and-out.md)). |
| **IFC class** | An element's type: `IfcBeam`, `IfcColumn`, `IfcSlab`, `IfcWall`, `IfcDuctSegment`, `IfcPipeSegment`, `IfcCableCarrierSegment`, … | Shown without the `Ifc` prefix in the UI; never in Muse's titles (`domain_packs/titles.md`). |
| **GlobalId** | The 22-character id every IFC element carries, stable across revisions. | ORCA addresses elements by GlobalId everywhere: picks, clashes, fixes, the API. |
| **Discipline / team** | Who models what. A team is named by the user per model in the report dialog; detection and requirements group a building's models by the discipline ORCA guesses (Structure, MEP (services), Architecture, Site). | `document.guess_team` (from the class histogram; a machine cell's model, or one with nothing to go on, gets its own name), typed in `ReportDialog`. |
| **MEP** | Mechanical, electrical and plumbing: ducts, pipes, cable trays, lights. "Services" in plain words. | |
| **Federation** | Several discipline files that share one coordinate system, opened together. | One `IfcScene` per set; `COORDINATE_TO_ORIGIN` stays off in the viewer. |
| **Storey / level** | `IfcBuildingStorey`: Level 01, Level 02… (not ORCA's design level, below). | `ReportElement.level`; the properties card's "Level". |
| **Design coordination** | Making the teams' models agree before anything is built. | The product's job; see "Wording" below. |
| **Clash** | One place where two elements conflict. | `ReportClash`; numbered `#N`. |
| **Hard clash** | Two solids overlap deeper than a tolerance (1 mm by default). | `detect.Test` kind hard; `verify.Hit.kind == "collision"`. |
| **Clearance** | The gap required between two elements. A clearance clash is closer than that. ORCA's fixes keep 25 mm by default, or what the requirements ask of the pair. | `requirements.DEFAULT_CLEARANCE_M`, `Workspace.clearance`; `Hit.kind == "clearance"`. |
| **Fixed in place** | An element a fix never moves to make room (a trim between two that stay is allowed). The requirements say which (`stays`, and groups allowed no edits); without them, the domain's frame classes. | `IfcScene.stays`, `requirements.stays_rule`, `domains.STAYS`. |
| **Domain** | Whether a project is a building (`construction`) or a machine (`machines`): ORCA's voice, fix pack, team guesses and what stays by default. The requirements file says which; else all-STEP models are a machine. | `requirements.Doc.domain`, `domains.of`. |
| **Tolerance** | The smallest overlap a test reports. | `ReportClash.tolerance_m`; requirements levels set it (`requirements.LEVELS`). |
| **Touch** | Elements meeting within 1 mm, not overlapping. Not a clash. | Triage basis `touch`; detection counts touches, does not report them. |
| **Duplicate** | An element modelled twice in the same place. | Detection's duplicates test. |
| **Clash test** | One pair of selections checked against each other (two models, or one against itself). | `detect.Test`, `detect.Selection`; Navisworks tests in an imported report. |
| **Segment, fitting, run** | A straight piece of duct, pipe or tray (`IfcFlowSegment`), the bends and tees between them (`IfcFlowFitting`), and a chain of segments joined through ports. | `IfcScene.connected_run` (stops at fittings); `scene.FITTINGS`. |
| **Bend, riser** | A fitting that turns a run (PredefinedType `BEND`); the short vertical piece of an offset between two bends. | `edits.bend_radius`, `edits.apply_offset`. |
| **Port** | A connection point on a service element (`IfcDistributionPort`), joined by `IfcRelConnectsPorts`. Port-joined neighbours touch by design. | Ignored in checks; never a clash in detection. |
| **Assembly** | Parts aggregated or nested into one element (`IfcRelAggregates`, `IfcRelNests`). | Never a clash in detection. |
| **Opening** | A void cut in a host (`IfcOpeningElement`, an `IfcFeatureElement`): not physical. Northbank's girder web openings are cut into its geometry instead. | `scene.NOT_PHYSICAL`; `edits.passages` finds openings by ray casting. |
| **Provision for void** | The space a service asks to be opened through a wall or slab, drawn in the service's own model (`IfcBuildingElementProxy`, PredefinedType `PROVISIONFORVOID`). Not physical. | `scene.is_provision`; written by every penetration fix. |
| **Penetration** | A service crossing a host through an opening. | Fix kind `penetration`, shown as "Opening". |
| **Host** | The element an opening goes through: a wall, a slab, a plate. | `hosts.py` decides which kinds may take one. |
| **Transfer element** | A beam or member that a column or wall stands on (Northbank's girder carries column B3). Never cut. | `hosts.hard_rule`. |
| **Gland plate, fitted gland** | A panel plate made to be drilled for cables; a fitted hole has no clearance round the conduit. | Cell C8; `edit.fit == "fitted"`. |
| **Space** | `IfcSpace`: a room volume. Not physical. | Excluded from sample reports (`SAMPLE_EXCLUDE`). |
| **Virtual element** | `IfcVirtualElement`: a boundary with no material. Not physical. | `scene.NOT_PHYSICAL`. |
| **Extrusion, profile, mesh** | A body swept from a 2D profile (`IfcExtrudedAreaSolid` with `IfcRectangleProfileDef` or a circle), or a triangle mesh (`IfcTriangulatedFaceSet`). | Offsets, trims and resizes need exact extrusions; meshes only move. |
| **Pset** | A property set. Standard ones are `Pset_*Common`. | Muse's host reading sees standard psets only. |
| **Slender member** | Long compared with its section: at least 3 times longer than across. | `edits.SLENDER`: only slender members are trimmed. |
| **Restricted space, working space** | Machine safety zones: the volume a robot can reach (ISO 10218-2), the space in front of a panel. Modelled see-through. | `scene.opacity`; the cell's C4 and C5. |
| **Equivalent diameter** | A rectangular duct's round equivalent (Huebscher), kept when a duct is flattened. | `edits.resize_size`. |
| **Navisworks** | Autodesk's clash tool. Its XML report, with a three-view (A/B/C) image export, can be imported. | `reports.py`. |
| **BCF** | BIM Collaboration Format 2.1: issues (topics) with viewpoints and comments that open in Revit, Navisworks, Solibri or BIMcollab. | `document.bcf_zip`; TopicType "Clash". |
| **LOD, RIBA, product phase** | Industry stage scales (Level of Development, the RIBA Plan of Work, EVT/DVT/PVT). Hints only. | `requirements.LEVELS[...]["hints"]`. |
| **STEP** | ISO 10303 mechanical CAD exchange (AP203, AP214, AP242). | `step.py` converts it to IFC on open. |

## ORCA's own terms

### Models, reports and clashes

| Term | Meaning | Code |
|---|---|---|
| **Scene** | A set of model files opened together, held in server memory with its edits; has an id and a revision. | `scene.IfcScene`; `scene_id`; `IfcScene.revision`, `IfcScene.bump`, `IfcScene.history` |
| **Workspace** | The server's holder of scenes, reports, detection runs, last tries and the lock every geometry operation takes. | `service.Workspace`; `Workspace.lock` (an RLock) |
| **Sample** | A model or report in `samples/` that the server lists. | `Workspace.list_samples`, `list_report_samples` ([19](19-demo-data.md)) |
| **Report** | A clash list: imported from Navisworks or found by ORCA. | `reports.Report`; `origin` `"navisworks"` or `"sightline"`; a detected report is titled "Coordination · n models" |
| **Clash** (report) | One item in a report, with its two elements, depth and pictures. | `reports.ReportClash`; id `c0001`… (imported) or `s` + a hash of the test and the pair (detected) |
| **Number, #N** | The clash's permanent number, unique across the report. Imported reports number by position; detected numbers are kept across reruns and never reused. | `ReportClash.number` |
| **Ref** | The source tool's own label ("Navisworks Clash39"), kept as a small reference. | `ReportClash.ref` |
| **Name** | A plain name from the two elements, "A × B", shown until a title lands. | `reports.plain_name` |
| **Title** | A short title Muse writes from the clash's facts. | `titles.py`, `domain_packs/titles.md`; `ReportClash.title` |
| **Label** | How people and models refer to a clash: "#N title-or-name". | `ReportClash.label`; `clashLabel` in the web app |
| **A, B** | The clash's two elements: A drawn red, B green; one element on both sides is purple. | `element_a`, `element_b`; `Side = "a" \| "b" \| "ab"` (`viewer/Viewer.ts`) |
| **A/B/C views** | Three pictures per clash: the pair, the pair in context, a second angle. Navisworks' own, or captured in the browser for detected clashes. | `ReportClash.images`; `Viewer.captureClash`; `POST …/images` |
| **Match** | A report clash's elements found in the open models (by GlobalId, else a unique class and name). | `Workspace.match`; `Matches` in `api.ts` |
| **Depth** | How far one element must move to clear the other (negative = overlap). | `distance_m`; `detect.measure_pair` |
| **Detection, run, coverage** | ORCA's own check, one run of its tests, and what each test covered (pairs, touching, meant to meet). | `detect.run`, `detect.Run`, `detect.Coverage`; `Workspace.detect` |
| **Resolved / new** | A rerun's diff against the last run of the same scene. | `run.diff` (`new`, `resolved`, `no_longer_checked`) |

### Fixes

| Term | Meaning | Code |
|---|---|---|
| **Clash** (agent) | The pair the fix agent works on, with images, notes, other obstacles and nearby clashes. | `agent.Clash` |
| **Proposal** | One run of the fix agent on a pair: rounds of ideas, checks and retries. | `agent.resolve`; `POST …/propose/stream`; `Proposal` in `api.ts` |
| **Idea, candidate** | One fix Muse suggests, before it is checked. | the model's JSON reply in `agent.resolve` |
| **Trial** | A candidate put in place in the model just before its check (streamed so the page can draw it). | event `{"type": "trial"}` (`resolve(trials=True)`) |
| **Attempt** | A checked idea, passed or failed, with the reason and what it hit. | `agent.Attempt` |
| **Option** | A verified fix shown to the user (1-3 per proposal). | `agent.Option`; `Option` in `api.ts` |
| **Verdict** (geometry) | The check's answer: passed, hits, nearest clearance. Not the triage verdict. | `verify.Verdict`, `verify.check` |
| **Hit** | Something a candidate runs into: a collision or too close. | `verify.Hit` (`kind`: `collision` / `clearance`) |
| **Fix kind** | What a fix edits. Registered once per layer. | `agent.TRIES`, `agent.PARAMS`, `plans.IN_TRIAL`, `plans.KEEP`, `KIND_LABEL` ([07](07-fixes-and-edits.md)) |
| **Move** | The element and its connected run moved as one. | kind `move`; UI "Move" |
| **Offset** | A straight segment split either side of an obstacle, the middle raised or lowered, joined with bends and risers. | kind `offset`; `edits.apply_offset`; UI "Offset" |
| **Trim** | A member's end cut back to butt the other's face. | kind `trim`; `edits.butt_trim`; UI "Trim" |
| **Route, reroute** | Up to three offset steps, up and/or sideways, on the run's own axes. | kind `route`; `edits.apply_route`, `edits.run_frame`; UI "Reroute" |
| **Resize** | A flatter section where the obstacle leaves too little depth, with transitions. | kind `resize`; `edits.apply_resize`; UI "Resize" |
| **Penetration** | An opening asked for through a wall, slab or plate, with a provision for void. | kind `penetration`; `edits.apply_penetration`; UI "Opening" |
| **Combined** | 1-3 steps on different elements, kept all or nothing. | kind `combined`; `agent._try_combined`; UI "Combined" |
| **Tier** | Ranking: plain one-element fixes first, then combined, resize, penetration (an opening in anything but a wall or slab after that). | `agent.TIERS`, `agent.tier` |
| **Passages, free bands** | The openings in an obstacle on a run's line, and the room beside or above it, measured and told to Muse. | `edits.passages`, `edits.free_bands` |
| **Supports** | What a moved element stands on, kept as it was; a lift off it fails. | `verify.supports`, `verify.keep_supports` |
| **Stays** | A structural element (by class, `agent.STAYS`): a combined fix's steps never move it, nor a run that holds it. | `agent.stays` |
| **Review** (on an option) | Who must review a fix before it is built (structure, services, architecture, fire, safety). | `Option.review`; `reviewText` in `fixKinds.ts` |
| **Meets** | The requirements a verified fix meets, in plain words. | `Option.meets` |
| **Model cleanup** | A trim inside one model: it tidies a joint for its author rather than settling something between teams. | `Option.cleanup`; "Accept this cleanup" |
| **Recommendation** | Where the requirements allow no edit: the change ORCA recommends for the designer, never tried or applied. | `agent._recommend`; `Result.recommendation`; "Recommended for the designer" |
| **Advice** | What a person should look at or decide, in the model's words, when nothing passes. | `Result.advice` |
| **Keep, accept, apply** | Making a fix permanent in the scene's in-memory model; only a kept fix marks a file edited. | `plans.KEEP`, `plans.apply`, `Workspace.apply` / `apply_offset` / …, `IfcScene.mark_edited` |
| **Patch, accept in place** | The meshes a kept fix changed, sent so the page updates its viewer without reloading the file. | `Workspace.patch`; `revision_before`; `Viewer.patch` ([13](13-3d-viewer.md)) |
| **Stand-ins** | Pieces an accepted offset added, shown as part of A or B. | `standIns` in `App.tsx` |
| **Pilot** | The page playing the agent's trials in the viewer; any camera move is a takeover; **Let ORCA drive** resumes. | `web/src/pilot.ts` (`Pilot`); `Viewer.onUserCamera` |
| **Escalation, second try** | A longer try on Muse Wonder, briefed with the first try. Modes off / button / auto. | `escalation.py`; `meta_client.escalation_model`; `Workspace.last_try`; `settings.ESCALATION` |
| **Built view, Show it built** | Muse Image restyling ORCA's own view of a verified fix, checked against the model. | `built.py` (`built.make`); `BuiltView.tsx`; `Viewer.captureBuilt` |
| **Wider fix (context fix)** | A complete arrangement of one to three coordinated edit groups around a clash, for designer review. | `context_planner.py`, `context_eval.py`; `ContextPlan.tsx`; "Explore wider fix" |

### Sorting and planning

| Term | Meaning | Code |
|---|---|---|
| **Triage** | A verdict for every clash: by rule where sure, else by the triage model. | `triage.py`, `triage.Job`; `TriageCard` |
| **Triage verdict** | `real_clash` ("Real problem"), `by_design`, `non_physical` ("Not physical"), `modelling_error` ("Model error"), `unknown` ("No answer"). | `TriageKind` in `api.ts`; `TRIAGE` in `Triage.tsx` |
| **Basis** | What settled a not-a-clash verdict without the model, or overrode it: `non_physical`, `touch`, `same_element`, `no_overlap`, `reviewed`, `requirement`, `strictness`. | `TriageVerdict.basis`; `BASIS` in `ClashPanel.tsx` |
| **Alike** | Three or more clashes of the same kinds, named alike, about as deep: read once, through the deepest. | `triage.alike_groups` |
| **By design** | How the parts are meant to go together (a bolt in its plate). | triage verdict; pattern verdict; requirements `by_design` rules |
| **Not a clash** | A clash the page says needs no fix (one element, non-physical side, touch, no overlap, or a by-design verdict). | `noClash.ts`; "Mark as not a clash" |
| **Reviewed** | The page's marks: by design, or for the model's author. Reviewed clashes drop out of root causes, patterns and plans. | `reviewed` in `App.tsx` (`by_design` / `author`) |
| **Pattern** | The same clash repeated (class pair and files, three or more); read as by design, modelling error or real problem. | `plans.patterns`, `plans.triage_patterns`, `domain_packs/patterns.md` |
| **Hub, root cause** | An element in several real clashes, and the cause and strategy Muse gives for it (`move_hub`, `fix_partners`, `as_designed`). | `plans.root_causes`, `plans.build_root_cause`, `domain_packs/root_cause.md` |
| **Plan, item** | Fixes for several pairs, checked together in one trial; each pair is an item. Kinds `batch` (Fix together) and `root_cause`. | `plans.Plan`, `plans.Item`, `plans.verify_together`, `plans.merge_shared` |
| **Fix together** | The user's name for a batch plan from ticked clashes. | `runPlan({ clash_ids })`; "Fix n together" |
| **Evidence** | What the page keeps per clash for the report: proposed, accepted or recommended, with pictures. | `evidence` in `App.tsx` |
| **Review, sign-off** | A team's name and decision on a clash, printed in the report; the PDF says DRAFT until every team has one. | `ReviewBlock` (`ReportDoc.tsx`); `signoffs` |
| **Acting team** | The team that acts on a clash in the report and BCF: whose element a fix changes, else triage's `responsible`, else the structure-stays order. | `document.STAYS_FIRST` |

### Standards, people and plumbing

| Term | Meaning | Code |
|---|---|---|
| **Requirements** | An optional `orca-requirements/1` JSON file: level, strictness, groups, checks, who moves, by-design and penetration rules, guidance. No file means ORCA's defaults. | `requirements.Doc`, `requirements.FORMAT`; `reqFile.ts` ([15](15-requirements-settings-and-config.md)) |
| **Design level** | L1 Concept, L2 Developed, L3 Coordinated, L4 Production, L5 As-built (L5: recommend, never edit). | `requirements.LEVELS`; `LEVEL_NAME` |
| **Strictness** | Lenient, Relaxed, Balanced, Strict, Exacting: covers both flagging and fixing. | `requirements.STRICTNESS`; `STRICTNESS_NAME` |
| **Group, check, mover** | A set of elements (by team, class, system or file), the check between two groups (hard, clearance, off), and what a group may do (edits any / move / none, largest move, trims). | `requirements.Group`, `Check`, `Mover` |
| **Params, policy** | The numbers a level and strictness compile into; what the requirements allow on one element. | `requirements.Params`, `requirements.resolve`, `requirements.Policy`, `requirements.policy` |
| **Domain pack** | A prompt file of construction rules of thumb and instructions for one workflow. | `server/sightline/domain_packs/*.md` ([08](08-ai-models-prompts-and-spend.md)) |
| **Effort** | The reasoning effort sent to a model: minimal, low, medium, high. | `settings.EFFORTS`; `MetaChatModel.effort` |
| **Open weights** | Whether titles and triage run on Muse Spark Open (Baseten) instead of Muse Spark. Off unless switched on. | `settings.open_weights`, `meta_client.triage_model` |
| **Owner** | The site's owner, unlocked by a token; gets owner settings and no demo caps. | `owner.py` (`cookie_ok`, `HEADER`, `COOKIE`); `Owner.tsx` |
| **Settings for everyone** | Settings the owner sets for every visitor, kept across restarts. | `settings.Settings` |
| **Cap** | A per-visitor-per-hour and per-day limit on a paid or heavy action. | `limits.ProposeLimit`; `*_limit` in `app.py` ([16](16-security-caps-and-cost.md)) |
| **Spend, budget** | Money claimed against the day's Muse Wonder budget. | `spend.claim`, `spend.held` |
| **Link, agent link** | A pairing token that ties an MCP client to a visitor's session. | `agents.Link`, `agents.Links`; tokens start `orca_` ([11](11-mcp-and-agent-links.md)) |
| **Job** | Long work run in the background and followed by id (triage, titles, MCP tool calls). | `triage.Job`, `titles.Job`, `agents.Job` |
| **Session, resume** | What this browser had open, kept so the landing can offer to reopen it. | `sightline.session` (`localStorage`); `resumeSession`; `Workspace.scene_info` |
| **Golden path** | The one-click demo: open, check, pick the duct, propose. | `startGolden` |
| **Landing, blank project** | The page before anything opens; the drop zone for one's own models. | `landing`, `blank`, `starting` in `App.tsx`; `About.tsx`, `ProjectStart.tsx` |
| **Insights** | The left pane's second tab: the run's summary, root causes and patterns. | `Insights.tsx`; `leftView` |
| **Sheet, peek, half, full** | The phone's bottom sheet and its heights. | `Sheet.tsx`, `layout.ts` (`Snap`, `follow`) |
| **Panel, dock** | On a desktop: Model, Coordination, Clash, Plan, Chat and Activity, laid out by the dock (dockview). | `dock.tsx`, `dockLayout.ts` (`PANELS`); [docs/panels.md](../panels.md) |
| **Side bar, float, pop out, put back** | A panel's places: a bar along the left, right or bottom that collapses to a strip of tabs; a floating window over the model; a browser window of its own; back in its bar. | dockview edge, floating and pop-out groups; `collapseEdge`, `floatPanel`, `moveHome` |
| **Properties panel** | The selected element's card and everything its model says about it (type, material, size, property sets, quantities); floats over the model on a selection on a desktop, the card's All properties elsewhere. | `Properties.tsx`, `properties.py`, `GET …/elements/{gid}/properties` |
| **Slot** | The element a panel's content is drawn into, moved by the dock or placed by the classic layout, so nothing remounts. | `usePanelSlots`, `inSlot`, `SlotHost` |
| **Classic layout** | The fixed panes of before: phones, tablets, the landing, and the desktop with the switch on. | `classic`, `sightline.dock.classic` |
| **Tour, recorded run** | The guided walk through the real app; a committed real run it replays when the live one is slow. | `Tour.tsx`; `web/public/tour/*.json` ([19](19-demo-data.md)) |

## Naming rules

### The product

- The product is **ORCA, by IssueLab**: Observe · Resolve · Check · Apply. It was called Sightline until Oct 29 (owner
  decision).
- ORCA has no association with any other IssueLab product. Do not name one in the app, the docs or commits. The demo
  models come from "IssueLab's private demo-models repo"; do not write that repo's name.
- **No "Meta" or "Muse" in the product name.** Model names (Muse Spark, Muse Spark Open, Muse Wonder, Muse Image, Muse
  Voice Transcribe) are fine as the names of the models, and the page names them.

### What users see says ORCA

**Approved identity:** direction **05 / ORCA Type** is the custom geometric wordmark and split-O monogram selected
on 30 October 2026. The master, icon variants, palette and motion live in
[`assets/brand/orca/`](../../assets/brand/orca/README.md), for the upcoming redesign. The name remains **ORCA, by IssueLab**.
Motion names are Orbit, Breathe, Resolve, phase cycle, Settle and Reveal; a cycle is demonstrative, while the production
phase indicator follows actual events. Identity inventory checked 2026-10-30 against `0390a12` plus this slice.

| Where | Name | Code |
|---|---|---|
| The app, its header and title | "ORCA" | `App.tsx`, `About.tsx` |
| The PDF | "Design coordination report"; footer "ORCA · AI-assisted design coordination report" | `document.py` |
| BCF topics | author "ORCA" | `document.bcf_zip` |
| The MCP server | `orca`, titled "ORCA" | `mcp_server.build` |
| Exported models | `<name>.orca.ifc`, `<name>.orca.step`; several in one zip, `<project>-orca.zip` (`orca-export.zip` when the files share no name) | `IfcScene.write_edited(suffix=".orca")`, `Workspace.export`, `app.export_zip_name` |
| The coordination report | `orca-report.pdf` (`orca-report-<team or model>.pdf`, zipped as `orca-report.zip`) with `orca-issues.bcfzip` | `document.generate` |
| A requirements file | `<name>.orca-requirements.json`, format `orca-requirements/1` | `reqFile.fileName`, `requirements.FORMAT` |
| STEP parts' property set | `ORCA_STEP` (Group, Label, Source) | `scene.STEP_PSET`, `step.py` |
| Agent link tokens | `orca_…` | `agents.Links` |
| A screenshot | `orca-clash-<n>.png` / `orca-view.png` | `screenshot` in `App.tsx` |
| The Modal app | `orca` | `deploy/modal_app.py` |

### Internal names kept on purpose

Renaming these would break deployed configuration, saved state or other people's files, so they keep the old name.
Each was checked at HEAD.

| Kept name | What it is | Where |
|---|---|---|
| `sightline` | The Python package (`server/sightline`, project `sightline-server`); `python -m sightline.mcp_server`, `sightline.app:app` | `server/pyproject.toml`, `deploy/modal_app.py` |
| `SIGHTLINE_*` | Every ORCA environment variable (about 50 at HEAD) | `server/sightline/*.py`, `deploy/modal_app.py` ([15](15-requirements-settings-and-config.md)) |
| `sightline-meta` | The Modal secret holding the API keys and the owner token | `deploy/modal_app.py` |
| `sightline-settings` | The Modal Dict holding the settings for everyone | `settings.DICT_NAME` |
| `server/.sightline-settings.json` | The local settings file (gitignored; `SIGHTLINE_SETTINGS_FILE`) | `settings.py` |
| `X-Sightline-Settings` | The owner's per-request settings header | `owner.HEADER`, `api.ts` |
| `X-Sightline-Requirements` | The header carrying the page's requirements id (not in CLAUDE.md's list, kept the same way) | `requirements.py`, `app.py`, `api.ts` |
| `X-Sightline-Gone` | The 404 header naming a scene or report the server no longer holds (`scene:<id>`, `report:<id>`), kept the same way | `app._gone`, `api.ts` `goneOf` |
| `sightline_owner` | The owner cookie | `owner.COOKIE` |
| `sightline.*` | Browser storage keys: `sightline.session`, `sightline.left-w`, `sightline.right-w`, `sightline.signoffs:clash:<id>` / `sightline.signoffs:import:<title>:<files>`, `sightline.reviewer`, `sightline.triage.compact`, `sightline.voice.handsfree`, `sightline.agent.setup`, `sightline.owner`, `sightline.requirements` | `App.tsx`, `ReportDoc.tsx`, `Triage.tsx`, `Chat.tsx`, `Agent.tsx`, `Owner.tsx`, `reqFile.ts`, `signoffs.ts` |
| `origin: "sightline"` | A report ORCA detected itself (else `"navisworks"`) | `reports.Report.origin`, `detect.py`; `ReportClash.source` |
| `Pset_SightlineConstraints` | The model convention for per-element constraints (`KeepFixed`) | `context_eval.element_constraints`, `fixtures.py` |
| `Sightline_STEP` | The old name of the STEP pset, still read so older caches open | `scene.STEP_PSETS`, `requirements.py` |
| `sightline-models`, `sightline-reports`, `sightline-exports`, `sightline-built`, `sightline-run-*` | The temp folders (uploads and STEP conversions, uploaded reports, written models, exports and report copies, built views, detection runs); never a download's name | `service.MODELS`, `app.UPLOADS`, `app.EXPORTS`, `built.CACHE`, `detect.py` |

### Wording

- **"Design coordination"** is the job and its outputs: the landing's "An AI design coordinator for 3D models", the
  header's **Coordinate** menu ("Check the open models"), the Detect card "Coordinate the models", a run's report
  "Coordination · n models", the PDF "Design coordination report", the chat prompt's "design coordination app".
- **"Clash"** is one geometric item. Code identifiers stay `clash` and `report`; BCF's TopicType stays "Clash".
- **Clashes are "#N title"**, never "Clash39". Muse's titles never use an IFC class name, a GlobalId or the word
  "Clash" (`domain_packs/titles.md`).
- **Navisworks is named where it is a fact:** an imported clash's reference ("imported from Navisworks, Clash7"), the
  BCF tools list, the README's "Works with Navisworks reports", a recorded plan's cause text.
- **Code kinds and UI names differ in two places:** `route` shows as "Reroute", `penetration` as "Opening"
  (`KIND_LABEL`). Triage's `real_clash` shows as "Real problem" (or "real"), `modelling_error` as "Model error".
- **Units:** metres in the server and the API (`_m` names); millimetres when quoting depths and clearances in the UI,
  signed ("−300 mm", "+400 mm").
- **British spelling** throughout the UI and docs: metres, colour, behaviour, centre, neighbour, licence (noun),
  modelling.
- **Plain words for people new to BIM:** the landing explains "clash", "check" and "clearance"; hints say tap on touch
  screens and click on a desktop.

## When to update this doc

- A new user-facing concept, fix kind, verdict, basis, plan kind or strategy, or a renamed one.
- A new or renamed core symbol named here (`IfcScene`, `Workspace`, `ReportClash`, `agent.Option`, `plans.Plan`, …).
- A new user-facing file name, header, cookie, storage key, Modal resource or env-var family (and whether it says ORCA
  or keeps `sightline`).
- A change to the naming or wording rules (an owner decision).
