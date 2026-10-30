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

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import agent, connections, edits, owner, requirements, verify
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
    others: list[str] = field(default_factory=list)  # more elements the same movable element runs into: one fix for all
    recommended: bool = False        # the requirements allow no edit: a recommendation, and no second try to make


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

_trial = edits.trial_files


def _in_trial_move(scene, it: Item, o: dict):
    plan = connections.plan_move(scene, o["moved"], o["delta_m"])
    if not plan.ok:   # never tried: it would pull a joint apart (the check reports which)
        broken = [verify.Hit(g, scene.entity(g).is_a(), "joint", 0.0) for g in plan.refused_at]
        return list(o["moved"]), set(o["moved"]), lambda clearance_m, owner: (broken, None)
    scene.translate(o["moved"], tuple(o["delta_m"]))
    return list(o["moved"]), set(o["moved"]), None


def _in_trial_offset(scene, it: Item, o: dict) -> tuple[list[str], set[str], set[str] | None]:
    off = edits.apply_offset(scene, o["moved"][0], o["split_m"][0], o["split_m"][1], o["delta_m"][2])
    other = it.element_b if o["moved"][0] == it.element_a else it.element_a
    return off.pieces, set(off.pieces), {other, *it.others}


def _in_trial_trim(scene, it: Item, o: dict) -> tuple[list[str], set[str], set[str] | None]:
    edits.apply_trim(scene, o["moved"][0], o["trim"]["end"], o["trim"]["by_m"])
    return list(o["moved"]), set(o["moved"]), None


def _in_trial_route(scene, it: Item, o: dict) -> tuple[list[str], set[str], set[str] | None]:
    r = edits.apply_route(scene, o["moved"][0], o["edit"]["steps"])
    other = it.element_b if o["moved"][0] == it.element_a else it.element_a
    return r.pieces, set(r.pieces), {other, *it.others}


def _in_trial_resize(scene, it: Item, o: dict) -> tuple[list[str], set[str], set[str] | None]:
    e = o["edit"]
    r = edits.apply_resize(scene, o["moved"][0], e["split_m"], e["depth_m"], e.get("keep", "bottom"))
    other = it.element_b if o["moved"][0] == it.element_a else it.element_a
    return r.pieces, set(r.pieces), {other, *it.others}


def _in_trial_penetration(scene, it: Item, o: dict) -> tuple[list[str], set[str], set[str] | None]:
    service, host = o["edit"]["service"], o["edit"]["host"]
    pen = edits.penetration(scene, service, host, o["edit"].get("clearance_m", 0.025), o["edit"].get("fit", "annular"))
    edits.apply_penetration(scene, pen, cut=True)
    return [service], {service}, None   # the host is not its own: the service is checked against it


def _in_trial_combined(scene, it: Item, o: dict):
    a, b = o["edit"]["pair"]
    steps = agent.combined_steps(scene, {"steps": [agent.step_candidate(st) for st in o["edit"]["steps"]]}, a, b)
    made = agent.apply_combined(scene, steps)
    now = [g for _, els in made for g in els]

    def check(clearance_m: float, owner: dict[str, str]):
        # As a single proposal checks it (agent.check_combined), the plan's other fixes counted as obstacles too.
        hits, least, _ = agent.check_combined(scene, made, a, b, clearance_m, [*it.others, *owner])
        return hits, least
    return now, set(now), check


# How each kind of fix is applied inside a plan's trial: → (elements to check, the fix's own elements, the obstacles
# its shortened end pieces are checked against; None when every element it changed is checked against everything;
# or, for a fix of several runs, its own check: (clearance, the plan's elements by fix) → (hits, least clearance)).
IN_TRIAL = {"move": _in_trial_move, "offset": _in_trial_offset, "trim": _in_trial_trim, "route": _in_trial_route,
            "resize": _in_trial_resize, "penetration": _in_trial_penetration, "combined": _in_trial_combined}
