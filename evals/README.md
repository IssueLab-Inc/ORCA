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

Details of the first runs: `spikes/README.md`, "Spike 4 on #042".
