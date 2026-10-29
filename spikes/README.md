# Day-1 spikes

Four questions that decide whether the plan holds. Run them against Northbank on Oct 27.

| # | Question | How | Pass |
|---|---|---|---|
| 1 | Does the browser load Northbank and stay smooth? | Put the Northbank IFCs in `samples/`, run the app, open each model. The top bar shows elements, triangles, parse time and fps. | Each model opens in under ~20 s; orbit stays above ~30 fps |
| 2 | Does IfcOpenShell move an element and write a valid IFC? | `uv run python ../spikes/02_move_and_check.py ../samples/<model>.ifc` to list candidates, then again with a GlobalId and `--dz -0.25` | The `.spike.ifc` reopens with the element moved (also open it in the app or Navisworks) |
| 3 | Is the geometry check fast enough? | Same script: it times the check before and after the move | A few seconds at most per check. If slower: limit the check to a neighbourhood box (planned) |
| 4 | Does Muse Spark return a usable proposal? | Set `META_*` in your shell, then `uv run python ../spikes/04_muse_proposal.py A.png B.png C.png --a "..." --b "..." --distance-mm -94.8 --runs 3` | Valid JSON every run, sensible moves, an understanding you would sign off |

## Results on Northbank (Oct 27, Rev03: Structure + MEP + Architecture, 1,732 physical elements)

| # | Result |
|---|---|
| 1 | **Pass.** Browser parses all three files in 0.8 s (69k triangles); open-to-rendered 6.8 s including the server's one-off 2.9 s geometry cache. fps not measured here (software GL in CI); check on a real GPU. |
| 2 | **Pass.** Elements move, the edited file writes and reopens with the new placement. |
| 3 | **Pass after a fix.** First version took 7.2 s per check (re-triangulating everything). Now a one-off box cache at open, then only the neighbourhood is checked: **0.4–0.6 s per check** (31–64 nearby elements). |
| 4 | **Pass, with images.** `muse-spark-1.3-contributor` at `https://api.meta.ai/v1`: valid JSON on 4/4 calls, 29–42 s each, no client changes needed. Details below. |

Answer key reproduced: #042 duct, #057 tray and #061 cold-water main each hit the transfer girder
(`IfcBeam`, −300 / −400 / −400 mm). Raising the #042 duct 0.40 m passes with exactly **50 mm** all round,
matching the web opening it was meant to pass through.

**Finding: whole-element moves are not enough.** Moving the whole tray or the whole cold-water run fails
everywhere (other ducts along their length; wall openings they pass through). The designer's Rev04 fixes all
three with a **local offset**: split either side of the girder (about x 2.6–4.4 m), raise the middle piece
(duct +400, tray +250, cold water +280 mm) and add short angled pieces with bends. ORCA needs that edit,
and Rev04 is the benchmark to compare its proposals against.

**Finding: the full model hides the clash.** With everything visible, the girder is behind the façade and
slabs. The viewer needs the context-ghost mode (image B) before the demo.

## Spike 4 on #042 (Oct 27)

Inputs: element names, classes, sizes, levels and boxes as text, signed distance −300 mm. Every candidate was then
run through `verify.check` (25 mm clearance) on Structure + MEP + Architecture.

| Run | Images | Top candidate | Verifier | Candidates passing |
|---|---|---|---|---|
| 0 | none | sideways +0.6 m "to the nearest opening" | fail: return-air main −200 mm | 0/4 |
| 1 | A/B/C | raise 0.35 m (+0.05 m Y) into the opening above | fail: 0 mm to the opening sill | 0/4 |
| 2 | A/B/C | raise 0.38 m into the opening above | **pass**, 30 mm | 1/4 |
| 3 | A/B/C | raise 0.38 m into the opening above | **pass**, 30 mm | 1/4 |

- **Images are what make it work.** Text only, it guessed where the openings are and every move hit the
  return-air main, the ceiling, the slab or the girder. With images, all three runs found the opening directly
  above the duct (it shows clearly in the elevation, C) and agreed on the fix direction.
- **Pixels give the direction, not the millimetres.** The designer's answer is +0.40 m (50 mm all round); the model
  said 0.35–0.38. Run 1 would be fixed by the retry loop (it is told it touched the sill). Better: give the opening's
  size and position as text, the same way severity comes from numbers.
- Fallbacks are sensible but all fail on this congested floor (drop → ceiling, over the top → Level 03 slab,
  sideways → return-air main or the girder), which is the case for verifying before showing anything.
- The images were quick matplotlib renders made for this spike (not committed); the product renders A/B/C in
  the browser viewer.
