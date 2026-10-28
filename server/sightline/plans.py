"""Fixing many clashes at once, and fixing the cause behind several.

A single fix is checked against the model as it is. Several fixes can each pass alone and still collide with each
other (two services raised into the same space), so a plan is checked as a whole: every fix applied together in
one trial, each changed element checked against everything, including the other fixes, then all undone.

Root causes: when one element is in several real clashes (a beam hit by three services, a pipe at the wrong height
through a row of joists), that element is the thing to look at. `root_causes` finds those elements from the report
and asks the geometry for clashes the report missed. `build` then asks Muse Spark what the cause is and whether to
move that one element (it clears every clash at once) or fix each partner in a coordinated way, runs the fix agent
accordingly, and checks the combined result.
"""
from __future__ import annotations

import contextlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import agent, edits, owner, verify
from .service import Workspace

PACKS = Path(__file__).parent / "domain_packs"
MAX_ITEMS = 8
NOT_PHYSICAL = {"IfcSpace", "IfcDistributionPort", "IfcOpeningElement", "IfcVirtualElement", "IfcZone"}


@dataclass
class Item:
    """One clash pair in a plan, and the fix chosen for it."""
    key: str                         # "<a>|<b>", the pair's GlobalIds
    element_a: str
    element_b: str
    label: str                       # "IfcBeam 'Transfer girder' x IfcDuctSegment 'Supply main'"
    clash_ids: list[str]             # report clashes this pair stands for (one pair can be reported by several tests)
    in_report: bool = True           # False: found by the geometry, not in the Navisworks report
    distance_m: float | None = None
    understanding: str = ""
    option: dict | None = None       # the chosen agent.Option, as a dict
    alternatives: list[dict] = field(default_factory=list)
    tried: int = 0
    error: str = ""


@dataclass
class Plan:
    kind: str                        # "batch" or "root_cause"
    title: str
    root_cause: str = ""
    strategy: str = ""               # root cause only: "move_hub" or "fix_partners"
    hub: dict | None = None
    items: list[Item] = field(default_factory=list)
    check: dict = field(default_factory=dict)   # the combined check (see verify_together)
    seconds: float = 0.0
    advice: str = ""                 # root cause "as_designed": what to do instead of editing the model


# ---------------------------------------------------------------------------------------------------------- checks

@contextlib.contextmanager
def _trial(scene, indexes: set[int]):
    """Edit several files of a scene, then undo every edit (cached boxes included)."""
    before = dict(scene.bounds())
    models = [scene.models[i] for i in sorted(indexes)]
    for m in models:
        m.begin_transaction()
    try:
        yield
    finally:
        for m in models:
            m.end_transaction()
            m.undo()
        scene._bounds = before


