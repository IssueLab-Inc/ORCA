# Evaluation log

`results.csv` is the running record of how Sightline's proposals score: one row per model call, appended, never
rewritten, so runs on new datasets and new prompts stay comparable with the first ones.

| Column | Meaning |
|---|---|
| `date` | Day of the run |
| `dataset` | Model set and revision, e.g. `northbank-rev03` |
| `clash` | Clash label from the dataset's answer key (`#042`) |
| `model` | Meta model id |
| `images` | `none` or `ABC` (see CLAUDE.md, "Images sent to the model") |
| `run` | Repeat number for the same clash and settings |
| `latency_s` | Wall time of the model call |
| `candidates` / `passing` | Candidates returned / candidates that pass `verify.check` (25 mm clearance) |
| `top1_pass` | Whether the model's first choice passes |
| `top1_delta_m` | First choice as `dx,dy,dz` in metres, Z up |
| `top1_clearance_mm` | Smallest clearance of the first choice, in mm |
| `reference_delta_m` | The dataset's known good fix, when it has one (Northbank: the designer's Rev04) |
| `notes` | What the first choice hit, or what stood out |

Headline numbers to watch: **top-1 pass rate** and **any-candidate pass rate** per dataset, before the retry loop.
The loop's own result (attempts until a verified option) gets its own columns once runs go through `agent.resolve`.

## Summary

| Date | Dataset | Clashes | Images | Calls | Top-1 pass | Any pass | Median latency |
|---|---|---|---|---|---|---|---|
| 2026-10-27 | northbank-rev03 | #042 | none | 1 | 0/1 | 0/1 | 28.8 s |
| 2026-10-27 | northbank-rev03 | #042 | ABC | 3 | 2/3 | 2/3 | 41.2 s |
| 2026-10-27 | northbank-rev03, local offsets, no opening data | #042 #057 #061 | ABC, ABC, none | 3 | 0/3 | 1/3 | 33.7 s |
| 2026-10-27 | northbank-rev03, local offsets + opening data | #042 #057 #061 | ABC, ABC, none | 3 | **3/3** | **3/3** | 34.8 s |
| 2026-10-27 | same, `reasoning_effort=low` | #042 #057 #061 | ABC, ABC, none | 3 | **3/3** | **3/3** | **18.4 s** |

Details of the first runs: `spikes/README.md`, "Spike 4 on #042".