# The files a fix changes beyond its moved elements' (a penetration's provision for void goes in the service's file).
EXTRA_FILES: dict[str, Callable[[dict], list[str]]] = {"penetration": lambda o: [o["edit"]["service"]]}
# Kinds whose element keeps the contacts it had (a trimmed member is framed into its neighbours, a service through a
# wall stays where it is): only contacts new or worse count, and the partner must clear (a trim may touch it).
KEEPS_CONTACTS = {"trim": lambda o: o["moved"], "penetration": lambda o: [o["edit"]["service"]]}


def option_files(scene, o: dict) -> set[int]:
    """The indexes of the files a fix changes."""
    return {scene.index_of(g) for g in [*o["moved"], *EXTRA_FILES.get(o["kind"], lambda _: [])(o)]}


def verify_together(ws: Workspace, scene_id: str, items: list[Item], clearance_m: float | None = None) -> dict:
    """Apply every item's chosen fix in one trial, check each against the whole model (the other fixes included),
    and undo. Returns {"passed", "items": {key: {"passed", "reason", "min_clearance_m"}}, "conflicts": [...]}.
    Each item keeps the clearance its coordination requirements ask for (25 mm without any), unless `clearance_m`."""
    scene = ws.scene(scene_id)
    live = [it for it in items if it.option]
    out: dict = {"passed": True, "items": {}, "conflicts": []}
    if not live:
        return {**out, "passed": False}
    need = {it.key: clearance_m if clearance_m is not None else
            ws.fix_settings(scene_id, it.element_a, it.element_b).get("clearance_m", 0.025) for it in live}
    with ws.lock:
        for it in live:
            if it.option["kind"] not in IN_TRIAL:
                raise ValueError(f"unknown kind of fix: {it.option['kind']!r}")
        files = set().union(*(option_files(scene, it.option) for it in live))
        # A trimmed member already touches what it is framed into: only contacts new or worse than these count.
        before = {it.key: {h.other: h.distance_m for h in verify.check(
                      scene, KEEPS_CONTACTS[it.option["kind"]](it.option), clearance_m=need[it.key]).hits}
                  for it in live if it.option["kind"] in KEEPS_CONTACTS}
        with _trial(scene, files):
            # key → (check these, own elements, obstacles of the shortened ends)
            changed: dict[str, tuple] = {}
            for it in live:
                changed[it.key] = IN_TRIAL[it.option["kind"]](scene, it, it.option)
            owner = {g: key for key, (_, own, _) in changed.items() for g in own}
            for it in live:
                clearance_m = need[it.key]
                check_ids, own, obstacles = changed[it.key]
                ignore = own | {c for g in own for c in scene.element(g).connected if c not in owner}
                least = None
                if callable(obstacles):   # a combined fix: each of its runs as it is checked alone
                    hits, least = obstacles(clearance_m, owner)
                    v = None
                elif obstacles:  # split runs: new pieces against everything, the shortened ends only against the obstacles
                    v = verify.check(scene, check_ids[1:-1], clearance_m=clearance_m, ignore=ignore)
                    ends = verify.check(scene, [check_ids[0], check_ids[-1]], clearance_m=clearance_m, ignore=ignore)
                    hits = v.hits + [h for h in ends.hits if h.other in obstacles or h.other in owner]
                else:
                    v = verify.check(scene, check_ids, clearance_m=clearance_m, ignore=ignore)
                    hits = v.hits
                if it.key in before:  # it keeps the contacts it had; a trim may butt its partner (and a service its
                    # fitted gland); a service through an annular opening must clear
                    mine = KEEPS_CONTACTS[it.option["kind"]](it.option)[0]
                    partner = it.element_b if mine == it.element_a else it.element_a
                    touch = it.option["kind"] == "trim" or (it.option.get("edit") or {}).get("fit") == "fitted"
                    was = before[it.key]
                    # Every element the item is for must clear (a merged item's others too); the rest only must not
                    # get worse.
                    meant = {partner, *it.others}
                    hits = [h for h in hits if ((h.distance_m < -0.002 or not touch) if h.other in meant
                                                else h.other not in was or h.distance_m < was[h.other] - 0.002)]
                for h in hits:
                    if h.other in owner and owner[h.other] != it.key:
                        out["conflicts"].append({"a": it.key, "b": owner[h.other],
                                                 "detail": f"{h.kind} {h.distance_m * 1000:+.0f} mm"})
                out["items"][it.key] = {"passed": not hits, "reason": agent._reason(hits),
                                        "min_clearance_m": v.min_clearance_m if v is not None else least}
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
            skipped.append(f"{c.label} ({c.test}): not in the open model")
            continue
        if m["a"] not in physical or m["b"] not in physical:
            skipped.append(f"{c.label} ({c.test}): a space or port, not a physical clash")
            continue
        key = "|".join(sorted([m["a"], m["b"]]))
        if key in items:
            items[key].clash_ids.append(cid)
            continue
        items[key] = Item(key, m["a"], m["b"], _label(ws, scene_id, m["a"], m["b"]), [cid], True, c.distance_m)
    return merge_shared(ws, scene_id, list(items.values())), skipped