def verify_together(ws: Workspace, scene_id: str, items: list[Item], clearance_m: float = 0.025) -> dict:
    """Apply every item's chosen fix in one trial, check each against the whole model (the other fixes included),
    and undo. Returns {"passed", "items": {key: {"passed", "reason", "min_clearance_m"}}, "conflicts": [...]}."""
    scene = ws.scene(scene_id)
    live = [it for it in items if it.option]
    out: dict = {"passed": True, "items": {}, "conflicts": []}
    if not live:
        return {**out, "passed": False}
    with ws.lock:
        files = {scene.index_of(g) for it in live for g in it.option["moved"]}
        # A trimmed member already touches what it is framed into: only contacts new or worse than these count.
        before = {it.key: {h.other: h.distance_m for h in verify.check(scene, it.option["moved"], clearance_m=clearance_m).hits}
                  for it in live if it.option["kind"] == "trim"}
        with _trial(scene, files):
            changed: dict[str, tuple[list[str], set[str], str | None]] = {}  # key → (check these, own elements, obstacle)
            for it in live:
                o = it.option
                if o["kind"] == "offset":
                    off = edits.apply_offset(scene, o["moved"][0], o["split_m"][0], o["split_m"][1], o["delta_m"][2])
                    other = it.element_b if o["moved"][0] == it.element_a else it.element_a
                    changed[it.key] = (off.pieces, set(off.pieces), other)
                elif o["kind"] == "trim":
                    edits.apply_trim(scene, o["moved"][0], o["trim"]["end"], o["trim"]["by_m"])
                    changed[it.key] = (list(o["moved"]), set(o["moved"]), None)
                else:
                    scene.translate(o["moved"], tuple(o["delta_m"]))
                    changed[it.key] = (list(o["moved"]), set(o["moved"]), None)
            owner = {g: key for key, (_, own, _) in changed.items() for g in own}
            for it in live:
                check_ids, own, obstacle = changed[it.key]
                ignore = own | {c for g in own for c in scene.element(g).connected if c not in owner}
                if obstacle:  # an offset: new pieces against everything, the shortened ends only against the obstacle
                    v = verify.check(scene, check_ids[1:-1], clearance_m=clearance_m, ignore=ignore)
                    ends = verify.check(scene, [check_ids[0], check_ids[-1]], clearance_m=clearance_m, ignore=ignore)
                    hits = v.hits + [h for h in ends.hits if h.other == obstacle or h.other in owner]
                else:
                    v = verify.check(scene, check_ids, clearance_m=clearance_m, ignore=ignore)
                    hits = v.hits
                if it.key in before:  # a trim butts its partner and keeps the contacts it had
                    partner = it.element_b if it.option["moved"][0] == it.element_a else it.element_a
                    was = before[it.key]
                    hits = [h for h in hits if (h.distance_m < -0.002 if h.other == partner
                                                else h.other not in was or h.distance_m < was[h.other] - 0.002)]
                for h in hits:
                    if h.other in owner and owner[h.other] != it.key:
                        out["conflicts"].append({"a": it.key, "b": owner[h.other],
                                                 "detail": f"{h.kind} {h.distance_m * 1000:+.0f} mm"})
                out["items"][it.key] = {"passed": not hits, "reason": agent._reason(hits),
                                        "min_clearance_m": v.min_clearance_m}
    out["passed"] = all(r["passed"] for r in out["items"].values()) and len(live) == len(items)
    return out


# ---------------------------------------------------------------------------------------------------------- pairs

def _label(ws: Workspace, scene_id: str, a: str, b: str) -> str:
    ea, eb = ws.scene(scene_id).element(a), ws.scene(scene_id).element(b)
    return f"{ea.ifc_class} '{ea.name}' x {eb.ifc_class} '{eb.name}'"


def pairs_for(ws: Workspace, scene_id: str, report_id: str, clash_ids: list[str]) -> tuple[list[Item], list[str]]:
    """Report clashes → distinct element pairs that can be fixed here, and why the others cannot."""
    matches = ws.match(report_id, scene_id)
    physical = ws.scene(scene_id).bounds().keys()
    items: dict[str, Item] = {}
    skipped: list[str] = []
    report = ws.report(report_id)
    for cid in clash_ids:
        c = report.clash(cid)
        m = matches.get(cid, {})
        if not (m.get("a") and m.get("b")):
            skipped.append(f"{c.name} ({c.test}): not in the open model")
            continue
        if m["a"] not in physical or m["b"] not in physical:
            skipped.append(f"{c.name} ({c.test}): a space or port, not a physical clash")
            continue
        key = "|".join(sorted([m["a"], m["b"]]))
        if key in items:
            items[key].clash_ids.append(cid)
            continue
        items[key] = Item(key, m["a"], m["b"], _label(ws, scene_id, m["a"], m["b"]), [cid], True, c.distance_m)
    return list(items.values()), skipped


