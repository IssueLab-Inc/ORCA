"""Hand edits: what a person (or Muse, on their word) does to the model directly (docs/manual-edits.md).

Each edit is a small JSON op, the same from the page, chat, voice and MCP:

    {"op": "push_pull", "element": gid, "face": "east end", "by_m": 0.15}
    {"op": "align", "element": gid, "face": "cap:end", "to": {"element": gid2, "face": "west face"}, "gap_m": 0.025}
    {"op": "move", "element": gid, "delta_m": [0, 0, 0.3]}            (or "from" and "to" points)

`resolve` reads the op against the model (which face, how far, what it changes) without editing anything; `make`
edits in place, inside the caller's transaction, raising `edits.Unsupported` with a reason. `check` makes the edit in
a trial and measures it: what it clears, what it hits that it did not before (or hits harder), the nearest gap. `apply`
does all that again on the server (never trusting the page), refuses an edit that would make more clashes than the
person accepted, then keeps it through the edit log (journal.py) and returns what the page needs to redraw.

The coordination requirements bind hand edits as they bind fixes (`gate`). ORCA's own hard rules only warn here
(`warnings`): the person is the designer, and the log keeps who must review it.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Callable

import ifcopenshell.geom
import ifcopenshell.util.placement
import ifcopenshell.util.system
import numpy as np

from . import connections, detect, edits, faces, hosts, requirements, verify
from .scene import IfcScene, not_physical

PARALLEL_COS = np.cos(np.radians(1))   # two faces this close to parallel align by a push or a move; else a clip
LEAST_M = 0.0005                       # an edit shorter than this is already there
WORSE_M = 0.002                        # a contact this much deeper than before counts as worse (agent._try_trim)


class NotKept(ValueError):
    """The edit was not kept: refused, changed since its check, or it would make clashes nobody accepted."""


@dataclass
class Plan:
    op: str
    element: str
    params: dict                     # the op as read: faces by id, numbers in metres
    files: set[int]
    targets: list[str]               # existing elements it changes: checked before and after
    summary: str
    kind: str                        # what the requirements see: move, resize, trim, cut, any
    size_m: float = 0.0              # how far it takes the element (the requirements' largest move)
    gated: list[str] = field(default_factory=list)   # whose policies apply (default: the element)
    touching: set[str] = field(default_factory=set)  # what it is meant to meet (an align's target): no clearance
    face: faces.Face | None = None
    warnings: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class Made:
    changed: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    pieces: list[str] = field(default_factory=list)
    open_ends: list[str] = field(default_factory=list)


@dataclass
class Op:
    resolve: Callable[[IfcScene, dict], Plan]
    make: Callable[[IfcScene, Plan], Made]
    words: str                       # what it is, for Muse and the page


# ----------------------------------------------------------------------------------------------------- words


def class_words(cls: str) -> str:
    """IfcDuctSegment → "duct segment"."""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", cls[3:] if cls.startswith("Ifc") else cls).lower()


def label(scene: IfcScene, gid: str) -> str:
    e = scene.entity(gid)
    name = getattr(e, "Name", None)
    return f"{class_words(e.is_a())} '{name}'" if name else class_words(e.is_a())


def _mm(m: float) -> str:
    return f"{abs(m) * 1000:,.0f} mm"


def _num(op: dict, key: str, default=None) -> float:
    v = op.get(key, default)
    if v is None:
        raise ValueError(f"say {key}")
    v = float(v)
    if not np.isfinite(v):
        raise ValueError(f"{key} must be a finite number")
    return v


def _vec(v, what: str) -> np.ndarray:
    a = np.asarray(v, float).reshape(-1)
    if a.shape != (3,) or not np.all(np.isfinite(a)):
        raise ValueError(f"{what} is three numbers, metres")
    return a


# ----------------------------------------------------------------------------------------------------- faces


def face_of(scene: IfcScene, gid: str, spec) -> faces.Face:
    """A face from what the op says: its id or name ("east end"), or a pick ({"point", "normal"})."""
    if isinstance(spec, dict):
        if spec.get("point") is not None and spec.get("normal") is not None:
            return faces.resolve(scene, gid, _vec(spec["point"], "point"), _vec(spec["normal"], "normal"))
        spec = spec.get("face") or spec.get("id")
    if not isinstance(spec, str) or not spec:
        raise ValueError("say which face: its name (east end, top) or a point and a normal on it")
    return faces.by_name(scene, gid, spec)


def _ports_at(scene: IfcScene, gid: str, point, normal) -> list[str]:
    """Elements joined to `gid` through a port on the plane of this face."""
    out = []
    P, N = np.asarray(point, float), np.asarray(normal, float)
    for port in ifcopenshell.util.system.get_ports(scene.entity(gid)):
        other = ifcopenshell.util.system.get_connected_port(port)
        if other is None or port.ObjectPlacement is None:
            continue
        at = scene.placement(port.GlobalId)[:3, 3]
        if abs((at - P) @ N) <= 0.005:
            owner = ifcopenshell.util.system.get_port_element(other)
            if owner is not None:
                out.append(owner.GlobalId)
    return out


def _openings(element) -> list:
    return [r.RelatedOpeningElement for r in getattr(element, "HasOpenings", None) or []]


def _world_verts(entity) -> np.ndarray:
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    return np.asarray(ifcopenshell.geom.create_shape(settings, entity).geometry.verts, float).reshape(-1, 3)


# ----------------------------------------------------------------------------------------------------- warnings


def structure_warnings(scene: IfcScene, gid: str, what: str = "this change") -> list[dict]:
    """ORCA's own rules about structure, as warnings with who must review (they never block a person's edit)."""
    e = scene.entity(gid)
    name = label(scene, gid)
    above = hosts.stands_on(scene, gid) if e.is_a("IfcBeam") or e.is_a("IfcMember") else None
    if above:
        return [{"rule": "transfer", "review": "structure",
                 "text": f"{name} is a transfer element ({above} stands on it): a structural engineer must confirm {what}"}]
    if any(e.is_a(c) for c in ("IfcColumn", "IfcFooting", "IfcPile", "IfcBeam", "IfcSlab")):
        return [{"rule": "structure", "review": "structure",
                 "text": f"{name} is structure: a structural engineer must confirm {what}"}]
    if scene.stays(gid):
        return [{"rule": "stays", "review": "design",
                 "text": f"{name} stays in place under the coordination rules: its designer must confirm {what}"}]
    return []


def cut_warnings(scene: IfcScene, host: str) -> list[dict]:
    """ORCA's hard rules about cutting a host (never a transfer girder, a column, glazing), as warnings."""
    why = hosts.hard_rule(scene, host)
    if why:
        return [{"rule": "hard_rule", "review": "structure", "text": f"ORCA would never cut {label(scene, host)}: {why}"}]
    return structure_warnings(scene, host, "the opening")


