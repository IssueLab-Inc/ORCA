"""ORCA detection against Navisworks on Northbank (docs/detection.md, "How we know it works").

Navisworks ran 1,275 automatic class-pair tests on Northbank and stored 7,668 results; the three-view package samples
up to 5 per test with pictures (317). This eval:
  1. runs ORCA's default tests (every pair of models, each model against itself, duplicates; hard, 1 mm) and times
     them;
  2. takes every sampled Navisworks result and says whether ORCA reports the same pair, and if not, why: a side that
     is not physical (port, space, opening), one element on both sides, a touch, a pair meant to meet (joined by ports,
     one assembly, a door in its wall), or ORCA measuring no overlap;
  3. checks the answer key (#042, #057, #061 on the Level 02 transfer girder);
  4. lines up Navisworks' stored counts with ORCA's per pair of disciplines (Navisworks also counts ports, spaces
     and sub-objects, so these are context, not a score).

    cd server
    uv run python ../evals/detection_navisworks.py --out ../evals/runs/<date>-northbank-detection
"""
from __future__ import annotations

import argparse
import os
import collections
import csv
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A clone of IssueLab's demo-models repo (CLAUDE.md, "Demo data"): $DEMO_MODELS, else ../demo-models.
DEMO = Path(os.environ.get("DEMO_MODELS", ROOT.parent / "demo-models"))
sys.path.insert(0, str(ROOT / "server"))

from sightline import detect, reports  # noqa: E402
from sightline.service import Workspace  # noqa: E402