def _resolve_items(ws: Workspace, scene_id: str, report_id: str | None, items: list[Item], notes: str,
                   emit: Callable[[dict], None], prefer: dict[str, str] | None = None) -> None:
    """Run the fix agent on every item at once (their model calls overlap; geometry trials take turns)."""
    def one(it: Item) -> None:
        emit({"type": "item", "key": it.key, "status": "thinking"})
        try:
            cid = it.clash_ids[0] if it.clash_ids and report_id else None
            clash = ws.clash_for(it.element_a, it.element_b, it.distance_m, None,
                                 "\n".join(filter(None, [notes, (prefer or {}).get(it.key, "")])), report_id, cid)

            def progress(e: dict) -> None:
                if e["type"] == "attempt":
                    emit({"type": "item", "key": it.key, "status": "checking", "attempt": e["title"], "passed": e["passed"]})
            result = agent.resolve(ws.scene(scene_id), clash, ws.model, on_event=progress, lock=ws.lock, max_rounds=2)
            it.understanding = result.understanding
            it.tried = len(result.attempts)
            options = [asdict(o) for o in result.options]
            it.option = options[0] if options else None
            it.alternatives = options[1:]
            if not options:
                it.error = "no fix passed the check: " + "; ".join(a.reason for a in result.attempts[:3])
        except Exception as e:  # one clash failing must not sink the plan
            it.error = f"{type(e).__name__}: {e}"
        emit({"type": "item", "key": it.key, "status": "done", "ok": bool(it.option),
              "title": it.option["title"] if it.option else it.error})

    with ThreadPoolExecutor(max_workers=4) as pool:
        [f.result() for f in [owner.submit(pool, one, it) for it in items]]


def _settle(ws: Workspace, scene_id: str, items: list[Item], emit) -> dict:
    """Check the plan as a whole; when two fixes collide, swap in an item's next-best option and check again."""
    emit({"type": "checking_plan"})
    check = verify_together(ws, scene_id, items)
    for _ in range(3):
        bad = [it for it in items if it.option and not check["items"].get(it.key, {}).get("passed", True)]
        swappable = [it for it in bad if it.alternatives]
        if not swappable:
            break
        for it in swappable:
            it.option = it.alternatives.pop(0)
        emit({"type": "checking_plan", "retry": [it.key for it in swappable]})
        check = verify_together(ws, scene_id, items)
    return check


# ---------------------------------------------------------------------------------------------------------- batch

def build_batch(ws: Workspace, scene_id: str, report_id: str, clash_ids: list[str],
                emit: Callable[[dict], None] = lambda e: None) -> Plan:
    started = time.perf_counter()
    items, skipped = pairs_for(ws, scene_id, report_id, clash_ids)
    items = items[:MAX_ITEMS]
    emit({"type": "plan_items", "items": [asdict(i) for i in items], "skipped": skipped})
    _resolve_items(ws, scene_id, report_id, items,
                   "This clash is being fixed together with others; prefer fixes that stay close to the element.",
                   emit)
    check = _settle(ws, scene_id, items, emit)
    n = len(items)
    plan = Plan("batch", f"Fix {n} clash{'es' if n != 1 else ''} together", items=items, check=check,
                seconds=round(time.perf_counter() - started, 1))
    if skipped:
        plan.root_cause = "Not included: " + "; ".join(skipped[:6])
    return plan


# ---------------------------------------------------------------------------------------------------------- root causes