Local offsets (`answer_key.py`, one round each; #061 has no Navisworks images). Rows 5-10 of `results.csv`.
- Without opening data the model offset around the girder, under it (into the ceiling and lights) or over it (into the
  slab): 1 of 13 candidates passed, a whole-run drop on #042.
- With the girder's openings measured on each run's line (`edits.passages`, rays through the obstacle: #042 fits at
  +0.375 to +0.425 m, #057 +0.225 to +0.275, #061 +0.252 to +0.308) the first candidate passed every time, at Rev04's
  own heights: +0.40, +0.25, +0.28 m, with 50/50/53 mm clearance.
- Muse Spark reasons before it answers, and that is most of the wait. `reasoning_effort=low` (now the default,
  `META_REASONING_EFFORT`) gave the same first answers in 15-19 s instead of 29-38 s. A bare prompt measured 58 s
  default, 23 s low, 7 s minimal.

## Triage of Navisworks results

`navisworks_triage.py` sends every clash in a Navisworks three-view sample package (ClashWiseDemoModels,
`northbank/StructuredOutputs/`) to the model with its A/B/C images and metadata, and asks for a verdict
(`real_clash` / `by_design` / `non_physical` / `modelling_error`), severity, owner and action under a strict JSON schema.
There is no human review yet, so it scores against a reference built from metadata only: a space or port on either
side is `non_physical`, a result within 1 mm is a touch (not a real clash), and the answer key must come back as
`real_clash` with the service, not the girder, moving. Each run keeps its replies, `triage.csv` and `summary.md` in
`runs/<date>-<name>/`.

| Date | Model | Package | Clashes | Images | Answer key | Non-physical | Touching | Failed calls | Median latency |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-27 | Muse Spark | Northbank-Demo-Clean, 73 tests × ≤5 | 317 | ABC | 6/6 | 129/129 | 51/55 | 0 | 10.0 s |
| 2026-10-27 | Muse Spark Open (Baseten) | Northbank-Demo-Clean, 73 tests × ≤5 | 317 | ABC | 6/6 | 129/129 | 49/55 | 0 | **6.1 s** |

The app's **Triage all** uses the same prompt, schema and sure rules (`server/sightline/triage.py`). To score the
open-weights model on the same package: `--open` (the app's triage host, needs `TRIAGE_API_KEY` or `BASETEN_API_KEY`),
or `--base-url URL --model NAME --api-key-env VAR [--effort ""]` for any OpenAI-compatible host.

Notes on the first run (`runs/2026-10-27-northbank-nwf-triage/summary.md`):
- The four touch misses: three task-chair parts (base, stem, seat are separate `IfcFurniture`) read as duplicated chairs
  (`modelling_error`), and a 0.5 mm tree canopy over a lighting column read as a real clash. Defensible on the tree,
  wrong on the chairs.
- #061 is not in the package: Navisworks stored no results for any pipe vs beam test.
- Outside the answer key it called 17 more results `real_clash`. They are real overlaps inside the Structure model that
  the answer key does not cover (it lists Structure vs services only): pad footing B1 vs the lift pit wall (−350 to
  −471 mm), column base plates buried 159 mm in ground beams, the grid B beam crossing the core trimmer (−216 mm) mid-span,
  and CHS X-bracing crossing at −9 mm. Checked against the images for the footing: the overlap is real.

Muse Spark Open (`meta-models/muse-spark-open` on Baseten, `runs/2026-10-27-northbank-open-triage/`):
- The host takes strict `json_schema` and the A/B/C images as they are; no `reasoning_effort` sent. 317 calls in 6 min 25 s
  with 8 workers, median 6.1 s (max 26 s) against Muse Spark's 10.0 s (max 56 s). No failed calls.
- Same answer key (6/6, service moves) and non-physical (129/129) scores. Touching 49/55: the tree canopy again, one task
  chair and the tea point counter as duplicates, and three main-entrance door parts as a duplicated door.
- It agrees with Muse Spark on 299 of 317 verdicts. 11 of the 18 differences are by_design → modelling_error (main
  entrance door parts, two beam-to-beam joints at −12 mm, a column in the ground slab). One is a worse call: pad footing
  B1 vs the lift pit wall (−471 mm, confirmed real from the images) came back by_design. Both called the same 20 clashes
  real_clash and agreed on severity for 15.
- Verdicts: by_design 145, non_physical 130, real_clash 21, modelling_error 21 (Muse Spark: 153, 129, 23, 12).

## Not a clash: don't fix

`not_a_clash.py` runs joints inside one model that are built that way, where the geometry check alone would pass a
harmful edit: a ground beam cast into its pad footing (Clash1, pad footing C1 vs ground beam grid C), a curtain-wall
transom into its mullion (Clash7), a steel beam into its column. Scored in `not_a_clash.csv` (append-only): triage's
verdict, the options, whether any option changes what must stay put (the pad, the mullion, the column), and whether
every option is marked model cleanup.

Before Oct 28 the agent offered "trim pad footing edge to ground beam face" (900 mm off an 1800 mm pad, half its
bearing) and it passed the geometry check. Trims now need a slender member (`edits.SLENDER`: length at least 3x its
width across) and a trim inside one model is marked `cleanup`.

| Date | Cases | Triage by design | Touches what must stay | All options model cleanup |
|---|---|---|---|---|
| 2026-10-28 | 3 | 3/3 | 0/3 | 3/3 (one trim each, on the beam, transom, beam) |

## Sightline detection

`detection_navisworks.py` runs Sightline's own detection (`server/sightline/detect.py`, docs/detection.md) on Northbank
and compares it with the Navisworks package. `detection_cell.py` checks it on the palletising cell from
ClashWiseDemoModels, against the cell's generated answer key.

    cd server
    uv run python ../evals/detection_navisworks.py --out ../evals/runs/<date>-northbank-detection
    uv run python ../evals/detection_cell.py --out ../evals/runs/<date>-cell-detection

Results on Oct 28 (`runs/2026-10-28-northbank-detection/`, `runs/2026-10-28-cell-detection/`):

| | Result |
|---|---|
| Northbank, default tests | 633 clashes in 1,961 elements, 7-12 s |
| Sampled Navisworks results Sightline also reports | 117 of 117 real overlaps. The other 200 are 129 not physical, 46 touches, 24 one element, 1 joined by ports |
| Answer key | 3/3, including #061, which Navisworks stored no result for |
| Cell Rev A / Rev B | 13/13 planted pairs and 0 unexpected / 0 planted and 0 unexpected |

The per-discipline counts in `summary.md` are context, not a score. Navisworks stores ports, spaces, sub-objects of one
element and repeated pairs, and 3,100 of its 7,668 stored results are tests of a space, port or opening.