def merge_shared(ws: Workspace, scene_id: str, items: list[Item]) -> list[Item]:
    """One problem, one fix: pairs that share an element which can move (a pipe through two conveyor rails, a duct
    through two beams) become one item, so one agent clears all of them at once. A shared element that stays put (a
    girder hit by three services) is not merged: each service gets its own fix."""
    scene = ws.scene(scene_id)
    count: dict[str, int] = {}
    for it in items:
        for g in (it.element_a, it.element_b):
            count[g] = count.get(g, 0) + 1
    shared = sorted((g for g, n in count.items() if n > 1 and not scene.element(g).fixed), key=lambda g: -count[g])
    used: set[str] = set()
    out: list[Item] = []
    for g in shared:
        group = [it for it in items if it.key not in used and g in (it.element_a, it.element_b)]
        if len(group) < 2:
            continue
        partners = [it.element_b if it.element_a == g else it.element_a for it in group]
        first = group[0]
        merged = Item("|".join(sorted([g, *partners])), g, partners[0], _merged_label(ws, scene_id, g, partners),
                      [c for it in group for c in it.clash_ids], all(it.in_report for it in group),
                      min((it.distance_m for it in group if it.distance_m is not None), default=first.distance_m),
                      others=partners[1:])
        out.append(merged)
        used.update(it.key for it in group)
    return out + [it for it in items if it.key not in used]


def _merged_label(ws: Workspace, scene_id: str, g: str, partners: list[str]) -> str:
    scene = ws.scene(scene_id)
    e = scene.element(g)
    names = [scene.element(p).name for p in partners]
    return f"{e.ifc_class} '{e.name}' x {len(partners)} elements: {', '.join(repr(n) for n in names)}"


def _direction(a) -> str:
    """"up 150 mm", "down 300 mm", "sideways 120 mm", "offset down 250 mm", "trimming it": what an idea did."""
    d = [float(x) for x in (a.delta_m or [0, 0, 0])]
    if getattr(a, "edit", None) and a.edit.get("summary"):
        return a.edit["summary"]
    if a.kind == "trim":
        return "trimming it"
    vertical = abs(d[2]) >= max(abs(d[0]), abs(d[1]))
    size = round(max(abs(x) for x in d) * 1000) if any(d) else 0
    move = (f"{'up' if d[2] > 0 else 'down'} {size} mm" if vertical else f"sideways {size} mm") if size else "in place"
    return f"offset {move}" if a.kind == "offset" else move