def root_causes(ws: Workspace, scene_id: str, report_id: str, fixed: list[str] | None = None, top: int = 6,
                only: str | None = None) -> list[dict]:
    """Elements in several real clashes, most telling first, with clashes the geometry finds that the report lacks.

    Real here means: both elements physical and in the open model, overlapping by more than 1 mm, not yet fixed.
    Clusters across disciplines (structure against services) rank above clusters inside one model, which are mostly
    connections.

    `only`: just that element's cluster, which may have a single clash left in the report when the geometry finds
    more (the girder after one of its three services is fixed)."""
    scene = ws.scene(scene_id)
    matches = ws.match(report_id, scene_id)
    physical = scene.bounds().keys()
    fixed_set = set(fixed or [])
    partners: dict[str, dict[str, dict]] = {}
    for c in ws.report(report_id).clashes:
        m = matches.get(c.id, {})
        a, b = m.get("a"), m.get("b")
        if not (a and b) or a not in physical or b not in physical or c.id in fixed_set:
            continue
        if c.distance_m is None or c.distance_m > -0.001:
            continue
        for x, y in ((a, b), (b, a)):
            p = partners.setdefault(x, {}).setdefault(y, {"global_id": y, "clash_ids": [], "distance_m": c.distance_m})
            p["clash_ids"].append(c.id)
            p["distance_m"] = min(p["distance_m"], c.distance_m)
    source = {g: scene.element(g).source for g in partners}
    ranked = []
    for hub, ps in partners.items():
        if (only and hub != only) or (len(ps) < 2 and hub != only):
            continue
        cross = sum(1 for p in ps if scene.element(p).source != source[hub])
        ranked.append((cross > 0, cross, len(ps), hub))
    ranked.sort(reverse=True)
    out = []
    with ws.lock:
        for _, cross, count, hub in ranked[:top]:
            e = scene.element(hub)
            known = partners[hub]
            # Ask the geometry what else this element runs into, across disciplines: the report may have missed it.
            extra = []
            for h in verify.check(scene, [hub], clearance_m=0.0).hits:
                if h.other in known or h.distance_m > -0.01 or h.other not in physical:
                    continue
                o = scene.element(h.other)
                if o.source != e.source and h.other not in e.connected:
                    extra.append({"global_id": h.other, "clash_ids": [], "distance_m": h.distance_m, "in_report": False})
            items = [{**p, "in_report": True} for p in known.values()] + extra
            if len(items) < 2:
                continue
            for p in items:
                o = scene.element(p["global_id"])
                p.update({"ifc_class": o.ifc_class, "name": o.name, "source": o.source, "storey": o.storey})
            out.append({"hub": asdict(e), "partners": items, "cross_discipline": cross + len(extra),
                        "clash_ids": sorted({cid for p in items for cid in p["clash_ids"]}),
                        "not_in_report": len(extra)})
    return out


def _describe_cluster(ws: Workspace, scene_id: str, cluster: dict) -> str:
    scene = ws.scene(scene_id)
    hub = cluster["hub"]
    lines = [f"Element in several clashes (the hub): {hub['ifc_class']} '{hub['name']}', level {hub['storey']}, "
             f"file {hub['source']}, GlobalId {hub['global_id']}"]
    with ws.lock:
        try:
            run = edits.run_of(scene, hub["global_id"])
            lines.append(f"  It is a straight segment {run.length_m:.2f} m long, profile {run.width_m * 1000:.0f} x "
                         f"{run.depth_m * 1000:.0f} mm, from {[round(v, 2) for v in run.start]} to {[round(v, 2) for v in run.end]}.")
        except (edits.Unsupported, KeyError, RuntimeError):
            pass
        lines.append("It clashes with:")
        for p in cluster["partners"]:
            src = "in the Navisworks report" if p["in_report"] else "found by the geometry check, NOT in the report"
            lines.append(f"- {p['ifc_class']} '{p['name']}' ({p['source']}, level {p['storey']}), "
                         f"{(p['distance_m'] or 0) * 1000:+.0f} mm, {src}, GlobalId {p['global_id']}")
            try:
                for h in edits.passages(scene, p["global_id"], hub["global_id"]):
                    lines.append(f"    the hub has an opening on its line: offset it {h['dz_min_m']:+.3f} to "
                                 f"{h['dz_max_m']:+.3f} m to pass through with 25 mm clearance")
            except (edits.Unsupported, KeyError, RuntimeError):
                pass
    return "\n".join(lines)


