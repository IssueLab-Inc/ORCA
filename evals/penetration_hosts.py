"""Which hosts may take an opening for a service: Muse's readings of labelled hosts, from Northbank and the PC-03
cell, scored against what a coordinator would say. Appends one row per host to penetration_hosts.csv.

    cd server
    uv run python ../evals/penetration_hosts.py

Hosts a hard rule settles (columns, glazing, equipment, zones, a transfer girder) are read by no model; they are
scored too, so a change in the rules shows. Each kind of host is read once (`hosts.read`), all in one call.
"""
from __future__ import annotations

import csv
import datetime
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from sightline import hosts  # noqa: E402
from sightline.meta_client import triage_model  # noqa: E402
from sightline.scene import IfcScene  # noqa: E402

ANY = None
# (case, model set, host name starts with, verdicts accepted, reviewers accepted (None: any), fit expected (None: any))
CASES = [
    ("core-wall", "northbank", "Core wall - lift / riser", {"with_review"}, {"structure"}, "annular"),
    ("external-wall", "northbank", "External wall W - rainscreen", {"with_review"}, {"architecture"}, "annular"),
    ("glazed-partition", "northbank", "Meeting room glazed partition", {"not_advised", "never"}, ANY, ANY),
    ("floor-slab", "northbank", "Composite floor slab 150", {"with_review"}, {"structure"}, "annular"),
    ("ground-slab", "northbank", "Ground bearing slab 250", {"with_review", "allowed"}, ANY, "annular"),
    ("lift-pit-wall", "northbank", "Lift pit wall 200", {"not_advised", "with_review"}, ANY, ANY),
    ("secondary-beam", "northbank", "UB 356x171x45 - secondary", {"with_review", "not_advised"}, {"structure"}, ANY),
    ("primary-beam", "northbank", "UB 457x191x67 - grid A", {"with_review", "not_advised", "never"}, {"structure"}, ANY),
    ("transfer-girder", "northbank", "Transfer plate girder", {"never"}, ANY, ANY),
    ("column", "northbank", "UC 254x254x89", {"never"}, ANY, ANY),
    ("base-plate", "northbank", "Base plate 450x450x30", {"never", "not_advised"}, ANY, ANY),
    ("bearing-stiffener", "northbank", "Bearing stiffener", {"never", "not_advised"}, ANY, ANY),
    ("mullion", "northbank", "Mullion 60x120", {"never", "not_advised"}, ANY, ANY),
    ("vision-glazing", "northbank", "Vision glazing unit", {"never"}, ANY, ANY),
    ("spandrel-panel", "northbank", "Insulated spandrel panel", {"never"}, ANY, ANY),   # its material: opaque glass
    ("suspended-ceiling", "northbank", "Suspended ceiling 600x600", {"allowed", "with_review"}, ANY, ANY),
    ("plant-wall", "cell", "Plant 2 west wall 200 blockwork", {"allowed", "with_review"}, ANY, "annular"),
    ("cell-floor", "cell", "Production floor slab 200", {"with_review", "allowed"}, ANY, "annular"),
    ("gland-plate", "cell", "EP-301 top gland plate", {"allowed", "with_review"}, ANY, "fitted"),
    ("guard-panel", "cell", "Mesh guard panel", {"not_advised", "never", "with_review"}, {"safety"}, ANY),
    ("fence-post", "cell", "Fence post W5", {"not_advised", "never"}, ANY, ANY),
    ("conveyor-rail", "cell", "CV-301 side rail north", {"not_advised", "never"}, ANY, ANY),
    ("mcc", "cell", "EP-301 Line 3 motor control centre", {"never"}, ANY, ANY),
    ("light-curtain", "cell", "Light curtain", {"never"}, ANY, ANY),
    ("robot-space", "cell", "R1 restricted space", {"never"}, ANY, ANY),
]
SETS = {"northbank": [f"Northbank-{n}.ifc" for n in ("Structure", "Architecture", "MEP")],
        "cell": ["PC-03-Palletising-Cell-RevA.ifc"]}


def main() -> None:
    samples = ROOT / "samples"
    scenes = {k: IfcScene([samples / f for f in files]) for k, files in SETS.items()}
    found = {}
    for case, which, name, *_ in CASES:
        s = scenes[which]
        gid = next((p.GlobalId for p in s.products() if (p.Name or "").startswith(name)), None)
        if gid is None:
            sys.exit(f"{case}: no host named '{name}' in {which}")
        found[case] = (s, gid)
    model, info = triage_model()
    profiles = {case: hosts.profile(s, g) for case, (s, g) in found.items() if not hosts.hard_rule(s, g)}
    t0 = time.perf_counter()
    hosts.read(model, list(profiles.values()))
    seconds = time.perf_counter() - t0
    rows, good = [], 0
    for case, which, name, verdicts, reviewers, fit in CASES:
        s, g = found[case]
        r = hosts.decide(s, g)
        ok = r.verdict in verdicts and (reviewers is None or r.verdict in ("never", "not_advised")
                                        or r.reviewer in reviewers) and (fit is None or r.refuses or r.fit == fit)
        good += ok
        rows.append({"date": datetime.date.today().isoformat(), "case": case, "host": name, "model": info["model"],
                     "source": r.source, "verdict": r.verdict, "reviewer": r.reviewer or "", "fit": r.fit,
                     "limits": json.dumps(r.limits, sort_keys=True), "ok": "yes" if ok else "no",
                     "seconds": round(seconds, 1) if r.source == "muse" else 0, "reasoning": r.reasoning})
        print(f"{'ok ' if ok else 'BAD'} {case:18} {r.source:8} {r.verdict:12} {r.reviewer or '-':12} {r.fit:8} "
              f"{hosts.reading_text(r)[:90]}")
    print(f"{good}/{len(CASES)} as expected; {len(profiles)} kinds read in {seconds:.1f} s on {info['model']}")
    out = ROOT / "evals" / "penetration_hosts.csv"
    new = not out.exists()
    with out.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new:
            w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
