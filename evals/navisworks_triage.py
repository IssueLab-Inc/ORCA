"""Triage a Navisworks clash-sample package with Muse Spark: is each result a real clash, and what should happen?

The package is the three-view export in ClashWiseDemoModels (`northbank/StructuredOutputs/<run>/`): per clash,
`clash.xml` plus A-transparent / B-context / C-alternate PNGs (item 1 red, item 2 green). Each clash goes to the
model as text (classes, names, levels, signed distance) plus the three images, with strict structured output.

    cd server
    uv run python ../evals/navisworks_triage.py <package dir> --out ../evals/runs/<date>-northbank-nwf-triage
    uv run python ../evals/navisworks_triage.py <package dir> --out ... --limit 5      # smoke test first

Open weights: `--open` uses the app's triage host (`meta_client.triage_model`: Muse Spark Open on Baseten when
TRIAGE_API_KEY or BASETEN_API_KEY is set); `--base-url/--model/--api-key-env` point at any OpenAI-compatible host.

Re-running with the same --out resumes (clashes already in replies.jsonl are skipped), then rescores.
Scoring is against a reference built from the metadata alone (see `reference`), not a human review:
non-physical classes, touching results, and the dataset's answer key. Everything else is reported, not scored.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from sightline import reports  # noqa: E402
from sightline import triage  # noqa: E402
from sightline.meta_client import MetaChatModel, triage_model  # noqa: E402

PROMPT = Path(__file__).resolve().parents[1] / "server/sightline/domain_packs/triage.md"
VIEWS = ["A-transparent.png", "B-context.png", "C-alternate.png"]

NON_PHYSICAL = {"IfcSpace", "IfcDistributionPort", "IfcOpeningElement", "IfcVirtualElement", "IfcZone"}
TOUCH_M = 0.001  # |distance| at or under this is a touch (the tests' tolerance is 10 mm)

# Northbank answer key (CLAUDE.md): the services that hit the Level 02 transfer girder.
GIRDER = "1eVHoPtl1IhAbbhivqVqb0"
ANSWER_KEY = {"2AbvqKF25LGeR0M34N_jld": "#042", "3tQ7zxxRDMefPXL6hbHmO2": "#057", "1RHD_I4ibLDuUhW1LBAckc": "#061"}

SCHEMA = triage.SCHEMA  # the app and the eval ask the same question


def load(package: Path) -> list[dict]:
    """The package's combined XML, through the same reader the app uses (`sightline.reports`)."""
    report = reports.load("eval", package, [package / "sampled-clashes.xml"], package.name)
    clashes = []
    for c in report.clashes:
        folder = c.images[0][1].parent
        clashes.append({
            "id": f"{folder.parent.name}/{folder.name}",
            "test": c.test, "tolerance_m": c.tolerance_m or 0.0, "clash": c.name, "distance_m": c.distance_m,
            "point": [round(v, 3) for v in c.point], "a": asdict(c.a), "b": asdict(c.b), "folder": folder,
        })
    return clashes


def describe(c: dict) -> str:
    def line(label: str, colour: str, e: dict) -> str:
        s = f"Element {label} ({colour}): {e['ifc_class']} '{e['name']}', {e['file']}, level {e['level']}"
        if e["part_of"]:
            s += f", part of '{e['part_of']}'"
        if e["system"]:
            s += f", system {e['system']}"
        if e["description"]:
            s += f" ({e['description']})"
        return s
    return "\n".join([
        f"Clash test: {c['test']} (hard, tolerance {c['tolerance_m'] * 1000:.0f} mm)",
        line("A", "red", c["a"]),
        line("B", "green", c["b"]),
        f"Signed distance: {c['distance_m'] * 1000:.1f} mm (negative = overlap)",
        f"Clash point: {c['point']} m, Z up",
    ])