MODELS = ["Northbank-Structure.ifc", "Northbank-MEP.ifc", "Northbank-Architecture.ifc", "Northbank-Site.ifc"]
NON_PHYSICAL = {"IfcSpace", "IfcDistributionPort", "IfcOpeningElement", "IfcVirtualElement", "IfcZone"}
TOUCH_M = 0.001
GIRDER = "1eVHoPtl1IhAbbhivqVqb0"
ANSWER_KEY = {"2AbvqKF25LGeR0M34N_jld": "#042", "3tQ7zxxRDMefPXL6hbHmO2": "#057", "1RHD_I4ibLDuUhW1LBAckc": "#061"}
TEST = re.compile(r"^(\w+) \((\w+)\) vs (\w+) \((\w+)\)$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, default=ROOT / "samples/reports/northbank-navisworks")
    ap.add_argument("--models", type=Path, default=ROOT / "samples")
    ap.add_argument("--manifest", type=Path, default=None, help="manifest.json with every test's stored count")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    ws = Workspace(samples=args.models)
    sid = ws.open(MODELS)
    scene = ws.scene(sid)
    t0 = time.perf_counter()
    run = detect.run(scene)
    elapsed = time.perf_counter() - t0
    found = {frozenset((c.a.global_id, c.b.global_id)): c for c in run.report.clashes}
    ix = detect._Index(scene)

    nav = reports.load("nav", args.package, [args.package / "sampled-clashes.xml"], "Navisworks")
    ws.reports[nav.id] = nav
    matches = ws.match(nav.id, sid)

    def why_not(a: str, b: str) -> tuple[str, float | None]:
        """Why ORCA does not report a pair Navisworks did: measured on its own, at tolerance 0."""
        rule = ix.excluded_by(a, b, {r: True for r in detect.RULES})
        if rule:
            return f"meant to meet: {detect.RULE_LABEL[rule]}", None
        pair = detect.Test(id="pair", name="pair", a=detect.Selection(ids=[a]), b=detect.Selection(ids=[b]),
                           tolerance_m=0.0)
        hit = detect.run(scene, [pair]).report.clashes
        if not hit:
            return "ORCA measures no overlap", None
        depth = -hit[0].distance_m
        if depth <= TOUCH_M:
            return "touch at 1 mm (ORCA)", depth
        return "missed", depth

    rows = []
    for c in nav.clashes:
        m = matches.get(c.id) or {}
        a, b = (m.get("show") or [m.get("a"), m.get("b")])[:2]
        nav_mm = None if c.distance_m is None else round(c.distance_m * 1000, 1)
        row = {"test": c.test, "clash": c.ref, "a": c.a.name, "a_class": c.a.ifc_class, "b": c.b.name,
               "b_class": c.b.ifc_class, "navisworks_mm": nav_mm, "tolerance_mm": round((c.tolerance_m or 0) * 1000, 1)}
        if c.a.ifc_class in NON_PHYSICAL or c.b.ifc_class in NON_PHYSICAL:
            row["outcome"] = "not physical (never reported)"
        elif not a or not b:
            row["outcome"] = "not in the open models"
        elif a == b:
            row["outcome"] = "one element on both sides"
        elif frozenset((a, b)) in found:
            s = found[frozenset((a, b))]
            row |= {"outcome": "found", "sightline_mm": round(s.distance_m * 1000, 1), "sightline_test": s.test}
        elif c.distance_m is not None and abs(c.distance_m) <= TOUCH_M:
            row["outcome"] = "touch at 1 mm (Navisworks)"
        else:
            reason, depth = why_not(a, b)
            row["outcome"] = reason
            if depth is not None:
                row["sightline_mm"] = round(-depth * 1000, 1)
        rows.append(row)

    outcomes = collections.Counter(r["outcome"] for r in rows)
    physical = [r for r in rows if r["outcome"] not in ("not physical (never reported)", "one element on both sides",
                                                          "not in the open models")]
    overlapping = [r for r in physical if r["outcome"] not in ("touch at 1 mm (Navisworks)", "touch at 1 mm (ORCA)")
                   and not r["outcome"].startswith("meant to meet")]
    recall = sum(r["outcome"] == "found" for r in overlapping)

    key = {}
    for gid, label in ANSWER_KEY.items():
        c = found.get(frozenset((gid, GIRDER)))
        nav_has = any({m.get("a"), m.get("b")} == {gid, GIRDER} for m in matches.values())
        key[label] = {"sightline_mm": None if c is None else round(c.distance_m * 1000, 1),
                      "test": None if c is None else c.test, "navisworks_sampled": nav_has}

    # Navisworks' stored counts per pair of disciplines, against ORCA's per pair of model files.
    team = dict(zip(ix.names, ix.teams))
    by_disc_s = collections.Counter()
    for c in run.report.clashes:
        by_disc_s[tuple(sorted((team[c.a.file], team[c.b.file])))] += 1
    by_disc_n = collections.Counter()
    nonphys_stored = total_stored = 0
    manifest = args.manifest or next(iter(sorted((DEMO / "northbank/StructuredOutputs")
                                                  .glob("*/manifest.json"))), None)
    if manifest and manifest.exists():
        for t in json.loads(manifest.read_text())["tests"]:
            m = TEST.match(t["testName"])
            if m and t.get("storedResults"):
                total_stored += t["storedResults"]
                if {m.group(1), m.group(3)} & NON_PHYSICAL:
                    nonphys_stored += t["storedResults"]
                    continue
                by_disc_n[tuple(sorted((m.group(2), m.group(4))))] += t["storedResults"]

    with (args.out / "pairs.csv").open("w", newline="") as f:
        cols = ["test", "clash", "a", "a_class", "b", "b_class", "navisworks_mm", "tolerance_mm", "outcome",
                "sightline_mm", "sightline_test"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    with (args.out / "coverage.json").open("w") as f:
        json.dump({"seconds": round(elapsed, 2), "elements": run.elements, "clashes": len(run.report.clashes),
                   "coverage": [c.__dict__ for c in run.coverage], "answer_key": key,
                   "outcomes": outcomes, "recall": [recall, len(overlapping)]}, f, indent=1)

    lines = [
        "# ORCA detection vs Navisworks, Northbank", "",
        f"ORCA's default tests (hard, 1 mm) on {run.elements} elements in {len(MODELS)} models: "
        f"**{len(run.report.clashes)} clashes in {elapsed:.1f} s** (from opening the models: element boxes, "
        "triangle tree, all tests).", "",
        "| Test | Elements A | Elements B | Pairs checked | Clashes | Touching | Meant to meet | Seconds |",
        "|---|---|---|---|---|---|---|---|",
        *[f"| {c.name} | {c.elements_a} | {c.elements_b} | {c.candidate_pairs} | {c.clashes} | {c.touching} | "
          f"{', '.join(f'{v} {detect.RULE_LABEL[k]}' for k, v in c.excluded.items()) or '0'} | {c.seconds} |"
          for c in run.coverage], "",
        "## Answer key", "",
        "| | ORCA | Test | In Navisworks' sample |", "|---|---|---|---|",
        *[f"| {k} | {v['sightline_mm']} mm | {v['test']} | {'yes' if v['navisworks_sampled'] else 'no'} |"
          for k, v in key.items()], "",
        f"## The {len(rows)} sampled Navisworks results", "",
        f"Of the {len(overlapping)} that are physical, on two elements and overlap deeper than 1 mm in Navisworks and "
        f"ORCA and are not meant to meet, ORCA reports **{recall}**.", "",
        "| Outcome | Results |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in outcomes.most_common()], "",
    ]
    missed = [r for r in rows if r["outcome"] == "missed"]
    if missed:
        lines += ["### Missed", "", "| Test | A | B | Navisworks mm | ORCA mm (tolerance 0) |", "|---|---|---|---|---|",
                  *[f"| {r['test']} | {r['a']} | {r['b']} | {r['navisworks_mm']} | {r.get('sightline_mm')} |" for r in missed], ""]
    if by_disc_n:
        lines += ["## Counts per pair of disciplines", "",
                  "Navisworks' stored results include ports, spaces and sub-objects of one element, and one element pair "
                  "can give several results; ORCA reports each physical element pair once. Context, not a score.", "",
                  f"Navisworks stored {total_stored} results; {nonphys_stored} of them are in tests of a space, port or "
                  "opening, which ORCA never reports. The rest, by pair of disciplines (still including touches, "
                  "one element's own parts and repeated pairs):", "",
                  "| Disciplines | Navisworks stored | ORCA |", "|---|---|---|",
                  *[f"| {' / '.join(k)} | {by_disc_n.get(k, 0)} | {by_disc_s.get(k, 0)} |"
                    for k in sorted(set(by_disc_n) | set(by_disc_s))], ""]
    (args.out / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
