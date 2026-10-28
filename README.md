# ClashWise Sightline

An AI design coordinator for 3D models, proven on buildings.

Sightline checks the models every team makes against each other, finds where they clash, sorts what matters from what
doesn't, and proposes one to three fixes by editing real model elements. Every fix
is checked with geometry before you see it: the clash is gone, there is clearance, and nothing new clashes.
You review the options in 3D and export the edited IFC.

Built for the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026) by IssueLab, the team behind
[ClashWise](https://clashwise.ai). See [BUILT_DURING_HACKATHON.md](BUILT_DURING_HACKATHON.md) for what
was built during the event.

## How it works

```
Browser (React + three.js + web-ifc)          Server (Python, FastAPI)
  view · pick · isolate · preview options  ⇄    Sightline core (also an MCP server)
                                                  ├─ IfcOpenShell: load, connected runs, edits, IFC export
                                                  ├─ Geometry check: collision + clearance (IfcOpenShell tree)
                                                  └─ Meta models: Muse Spark (vision, reasoning)
```

The agent loop is **propose → verify → retry → rank**: Muse Spark proposes fixes from the images, the
element data and a domain pack (construction rules of thumb, in `server/sightline/domain_packs/`); the
geometry check tests each one; failures are fed back with what they hit; only verified options are shown.
A fix is a **move** (an element and its straight run) or a **local offset** (`server/sightline/edits.py`): split a
segment either side of an obstacle, raise or lower the middle piece, join it with risers, re-chain the ports, as a
designer would around a beam. Openings through the obstacle are measured on the run's line and given to the model as
heights. **Accept this fix** keeps it in the server's model; **Export edited IFC** downloads the changed files.

The browser previews moves instantly; the server makes the real edit and is the only source of
clearance numbers. Elements are addressed by IFC GlobalId everywhere.

**Coordinate › Check the open models** finds the clashes (design: [docs/detection.md](docs/detection.md), code:
`server/sightline/detect.py`). The demo opens Northbank and runs it at once:
- **Tests:** every pair of open models and each model against itself, hard at 1 mm, plus duplicates.
- **Not reported:** pairs meant to meet (joined by ports, one assembly, a door in its wall) and touches. They are
  counted and shown under "What was checked".
- **Engine:** a sweep over the element boxes finds every pair that could clash; IfcOpenShell's triangle tree measures
  them, with an exact check for flush rectangular solids.
- **Result:** the clash list, which triage, insights, fixes, chat ("find the clashes") and the PDF all work on.
  Sightline takes each clash's A/B/C views in the browser for the fix agent.
- **Detect again:** after fixes, it says which clashes were resolved.

A site model (terrain, paving, planting) is context: its tests are listed but off by default, so Northbank's default
check covers Structure, MEP and Architecture (1,732 elements): 464 clashes in about 4 s, including all three of the
answer key's girder clashes. With every test on (1,961 elements, 633 clashes, 7-12 s) it finds every sampled Navisworks
result that is a real overlap (117 of 117).

**Clashes have numbers and titles, not "Clash39".**
- **Number:** every clash has a number, #39, unique across the whole report. For clashes Sightline finds, it is kept
  across runs.
- **Title:** Muse writes one from the clash's facts ("Cold-water main clips the transfer girder at grid 3, level 02";
  `server/sightline/titles.py`). Until it lands, a plain name from the two elements shows.
- **Navisworks label:** on an imported report, kept as a small reference.
- **Using the number:** chat and voice understand "#39".

For a clash that needs changes around it, choose **Explore wider fix** on a matched report clash or two manually
picked model elements. Sightline inspects nearby geometry, discovers blockers and checks complete arrangements with
up to three coordinated edit groups. The **Plan** tab shows up to three alternatives, every edit and its reason,
geometry and model integrity evidence, retained authored frame warnings, and individual designer review conditions.
**Before / After / Both** previews the entire arrangement, including surrounding elements that must move.

Wider-search offsets support horizontal straight service segments with plain rectangular or circular profiles.
Hollow, rounded and open-section profiles cannot yet retain their shape through generated bends, so those offsets
are rejected and inspection explains the limit. Whole-run moves remain available when supported by the model.

