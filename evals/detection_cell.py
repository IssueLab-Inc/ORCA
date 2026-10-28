"""Sightline detection on the PC-03 palletising cell, a machine model (ClashWiseDemoModels `palletising-cell/`).

The cell is generated with an answer key: Rev A has five planted problems (13 part pairs, `verify_cell.PLANTED`) and
Rev B fixes all of them; every other overlap is a contact the cell is built with (`verify_cell.BY_DESIGN`: anchor bolts
in their plates and the floor, the conveyor's drums in its rails, the robot working over the conveyor and pallets).
Sightline's default tests on the one-file model (the model against itself, and duplicates) must find every planted pair
in Rev A, none in Rev B, and nothing that is neither planted nor by design.

    cd server
    uv run python ../evals/detection_cell.py --cell ../../ClashWiseDemoModels/palletising-cell \
        --out ../evals/runs/<date>-cell-detection
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from sightline import detect  # noqa: E402
from sightline.scene import IfcScene  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", type=Path, default=ROOT.parent / "ClashWiseDemoModels/palletising-cell")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(args.cell / "Code"))
    from cellcore import gid  # the cell's GlobalIds come from its part keys
    from celllayout import build
    from verify_cell import PLANTED, by_design

    args.out.mkdir(parents=True, exist_ok=True)
    lines = ["# Sightline detection on the PC-03 palletising cell", ""]
    ok = True
    for rev in ("A", "B"):
        keys = {gid(p.key): p.key for p in build(rev).parts}
        t0 = time.perf_counter()
        run = detect.run(IfcScene(args.cell / "IFC" / f"PC-03-Palletising-Cell-Rev{rev}.ifc"))
        seconds = time.perf_counter() - t0
        found = {frozenset((keys[c.a.global_id], keys[c.b.global_id])): c for c in run.report.clashes}
        planted = {frozenset((a, b)): label for label, a, b in PLANTED}
        hit = {p: label for p, label in planted.items() if p in found}
        unexpected = [sorted(p) for p in found if p not in planted and not by_design(*sorted(p))]
        designed = sum(1 for p in found if p not in planted and by_design(*sorted(p)))
        want = len(planted) if rev == "A" else 0
        good = len(hit) == want and not unexpected
        ok &= good
        lines += [f"## Rev {rev}: {'pass' if good else 'FAIL'}", "",
                  f"{len(run.report.clashes)} clashes in {seconds:.1f} s over {run.elements} parts: "
                  f"{len(hit)} of the {len(planted)} planted pairs (expected {want}), {designed} by design, "
                  f"{len(unexpected)} unexpected.", "",
                  "| Test | Pairs checked | Clashes | Touching | Meant to meet |", "|---|---|---|---|---|",
                  *[f"| {c.name} | {c.candidate_pairs} | {c.clashes} | {c.touching} | "
                    f"{', '.join(f'{v} {detect.RULE_LABEL[k]}' for k, v in c.excluded.items()) or '0'} |"
                    for c in run.coverage], ""]
        if hit:
            lines += ["| Problem | Parts | Sightline mm |", "|---|---|---|",
                      *[f"| {label} | {' × '.join(sorted(p))} | {found[p].distance_m * 1000:.1f} |"
                        for p, label in sorted(hit.items(), key=lambda kv: (kv[1], sorted(kv[0])))], ""]
        lines += [f"Unexpected: {' × '.join(p)}" for p in unexpected]
    (args.out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
