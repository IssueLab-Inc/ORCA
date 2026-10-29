"""E0 for the second try on Muse Wonder (docs/escalation.md): does Wonder fix clashes Muse Spark cannot, and is it
the model or the brief that does it?

Cases: every planted pair of the PC-03 cell (Rev A, opened from STEP as the app does) and Northbank's real
coordination clashes (the answer key's three services through the transfer girder, and the B1 pad footing against the
lift-pit wall). Each gets one Muse Spark proposal first (the sweep, as the app's Propose fixes: up to three rounds).

- The set: cases with no verified fix after the sweep.
- Arms on the set, each from the same first try and with the same two-round limit: Spark again (control), Spark with
  the escalation brief, Wonder with the brief.
- Better fix: on cases the sweep fixed only with a resize or an opening, Wonder with the brief: does it find a plain
  fix? (Spark's own options stay on offer in the app either way.)

Writes results.json and summary.md to --out, and appends rows to evals/results.csv.

    cd server
    uv run python ../evals/escalation.py --cell $DEMO_MODELS/palletising-cell \\
        --northbank $DEMO_MODELS/northbank/IFC --out ../evals/runs/<date>-escalation
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = Path(os.environ.get("DEMO_MODELS", ROOT.parent / "demo-models"))
sys.path.insert(0, str(ROOT / "server"))

from sightline import agent, escalation  # noqa: E402
from sightline.meta_client import MetaChatModel, escalation_model, triage_model  # noqa: E402
from sightline.service import Workspace  # noqa: E402

GIRDER = "1eVHoPtl1IhAbbhivqVqb0"
ANSWER_KEY = {"#042 duct": "2AbvqKF25LGeR0M34N_jld", "#057 tray": "3tQ7zxxRDMefPXL6hbHmO2",
              "#061 cold water": "1RHD_I4ibLDuUhW1LBAckc"}
B1_FOOTING = "19OJpW66zUKRUGqW4Z_o71"
NORTHBANK = ["Northbank-Architecture.ifc", "Northbank-MEP.ifc", "Northbank-Structure.ifc"]


def summary_of(result: dict, seconds: float) -> dict:
    best = result["options"][0] if result["options"] else None
    return {"verified": bool(result["options"]), "options": len(result["options"]), "tried": len(result["attempts"]),
            "seconds": round(seconds, 1), "usage": result.get("usage"),
            "best": None if best is None else {"title": best["title"], "kind": best["kind"], "model": best.get("model"),
                                                "delta_m": best["delta_m"], "clearance_mm": None if best["min_clearance_m"] is None
                                                else round(best["min_clearance_m"] * 1000),
                                                "summary": (best.get("edit") or {}).get("summary")},
            "advice": result.get("advice", ""),
            "failures": [f"{a['title']}: {a['reason']}" for a in result["attempts"] if not a["passed"]][:6]}


def run_arm(ws: Workspace, sid: str, a: str, b: str, model, first: dict | None, brief: bool, label: str) -> dict:
    """One arm from the same first try, two rounds, the requirements none (as in the app without a file)."""
    scene = ws.scene(sid)
    clash = ws.clash_for(a, b, scene_id=sid)
    fix = ws.fix_settings(sid, a, b)
    text = ""
    if brief:
        with ws.lock:
            text = escalation.brief(scene, clash, first, fix.get("clearance_m", 0.025))
        fix["guidance"] = fix.get("guidance", "") + "\n" + escalation.PACK.read_text()
    if hasattr(model, "usage"):
        model.usage = type(model.usage)()   # this arm's tokens only
    t = time.perf_counter()
    result = asdict(agent.resolve(scene, clash, model, lock=ws.lock, hosts_model=ws.hosts_model, max_rounds=2,
                                  brief=text, label=label, **fix))
    return summary_of(result, time.perf_counter() - t)


def cases_cell(cell: Path, work: Path, classifier) -> tuple[Workspace, str, list[tuple[str, str, str]]]:
    sys.path.insert(0, str(cell / "Code"))
    from celllayout import build
    from verify_cell import PLANTED
    shutil.copy(cell / "STEP" / "PC-03-Palletising-Cell-RevA.step", work)
    ws = Workspace(samples=work)
    sid = ws.open(["PC-03-Palletising-Cell-RevA.step"], classify_with=classifier)
    scene = ws.scene(sid)
    key_of = {p.name: p.key for p in build("A").parts}
    manifest = json.loads(Path(ws.sources[sid][0]["manifest"]).read_text())
    gid_of = {key_of[scene.entity(g).Name]: g for g in manifest["parts"]}
    return ws, sid, [(f"cell {label} {x} x {y}", gid_of[x], gid_of[y]) for label, x, y in PLANTED]


def cases_northbank(folder: Path, work: Path) -> tuple[Workspace, str, list[tuple[str, str, str]]]:
    for name in NORTHBANK:
        shutil.copy(folder / name, work)
    ws = Workspace(samples=work)
    sid = ws.open(NORTHBANK)
    boxes = ws.scene(sid).bounds()
    import numpy as np
    walls = [g for g in boxes if ws.scene(sid).entity(g).is_a("IfcWall") and "pit" in (ws.scene(sid).entity(g).Name or "").lower()]
    lo = lambda x, y: np.prod(np.clip(np.minimum(boxes[x][1], boxes[y][1]) - np.maximum(boxes[x][0], boxes[y][0]), 0, None))  # noqa: E731
    wall = max(walls, key=lambda w: lo(B1_FOOTING, w))
    return ws, sid, [*((f"northbank {k}", g, GIRDER) for k, g in ANSWER_KEY.items()),
                     ("northbank B1 pad footing x lift pit wall", B1_FOOTING, wall)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", type=Path, default=DEMO / "palletising-cell")
    ap.add_argument("--northbank", type=Path, default=DEMO / "northbank" / "IFC")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    work_cell, work_nb = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    spark = MetaChatModel()
    started = time.perf_counter()
    sets = [cases_cell(args.cell, work_cell, triage_model()[0]), cases_northbank(args.northbank, work_nb)]
    print(f"opened in {time.perf_counter() - started:.0f} s", flush=True)

    # The sweep: one Spark proposal each (the app's Propose fixes).
    jobs = [(ws, sid, label, a, b) for ws, sid, cases in sets for label, a, b in cases]

    def sweep(job):
        ws, sid, label, a, b = job
        t = time.perf_counter()
        try:
            r = ws.propose(sid, a, b)
        except Exception as e:  # a case that cannot be proposed at all is recorded, not fatal
            return label, {"error": f"{type(e).__name__}: {e}"}, None
        return label, summary_of(r, time.perf_counter() - t), r
    with ThreadPoolExecutor(args.workers) as pool:
        swept = list(pool.map(sweep, jobs))
    for (label, s, _), _ in zip(swept, jobs):
        print("sweep", label, "->", "ERROR" if "error" in s else (s["best"]["kind"] if s["verified"] else "no fix"), flush=True)

    rows = {label: {"sweep": s} for label, s, _ in swept}
    no_fix = [(j, r) for j, (label, s, r) in zip(jobs, swept) if r is not None and not s["verified"]]
    partial = [(j, r) for j, (label, s, r) in zip(jobs, swept)
               if r is not None and s["verified"] and all(agent.tier(o["kind"], o.get("edit")) > 0 for o in r["options"])]

    def arms(item):
        (ws, sid, label, a, b), first = item
        out = {}
        out["spark_again"] = run_arm(ws, sid, a, b, MetaChatModel(), first, False, "Muse Spark")
        out["spark_brief"] = run_arm(ws, sid, a, b, MetaChatModel(), first, True, "Muse Spark")
        out["wonder_brief"] = run_arm(ws, sid, a, b, escalation_model(), first, True, "Muse Wonder")
        return label, out

    def better(item):
        (ws, sid, label, a, b), first = item
        return label, {"wonder_better": run_arm(ws, sid, a, b, escalation_model(), first, True, "Muse Wonder")}
    with ThreadPoolExecutor(args.workers) as pool:
        for label, out in [*pool.map(arms, no_fix), *pool.map(better, partial)]:
            rows[label].update(out)
            print(label, {k: (v["best"] or {}).get("kind") if v["verified"] else "no fix" for k, v in out.items()},
                  flush=True)

    (args.out / "results.json").write_text(json.dumps(rows, indent=2, default=str))
    write_summary(args.out, rows, time.perf_counter() - started)
    append_csv(rows)
    print((args.out / "summary.md").read_text())


def write_summary(out: Path, rows: dict, seconds: float) -> None:
    arms = ("spark_again", "spark_brief", "wonder_brief")
    set_ = {k: v for k, v in rows.items() if "wonder_brief" in v}
    better = {k: v for k, v in rows.items() if "wonder_better" in v}
    cost = sum(((v[a].get("usage") or {}).get("usd") or 0) for v in rows.values() for a in (*arms, "wonder_better") if a in v)
    lines = ["# E0: a second try on Muse Wonder", "",
             f"{len(rows)} cases, one Muse Spark proposal each; {len(set_)} with no verified fix; "
             f"{len(better)} fixed only with a resize or an opening. {seconds / 60:.0f} min, Muse Wonder ${cost:.2f}.", "",
             "## The sweep", "", "| Case | Spark's first try | Tried | s |", "|---|---|---|---|"]
    for k, v in rows.items():
        s = v["sweep"]
        if "error" in s:
            lines.append(f"| {k} | error: {s['error'][:80]} | | |")
            continue
        best = s["best"]
        first = f"{best['kind']}: {best['title']}" if best else "no fix"
        lines.append(f"| {k} | {first} | {s['tried']} | {s['seconds']} |")
    if set_:
        lines += ["", "## No fix after the sweep: three arms, two rounds each", "",
                  "| Case | Spark again | Spark + brief | Wonder + brief | Wonder s / $ |", "|---|---|---|---|---|"]
        for k, v in set_.items():
            cell = lambda a: (f"{v[a]['best']['kind']}: {v[a]['best']['title']}" if v[a]["verified"] else "no fix")  # noqa: E731
            u = v["wonder_brief"].get("usage") or {}
            lines.append(f"| {k} | {cell('spark_again')} | {cell('spark_brief')} | {cell('wonder_brief')} | "
                         f"{v['wonder_brief']['seconds']} / {u.get('usd', 0):.2f} |")
        for a in arms:
            lines.append(f"- {a}: {sum(v[a]['verified'] for v in set_.values())} of {len(set_)} verified")
    if better:
        lines += ["", "## Fixed only with a resize or an opening: Wonder looking for a better fix", "",
                  "| Case | Spark | Wonder | Plain fix found |", "|---|---|---|---|"]
        for k, v in better.items():
            w = v["wonder_better"]
            plain = w["verified"] and agent.tier(w["best"]["kind"]) == 0
            lines.append(f"| {k} | {v['sweep']['best']['kind']}: {v['sweep']['best']['title']} | "
                         f"{(w['best'] or {}).get('kind', 'no fix')}: {(w['best'] or {}).get('title', '')} | {'yes' if plain else 'no'} |")
    lines += ["", "Advice and failures per arm: results.json."]
    (out / "summary.md").write_text("\n".join(lines) + "\n")


def append_csv(rows: dict) -> None:
    path = ROOT / "evals" / "results.csv"
    date = time.strftime("%Y-%m-%d")
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        for k, v in rows.items():
            dataset = "cell-revA-step" if k.startswith("cell") else "northbank-rev03"
            for arm, r in v.items():
                if "error" in r:
                    continue
                best = r["best"] or {}
                model = ((r.get("usage") or {}).get("model") or
                         ("muse-wonder-1.0" if "wonder" in arm else "muse-spark-1.3-contributor"))
                w.writerow([date, dataset, k, model, "none", f"escalation-{arm}", r["seconds"], r["tried"], r["options"],
                            "yes" if r["verified"] else "no", ",".join(str(round(x, 3)) for x in best.get("delta_m", [])),
                            best.get("clearance_mm", ""), "",
                            f"{best.get('kind', 'no fix')}: {best.get('title', '')}"[:120]])


if __name__ == "__main__":
    main()