def failure_summary(scene, result) -> str:
    """Why nothing passed, in plain words, one line per idea: what it did and what it hit, by name; then the agent's
    advice. The full reasons stay with the attempts."""
    lines = []
    for a in result.attempts[:4]:
        if a.reason.startswith("cannot"):
            lines.append(f"{a.title}: {a.reason}")
            continue
        hit = []
        for g in a.hit_ids[:2]:
            try:
                hit.append(scene.entity(g).Name or scene.entity(g).is_a()[3:])
            except Exception:
                continue
        lines.append(f"{_direction(a)}: hits {', '.join(hit)}" if hit else f"{_direction(a)}: {a.reason}")
    if getattr(result, "advice", ""):
        lines.append(result.advice)
    return "\n".join(lines) or "No idea passed the geometry check."


def _resolve_items(ws: Workspace, scene_id: str, report_id: str | None, items: list[Item], notes: str,
                   emit: Callable[[dict], None], prefer: dict[str, str] | None = None) -> None:
    """Run the fix agent on every item at once (their model calls overlap; geometry trials take turns)."""
    def one(it: Item) -> None:
        emit({"type": "item", "key": it.key, "status": "thinking"})
        try:
            cid = it.clash_ids[0] if it.clash_ids and report_id else None
            also = ""
            if it.others:
                scene = ws.scene(scene_id)
                also = ("It also runs into: " + "; ".join(f"{scene.element(o).ifc_class} '{scene.element(o).name}'"
                                                          for o in it.others) + ". One fix must clear all of them.")
            clash = ws.clash_for(it.element_a, it.element_b, it.distance_m, None,
                                 "\n".join(filter(None, [notes, (prefer or {}).get(it.key, ""), also])), report_id, cid,
                                 scene_id)
            clash.others = list(it.others)

            def progress(e: dict) -> None:
                if e["type"] == "attempt":
                    emit({"type": "item", "key": it.key, "status": "checking", "attempt": e["title"], "passed": e["passed"]})
            stamp = ws._stamp(scene_id)
            result = agent.resolve(ws.scene(scene_id), clash, ws.model, on_event=progress, lock=ws.lock, max_rounds=2,
                                   hosts_model=ws.hosts_model,
                                   **ws.fix_settings(scene_id, it.element_a, it.element_b))
            # What a second try on this pair reads (Ask Muse Wonder on a failed item: docs/escalation.md).
            ws._remember(scene_id, it.element_a, it.element_b, asdict(result), stamp)
            it.understanding = result.understanding
            it.tried = len(result.attempts)
            options = [asdict(o) for o in result.options]
            it.option = options[0] if options else None
            it.alternatives = options[1:]
            if result.recommendation:
                it.recommended = True
                r = result.recommendation
                it.error = (f"Not edited: {r['blocked_by']}. Muse Spark recommends for the designer: {r['title']}"
                            + (f" ({r['rationale']})" if r.get("rationale") else ""))
            elif not options:
                it.error = failure_summary(ws.scene(scene_id), result)
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
    settings = ws.fix_settings(scene_id, hub["global_id"], cluster["partners"][0]["global_id"]) if cluster["partners"] else {}
    clearance_m = settings.get("clearance_m", 0.025)
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
                for h in edits.passages(scene, p["global_id"], hub["global_id"], clearance_m=clearance_m):
                    lines.append(f"    the hub has an opening on its line: offset it {h['dz_min_m']:+.3f} to "
                                 f"{h['dz_max_m']:+.3f} m to pass through with {clearance_m * 1000:.0f} mm clearance")
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
    doc = requirements.current()
    reply = ws.model.complete_json((PACKS / "root_cause.md").read_text()
                                   + (requirements.prompt_text(doc, "fixes") if doc else ""), text)
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
        # Every other partner is an obstacle of the same fix: a split hub's ends are checked against all of them.
        item = Item("|".join(sorted([hub, first["global_id"]])), hub, first["global_id"],
                    _label(ws, scene_id, hub, first["global_id"]), cluster["clash_ids"], True, first["distance_m"],
                    others=[p["global_id"] for p in cluster["partners"][1:]])
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
        # The hub changed: every partner pair must be clear. A move is checked against everything; a split hub's new
        # pieces against everything and its shortened ends against every partner (the item's `others`).
        check["covers"] = [p["global_id"] for p in cluster["partners"]]
    return Plan("root_cause", f"Root cause: {hub_el['ifc_class']} '{hub_el['name']}'", reply.get("root_cause", ""),
                strategy, cluster, items, check, round(time.perf_counter() - started, 1))