def reference(c: dict) -> dict | None:
    """What a coordinator would say from the metadata alone, where that is unambiguous; None when it is not."""
    ids = {c["a"]["global_id"], c["b"]["global_id"]}
    if GIRDER in ids and ids & ANSWER_KEY.keys():
        service = "A" if c["a"]["global_id"] in ANSWER_KEY else "B"
        return {"kind": "answer_key", "label": ANSWER_KEY[(ids & ANSWER_KEY.keys()).pop()],
                "verdict": {"real_clash"}, "action": {f"move_{service}", f"modify_{service}"}}
    if {c["a"]["ifc_class"], c["b"]["ifc_class"]} & NON_PHYSICAL:
        return {"kind": "non_physical", "verdict": {"non_physical"}}
    if abs(c["distance_m"]) <= TOUCH_M:
        return {"kind": "touching", "verdict": {"by_design", "non_physical"}}
    return None


def run(clashes: list[dict], out: Path, model: MetaChatModel, workers: int, images: bool) -> None:
    replies = out / "replies.jsonl"
    done = {json.loads(l)["id"] for l in replies.read_text().splitlines()} if replies.exists() else set()
    todo = [c for c in clashes if c["id"] not in done]
    print(f"{len(done)} already done, {len(todo)} to go")
    system, lock = PROMPT.read_text(), threading.Lock()

    def one(c: dict) -> dict:
        pics = [c["folder"] / v for v in VIEWS] if images else []
        for attempt in range(4):
            t = time.perf_counter()
            try:
                reply = model.complete_json(system, describe(c), pics, schema=SCHEMA)
                return {"id": c["id"], "latency_s": round(time.perf_counter() - t, 1), "reply": reply}
            except Exception as e:  # rate limits, timeouts, bad JSON: back off and retry, then record the failure
                err = f"{type(e).__name__}: {e}"[:300]
                time.sleep(2 ** (attempt + 1))
        return {"id": c["id"], "latency_s": None, "error": err}

    with ThreadPoolExecutor(workers) as pool, replies.open("a") as f:
        for i, fut in enumerate(as_completed(pool.submit(one, c) for c in todo), 1):
            row = fut.result()
            with lock:
                f.write(json.dumps(row) + "\n")
                f.flush()
            status = row.get("error") or f"{row['reply']['verdict']} {row['latency_s']} s"
            print(f"[{i}/{len(todo)}] {row['id']}: {status}", flush=True)


