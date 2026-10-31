# ORCA detection: design

ORCA finds clashes itself, in the models that are open, and hands them to everything else: the list, triage,
insights, root causes, plans, chat, the PDF and BCF, and export. This is the main way in (Oct 28): the demo opens the
models and runs it, and the header's **Coordinate** menu leads with **Check the open models**. Importing a Navisworks
report is the second way, for teams that already run it. Detection matters most for models no one runs Navisworks on,
such as a machine cell from mechanical CAD.

In the product the job is **design coordination** (the card is "Coordinate the models", a run's report is "Coordination ·
4 models", the PDF is a "Design coordination report"); a single item is still a **clash**, and one it finds is **found
by ORCA**. It is new work, written
for ORCA during the event.

## What we measured first (Oct 28)

- **Navisworks on Northbank** (the three-view package in `samples/reports/northbank-navisworks/`):
  - 1,275 automatic class-pair tests, of which 73 had results, 7,668 stored results in all. 317 were sampled with pictures.
  - Tolerances vary per test, from 0 to 50 mm. The test names' "IfcProject" means "any element of that model".
  - No result for the cold-water main through the transfer girder (#061), although it runs 400 mm into it.
- **Our verifiers** (`verify_northbank.py`) only ran cross-model tests, so they never saw about 17 real problems inside
  the Structure model (pad footing B1 into the lift-pit wall, base plates buried in ground beams, crossing braces).
- **IfcOpenShell 0.9 on Northbank** (1,961 physical elements in four files):

  | Step | Time / count |
  |---|---|
  | Element boxes (`IfcScene.bounds()`) | 5.7 s |
  | Building the triangle tree (multi-threaded iterator) | 5.0 s |
  | All-vs-all intersection query, 1 mm | 0.3 s, 548 pairs |
  | All-vs-all collision query (no touching) | 0.1 s, 638 pairs (94 not found by intersection) |
  | Answer key #042, #057, #061 | all three found |

  Each hit carries two witness points, `p1` and `p2`, so every clash gets a point.

Lessons we take from elsewhere:
- **Large coordinates.** The tree's intersection query silently drops real overlaps a few hundred metres from its
  origin.
- **Flush faces.** Two solids that share a face plane can overlap without the intersection query noticing. The
  collision query sees them, but gives no depth.
- **Box framing.** A picture framed on the union of both elements' boxes shows a distant model with no clash in sight:
  frame where they meet.
- **Absence.** A clash missing from a new run is resolved only if both elements were still checked against each other.

## 1. Clash tests

A test is one question about the models:

| Field | Meaning |
|---|---|
| `id`, `name` | Stable key and the name shown ("Structure vs MEP") |
| `kind` | `hard` (things overlap), `clearance` (closer than a distance) or `duplicate` (the same thing twice) |
| `a`, `b` | Selections. `b = self` checks A against itself |
| `tolerance_m` | Hard: an overlap must be deeper than this. Default **1 mm** |
| `clearance_m` | Clearance: report gaps smaller than this |
| `rules` | Which "never a clash" rules apply (section 2). All on by default |

A **selection** picks elements by model file, by discipline (the team guessed per file from its contents, as the PDF
report does), by IFC class (include or exclude), by system, by GlobalId, or by a **filter** (Oct 31, owner request):
`{when: [conditions], invert}` as the Filters panel writes them, found against the filters' index when the run starts
(`facets.found`), so a rerun after a kept fix selects by properties again ([filters.md](filters.md), "Checks").

**A check on filters** is one test: side A a filter, side B a filter, everything (`{}`) or itself (`null`). It needs no
id: `Test.from_dict` gives it `filter:` and a hash of what it compares (its sides and kind, written one way only, so
the same filter in another order is the same check; not its name or tolerance), and a name from its sides
("DuctSegment vs Everything", "… (within)", ", 50 mm clearance"). An element on both sides is never paired with itself,
and each pair is measured once.

**Default tests** for the open models:
- every pair of model files, hard, 1 mm: "Structure vs MEP", "Architecture vs Structure", …;
- each model against itself, hard, 1 mm: "Structure (within)";
- "Duplicates (all models)".

A site model (its team guessed as Site: terrain, paving, planting) is context for the building, so its tests are listed
but off by default, and duplicates cover the building models only (owner decision, Oct 28). On Northbank that leaves
Structure, MEP and Architecture: 1,732 elements, 464 clashes, about 4 s. A run's title and element count say what was
checked ("Coordination · 3 models").

A one-file model (a machine cell) therefore gets its within-model test and duplicates. A clearance preset ("MEP vs
Structure, 25 mm") is offered but not run by default.

## 2. What is never a clash

Each rule is applied before measuring, **counted**, and shown with the results, so nothing disappears silently. A test
can switch any rule off.

| Rule | What it removes |
|---|---|
| Not physical | Openings and other feature elements, virtual elements, spaces and zones, ports, grids, annotations, anything without a body |
| Same element | Both sides are one element, also after a port is replaced by the element that owns it |
| Connected | Neighbours joined port to port (`IfcRelConnectsPorts`): a pipe and its fitting are meant to meet |
| One assembly | Parent and child, or two parts, of one aggregate or nest: a curtain wall's panels, a stair's flights |
| Host and filler | A door or window and the wall it fills (`IfcRelFillsElement` through the wall's opening) |
| Touching | Overlap no deeper than the tolerance: counted as touching, never reported as a clash |

Everything else is reported, including bolts in plates and beams running into columns. Those are real overlaps that
designers often accept; triage, insights ("11× Mechanical fastener with Plate") and **Mark as not a clash** already
sort them, and keeping that policy visible is better than hiding it in the engine.

## 3. The engine

1. **Element boxes.** `IfcScene.bounds()` already caches a world box per physical element when the models open.
2. **Broad phase.** A sort and sweep over the boxes, grown by the tolerance or clearance, gives the candidate pairs for
   each test. This is the completeness argument: a pair whose boxes never come that close cannot clash, so it needs no
   further check. It also gives the coverage count.
3. **Narrow phase.** One triangle tree per run (`ifcopenshell.geom.tree(backend="opencascade.trianglebvh")`) holds every
   element that appears in a candidate pair, from one multi-threaded iterator per file. Per test:
   - **hard:**
     - `clash_intersection_many(check_all=True)` measures the depth.
     - `clash_collision_many(allow_touching=False)` catches the flush-face overlaps the first query misses. Their depth
       is exact for two rectangular solids (separating axes, `verify._rectangular_penetration`), else the boxes' smallest
       overlap.
   - **clearance:** `clash_clearance_many`, skipping pairs that already overlap.
   - **duplicate:** same class, boxes equal within 1 mm, and the two overlap through nearly their whole depth.
4. **Far from the origin.** If the models lie more than 200 m from the origin, all files get the same `model-offset` to
   bring their middle near it (so they stay aligned with each other), and points are moved back afterwards.
5. **One result per pair.** For each unordered pair in a test, the deepest result is kept. A self test never pairs an
   element with itself and never counts a pair twice.
6. **Cap.** At most 5,000 clashes per test. A test that reaches it is marked **partial**, with the advice to narrow it.

**Measures.** `distance_m` is signed: minus the depth for an overlap, the gap for clearance.

**Depth** is how far one element must move to clear the other:
- For two rectangular solids it is exact (separating axes).
- Otherwise it is an estimate: the lesser of the intersection query's figure and how far the two boxes must move
  apart. Moving the boxes apart moves what is inside them apart too, so the box figure never understates.

The query's own figure is not used alone because it is unreliable both ways:
- a pipe half a millimetre into a beam's underside reads 200 mm (the beam's width);
- a top rail 40 mm into a post reads 20 mm.

So ORCA's depth can differ from Navisworks' (#042: ORCA −300 mm, Navisworks −150 mm). The clash panel's "Now"
uses the same measure, so it agrees with the run.

The clash point is the middle of the two witness points, else the middle of the boxes' overlap.

**Flush faces.** Neither triangle query sees two rectangular solids that overlap with every side face flush (a strut
run 30 mm into a beam's end, two panels of one wall lapping, two duct pieces joined port to port). The exact
separating-axis check runs on every pair whose boxes overlap deeper than the tolerance and that both queries missed.

## 4. What a run returns

A run is a clash report like an imported one, so every existing feature works on it unchanged. It differs in four ways:
- **Origin.** It is marked `sightline` rather than `navisworks`, so the wording changes: "Found by ORCA: −300 mm".
- **Stable ids.** A clash's id is `s` plus a hash of its test and the two GlobalIds, sorted. Running again gives the same
  ids, so fixes, reviews and sign-offs stay attached. There are no "Clash 1, 2, …" names. Each clash has a
  number, #N, unique across the whole report and kept across runs (a new clash takes the next number; a resolved one's
  number is never reused). It has a plain name from its two elements at once, and a title Muse writes from its facts
  shortly after ("Cold-water main clips the transfer girder at grid 3, level 02"; `server/sightline/titles.py`).
- **The same clash in another check.** A clash takes the id the last run gave the same pair of the same kind under
  another test (a check on filters finding a pair the full check found), so its #N, title, views, sign-offs and marks
  follow it between the full check and checks on filters.
- **Run diff.** ORCA keeps the last run per set of open models. On the next run each clash is `new` or `active`,
  and a clash that has gone is listed as **resolved** only if both elements were still checked against each other in
  a complete test. If one left the selection (deleted, or the test changed) it is **no longer checked**, which is not
  the same as resolved. **Only like with like:** when the run shares no test with the last one (the full check after a
  check on filters, or the other way round), it says nothing about resolved or no longer checked, and a clash is new
  only if these models never gave it a number (going back to the full check brings its clashes back, not anew).
- **Title.** A run of one check on filters is titled with it: "Coordination · DuctSegment vs Everything".
- **Coverage.** Per test it reports:
  - elements on each side;
  - candidate pairs checked;
  - clashes, and touching pairs;
  - pairs removed by each rule;
  - seconds taken, and whether it was partial.

  The UI and the PDF show this, so a reader can see what was and wasn't checked.

## 5. Pictures

A detected clash has no Navisworks pictures, and nothing needs them. The browser takes the three views the model reads
best (see CLAUDE.md, "Images sent to the model"):

| | Picture |
|---|---|
| A | The pair only, 40% transparent, framed on where they meet |
| B | The pair solid, with grey context within 2.5 m, same camera |
| C | The pair only, about 90° round from A |

ORCA takes the pictures when a clash is opened and before a fix is proposed, and uploads them to the run. The fix
agent, triage of that clash and the PDF then use them like Navisworks pictures.

## 6. How we know it works

- **Unit tests on small synthetic models,** one per rule and measure:
  - overlap; touch at and under 1 mm; flush faces; one element inside another;
  - connected ports; assembly; door in its wall; same element; duplicate; clearance gap;
  - a model 300 m from the origin;
  - self-test pairs counted once; ids stable across runs; resolved vs no longer checked; the cap;
  - the report working with matching, triage rules and patterns.
- **Northbank against Navisworks** (`evals/detection_navisworks.py`):
  - run Navisworks' own 73 tests (class pairs and tolerances read from the package);
  - compare the counts per test;
  - check how many of the 317 sampled clashes ORCA finds, with every miss explained;
  - check the answer key, including #061.
- **The palletising cell** (the demo-models repo's `palletising-cell/`):
  - Rev A: all 13 planted pairs found, and everything else is one of the cell's by-design contacts.
  - Rev B: none of the planted pairs.
  - Compare with Navisworks once that run exists.
- **In the browser:** open Northbank → Detect → triage → fix #061 → Detect again → #061 resolved.
- **Speed target:** a default run on Northbank in under 30 s, with the measured number recorded in CLAUDE.md.

## Results (Oct 28)

| | Result |
|---|---|
| Northbank, default tests (`evals/runs/2026-10-28-northbank-detection/`) | 633 clashes in 1,961 elements in 7-12 s; 0 between models except the 3 girder clashes; 449 inside Structure, 169 inside Site, 12 inside Architecture |
| Sampled Navisworks results ORCA reports | **117 of 117** that are physical, on two elements, deeper than 1 mm and not meant to meet; of the other 200: 129 not physical, 46 touches, 24 one element, 1 joined by ports |
| Answer key | #042 −300 mm, #057 −100 mm, #061 −77 mm, all in "MEP vs Structure"; Navisworks stored no result for #061 |
| Palletising cell (`evals/runs/2026-10-28-cell-detection/`) | Rev A: 13/13 planted pairs, 94 by design, 0 unexpected; Rev B: 0 planted, 92 by design, 0 unexpected; 0.6 s each |

## Not in this version

- Tests saved with a project, and run history beyond the last run (this belongs with saving state).
- Splitting very large federations into local cells. Northbank and the cell fit in one tree; the far-from-origin offset
  covers the coordinate trap.
- Detection on STEP models directly. STEP arrives as IFC (the cell is generated both ways), so it is detected like any IFC.