# ----------------------------------------------------------------------------------------------------- push/pull


def _resolve_push(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    face = face_of(scene, gid, op.get("face") if not isinstance(op.get("face"), dict) else op["face"])
    if "push_pull" not in face.allows:
        raise edits.Unsupported(f"its {face.name} cannot be pushed or pulled" + (f": {face.why_not}" if face.why_not else
                                ": an I, U or L section's sides are its section, not a size to stretch"))
    by = _num(op, "by_m")
    if abs(by) < LEAST_M:
        raise edits.Unsupported("push or pull a face at least 0.5 mm")
    if face.kind == "cap":
        listed = next(f for f in faces.faces(scene, gid) if f.id == face.id)
        joined = _ports_at(scene, gid, listed.point, listed.normal)
        if joined:
            raise edits.Unsupported(f"its {face.name} is joined to {label(scene, joined[0])}: move the run instead, "
                                    "or split it first")
    size = face.size_m
    after = None if size is None else size + (2 * by if face.kind == "radial" else by)
    what = {"cap": "long" if face.name.endswith("end") else "thick" if face.name.endswith("face") else "deep",
            "side": "deep" if abs(face.normal[2]) > 0.9 else "wide", "radial": "across", "edge": "long"}.get(face.kind, "")
    change = f"{_mm(by)} {'out' if by > 0 else 'in'}"
    sizes = f" ({size:.3f} → {after:.3f} m {what})" if size is not None and after is not None and face.kind != "edge" else ""
    params = {"op": "push_pull", "element": gid, "face": face.id, "by_m": by}
    warn = structure_warnings(scene, gid, "the new size")
    if face.kind == "radial" and scene.entity(gid).is_a("IfcFlowSegment"):
        warn.append({"rule": "size", "review": "services",
                     "text": f"{label(scene, gid)} changes size: its designer must confirm what it carries"})
    return Plan("push_pull", gid, params, {scene.index_of(gid)}, [gid],
                f"{face.name} of {label(scene, gid)} pushed {change}{sizes}", "resize", abs(by), face=face, warnings=warn)


def _opening_corners(scene: IfcScene, gid: str) -> list[np.ndarray]:
    """The corners of the element's openings that lie in its outline, in the outline's plane (file units)."""
    element = scene.entity(gid)
    i, s, item, world = faces._world(scene, element)
    inv = np.linalg.inv(world)
    pts = faces.outline(item.SweptArea) or []
    out = []
    for o in _openings(element):
        try:
            v = _world_verts(o)
        except RuntimeError:
            continue
        lo, hi = v.min(axis=0), v.max(axis=0)
        for c in np.array(np.meshgrid(*zip(lo, hi))).T.reshape(-1, 3):
            q = (inv @ np.append(c / s, 1.0))[:2]
            if pts and edits.inside(pts, q):
                out.append(q)
    return out


def _stretch_openings(scene: IfcScene, gid: str, face: faces.Face, by: float) -> None:
    """A wall made thicker: its openings' ends on that face go out with it, so they still pass through."""
    if by <= 0:
        return
    n = np.asarray(face.normal)
    for o in _openings(scene.entity(gid)):
        try:
            i, s, item, world = faces._world(scene, o)
        except (edits.Unsupported, RuntimeError):
            continue
        d = world[:3, 2] / np.linalg.norm(world[:3, 2])
        try:   # drawn through the wall (its depth) or across it (a box's side): it grows the same way
            if abs(d @ n) > 0.999:
                edits.stretch(scene, o.GlobalId, "end" if d @ n > 0 else "start", by)
            else:
                edits.stretch(scene, o.GlobalId, "side", by, normal=n)
        except edits.Unsupported:
            continue


def _make_push(scene: IfcScene, plan: Plan) -> Made:
    gid, face, by = plan.element, plan.face, plan.params["by_m"]
    if face.kind == "cap":
        edits.stretch(scene, gid, face.id.split(":")[1], by)
        _stretch_openings(scene, gid, face, by)
    elif face.kind == "side":
        edits.stretch(scene, gid, "side", by, normal=face.normal)
    elif face.kind == "radial":
        edits.stretch_radius(scene, gid, by)
    elif face.kind == "edge":
        edits.offset_edge(scene, gid, int(face.id.split(":")[1]), by, keep_inside=_opening_corners(scene, gid))
    else:
        raise edits.Unsupported(f"its {face.name} cannot be pushed or pulled")
    return Made(changed=[gid])


# ----------------------------------------------------------------------------------------------------- move


def _resolve_move(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    if op.get("delta_m") is not None:
        delta = _vec(op["delta_m"], "delta_m")
    else:
        delta = _vec(op.get("to"), "to") - _vec(op.get("from"), "from")
    if np.linalg.norm(delta) < LEAST_M:
        raise edits.Unsupported("move it at least 0.5 mm")
    run = connections.run(scene, gid) if not op.get("alone") else [gid]
    plan = connections.plan_move(scene, run, delta.tolist())
    if not plan.ok:
        raise edits.Unsupported(f"it cannot keep its joints: {plan.refused}")
    changed = plan.changed()
    with_run = f" with its run ({len(run)} pieces)" if len(run) > 1 else ""
    return Plan("move", gid, {"op": "move", "element": gid, "delta_m": [round(float(x), 6) for x in delta]},
                {scene.index_of(g) for g in changed}, changed,
                f"{label(scene, gid)} moved {connections.move_words(delta.tolist())}{with_run}", "move",
                float(np.linalg.norm(delta)), gated=list(run), warnings=structure_warnings(scene, gid, "the move"),
                extra={"plan": plan})


def _make_move(scene: IfcScene, plan: Plan) -> Made:
    mp = connections.plan_move(scene, plan.extra["plan"].moved, plan.params["delta_m"])
    if not mp.ok:
        raise edits.Unsupported(f"it cannot keep its joints: {mp.refused}")
    connections.apply_move(scene, mp)
    broken = connections.check_joints(scene, mp)
    if broken:
        raise edits.Unsupported("a joint would not hold: " + "; ".join(w for *_, w in broken))
    return Made(changed=list(mp.changed()))


# ----------------------------------------------------------------------------------------------------- align


def _target_plane(scene: IfcScene, to: dict) -> tuple[np.ndarray, np.ndarray, str, str | None]:
    """The plane to align to: a face of another element (by name, id or pick), or a bare point and normal."""
    gid = to.get("element")
    if gid and (to.get("face") or (to.get("point") is not None and to.get("normal") is not None)):
        f = face_of(scene, gid, to if to.get("point") is not None else to["face"])
        listed = next((x for x in faces.faces(scene, gid) if x.id == f.id and x.kind != "other"), None)
        point = np.asarray(listed.point if listed is not None else f.point, float)
        return point, np.asarray(f.normal, float), f"{f.name} of {label(scene, gid)}", gid
    if to.get("point") is not None and to.get("normal") is not None:
        n = _vec(to["normal"], "normal")
        return _vec(to["point"], "point"), n / np.linalg.norm(n), "the plane picked", gid
    raise ValueError("say what to align to: an element and its face, or a point and a normal")


def _resolve_align(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    face = face_of(scene, gid, op.get("face"))
    if "align" not in face.allows:
        raise edits.Unsupported(f"its {face.name} cannot be aligned")
    listed = next((x for x in faces.faces(scene, gid) if x.id == face.id and x.kind != "other"), None)
    pa = np.asarray(listed.point if listed is not None else face.point, float)
    na = np.asarray(face.normal, float)
    pb, nb, target, other = _target_plane(scene, op.get("to") or {})
    if other == gid:
        raise edits.Unsupported("align it to another element's face")
    gap = _num(op, "gap_m", 0.0)
    cos = abs(na @ nb)
    if cos < PARALLEL_COS:
        raise edits.Unsupported(f"the faces are {np.degrees(np.arccos(min(cos, 1.0))):.0f}° apart, not parallel: clip "
                                "its end to that face instead")
    t = float(((pb - pa) @ nb) / (na @ nb)) - gap
    if abs(t) < LEAST_M:
        raise edits.Unsupported("it is already there")
    how = op.get("how") or ("stretch" if "push_pull" in face.allows else "move")
    where = "flush with" if abs(gap) < 1e-6 else f"{_mm(gap)} off"
    if how == "stretch":
        if "push_pull" not in face.allows:
            raise edits.Unsupported(f"its {face.name} cannot be stretched: move it instead")
        plan = _resolve_push(scene, {"op": "push_pull", "element": gid, "face": face.id, "by_m": t})
        plan.summary = f"{face.name} of {label(scene, gid)} stretched {_mm(t)} {'out' if t > 0 else 'in'}, {where} the {target}"
    elif how == "move":
        plan = _resolve_move(scene, {"op": "move", "element": gid, "delta_m": (na * t).tolist()})
        plan.summary = f"{label(scene, gid)} moved {_mm(t)} so its {face.name} is {where} the {target}"
    else:
        raise ValueError("how is stretch or move")
    plan.op = "align"
    plan.params = {"op": "align", "element": gid, "face": face.id, "to": op.get("to"), "gap_m": gap, "how": how,
                   "by_m": t, **({"delta_m": plan.params["delta_m"]} if how == "move" else {})}
    if other:
        plan.touching.add(other)
    plan.extra["how"] = how
    return plan


def _make_align(scene: IfcScene, plan: Plan) -> Made:
    return _make_move(scene, plan) if plan.extra.get("how") == "move" else _make_push(scene, plan)


# ----------------------------------------------------------------------------------------------------- void


def _resolve_void(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    face = face_of(scene, gid, op.get("face"))
    if "void" not in face.allows:
        raise edits.Unsupported(f"its {face.name} does not take an opening: pick one of its faces")
    n = np.asarray(face.normal, float)
    listed = next((x for x in faces.faces(scene, gid) if x.id == face.id), None)
    plane = np.asarray(listed.point if listed is not None and face.kind != "flank" else face.point, float)
    at = _vec(op["at"], "at") if op.get("at") is not None else np.asarray(face.point, float)
    at = at - ((at - plane) @ n) * n   # on the face's plane
    shape = op.get("shape") or ("round" if op.get("diameter_m") is not None else "rect")
    if shape not in ("rect", "round"):
        raise ValueError("shape is rect or round")
    if shape == "round":
        w = h = _num(op, "diameter_m")
    else:
        w, h = _num(op, "width_m"), _num(op, "height_m")
    if min(w, h) < 0.005:
        raise edits.Unsupported("an opening is at least 5 mm across")
    u, v = edits.face_axes(n)
    offsets = edits._outline(shape, w, h, u, v)
    blind = op.get("depth_m")
    if blind is not None:
        depth = _num(op, "depth_m")
        if depth <= 0:
            raise edits.Unsupported("a recess is at least 1 mm deep")
    else:
        depth = edits.through_depth(scene, gid, at, n, offsets)
        if depth is None:
            raise edits.Unsupported("it does not come out the other side here: give it a depth (a recess)")
    warn = cut_warnings(scene, gid)
    if edits.misses(scene, gid, at, n, edits._outline(shape, w + 2 * edits.OPENING_EDGE_M, h + 2 * edits.OPENING_EDGE_M, u, v)):
        warn.append({"rule": "edge", "review": None,
                     "text": f"it comes within {edits.OPENING_EDGE_M * 1000:.0f} mm of the face's edge: a notch more than a hole"})
    size = f"Ø{w * 1000:.0f}" if shape == "round" else f"{w * 1000:.0f} x {h * 1000:.0f}"
    kind = f"{depth * 1000:.0f} mm recess" if blind is not None else "opening"
    params = {"op": "void", "element": gid, "face": face.id, "at": [round(float(c), 4) for c in at], "shape": shape,
              **({"diameter_m": w} if shape == "round" else {"width_m": w, "height_m": h}),
              **({"depth_m": depth} if blind is not None else {})}
    return Plan("void", gid, params, {scene.index_of(gid)}, [gid], f"{size} mm {kind} cut in the {face.name} of {label(scene, gid)}",
                "cut", face=face, warnings=warn,
                extra={"shape": shape, "w": w, "h": h, "depth": depth, "n": n, "u": u, "at": at, "recess": blind is not None,
                       "name": f"{'Recess' if blind is not None else 'Opening'} {size}"})


def _make_void(scene: IfcScene, plan: Plan) -> Made:
    x = plan.extra
    proud = edits.OPENING_PROUD_M
    start = x["at"] + x["n"] * proud
    depth = x["depth"] + (proud if x["recess"] else 2 * proud)
    opening = edits.cut_void(scene, plan.element, x["shape"], x["w"], x["h"], start, -x["n"], x["u"], depth,
                             recess=x["recess"], name=x["name"])
    return Made(changed=[plan.element], created=[opening])


# ----------------------------------------------------------------------------------------------------- cut by shape


def _resolve_cut_by(scene: IfcScene, op: dict) -> Plan:
    gid, cutter = op["element"], op.get("cutter")
    if not isinstance(cutter, str) or not cutter:
        raise ValueError("say which element's shape cuts it (cutter)")
    if cutter == gid:
        raise edits.Unsupported("an element cannot cut itself")
    scene.index_of(cutter)
    if not_physical(scene.entity(cutter)):
        raise edits.Unsupported(f"{label(scene, cutter)} is not a physical element")
    gap = _num(op, "gap_m", 0.0)
    if gap < 0 or gap > 0.5:
        raise edits.Unsupported("the gap is between 0 and 500 mm")
    boxes = scene.bounds()
    a, b = boxes.get(gid), boxes.get(cutter)
    if a is None or b is None or np.any(a[0] > b[1] + gap) or np.any(b[0] > a[1] + gap):
        raise edits.Unsupported(f"{label(scene, cutter)} does not reach it: there is nothing to cut")
    return Plan("cut_by", gid, {"op": "cut_by", "element": gid, "cutter": cutter, "gap_m": gap}, {scene.index_of(gid)}, [gid],
                f"{label(scene, gid)} cut round {label(scene, cutter)}" + (f" with a {gap * 1000:.0f} mm gap" if gap else ""),
                "cut", warnings=cut_warnings(scene, gid), touching={cutter} if gap == 0 else set())


def _make_cut_by(scene: IfcScene, plan: Plan) -> Made:
    opening, exact = edits.cut_by_shape(scene, plan.element, plan.params["cutter"], plan.params["gap_m"])
    if not exact:
        plan.warnings.append({"rule": "approximate", "review": None,
                              "text": "the cutter is not plain extrusions: the gap is grown along its surface, approximately"})
    return Made(changed=[plan.element], created=[opening])


OPS: dict[str, Op] = {
    "push_pull": Op(_resolve_push, _make_push, "push or pull one face: a length, a width, a radius, a wall's end"),
    "align": Op(_resolve_align, _make_align, "make one face flush with another face (or a gap off it), by stretching or moving"),
    "move": Op(_resolve_move, _make_move, "move an element (and the straight run it is in) by a vector"),
    "void": Op(_resolve_void, _make_void, "cut a rectangular or round opening through a face (or a recess to a depth)"),
    "cut_by": Op(_resolve_cut_by, _make_cut_by, "cut an element where another element is, with a gap all round"),
}


# ----------------------------------------------------------------------------------------------------- the check


def resolve(scene: IfcScene, op: dict) -> Plan:
    if not isinstance(op, dict):
        raise ValueError("an edit is an object with op and element")
    name = op.get("op")
    if name not in OPS:
        raise ValueError(f"unknown edit {name!r}: one of {', '.join(OPS)}")
    gid = op.get("element")
    if not isinstance(gid, str) or not gid:
        raise ValueError("say which element (its GlobalId)")
    scene.index_of(gid)
    return OPS[name].resolve(scene, op)


def gate(scene: IfcScene, plan: Plan) -> str | None:
    """Why the coordination requirements forbid this edit, or None."""
    doc = requirements.current()
    if doc is None:
        return None
    m = requirements.Matcher(scene, doc)
    for gid in plan.gated or [plan.element]:
        pol = requirements.policy(doc, m, gid)
        if plan.kind == "cut":
            if not requirements.can_cut(pol):
                return f"blocked by requirements: {pol.group_name} may not be cut"
        elif plan.kind == "any":
            if pol.edits != "any":
                return (f"blocked by requirements: {pol.group_name} "
                        + ("may only be moved whole" if pol.edits == "move" else "may not be edited"))
        else:
            why = requirements.blocked(pol, None, plan.kind, [plan.size_m], True)
            if why:
                return why
    return None


def _hit(scene: IfcScene, h: verify.Hit) -> dict:
    out = asdict(h)
    try:
        out["name"] = label(scene, h.other)
    except KeyError:
        out["name"] = h.other_class
    return out


def _exists(scene: IfcScene, gid: str) -> bool:
    try:
        scene.index_of(gid)
        return True
    except KeyError:
        return False


def key_of(op: dict, revision: int) -> str:
    raw = json.dumps({"op": op, "revision": revision, "requirements": requirements.current_id()}, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def check(ws, scene_id: str, op: dict, preview: bool = True) -> dict:
    """Make the edit in a trial and measure it; nothing is kept. Refusals come back as `blocked` with why."""
    scene = ws.scene(scene_id)
    with ws.lock:
        try:
            plan = resolve(scene, op)
        except (edits.Unsupported, KeyError, ValueError, TypeError) as e:
            return {"op": op, "passed": False, "blocked": str(e).strip("'\""), "warnings": [], "clashes": 0}
        refused = gate(scene, plan)
        base = {"op": plan.params, "summary": plan.summary, "face": plan.face.to_dict() if plan.face else None,
                "warnings": plan.warnings, "revision": scene.revision, "key": key_of(plan.params, scene.revision),
                "targets": plan.targets}
        if refused:
            return {**base, "passed": False, "blocked": refused, "clashes": 0}
        clearance = ws.clearance(scene_id)
        boxes = scene.bounds()
        targets = [g for g in plan.targets if g in boxes]
        before = {h.other: h for h in verify.check(scene, targets, clearance_m=clearance).hits} if targets else {}
        shapes_before = edits.meshes(scene, [g for g in plan.targets if _exists(scene, g)]) if preview else None
        try:
            with edits.trial_files(scene, plan.files):
                made = OPS[plan.op].make(scene, plan)
                boxes = scene.bounds()
                mine = [g for g in dict.fromkeys([*made.changed, *made.created]) if g in boxes]
                v = (verify.check(scene, mine, clearance_m=clearance, ignore=set(mine), touching=plan.touching)
                     if mine else verify.Verdict(True, [], None, 0))
                shapes = edits.meshes(scene, [g for g in dict.fromkeys([*made.changed, *made.created])
                                              if _exists(scene, g) and not not_physical(scene.entity(g))]) if preview else None
        except edits.Unsupported as e:
            return {**base, "passed": False, "blocked": str(e), "clashes": 0}
        hits = [h for h in v.hits if not (h.other in plan.touching and h.distance_m > -WORSE_M)]
        new = [h for h in hits if h.other not in before]
        worse = [h for h in hits if h.other in before and h.distance_m < before[h.other].distance_m - WORSE_M]
        still = {h.other for h in v.hits if h.kind == "collision"}   # closer than the clearance is no longer a clash
        cleared = [{"other": g, "name": label(scene, g) if _exists(scene, g) else g, "was_m": before[g].distance_m}
                   for g in before if g not in still and before[g].kind == "collision"]
        clashes = [h for h in new + worse if h.kind == "collision"]
        return {**base, "passed": not clashes, "blocked": None, "clashes": len(clashes),
                "close": len([h for h in new + worse if h.kind != "collision"]),
                "new": [_hit(scene, h) for h in new], "worse": [_hit(scene, h) for h in worse], "cleared": cleared,
                "min_clearance_m": v.min_clearance_m, "checked_against": v.checked_against,
                "changed": made.changed, "created": made.created, "removed": made.removed, "open_ends": made.open_ends,
                "preview": shapes, "before": shapes_before}


def apply(ws, scene_id: str, op: dict, *, key: str | None = None, accept_clashes: int = 0, source: str = "you",
          actor: str | None = None, clash_id: str | None = None, pair: list[str] | None = None) -> dict:
    """Keep a hand edit: checked again first, here and now; refused (NotKept) when the requirements forbid it, the
    model changed since its check (`key`), or it would make more clashes than `accept_clashes`. Kept through the edit
    log, tied to the clash (`clash_id`, `pair`) and to any fix it follows; the clash is measured again after."""
    scene = ws.scene(scene_id)
    log = ws.journal(scene_id)
    with ws.lock:
        r = check(ws, scene_id, op, preview=False)
        if r.get("blocked"):
            raise NotKept(r["blocked"])
        if key and key != r["key"]:
            raise NotKept("the model changed since this edit was checked: check it again")
        if r["clashes"] > max(int(accept_clashes or 0), 0):
            n = r["clashes"]
            raise NotKept(f"it would make {n} clash{'es' if n > 1 else ''} ({', '.join(h['name'] for h in r['new'][:3])}): "
                          f"keep it with {n} clash{'es' if n > 1 else ''} to go ahead")
        plan = resolve(scene, op)
        clashes = [{"id": clash_id, "pair": list(pair)}] if pair and len(pair) == 2 else (
            [{"id": clash_id, "pair": None}] if clash_id else [])
        with log.record(scene, source, plan.op, actor=actor, requirements=requirements.current_id()) as rec, \
                edits.kept_files(scene, plan.files):
            made = OPS[plan.op].make(scene, plan)
            scene._edited.update(plan.files)   # export writes these files
            scene.bump(plan.files)
            rec.changed, rec.summary, rec.title = list(made.changed), plan.summary, plan.summary
            rec.params, rec.clashes, rec.warnings = plan.params, clashes, list(r["warnings"])
            rec.check = {"verified": False, "cleared": r["cleared"], "new": r["new"], "worse": r["worse"],
                         "accepted_clashes": r["clashes"], "min_clearance_m": r["min_clearance_m"]}
        entry = rec.entry
        if entry is not None:
            entry.status = _status(scene, log, entry)
    return {"entry": entry.to_dict() if entry else None, "files": sorted(plan.files),
            "changed": list(dict.fromkeys([*made.changed, *made.created])), "created": made.created,
            "removed": made.removed, "pieces": made.pieces, "check": {k: v for k, v in r.items() if k not in ("preview", "before")}}


def _status(scene: IfcScene, log, entry) -> dict | None:
    """Where the entry's clash stands now: its elements, and everything a fix made from them, measured again."""
    for c in entry.clashes:
        pair = c.get("pair")
        if not pair or len(pair) != 2:
            continue
        left = [g for g in log.made_from(pair[0]) if g in scene.bounds()]
        right = [g for g in log.made_from(pair[1]) if g in scene.bounds()]
        depths = [d for x in left for y in right if x != y for d in [detect.measure_pair(scene, x, y)] if d is not None]
        worst = min(depths) if depths else None
        return {"clash": c.get("id"), "pair": pair, "resolved": worst is None, "depth_m": worst}
    return None


def describe() -> str:
    """The edits there are, one line each, for Muse's tool notes."""
    return "; ".join(f"{name}: {op.words}" for name, op in OPS.items())
