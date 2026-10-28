"""Clashes that should not be "fixed": joints inside one model that are built that way. Appends one row per case to
not_a_clash.csv.

    cd server
    uv run python ../evals/not_a_clash.py

A good answer: triage reads the clash as by design (or not physical); the agent changes nothing it must not (a pad
footing's body, a column), and any trim it offers is on the slender member and marked model cleanup. The geometry check
alone passes all of these, so they test judgement, not geometry.
"""
from __future__ import annotations

import csv
import datetime
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from sightline import agent, triage  # noqa: E402
from sightline.meta_client import MetaChatModel, triage_model  # noqa: E402
from sightline.service import Workspace  # noqa: E402

# (label, A's name, B's name, the element that must not change, why)
CASES = [
    ("pad-footing-ground-beam", "Pad footing 1800x1800x600 - C1", "Ground beam 450x500 - grid C",
     "Pad footing 1800x1800x600 - C1", "a ground beam is cast into its pad footing; cutting the pad halves its bearing"),
    ("transom-mullion", "Transom 60x120", "Mullion 60x120",
     "Mullion 60x120", "a transom stops at its mullion; the mullion runs through"),
    ("beam-column", "UB 457x191x67 - grid 1", "UC 254x254x89 - A1",
     "UC 254x254x89 - A1", "a beam is bolted to its column; the column stays where the grid puts it"),
]


def main() -> None:
    ws = Workspace()
    files = [f for f in ws.list_samples() if f.startswith("Northbank-") and "Rev04" not in f and "Grids" not in f]
    sid = ws.open(files)
    rid = ws.open_report_sample("northbank-navisworks").id
    report = ws.report(rid)
    matches = ws.match(rid, sid)
    scene = ws.scene(sid)
    scene.bounds()
    model = MetaChatModel(timeout_s=240)
    tri_model, tri_info = triage_model()
    out = ROOT / "evals" / "not_a_clash.csv"
    new = not out.exists()
    with out.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "case", "report_clash", "triage_model", "triage_verdict", "fix_model", "latency_s",
                        "options", "touches_fixed_element", "all_cleanup", "options_detail", "advice"])
        for label, a_name, b_name, keep_name, why in CASES:
            c = next((c for c in report.clashes if {c.a.name, c.b.name} == {a_name, b_name}
                      and matches[c.id]["a"] and matches[c.id]["b"]), None)
            if c is None:
                print(label, "not in the report"); continue
            m = matches[c.id]
            keep = next(g for g in (m["a"], m["b"]) if scene.element(g).name == keep_name)
            verdict = triage.triage_one(tri_model, c, images=True).get("verdict")
            started = time.perf_counter()
            result = agent.resolve(scene, ws.clash_for(m["a"], m["b"], c.distance_m, report_id=rid, clash_id=c.id),
                                   model, lock=ws.lock)
            seconds = round(time.perf_counter() - started, 1)
            touches = [o for o in result.options if keep in o.moved]
            detail = "; ".join(f"{o.kind} {scene.element(o.moved[0]).name}{' (cleanup)' if o.cleanup else ''}"
                               for o in result.options)
            row = [datetime.date.today().isoformat(), label, c.ref, tri_info["model"], verdict, model.model, seconds,
                   len(result.options), "yes" if touches else "no",
                   "yes" if result.options and all(o.cleanup for o in result.options) else "no" if result.options else "-",
                   detail, result.advice.replace("\n", " ")[:300]]
            w.writerow(row)
            f.flush()
            print(f"{label}: triage {verdict}; {len(result.options)} option(s): {detail or 'none'}; "
                  f"touches {keep_name}: {'YES' if touches else 'no'} ({why})")


if __name__ == "__main__":
    main()
