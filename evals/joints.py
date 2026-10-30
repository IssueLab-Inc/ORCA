"""What moves keep their joints on Northbank (connections.py): a census of dry move plans, no model calls.

For every straight MEP segment's run (connections.run), a move of 100 mm in each of the six directions is planned with
its joints ("carry"): it keeps them (taking fittings along, stretching segments the move runs along), or it is refused,
and why (equipment or a terminal beyond it, a segment too short, a branch, too many parts). Also the answer key's duct
#042 raised 400 mm, which its tees cannot allow as a whole move.

    cd server
    uv run python ../evals/joints.py --out ../evals/runs/<date>-northbank-joints
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
os.environ.setdefault("SIGHTLINE_CONNECTED_MOVES", "carry")

from sightline import connections  # noqa: E402
from sightline.scene import IfcScene  # noqa: E402

DUCT_042 = "2AbvqKF25LGeR0M34N_jld"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=Path, default=ROOT / "samples")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    scene = IfcScene([args.samples / "Northbank-MEP.ifc"])
    scene.bounds()
    runs, seen = [], set()
    for e in scene.model.by_type("IfcFlowSegment"):
        if e.GlobalId in seen or connections.classify(scene, e.GlobalId) != "straight":
            continue
        run = connections.run(scene, e.GlobalId)
        seen.update(run)
        runs.append(run)
    outcomes, carried, times = Counter(), Counter(), []
    for run in runs:
        for name, vec in connections.DIRECTIONS:
            t = time.perf_counter()
            plan = connections.plan_move(scene, run, [v * 0.1 for v in vec])
            times.append(time.perf_counter() - t)
            outcomes["keeps its joints" if plan.ok else f"refused: {plan.code}"] += 1
            if plan.ok:
                carried[min(len(plan.carried), 5)] += 1
    duct = connections.plan_move(scene, connections.run(scene, DUCT_042), [0, 0, 0.4])
    times.sort()
    lines = ["# Northbank: moves with their joints", "",
             f"- {len(runs)} straight runs, 6 directions each ({len(times)} plans), "
             f"median {times[len(times) // 2] * 1000:.0f} ms, slowest {times[-1] * 1000:.0f} ms.", ""]
    lines += [f"- {what}: {n}" for what, n in outcomes.most_common()]
    lines += ["", "Parts taken along by the moves that keep their joints:", ""]
    lines += [f"- {k}{'+' if k == 5 else ''}: {n}" for k, n in sorted(carried.items())]
    lines += ["", f"- #042 raised 400 mm: {'keeps its joints' if duct.ok else duct.refused}."]
    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "README.md").write_text(text)


if __name__ == "__main__":
    main()