def score(clashes: list[dict], out: Path, model_id: str, images: bool) -> None:
    rows = {}
    for line in (out / "replies.jsonl").read_text().splitlines():
        r = json.loads(line)
        if "reply" in r or r["id"] not in rows:
            rows[r["id"]] = r
    table, groups = [], collections.defaultdict(lambda: {"n": 0, "ok": 0})
    by_pair = collections.defaultdict(collections.Counter)
    for c in clashes:
        r = rows.get(c["id"])
        if not r or "reply" not in r:
            continue
        reply, ref = r["reply"], reference(c)
        ok = None
        if ref:
            ok = reply["verdict"] in ref["verdict"] and (reply["action"] in ref.get("action", {reply["action"]}))
            g = groups[ref["kind"]]
            g["n"] += 1
            g["ok"] += ok
        pair = " vs ".join(sorted([c["a"]["ifc_class"], c["b"]["ifc_class"]]))
        by_pair[pair][reply["verdict"]] += 1
        table.append({
            "id": c["id"], "test": c["test"], "a_class": c["a"]["ifc_class"], "a_name": c["a"]["name"],
            "b_class": c["b"]["ifc_class"], "b_name": c["b"]["name"], "distance_mm": round(c["distance_m"] * 1000, 1),
            "reference": (ref["label"] if ref and ref["kind"] == "answer_key" else ref["kind"]) if ref else "",
            "verdict": reply["verdict"], "severity": reply["severity"], "action": reply["action"],
            "responsible": reply["responsible"], "confidence": reply["confidence"],
            "match": "" if ok is None else ("yes" if ok else "no"), "latency_s": r["latency_s"],
            "understanding": reply["understanding"], "fix_hint": reply["fix_hint"],
        })
    with (out / "triage.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)

    lat = sorted(t["latency_s"] for t in table)
    errors = len(rows) - len(table)
    verdicts = collections.Counter(t["verdict"] for t in table)
    lines = [
        f"# Triage run: {out.name}", "",
        f"Model `{model_id}`, images {'A/B/C' if images else 'none'}, prompt `server/sightline/domain_packs/triage.md`, "
        f"strict JSON schema.", "",
        f"- Clashes: {len(clashes)}; replies: {len(table)}; failed calls: {errors}; "
        f"median latency {lat[len(lat) // 2]:.1f} s (max {lat[-1]:.1f} s)",
        f"- Verdicts: " + ", ".join(f"{k} {v}" for k, v in verdicts.most_common()), "",
        "## Against the metadata reference", "",
        "| Reference | Expected | Clashes | Match |", "|---|---|---|---|",
    ]
    expected = {"answer_key": "real_clash, and move/modify the service", "non_physical": "non_physical",
                "touching": "by_design or non_physical"}
    for kind in ("answer_key", "non_physical", "touching"):
        g = groups.get(kind)
        if g:
            lines.append(f"| {kind} | {expected[kind]} | {g['n']} | {g['ok']}/{g['n']} ({g['ok'] / g['n']:.0%}) |")
    misses = [t for t in table if t["match"] == "no"]
    if misses:
        lines += ["", "### Misses", "", "| Clash | Pair | mm | Reference | Verdict / action | Model's reading |",
                  "|---|---|---|---|---|---|"]
        for t in misses:
            lines.append(f"| {t['id']} | {t['a_class']} '{t['a_name']}' vs {t['b_class']} '{t['b_name']}' | "
                         f"{t['distance_mm']} | {t['reference']} | {t['verdict']} / {t['action']} | "
                         f"{t['understanding'].replace('|', '/')} |")
    keys = [t for t in table if t["reference"].startswith("#")]
    if keys:
        lines += ["", "### Answer-key clashes", ""]
        for t in keys:
            lines.append(f"- **{t['reference']}** {t['id']} ({t['distance_mm']} mm): {t['verdict']}, {t['severity']}, "
                         f"{t['action']}. {t['understanding']} Fix: {t['fix_hint']}")
    lines += ["", "## Verdicts by class pair (unscored where no reference applies)", "",
              "| Pair | real_clash | by_design | non_physical | modelling_error |", "|---|---|---|---|---|"]
    for pair, cnt in sorted(by_pair.items()):
        lines.append(f"| {pair} | " + " | ".join(str(cnt.get(v, "")) for v in
                                                  ("real_clash", "by_design", "non_physical", "modelling_error")) + " |")
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:16]))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("package", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--no-images", action="store_true")
    p.add_argument("--score-only", action="store_true")
    p.add_argument("--open", action="store_true", help="the app's triage host (open weights when configured)")
    p.add_argument("--base-url")
    p.add_argument("--model")
    p.add_argument("--api-key-env", help="environment variable holding the host's key")
    p.add_argument("--effort", help="reasoning_effort ('' to omit)")
    args = p.parse_args()

    clashes = load(args.package)[: args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    if args.open:
        model, info = triage_model(timeout_s=240)
        if not info["open_weights"]:
            sys.exit("No open-weights host configured: set TRIAGE_API_KEY (or BASETEN_API_KEY).")
    else:
        key = os.environ[args.api_key_env] if args.api_key_env else None
        model = MetaChatModel(args.base_url, key, args.model, timeout_s=240, reasoning_effort=args.effort)
    if not args.score_only:
        run(clashes, args.out, model, args.workers, not args.no_images)
    score(clashes, args.out, model.model, not args.no_images)


if __name__ == "__main__":
    main()
