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

| Date | Package | Clashes | Images | Answer key | Non-physical | Touching | Failed calls | Median latency |
|---|---|---|---|---|---|---|---|---|
| 2026-10-27 | Northbank-Demo-Clean, 73 tests × ≤5 | 317 | ABC | 6/6 | 129/129 | 51/55 | 0 | 10.0 s |

The app's **Triage all** uses the same prompt, schema and sure rules (`server/sightline/triage.py`). To score the
open-weights model on the same package: `--open` (the app's triage host, needs `TRIAGE_API_KEY` or `BASETEN_API_KEY`),
or `--base-url URL --model NAME --api-key-env VAR [--effort ""]` for any OpenAI-compatible host. Not run yet: no
open-weights key in the environment on Oct 27.

Notes on the first run (`runs/2026-10-27-northbank-nwf-triage/summary.md`):
- The four touch misses: three task-chair parts (base, stem, seat are separate `IfcFurniture`) read as duplicated chairs
  (`modelling_error`), and a 0.5 mm tree canopy over a lighting column read as a real clash. Defensible on the tree,
  wrong on the chairs.
- #061 is not in the package: Navisworks stored no results for any pipe vs beam test.
- Outside the answer key it called 17 more results `real_clash`. They are real overlaps inside the Structure model that
  the answer key does not cover (it lists Structure vs services only): pad footing B1 vs the lift pit wall (−350 to
  −471 mm), column base plates buried 159 mm in ground beams, the grid B beam crossing the core trimmer (−216 mm) mid-span,
  and CHS X-bracing crossing at −9 mm. Checked against the images for the footing: the overlap is real.
