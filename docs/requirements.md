# Coordination requirements: design

Real projects coordinate to a standard: how mature the models are, what is checked against what, how much space
services keep around structure, who moves, what is by design. **Coordination requirements** let a team set that
standard once and have ORCA's checks, triage and fixes follow it. They are **optional**: without a file, ORCA behaves
exactly as before. With one, the numbers become fixed and declared cases are settled without a model call, so results
are repeatable from run to run and from project to project.

Code: `server/sightline/requirements.py` (the file, the scale, compiling, policy, prompts, the Muse draft),
`web/src/Requirements.tsx` (the dialog), `web/src/reqFile.ts` (keep, download, upload, edit). Owner decisions,
Oct 29: both flagging and fixing on one strictness scale; five levels; the Muse draft only on a button; the hackathon
slice. Written for ORCA during the event.

## Muse Spark stays in the loop

Requirements fix the **numbers** and settle the **declared** cases. They never take Muse out:

- **Triage.** Muse still reads every clash no rule settles. Its prompt gains only what differs from ORCA's defaults:
  a level other than L3, the strictness's lean, a tolerance other than 1 mm, clearance checks, the by-design rules
  and the team's guidance. A clash a by-design rule covers is settled without a call, and **Muse audits each rule**
  after the run. It gets one call per rule, on its three deepest clashes, and answers consistent, looks real or
  unsure. A rule it disputes marks its clashes "Muse disagrees: check" and shows a warning on the rule, with Keep
  and Remove.
- **Fixes.** Muse proposes as before, told the requirements. A candidate they forbid (an element that may not be
  edited, a move over the limit, a trim where trims are off) is refused before it is tried, as a failed attempt, so
  Muse hears why and tries something else. Each verified option lists what it **meets**, computed from the geometry
  check and the policy, not written by Muse. Example: "nearest 50 mm ≥ 40 mm required (Strict); edits MEP only;
  Structure untouched; 400 mm within the 400 mm limit".
- **When nothing may be edited** (L5, or both groups set to "never edited"), Muse is still asked, once, in
  **recommend mode**. Its best idea comes back as a recommendation for the designer, never tried or applied. It shows
  in the clash panel and goes into the PDF and BCF.
- **The file itself.** Muse drafts one from the open models on request (**Suggest with Muse Spark**), and Insights'
  pattern readings feed rules into it (**Add to requirements**).