def build_root_cause(ws: Workspace, scene_id: str, report_id: str, hub: str, fixed: list[str] | None = None,
                     emit: Callable[[dict], None] = lambda e: None,
                     charge: Callable[[int], str | None] = lambda n: None) -> Plan:
    """`charge(n)` is asked before the fix agents run (one model call per pair); it returns why not, or None. The
    cause itself costs one call, charged by the caller, so a cause that needs no edits costs no more than that."""
    started = time.perf_counter()
    cluster = next(iter(root_causes(ws, scene_id, report_id, fixed, only=hub)), None)
    if cluster is None:
        raise KeyError("That element is not in several open clashes.")
    emit({"type": "thinking", "what": "root cause"})
    text = _describe_cluster(ws, scene_id, cluster)
    reply = ws.model.complete_json((PACKS / "root_cause.md").read_text(), text)
    strategy = reply.get("strategy") if reply.get("strategy") in ("move_hub", "fix_partners", "as_designed") else "fix_partners"
    emit({"type": "root_cause", "root_cause": reply.get("root_cause", ""), "strategy": strategy,
          "reason": reply.get("reason", "")})
    hub_el = cluster["hub"]
    if strategy == "as_designed":  # connections, not conflicts: nothing to edit, say what to do instead
        return Plan("root_cause", f"Root cause: {hub_el['ifc_class']} '{hub_el['name']}'", reply.get("root_cause", ""),
                    strategy, cluster, [], {"passed": True, "items": {}, "conflicts": []},
                    round(time.perf_counter() - started, 1), reply.get("reason", ""))
    notes = f"Root cause: {reply.get('root_cause', '')}\nCoordinated plan: {reply.get('reason', '')}"
    if strategy == "move_hub":
        first = cluster["partners"][0]
        others = ", ".join(f"{p['ifc_class']} '{p['name']}'" for p in cluster["partners"][1:])
        item = Item("|".join(sorted([hub, first["global_id"]])), hub, first["global_id"],
                    _label(ws, scene_id, hub, first["global_id"]), cluster["clash_ids"], True, first["distance_m"])
        items = [item]
        prefer = {item.key: f"Move element A (the hub) so that it also clears: {others}. Do not move B."}
    else:
        items = [Item("|".join(sorted([p["global_id"], hub])), p["global_id"], hub,
                      _label(ws, scene_id, p["global_id"], hub), p["clash_ids"], p["in_report"], p["distance_m"])
                 for p in cluster["partners"]][:MAX_ITEMS]
        prefer = {it.key: "Move or offset element A; element B is the hub and stays." for it in items}
    refused = charge(len(items))
    if refused:
        for it in items:
            it.error = refused
        return Plan("root_cause", f"Root cause: {hub_el['ifc_class']} '{hub_el['name']}'", reply.get("root_cause", ""),
                    strategy, cluster, items, {"passed": False, "items": {}, "conflicts": []},
                    round(time.perf_counter() - started, 1), refused)
    emit({"type": "plan_items", "items": [asdict(i) for i in items], "skipped": []})
    _resolve_items(ws, scene_id, report_id, items, notes, emit, prefer)
    check = _settle(ws, scene_id, items, emit)
    if strategy == "move_hub" and items[0].option:
        # The hub moved: every partner pair must be clear, which the hub's own check (against everything) covers.
        check["covers"] = [p["global_id"] for p in cluster["partners"]]
    return Plan("root_cause", f"Root cause: {hub_el['ifc_class']} '{hub_el['name']}'", reply.get("root_cause", ""),
                strategy, cluster, items, check, round(time.perf_counter() - started, 1))


def apply(ws: Workspace, scene_id: str, options: list[dict]) -> dict:
    """Keep every fix of an accepted plan. Returns the files changed and, per offset, its pieces."""
    files: set[int] = set()
    pieces: list[list[str]] = []
    with ws.lock:
        for o in options:
            if o["kind"] == "offset":
                r = ws.apply_offset(scene_id, o["moved"][0], o["split_m"], o["delta_m"][2])
                pieces.append(r["pieces"])
            elif o["kind"] == "trim":
                r = ws.apply_trim(scene_id, o["moved"][0], o["trim"]["end"], o["trim"]["by_m"])
                pieces.append([])
            else:
                r = ws.apply(scene_id, o["moved"], o["delta_m"])
                pieces.append([])
            files.update(r["files"])
    return {"files": sorted(files), "pieces": pieces}


