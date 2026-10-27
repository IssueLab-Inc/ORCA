# Day-1 spikes

Four questions that decide whether the plan holds. Run them against Northbank on Oct 27.

| # | Question | How | Pass |
|---|---|---|---|
| 1 | Does the browser load Northbank and stay smooth? | Put the Northbank IFCs in `samples/`, run the app, open each model. The top bar shows elements, triangles, parse time and fps. | Each model opens in under ~20 s; orbit stays above ~30 fps |
| 2 | Does IfcOpenShell move an element and write a valid IFC? | `uv run python ../spikes/02_move_and_check.py ../samples/<model>.ifc` to list candidates, then again with a GlobalId and `--dz -0.25` | The `.spike.ifc` reopens with the element moved (also open it in the app or Navisworks) |
| 3 | Is the geometry check fast enough? | Same script: it times the check before and after the move | A few seconds at most per check. If slower: limit the check to a neighbourhood box (planned) |
| 4 | Does Muse Spark return a usable proposal? | Set `META_*` in your shell, then `uv run python ../spikes/04_muse_proposal.py A.png B.png C.png --a "..." --b "..." --distance-mm -94.8 --runs 3` | Valid JSON every run, sensible moves, an understanding you would sign off |

Already run on the synthetic test model (Oct 27): spikes 2 and 3 pass (the check takes milliseconds);
the app loads it in a headless browser, previews a 0.8 m drop and the server reports +100.0 mm clearance.
Northbank is the real test.