Acknowledge every condition to **Accept complete proposal**. The server rechecks its stored proposal against the
current model revision and keeps all dependent edits atomically; the browser reloads every affected IFC file and
marks only confirmed resolved pairs fixed. If the model changed, regenerate for the proposal's original objective.
Chat can also explore wider fixes; the same review appears in Plan while the conversation stays open. Search is
bounded, so an empty result does not prove no solution exists. These are geometry and model checks with designer
review conditions, not a claim of engineering adequacy or full IFC conformance. **Export IFC** includes all edited files.

## Run it

Requirements: Python 3.13+, [uv](https://docs.astral.sh/uv/), Node 22+.

```bash
# server
cd server
uv sync
uv run python -m sightline.fixtures ../samples/fixture-clash.ifc   # small test model
cp ../.env.example ../.env   # then fill in the Meta Model API settings (only needed for "Propose fixes")
uv run uvicorn sightline.app:app --reload --port 8000

# web (second terminal)
cd web
npm install
npm run dev     # http://localhost:5173
```

Open a model, double-click element A then element B, and choose **Propose fixes**. **Check this move**
tries a vertical move by hand and works without any API key.

While the agent works it drives the viewer ([`web/src/pilot.ts`](web/src/pilot.ts)): each idea appears in place as
the geometry check runs (amber), then turns teal when it is clear or lights up what it hit in magenta, and the camera
follows; between rounds it turns slowly round the clash. Drag, scroll or click in the view to take it back (the agent
keeps working); **Let Sightline drive** hands it over again.

### Works with Navisworks reports

Teams that already run Navisworks can bring its results instead: **Coordinate › Import a Navisworks clash report** opens
an XML clash report: a sample from `samples/reports/<name>/` (any
`*.xml` at the top of the folder, with the images it links to), or an upload of an export folder or XML files. Several
XML files open as one report; a result exported twice is kept once. Each clash is matched to the open model by IFC
GlobalId (else by a unique class and name), shown with its Navisworks images, and measured again by Sightline's own
check (Navisworks and IfcOpenShell report depth differently: #042 is −150 mm in Navisworks, −300 mm here).
**Propose fixes** on a report clash sends its Navisworks images and distance to the model.

### Triage

**Triage all** gives every clash a verdict (real, by design, not physical, model error) before anyone
opens one ([`server/sightline/triage.py`](server/sightline/triage.py)). Sure cases are settled by rule with no model call
(a space, port or opening on either side; a touch within 1 mm); the rest go to the triage model, eight at a time, with
their images. The list shows a tag per row and filters by verdict, the clash panel shows the reading, and **Set aside**
marks the by-design and non-physical results as reviewed. One run per sample report is shared by every visitor.

The triage model is **Muse Spark Open** (open weights) on any OpenAI-compatible host when a key is set, and Muse Spark on
Meta's API otherwise; the card says which one answered:

| Variable | Default |
|---|---|
| `TRIAGE_API_KEY` (or `BASETEN_API_KEY`) | unset: use Muse Spark |
| `TRIAGE_API_BASE_URL` | `https://inference.baseten.co/v1` |
| `TRIAGE_MODEL` | `meta-models/muse-spark-open` |
| `TRIAGE_IMAGES` | `1` (`0` for a text-only host) |
| `SIGHTLINE_TRIAGE_WORKERS` | `8` |

A host without strict structured output gets JSON mode with the schema in the prompt (switched on the first 400).
Alike clashes (the same kinds of element, named alike, about as deep; three or more) are read once, through the deepest:
Northbank's 464 detected clashes (default tests) took 39 model calls and 101 s on Muse Spark Open: 5 real, including the
answer key's three, all high and for MEP (all 633 with Site: 98 calls, 214 s). Navisworks' 317 results: 184 by rule, 133 by the model, 119 s on Muse Spark with `reasoning_effort=low`, 189 s on Muse
Spark Open on Baseten (live deploy, Oct 27: median call 7.9 s but a longer tail, up to 33 s). Scored on the whole package
the two models agree on 299 of 317 verdicts ([evals/README.md](evals/README.md#triage-of-navisworks-results)).

### Several clashes at once, and root causes

Tick clashes in the list and choose **Fix together**: Sightline runs the fix agent on every pair at once, then applies
all the chosen fixes in one trial and checks each against the whole model, the other fixes included, swapping in a
next-best option when two collide (`server/sightline/plans.py`). **Root causes** lists elements in several real
clashes (cross-discipline first) and asks the geometry for clashes the report missed; **Fix** asks Muse Spark for the
cause and a strategy (move that element, or coordinate everything crossing it) and builds one plan. On Northbank it
finds the transfer girder, adds the cold water main Navisworks missed, and offsets all three services through the
girder's openings at Rev04's heights, verified together. Plans preview in 3D (before / after / both) and are accepted
in one go. When a root cause is how the parts are meant to go together (a ground beam tying into its footings), the
plan says so instead, with the clash rule to add, and marks those clashes as by design.

**Patterns** are the same clash repeated (every column through every slab, curtain-wall members all at −30 mm).
**Explain** asks Muse Spark about all of them in one call: by design (with the clash rule to add), a modelling error
(flag for the author) or a real problem (fix together). Reviewed clashes drop out of root causes, patterns and plans.
The chat can do the same (`find_root_causes`, `find_patterns`, `plan_root_cause`, `plan_fixes_together`).

### Chat

**Chat with Sightline** (right pane) talks to Muse Spark with tools over the open report and model
(`server/sightline/chat.py`, prompt `domain_packs/chat.md`): report summary, list/get clashes, look at a clash's
images, measure, describe/find elements, find openings, check a move or offset, propose fixes (the same verified
agent), and two page actions, show a clash and set the view. Every tool call streams to the page. Chat messages are
capped per visitor (`SIGHTLINE_CHAT_PER_HOUR`, `SIGHTLINE_CHAT_PER_DAY`); proposals made through the chat count
against the proposal caps.

### Viewer

Modes Shaded / X-ray / Context / Isolate, edges through geometry, section box, measure, properties on click, preset
views and fit, per-model visibility and screenshots. Keys: 1-4 views, H fit, F go to the clash, X/C/I/V modes,
S section, E edges, M measure, Esc clears. Double-click picks element A, then B.

Uploads stay in a temp folder while the report is open (`SIGHTLINE_UPLOAD_MAX_MB`, default 200;
`SIGHTLINE_UPLOAD_MAX_FILES`, default 5000; `SIGHTLINE_MAX_REPORTS` open at once).

MCP server (stdio), for agents such as ClashWise's Wise:

```bash
cd server && uv run python -m sightline.mcp_server
```

## Deploy (public demo on Modal)

One container serves the built web app and the API from the same origin
([`deploy/modal_app.py`](deploy/modal_app.py)). Put the demo `*.ifc` files in `samples/` and any sample clash
reports in `samples/reports/<name>/` first.

```bash
cd web && npm ci && npm run build && cd ..
modal secret create sightline-meta META_API_KEY="$META_API_KEY" TRIAGE_API_KEY="$BASETEN_API_KEY" --force   # once; no echo
modal deploy deploy/modal_app.py
```

It runs one container on purpose: open models and edits live in server memory. Proposals are capped per visitor
and per day (`SIGHTLINE_PROPOSE_PER_HOUR`, `SIGHTLINE_PROPOSE_PER_DAY`, in `server/sightline/limits.py`), because
each one is a paid Muse Spark call; **Check this move** is not limited.

## Tests

```bash
cd server && uv run pytest -q      # geometry check, detection, agent loop, web API, MCP tools
cd web && npm run build            # type-check + production build
```

## Day-1 spikes

See [spikes/README.md](spikes/README.md).

## Licences

Sightline's own code: MIT (see LICENSE). Dependencies keep their own licences: IfcOpenShell (LGPL-3.0),
web-ifc (MPL-2.0), three.js (MIT), React (MIT).
