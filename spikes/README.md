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
| 4 | Not run yet (needs the Meta API key). |

Answer key reproduced: #042 duct, #057 tray and #061 cold-water main each hit the transfer girder
(`IfcBeam`, −300 / −400 / −400 mm). Raising the #042 duct 0.40 m passes with exactly **50 mm** all round,
matching the web opening it was meant to pass through.

**Finding: whole-element moves are not enough.** Moving the whole tray or the whole cold-water run fails
everywhere (other ducts along their length; wall openings they pass through). The designer's Rev04 fixes all
three with a **local offset**: split either side of the girder (about x 2.6–4.4 m), raise the middle piece
(duct +400, tray +250, cold water +280 mm) and add short angled pieces with bends. Sightline needs that edit,
and Rev04 is the benchmark to compare its proposals against.

**Finding: the full model hides the clash.** With everything visible, the girder is behind the façade and
slabs. The viewer needs the context-ghost mode (image B) before the demo.