def _keep_move(ws: Workspace, scene_id: str, o: dict) -> tuple[dict, list[str]]:
    return ws.apply(scene_id, o["moved"], o["delta_m"]), []


def _keep_offset(ws: Workspace, scene_id: str, o: dict) -> tuple[dict, list[str]]:
    r = ws.apply_offset(scene_id, o["moved"][0], o["split_m"], o["delta_m"][2])
    return r, r["pieces"]


def _keep_trim(ws: Workspace, scene_id: str, o: dict) -> tuple[dict, list[str]]:
    return ws.apply_trim(scene_id, o["moved"][0], o["trim"]["end"], o["trim"]["by_m"]), []


def _keep_route(ws: Workspace, scene_id: str, o: dict) -> tuple[dict, list[str]]:
    r = ws.apply_route(scene_id, o["moved"][0], o["edit"]["steps"])
    return r, r["pieces"]


def _keep_resize(ws: Workspace, scene_id: str, o: dict) -> tuple[dict, list[str]]:
    e = o["edit"]
    r = ws.apply_resize(scene_id, o["moved"][0], e["split_m"], e["depth_m"], e.get("keep", "bottom"))
    return r, r["pieces"]


def _keep_penetration(ws: Workspace, scene_id: str, o: dict) -> tuple[dict, list[str]]:
    return ws.apply_penetration(scene_id, o["edit"]["service"], o["edit"]["host"]), []


def _keep_combined(ws: Workspace, scene_id: str, o: dict) -> tuple[dict, list[list[str]]]:
    r = ws.apply_combined(scene_id, o["edit"]["steps"], *o["edit"]["pair"])
    return r, r["pieces"]


# How each kind of fix is kept in the scene: → (the Workspace's reply, with "files"; the pieces, the original first;
# a fix of several runs, one such list per run).
KEEP = {"move": _keep_move, "offset": _keep_offset, "trim": _keep_trim, "route": _keep_route,
        "resize": _keep_resize, "penetration": _keep_penetration, "combined": _keep_combined}


def apply(ws: Workspace, scene_id: str, options: list[dict]) -> dict:
    """Keep every fix of an accepted plan (or one accepted option). Returns the files changed, per run a fix split its
    pieces with the original first (`pieces`: one list per fix, or per run of a combined fix; `groups`: those lists by
    fix), and the penetrations only requested (`not_cut`: the host's team cuts the opening)."""
    unknown = [o["kind"] for o in options if o.get("kind", "move") not in KEEP]
    if unknown:
        raise ValueError(f"unknown kind of fix: {unknown[0]!r}")
    files: set[int] = set()
    pieces: list[list[str]] = []
    changed: list[str] = []
    not_cut: list[dict] = []
    groups: list[list[list[str]]] = []
    with ws.lock:
        for k, o in enumerate(options):
            r, made = KEEP[o.get("kind", "move")](ws, scene_id, o)
            runs = made if made and isinstance(made[0], list) else [made] if made else []
            pieces += runs or [[]]
            groups.append(runs)
            files.update(r["files"])
            changed += r.get("changed", [g for run in runs for g in run] or o["moved"])
            if r.get("cut") is False:   # a penetration its host's team must cut: the clash stays open
                not_cut.append({"index": k, "blocked_by": r["blocked_by"]})
    return {"files": sorted(files), "pieces": pieces, "groups": groups, "changed": list(dict.fromkeys(changed)),
            "not_cut": not_cut}


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
    doc = requirements.current()
    reply = ws.model.complete_json((PACKS / "patterns.md").read_text()
                                   + (requirements.prompt_text(doc, "triage") if doc else ""), "\n".join(lines))
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
