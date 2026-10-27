"""Propose fixes for the Northbank answer key with Muse Spark and append one row per call to results.csv.

    cd server
    uv run python ../evals/answer_key.py --runs 1            # #042, #057, #061
    uv run python ../evals/answer_key.py --clash '#057' --no-images

Images come from the Navisworks sample report in samples/reports/northbank-navisworks when it has the clash
(#042 and #057; Navisworks reported no pipe-vs-beam results, so #061 runs on text alone).
"""
from __future__ import annotations

import argparse
import csv
import datetime
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from sightline import agent, reports  # noqa: E402
from sightline.meta_client import MetaChatModel  # noqa: E402
from sightline.scene import IfcScene  # noqa: E402

GIRDER = "1eVHoPtl1IhAbbhivqVqb0"
KEY = {  # label: (service GlobalId, Rev04's fix as offset dz)
    "#042": ("2AbvqKF25LGeR0M34N_jld", 0.40),
    "#057": ("3tQ7zxxRDMefPXL6hbHmO2", 0.25),
    "#061": ("1RHD_I4ibLDuUhW1LBAckc", 0.28),
}
SAMPLES = ROOT / "samples"


def images_for(service: str) -> list[Path]:
    folder = SAMPLES / "reports" / "northbank-navisworks"
    if not folder.is_dir():
        return []
    report = reports.load("eval", folder, list(folder.glob("*.xml")), "northbank")
    for c in report.clashes:
        if {c.a.global_id, c.b.global_id} == {GIRDER, service} and len(c.images) == 3:
            return [p for _, p in c.images]
    return []


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--clash", action="append", choices=list(KEY))
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--no-images", action="store_true")
    args = p.parse_args()

    scene = IfcScene([SAMPLES / f"Northbank-{n}.ifc" for n in ("Structure", "MEP", "Architecture")])
    scene.bounds()
    model = MetaChatModel(timeout_s=240)
    out = ROOT / "evals" / "results.csv"
    for label in args.clash or list(KEY):
        service, ref_dz = KEY[label]
        pics = [] if args.no_images else images_for(service)
        for run in range(1, args.runs + 1):
            t = time.perf_counter()
            result = agent.resolve(scene, agent.Clash(GIRDER, service, images=pics), model, max_rounds=1, want=3)
            latency = time.perf_counter() - t
            first = result.attempts[0] if result.attempts else None
            top = result.options[0] if result.options else None
            kinds = sorted({a.kind for a in result.attempts})
            def describe(a) -> str:
                return f"offset {a.split_m} {a.delta_m[2]:+.2f}" if a.kind == "offset" else f"move {a.delta_m}"
            notes = (f"first: {first.title} ({describe(first)}){'' if first.passed else ', ' + first.reason}"
                     if first else "no candidates")
            row = [datetime.date.today().isoformat(), "northbank-rev03", label, model.model, "ABC" if pics else "none",
                   run, f"{latency:.1f}", len(result.attempts), sum(a.passed for a in result.attempts),
                   "yes" if first and first.passed else "no",
                   ",".join(f"{v:g}" for v in first.delta_m) if first else "",
                   f"{top.min_clearance_m * 1000:.0f}" if top and top.min_clearance_m is not None else "",
                   f"0,0,{ref_dz:g} (offset)", f"kinds {'+'.join(kinds)}; {notes}"]
            with out.open("a", newline="") as f:
                csv.writer(f).writerow(row)
            print(label, run, f"{latency:.0f}s", f"{row[8]}/{row[7]} pass", notes, flush=True)
            for a in result.attempts:
                print("   ", "PASS" if a.passed else "fail", a.title, describe(a), a.reason[:90])


if __name__ == "__main__":
    main()