def to_json(plan: Plan) -> str:
    return json.dumps(asdict(plan), default=str)


# ---------------------------------------------------------------------------------------------------------- patterns

def patterns(ws: Workspace, scene_id: str, report_id: str, fixed: list[str] | None = None, min_pairs: int = 3) -> list[dict]:
    """The same kind of clash, many times over: real clashes grouped by the two element classes and their files.

    A root cause is one element in many clashes; a pattern is many elements clashing the same way (every column
    through every slab, curtain-wall members all overlapping by exactly 30 mm). Patterns are usually a modelling
    convention or a systematic error, and are fixed by a clash rule or one decision, not one edit at a time."""
    scene = ws.scene(scene_id)
    matches = ws.match(report_id, scene_id)
    physical = scene.bounds().keys()
    fixed_set = set(fixed or [])
    groups: dict[tuple, list] = {}
    for c in ws.report(report_id).clashes:
        m = matches.get(c.id, {})
        a, b = m.get("a"), m.get("b")
        if not (a and b) or a not in physical or b not in physical or c.id in fixed_set:
            continue
        if c.distance_m is None or c.distance_m > -0.001:
            continue
        ea, eb = scene.element(a), scene.element(b)
        sides = sorted([(ea.ifc_class, ea.source), (eb.ifc_class, eb.source)])
        groups.setdefault(tuple(sides), []).append((c, ea, eb))
    out = []
    for (sa, sb), rows in groups.items():
        pairs = {tuple(sorted([ea.global_id, eb.global_id])) for _, ea, eb in rows}
        if len(pairs) < min_pairs:
            continue
        ds = sorted(c.distance_m * 1000 for c, _, _ in rows)
        examples = []
        for c, ea, eb in rows[:4]:
            examples.append(f"{ea.ifc_class} '{ea.name}' x {eb.ifc_class} '{eb.name}' ({c.distance_m * 1000:+.0f} mm, {ea.storey})")
        out.append({
            "id": f"{sa[0]}|{sb[0]}|{sa[1]}|{sb[1]}",
            "classes": [sa[0], sb[0]], "files": [sa[1], sb[1]], "cross_discipline": sa[1] != sb[1],
            "clashes": len(rows), "pairs": len(pairs),
            "levels": sorted({ea.storey or "?" for _, ea, _ in rows} | {eb.storey or "?" for _, _, eb in rows}),
            "min_mm": round(ds[0]), "max_mm": round(ds[-1]), "constant": ds[-1] - ds[0] <= 2,
            "clash_ids": [c.id for c, _, _ in rows], "examples": examples,
        })
    out.sort(key=lambda p: (not p["cross_discipline"], -p["pairs"]))
    return out


def triage_patterns(ws: Workspace, pats: list[dict]) -> dict[str, dict]:
    """One Muse Spark call over every pattern: by design, a modelling error, or a real problem, and what to do."""
    if not pats:
        return {}
    lines = []
    for i, p in enumerate(pats, 1):
        lines.append(f"P{i}: {p['classes'][0]} ({p['files'][0]}) x {p['classes'][1]} ({p['files'][1]}): {p['clashes']} "
                     f"clashes, {p['pairs']} element pairs, levels {', '.join(p['levels'])}, overlap {p['min_mm']} to "
                     f"{p['max_mm']} mm{' (the same every time)' if p['constant'] else ''}. Examples: "
                     + "; ".join(p["examples"][:3]))
    reply = ws.model.complete_json((PACKS / "patterns.md").read_text(), "\n".join(lines))
    out = {}
    for row in reply.get("patterns", []):
        try:
            p = pats[int(str(row.get("id", "")).lstrip("Pp")) - 1]
        except (ValueError, IndexError):
            continue
        verdict = row.get("verdict") if row.get("verdict") in ("by_design", "modelling_error", "real_problem") else "real_problem"
        out[p["id"]] = {"verdict": verdict, "cause": row.get("cause", ""), "action": row.get("action", ""),
                        "rule": row.get("rule", "")}
    return out