Measured on Northbank with Muse Spark (Oct 29), with the girder clash #1:
- **Strict** proposed the offset up 400 mm through the web opening (Rev04's height), within the 400 mm limit and
  50 mm clear of the 40 mm needed.
- **L5** recommended the same change and edited nothing.
- **The Muse draft at L4 Strict** took 36 to 85 s. It kept structure and site never edited, architecture whole moves
  only, and MEP moving first. It set a 50 mm clearance between MEP and structure and 25 mm elsewhere, and declared six
  by-design pairs (fittings on their segments, fasteners in plates, doors in walls, columns on footings). It invented
  no classes.

## The file: `orca-requirements/1`

JSON, at most 64 KB. It is validated on the server (`requirements.parse`): unknown fields are dropped and numbers are
clamped. A group that selects nothing, or a check or mover naming a missing group, is dropped.

| Field | Meaning |
|---|---|
| `name`, `version`, `notes` | Shown in the dialog and the report. The version goes up with every edit |
| `level` | 1-5 (below) |
| `strictness` | `lenient`, `relaxed`, `balanced`, `strict` or `exacting` (below) |
| `groups[]` | `id`, `name`, `role` (structure, services, architecture, equipment, site, other) and a selection by `teams`, `classes`, `exclude_classes`, `systems`, `files` |
| `checks[]` | `a`, `b` (`null`: the group against itself), `check` (`hard`, `clearance`, `off`), `clearance_mm`, `tolerance_mm`, `reason`, `source` |
| `duplicates`, `rules` | The duplicates test, and the four never-a-clash rules (same element, joined by ports, one assembly, door in its wall) |
| `who_moves[]` | In order, from the group that stays put most to the one that moves first: `edits` (`any`, `move`, `none`), `max_move_mm`, `trims` |
| `by_design[]` | `a_classes` with `b_classes`, `reason`, `source` |
| `guidance` | `triage` and `fixes`, up to 1,000 characters each, for Muse Spark |

**Selectors** name teams, classes, systems or files, never GlobalIds, so a file is reusable on another project.
`source` says where an item came from: `level` (ORCA's start), `orca` (Muse's draft), `triage` (Insights) or
`user`.

The **starting point** comes from the open models (`default_doc`):
- **Groups:** one per team (`document.guess_team`, as detection guesses), or one per kind of thing when only one team
  is open. Kinds are frame and structure, services, and equipment and other: the palletising cell gets those three.
- **Checks:** hard between every pair of groups and within each, with Site off.
- **Who moves:** structure stays, then architecture and site, and services move.

At L3 Balanced this is what ORCA checks without requirements. That is the invariant, and it is tested: on the
fixtures, and measured on Northbank (464 = 464) and the cell (107 = 107, the same pairs).

## Level × strictness → numbers

Level and strictness only ever become numbers, through the tables in `requirements.py` (`resolve`). The UI shows the
server's numbers. The level names fit any industry; the hints are rough equivalents.

| Level | Meaning | Hints | Tolerance | Smallest element | Services ↔ structure | Edits |
|---|---|---|---|---|---|---|
| L1 Concept | Massing and zones | RIBA 2, LOD 100, Concept | 50 mm | 300 mm | — | whole moves |
| L2 Developed | Main systems and primary structure | RIBA 3, LOD 200, EVT | 10 mm | 100 mm | — | any |
| L3 Coordinated | Everything at its real size and place | RIBA 4, LOD 300, DVT | 1 mm | — | — | any |
| L4 Production | Ready to fabricate and install | RIBA 5, LOD 400, PVT | 1 mm | — | 25 mm | any |
| L5 As-built | A record of what was built | RIBA 6-7, LOD 500, In service | 1 mm | — | 25 mm | none: Muse recommends |

| Strictness | Tolerance × | Clearances × | Smallest × | Fix clearance | Largest move | Trims | Triage when unsure | Low-confidence "by design" |
|---|---|---|---|---|---|---|---|---|
| Lenient | 10 | 0 (hard only) | 2 | 10 mm | — | yes | by design | trusted |
| Relaxed | 4 | 0.5 | 1.5 | 15 mm | — | yes | by design | trusted |
| **Balanced** | 1 | 1 | 1 | **25 mm** | — | yes | no lean | trusted |
| Strict | 0.5 | 1 | 0.5 | 40 mm | 400 mm | within one model only | real | under 0.6 → real |
| Exacting | 0.25 | 1.5 | 0 | 50 mm | 300 mm | no | real | under 0.8 → real |

- **Limits:** the tolerance is kept between 1 and 200 mm. A mover row's limit applies on top: the stricter one wins.
- **One scale for flagging and fixing:** strict flags more and fixes cautiously (more clearance, smaller moves, no
  trims); lenient flags less and allows bolder fixes.
- **The overlay:** "Low-confidence by design" (`overlay`) is deterministic given the model's answer. Under Strict a
  model "by design" below 0.6 confidence becomes "real" for a person to check, with `basis: strictness` and the
  model's verdict kept.

## How it compiles

- **Detection** (`compile_tests`):
  - every check that is not off becomes a `detect.Test`, with ids `req:a|b` and `req:a`;
  - each one gets the resolved tolerance, clearance and `min_size_m` (new: elements whose largest box side is under it
    are left out), and the four rules;
  - a hard check between services and structure keeps the level's clearance (L4 and L5);
  - a rerun compares with the last run only under the same requirements (other tests, other ids).
- **Triage:**
  - **Order of settling:** what the open model settles (same element), then the sure rules (not physical, a touch),
    then a by-design rule (`settle`, `basis: requirement`, the model's earlier reading kept), then the model.
  - **Job keys:** a run is keyed by the report, `model_key` (what changes the prompt: level, strictness, triage
    guidance, clearance checks) and `rules_key`.
  - **A rule added or removed** starts a run under the new rules from the last run's readings: free, asking only
    what the rules no longer settle.
  - **A run under another prompt** is shown "stale" until triage runs again, with the rules now in force already
    applied.
- **Fixes** (`Workspace.fix_settings`):
  - the clearance a fix must keep is the strictness's, or the pair's clearance check when larger;
  - who may be edited and how (`policy`: the level's ceiling, strictness, the group's mover row, the stricter wins);
  - the prompt lines, and recommend mode when neither side may be edited;
  - single proposals, plans and root causes all use it;
  - the context path (`context_eval`) keeps a never-edited group fixed.
- **Reports:** the PDF's cover and BCF comments say "Checked against *name* v*n*, L4 Production · Strict (*id*)",
  the clearance sentence uses the required clearance, and an appendix lists the whole file. A recommendation
  appears on its clash's page as "Recommended for the designer · not edited".

## How a page uses it

- `POST /api/requirements` registers a file. It is content-addressed: the id is a hash of the normalised file, kept
  in memory (500 most recent).
- **The header:** the page sends the id as `X-Sightline-Requirements` with every call. The middleware puts the file in
  a context variable that `owner.spawn` and `owner.submit` carry into workers. An id the server has forgotten (a
  restart) answers 409 `requirements_unknown`, and the page registers the file again and retries (`api.ts` `send`).
- **Endpoints:**
  - `GET /api/requirements/scale`;
  - `GET /api/scenes/{sid}/requirements/default`: the starting point and the inventory;
  - `POST .../requirements/suggest`: the Muse draft, one proposal;
  - `POST .../requirements/preview`: counts with the file and with ORCA's defaults, by running detection without
    keeping it. Cached per file; caps `SIGHTLINE_REQUIREMENTS_PER_HOUR` / `SIGHTLINE_PREVIEW_PER_HOUR`.
- **Agent links** carry the page's id (set by its context PUT), so an MCP agent works under the same requirements.
- **The browser** keeps the file and whether it is in use (`sightline.requirements`). Download and Upload make it a
  file to reuse. Accounts come later.

## Not yet

- Requirements per element (by GlobalId).
- Importing Navisworks clash-test definitions.
- A tour act.
- STEP part groups as selectors.
- Requirements on the chat's own words ("use strict").
