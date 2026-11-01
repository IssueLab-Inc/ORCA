"""Hand edits: what a person (or Muse, on their word) does to the model directly (docs/manual-edits.md).

Each edit is a small JSON op, the same from the page, chat, voice and MCP:

    {"op": "push_pull", "element": gid, "face": "east end", "by_m": 0.15}
    {"op": "align", "element": gid, "face": "cap:end", "to": {"element": gid2, "face": "west face"}, "gap_m": 0.025}
    {"op": "move", "element": gid, "delta_m": [0, 0, 0.3]}            (or "from" and "to" points)

An edit changes the face or element picked and nothing else (owner decision, Nov 1): a joint it leaves open is listed
and kept only when the person says so. `"carry": true` takes joined parts along instead: a straight neighbour follows a
pushed cap, a move takes its run and fittings.

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

from . import connections, consistency, detect, edits, faces, hosts, parametric, requirements, verify
from .scene import IfcScene, not_physical

PARALLEL_COS = np.cos(np.radians(1))   # two faces this close to parallel meet all over when aligned
ALIGN_MAX_DEG = 80                     # past this apart, a face meets the other at its first corner only: clip instead
LEAST_M = 0.0005                       # an edit shorter than this is already there
WORSE_M = 0.002                        # a contact this much deeper than before counts as worse (agent._try_trim)
MIN_HAND_M = 0.005                     # the least a hand edit leaves of a length or a width (fixes keep MIN_PIECE_M)
PICKED = ("other", "flank", "plane")   # faces whose plane only a pick on them says: a name is not enough


class NotKept(ValueError):
    """The edit was not kept: refused, changed since its check, or it would make clashes nobody accepted."""


def carries(op: dict) -> bool:
    """Whether the edit takes joined parts along (`carry`); by default it changes the picked face or element only.
    The old opt-out `alone` is still read: it never carries."""
    return bool(op.get("carry")) and not op.get("alone")


def to_type(op: dict) -> bool:
    """Whether the person applies the edit to the element's type (`scope: "type"`): the shape or section its type gives
    changes for every element of the type, each checked. By default an edit is the element's own (owner decision)."""
    return op.get("scope") == "type"


TYPE_OPS = ("push_pull", "align")   # the edits that change what a type gives: its shape, its section


class Offered(edits.Unsupported):
    """Refused as asked, with another way the page can offer (an op): "Move it on its own"."""

    def __init__(self, message: str, offer: dict, words: str):
        super().__init__(message)
        self.offer, self.words = offer, words


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
    """A face from what the op says: its id or name ("east end"), or a pick ({"point", "normal"}). A face only a pick
    can place (an I-section's sides, a clipped end, a fitting's face) is refused by name: say where on it."""
    if isinstance(spec, dict):
        if spec.get("point") is not None and spec.get("normal") is not None:
            return faces.resolve(scene, gid, _vec(spec["point"], "point"), _vec(spec["normal"], "normal"))
        spec = spec.get("face") or spec.get("id")
    if not isinstance(spec, str) or not spec:
        raise ValueError("say which face: its name (east end, top) or a point and a normal on it")
    f = faces.by_name(scene, gid, spec)
    if f.kind == "plane" and f.point:   # a mesh's face as listed: its middle is on it
        return faces.resolve(scene, gid, np.asarray(f.point), np.asarray(f.normal))
    if f.kind in PICKED:
        raise ValueError(f"its {f.name if f.kind != 'other' else 'faces'} need a pick: give a point and a normal on the face")
    return f


def spec(face: faces.Face):
    """How the op as read names its face, so its check and its keep read the same face: its id, or the pick for a face
    only a pick places (and a round side, whose normal is where it was picked)."""
    if face.kind in PICKED or face.kind == "radial":
        return {"point": [round(float(c), 6) for c in face.point], "normal": [round(float(c), 6) for c in face.normal]}
    return face.id


def plane_point(scene: IfcScene, gid: str, face: faces.Face) -> np.ndarray:
    """A point on the face's plane: the listed face's middle for a face ORCA sizes (a cap, a rectangle's side, an
    outline edge), else the pick itself (a flank, a clipped end, a round side, a fitting's face)."""
    if face.kind in ("cap", "side", "edge"):
        listed = next((x for x in faces.faces(scene, gid) if x.id == face.id), None)
        if listed is not None and listed.point:
            return np.asarray(listed.point, float)
    return np.asarray(face.point, float)


def _ports_at(scene: IfcScene, gid: str, point, normal) -> list[str]:
    """Elements joined to `gid` through a port on the plane of this face."""
    return [peer for _, _, peer in _joints_at(scene, gid, point, normal)]


def _joints_at(scene: IfcScene, gid: str, point, normal) -> list[tuple[object, object, str]]:
    """The joints on the plane of this face: (its port, the port it joins, the element that port is on)."""
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
                out.append((port, other, owner.GlobalId))
    return out


def _follows(scene: IfcScene, gid: str, face: faces.Face, peer: str, other) -> str | None:
    """Which cap of `peer` stretches with this face so their joint moves and holds: a straight segment of one
    extrusion on the face's axis, joined at its start or end cap. None: it cannot follow (a fitting, a branch)."""
    if face.kind != "cap" or faces.split_id(face.id)[0] is not None:
        return None
    sol = edits.solids(scene, scene.entity(peer))
    if len(sol) != 1 or sol[0].kind != "extrusion" or not scene.entity(peer).is_a("IfcFlowSegment"):
        return None
    try:
        run = edits.run_of(scene, peer)
    except (edits.Unsupported, AttributeError):
        return None
    if abs(np.asarray(run.direction) @ np.asarray(face.normal)) < 0.999:
        return None
    at = scene.placement(other.GlobalId)[:3, 3]
    if np.linalg.norm(at - np.asarray(run.start)) <= 0.005:
        return "start"
    if np.linalg.norm(at - np.asarray(run.end)) <= 0.005:
        return "end"
    return None


def _open_joint_words(scene: IfcScene, gid: str, peers: list[dict]) -> dict:
    names = ", ".join(p["name"] for p in peers[:3])
    return {"rule": "open_joint", "review": "services",
            "text": f"{label(scene, gid)} is no longer joined to {names}: its designer must join or cap "
                    f"{'it' if len(peers) == 1 else 'them'}"}


def _openings(element) -> list:
    return [r.RelatedOpeningElement for r in getattr(element, "HasOpenings", None) or []]


def _world_verts(entity) -> np.ndarray:
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    return np.asarray(ifcopenshell.geom.create_shape(settings, entity).geometry.verts, float).reshape(-1, 3)


# ----------------------------------------------------------------------------------------------------- warnings


def structure_warnings(scene: IfcScene, gid: str, what: str = "this change") -> list[dict]:
    """ORCA's own rules about structure, as warnings with who must review (they never block a person's edit)."""
    name = label(scene, gid)
    above = hosts.transfer(scene, gid)   # the domain's own rules (hosts.py), never a class list here
    if above:
        return [{"rule": "transfer", "review": "structure",
                 "text": f"{name} is a transfer element ({above} stands on it): a structural engineer must confirm {what}"}]
    if hosts.structural(scene, gid):
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
    face = face_of(scene, gid, op.get("face"))
    if "push_pull" not in face.allows:
        raise edits.Unsupported(f"its {face.name} cannot be pushed or pulled" + (f": {face.why_not}" if face.why_not else
                                ": an I, U or L section's sides are its section, not a size to stretch"))
    by = _num(op, "by_m")
    if abs(by) < LEAST_M:
        raise edits.Unsupported("push or pull a face at least 0.5 mm")
    follow, opened = [], []
    if face.kind in ("cap", "plane", "side"):
        for port, other, peer in _joints_at(scene, gid, plane_point(scene, gid, face), face.normal):
            cap = _follows(scene, gid, face, peer, other) if carries(op) else None
            if cap is not None:   # a straight segment on its axis: it stretches too, and the joint moves and holds
                length = edits.run_of(scene, peer).length_m
                if length - by < MIN_HAND_M - 1e-9:
                    raise edits.Unsupported(f"{label(scene, peer)} it is joined to would be under "
                                            f"{MIN_HAND_M * 1000:.0f} mm: move the run instead")
                follow.append((peer, cap))
            else:                 # anything else: the joint is left open, kept only when the person says so
                opened.append({"element": peer, "name": label(scene, peer), "port": port.GlobalId})
    size = face.size_m
    after = None if size is None else size + (2 * by if face.kind == "radial" else by)
    what = {"cap": "long" if face.name.endswith("end") else "thick" if face.name.endswith("face") else "deep",
            "side": "deep" if abs(face.normal[2]) > 0.9 else "wide", "radial": "across", "edge": "long",
            "plane": "thick behind it", "clip": "long behind it"}.get(face.kind, "")
    change = f"{_mm(by)} {'out' if by > 0 else 'in'}"
    sizes = f" ({size:.3f} → {after:.3f} m {what})" if size is not None and after is not None and face.kind != "edge" else ""
    params = {"op": "push_pull", "element": gid, "face": spec(face), "by_m": by}
    warn = structure_warnings(scene, gid, "the new size")
    if face.kind == "side":
        so = edits.solid(scene, scene.entity(gid), faces.split_id(face.id)[0], through_maps=True)
        prof = so.item.SweptArea if so.kind == "extrusion" else None
        if prof is not None and prof.is_a() in edits.SECTION_DIMS:
            name = f" ({prof.ProfileName})" if prof.ProfileName else ""
            warn.append({"rule": "section", "review": "structure",
                         "text": f"{label(scene, gid)} changes section{name}: a structural engineer must confirm the new section"})
    if face.kind == "radial" and scene.entity(gid).is_a("IfcFlowSegment"):
        warn.append({"rule": "size", "review": "services",
                     "text": f"{label(scene, gid)} changes size: its designer must confirm what it carries"})
    # A duct's or pipe's section changed where it is joined: carried, a transition back to the old size at each joined
    # end keeps the joints meeting what they join; on its own, the ends no longer match (said so)
    resized_ends = (edits.joined_caps(scene, gid) if face.kind in ("side", "radial") and faces.split_id(face.id)[0] is None
                    and scene.entity(gid).is_a("IfcFlowSegment") and scene.entity(gid).is_a() in edits.TRANSITION_TYPE else [])
    transitions = resized_ends if carries(op) else []
    if resized_ends and not transitions:
        warn.append({"rule": "size", "review": "services",
                     "text": f"{label(scene, gid)} no longer matches the size of what it joins at its "
                             f"{' and '.join(resized_ends)}: take joined parts along to add transitions"})
    if carries(op):
        params["carry"] = True
    share = parametric.type_share(scene, gid, face, label) if to_type(op) else None
    if share is not None:
        params["scope"] = "type"
    if opened:
        warn.append(_open_joint_words(scene, gid, opened))
    kept = f"; {', '.join(label(scene, p) for p, _ in follow)} {'shorter' if by > 0 else 'longer'} so the joint holds" if follow else ""
    if transitions:
        kept += f"; a transition back to its old size at its {' and '.join(transitions)}"
    others = share.others if share is not None else []
    if share is not None:
        n = len(others)
        kept += (f"; its type {share.type_name} too" + (f", and the {n} other element{'s' if n > 1 else ''} of it"
                                                         if n else ""))
    plan = Plan("push_pull", gid, params, {scene.index_of(gid), *(scene.index_of(p) for p, _ in follow)},
                [gid, *(p for p, _ in follow), *others], f"{face.name} of {label(scene, gid)} pushed {change}{sizes}{kept}",
                "resize", abs(by), gated=[gid, *(p for p, _ in follow), *others], face=face, warnings=warn)
    plan.extra.update(follow=follow, open_joints=opened, transitions=transitions)
    if share is not None:   # what the edit changes of the type is changed on purpose: every element of it is checked
        plan.extra.update(type_share=share, consistent=("type",) if share.kind == "map" else ("shared",))
        if share.kind == "layers":
            plan.summary += f" (each wall of it {'thicker' if by > 0 else 'thinner'} on the same layer)"
    return plan


def _push_face(scene: IfcScene, gid: str, point, normal, by: float) -> list[str]:
    """Push another element's face, found by a point and normal on it, as a hand push would (its own openings, layers
    and quantities following): for an edit to a type that every element of it follows."""
    face = faces.resolve(scene, gid, np.asarray(point, float), np.asarray(normal, float))
    if float(np.asarray(face.normal, float) @ np.asarray(normal, float)) < 0.99:
        raise edits.Unsupported(f"{label(scene, gid)} has no face there to follow its type")
    sub = _resolve_push(scene, {"op": "push_pull", "element": gid, "face": spec(face), "by_m": by})
    return _make_push(scene, sub).changed


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


def _openings_on(scene: IfcScene, gid: str, face: faces.Face) -> list:
    """The element's openings that reach this face (measured before the push): their far side on the face's side is at
    its plane or stands proud of it (an opening is drawn 10 mm or more past the faces it passes through). A beam's web
    opening is not on its end, nor a slab's soffit recess on its top."""
    n = np.asarray(face.normal, float)
    level = float(plane_point(scene, gid, face) @ n)
    out = []
    for o in _openings(scene.entity(gid)):
        try:
            v = _world_verts(o) @ n
        except RuntimeError:
            continue
        if -faces.NEAR_M <= v.max() - level <= 0.2 and v.min() < level:
            out.append(o)
    return out


def _stretch_openings(scene: IfcScene, openings: list, face: faces.Face, by: float) -> None:
    """A wall made thicker: the openings through the pushed face go out with it, so they still pass through."""
    if by <= 0:
        return
    n = np.asarray(face.normal)
    for o in openings:
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
    k, own = faces.split_id(face.id)    # which solid of the body (None: its one solid), and the face's own id
    hand = {"least_m": MIN_HAND_M, "unique": True}
    # The openings through this face, found before it moves: a thicker wall, however drawn (an elevation's cap, a plan
    # rectangle's side, a plan outline's edge), takes them with it
    through = _openings_on(scene, gid, face) if k is None and by > 0 and face.kind in ("cap", "side", "edge") else []
    before = edits.section_of(scene, gid) if plan.extra.get("transitions") else None
    share = plan.extra.get("type_share")
    held = parametric.hold(scene, gid, share) if share is not None else None
    if face.kind == "cap":
        edits.stretch(scene, gid, own.split(":")[1], by, clipped=edits._is_clipped(scene.entity(gid), k), item=k, **hand)
    elif face.kind == "side":
        edits.stretch(scene, gid, "side", by, normal=face.normal, clipped=edits._is_clipped(scene.entity(gid), k), item=k,
                      sections=True, **hand)
    elif face.kind == "radial":
        edits.stretch_radius(scene, gid, by, unique=True, item=k)
    elif face.kind == "edge":
        edits.offset_edge(scene, gid, int(own.split(":")[1]), by, unique=True, item=k,
                          keep_inside=_opening_corners(scene, gid) if k is None else [])
    elif face.kind == "plane":
        edits.push_mesh_face(scene, gid, face.point, face.normal, by, item=k, **hand)
    elif face.kind == "clip":
        edits.move_clip(scene, gid, int(own.split(":")[1]), by, item=k, least_m=MIN_HAND_M)
    else:
        raise edits.Unsupported(f"its {face.name} cannot be pushed or pulled")
    _stretch_openings(scene, through, face, by)
    followed = parametric.to_type(scene, gid, share, held,
                                     push=lambda g, p, n, by: _push_face(scene, g, p, n, by)) if share is not None else []
    made = edits.add_transitions(scene, gid, before, plan.extra["transitions"]) if before is not None else []
    for peer, cap in plan.extra.get("follow", []):   # its joined segment's end goes the same way: the joint holds
        edits.stretch(scene, peer, cap, -by, **hand)
    model = scene.models[scene.index_of(gid)]
    for j in plan.extra.get("open_joints", []):
        port = model.by_guid(j["port"])
        if ifcopenshell.util.system.get_connected_port(port) is not None:
            ifcopenshell.api.run("system.disconnect_port", model, port=port)
    return Made(changed=[gid, *(p for p, _ in plan.extra.get("follow", [])), *followed], created=made,
                open_ends=[gid, *(j["element"] for j in plan.extra.get("open_joints", []))] if plan.extra.get("open_joints") else [])


# ----------------------------------------------------------------------------------------------------- move

RETRIM_MIN_COS = 0.2   # a joined wall this close to in line with the moved one cannot follow a move across it


def _retrims(scene: IfcScene, gid: str, delta) -> list[Plan]:
    """A carried move of an element with path joins (a wall drawn with an axis): each wall whose end is joined to it
    (ATSTART or ATEND on that wall's side) has that end pushed along its own axis so it meets the moved one as it did, in
    plan (docs/editing-parity.md, "A carried wall end"). Done with the hand edits' own push, so its axis, layers,
    quantities and openings come along, and refused as a push would be. Ends in line with the moved wall, or that only
    a pick could place, are left: their joins open as for a move on its own."""
    e = scene.entity(gid)
    mine = consistency._world_axis(scene, e)
    if mine is None:
        return []
    dm = mine[1][:2] - mine[0][:2]
    if np.linalg.norm(dm) < 1e-9:
        return []
    n_m = np.array([-dm[1], dm[0]]) / np.linalg.norm(dm)
    d = np.asarray(delta, float)[:2]
    out = []
    for rel in [*getattr(e, "ConnectedTo", []), *getattr(e, "ConnectedFrom", [])]:
        if not rel.is_a("IfcRelConnectsPathElements"):
            continue
        other, at = ((rel.RelatedElement, rel.RelatedConnectionType) if rel.RelatingElement == e
                     else (rel.RelatingElement, rel.RelatingConnectionType))
        if at not in ("ATSTART", "ATEND") or not scene.has(other.GlobalId):
            continue
        theirs = consistency._world_axis(scene, other)
        if theirs is None:
            continue
        du = theirs[1][:2] - theirs[0][:2]
        if np.linalg.norm(du) < 1e-9:
            continue
        u = du / np.linalg.norm(du)
        cos = float(u @ n_m)
        if abs(cos) < RETRIM_MIN_COS:
            continue
        t = float(d @ n_m) / cos   # how far along its axis its end goes to stay where it met the moved one's
        if abs(t) < LEAST_M:
            continue
        end = theirs[0] if at == "ATSTART" else theirs[1]
        outward = -u if at == "ATSTART" else u
        box = scene.bounds()[other.GlobalId]
        middle = box.mean(axis=0)
        across = middle[:2] - end[:2]
        across = across - (across @ u) * u          # the end face's middle: the axis end, across to the body's middle
        point = np.array([*(end[:2] + across), middle[2]])
        try:
            face = faces.resolve(scene, other.GlobalId, point, np.array([*outward, 0.0]))
        except (edits.Unsupported, ValueError, KeyError):
            continue
        if float(np.asarray(face.normal, float) @ np.array([*outward, 0.0])) < 0.99 or "push_pull" not in face.allows:
            continue
        out.append(_resolve_push(scene, {"op": "push_pull", "element": other.GlobalId, "face": spec(face),
                                         "by_m": t if at == "ATEND" else -t}))
    return out


def _resolve_move(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    if op.get("delta_m") is not None:
        delta = _vec(op["delta_m"], "delta_m")
    else:
        delta = _vec(op.get("to"), "to") - _vec(op.get("from"), "from")
    if np.linalg.norm(delta) < LEAST_M:
        raise edits.Unsupported("move it at least 0.5 mm")
    params = {"op": "move", "element": gid, "delta_m": [round(float(x), 6) for x in delta]}
    words = connections.move_words(delta.tolist())
    if not carries(op):   # the element only: every joint it has is left open, kept only when the person says so
        opened = []
        for port in ifcopenshell.util.system.get_ports(scene.entity(gid)):
            other = ifcopenshell.util.system.get_connected_port(port)
            owner = ifcopenshell.util.system.get_port_element(other) if other is not None else None
            if owner is not None:
                opened.append({"element": owner.GlobalId, "name": label(scene, owner.GlobalId), "port": port.GlobalId})
        warn = structure_warnings(scene, gid, "the move") + ([_open_joint_words(scene, gid, opened)] if opened else [])
        return Plan("move", gid, params, {scene.index_of(gid)}, [gid],
                    f"{label(scene, gid)} moved {words}{' on its own' if opened else ''}", "move",
                    float(np.linalg.norm(delta)), gated=[gid],
                    warnings=warn, extra={"plan": connections.MovePlan([gid], [float(x) for x in delta]), "open_joints": opened})
    run = connections.run(scene, gid)
    plan = connections.plan_move(scene, run, delta.tolist(), refit=True)   # a neighbour square to it re-fitted
    if not plan.ok:
        raise Offered(f"it cannot keep its joints: {plan.refused}", params, "Move it on its own")
    changed = plan.changed()
    with_run = f" with its run ({len(run)} pieces)" if len(run) > 1 else ""
    params = {**params, "carry": True}
    retrim = [r for r in _retrims(scene, gid, delta) if r.element not in changed]
    follows = "".join(f"; the {r.face.name} of {label(scene, r.element)} follows it "
                      f"({_mm(r.params['by_m'])} {'longer' if r.params['by_m'] > 0 else 'shorter'})" for r in retrim)
    follows += "".join(f"; {label(scene, j.global_id)} re-fitted at its {j.end} with a pair of bends, the rest where it is"
                       for j in plan.jogs)
    return Plan("move", gid, params, {scene.index_of(g) for g in [*changed, *(r.element for r in retrim)]},
                [*changed, *(r.element for r in retrim)], f"{label(scene, gid)} moved {words}{with_run}{follows}", "move",
                float(np.linalg.norm(delta)), gated=[*run, *(j.global_id for j in plan.jogs), *(r.element for r in retrim)],
                warnings=[*structure_warnings(scene, gid, "the move"), *(w for r in retrim for w in r.warnings)],
                extra={"plan": plan, "retrim": retrim})


def _make_move(scene: IfcScene, plan: Plan) -> Made:
    if not plan.params.get("carry"):
        model = scene.models[scene.index_of(plan.element)]
        for j in plan.extra.get("open_joints", []):
            ifcopenshell.api.run("system.disconnect_port", model, port=model.by_guid(j["port"]))
        scene.translate([plan.element], tuple(plan.params["delta_m"]))
        opened = plan.extra.get("open_joints", [])
        return Made(changed=[plan.element], open_ends=[plan.element, *(j["element"] for j in opened)] if opened else [])
    mp = connections.plan_move(scene, plan.extra["plan"].moved, plan.params["delta_m"], refit=True)
    if not mp.ok:
        raise edits.Unsupported(f"it cannot keep its joints: {mp.refused}")
    connections.apply_move(scene, mp)
    broken = connections.check_joints(scene, mp)
    if broken:
        raise edits.Unsupported("a joint would not hold: " + "; ".join(w for *_, w in broken))
    followed = [g for r in plan.extra.get("retrim", []) for g in _make_push(scene, r).changed]
    return Made(changed=list(dict.fromkeys([*mp.changed(), *followed])), created=list(mp.made))


# ----------------------------------------------------------------------------------------------------- align


SNAP_WORDS = {"end": "corner", "mid": "midpoint of an edge", "edge": "edge"}


def _target_plane(scene: IfcScene, to: dict) -> tuple[np.ndarray, np.ndarray | None, str, str | None]:
    """The plane to align to: a face of another element (by name, id or pick), or a bare point and normal. A point
    with no normal (a corner, an edge's midpoint, a point on an edge, snapped as a measure snaps) is a point target:
    its normal is None."""
    gid = to.get("element")
    if to.get("point") is not None and to.get("normal") is None and not to.get("face"):
        what = SNAP_WORDS.get(to.get("snap") or "end", "point")
        return _vec(to["point"], "point"), None, f"{what} of {label(scene, gid)}" if gid else "point picked", gid
    if gid and (to.get("face") or (to.get("point") is not None and to.get("normal") is not None)):
        f = face_of(scene, gid, to if to.get("point") is not None else to["face"])
        return plane_point(scene, gid, f), np.asarray(f.normal, float), f"{f.name} of {label(scene, gid)}", gid
    if to.get("point") is not None and to.get("normal") is not None:
        n = _vec(to["normal"], "normal")
        return _vec(to["point"], "point"), n / np.linalg.norm(n), "plane picked", gid
    raise ValueError("say what to align to: an element and its face, or a point and a normal")


def _resolve_align(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    face = face_of(scene, gid, op.get("face"))
    if "align" not in face.allows:
        raise edits.Unsupported(f"its {face.name} cannot be aligned")
    pa = plane_point(scene, gid, face)
    na = np.asarray(face.normal, float)
    pb, nb, target, other = _target_plane(scene, op.get("to") or {})
    if other == gid:
        raise edits.Unsupported("align it to another element's face")
    gap = _num(op, "gap_m", 0.0)
    meets = ""
    if nb is None:   # a point: the face's plane through it, parallel to itself, the gap short of it
        t0 = float((pb - pa) @ na)
        t = t0 - gap * (1.0 if t0 >= 0 else -1.0)
    else:
        t, meets = _first_contact(scene, gid, face, pa, na, pb, nb, gap)
    if abs(t) < LEAST_M:
        raise edits.Unsupported("it is already there")
    how = op.get("how") or ("stretch" if "push_pull" in face.allows else "move")
    where = ("flush with" if abs(gap) < 1e-6 else f"{_mm(gap)} off") if nb is not None else (
        "through" if abs(gap) < 1e-6 else f"{_mm(gap)} short of")
    if how == "stretch":
        if "push_pull" not in face.allows:
            raise edits.Unsupported(f"its {face.name} cannot be stretched: move it instead")
        plan = _resolve_push(scene, {"op": "push_pull", "element": gid, "face": spec(face), "by_m": t, "carry": carries(op),
                                     **({"scope": "type"} if to_type(op) else {})})
        plan.summary = f"{face.name} of {label(scene, gid)} stretched {_mm(t)} {'out' if t > 0 else 'in'}, {where} the {target}{meets}"
    elif how == "move":
        if to_type(op):
            raise edits.Unsupported("moving it is its own: Apply to the type changes the shape or section its type gives")
        try:
            plan = _resolve_move(scene, {"op": "move", "element": gid, "delta_m": (na * t).tolist(), "carry": carries(op)})
        except Offered as e:   # the align itself, on its own
            raise Offered(str(e), {k: v for k, v in op.items() if k not in ("carry", "alone")}, e.words) from None
        plan.summary = f"{label(scene, gid)} moved {_mm(t)} so its {face.name} is {where} the {target}{meets}"
    else:
        raise ValueError("how is stretch or move")
    plan.op = "align"
    plan.params = {"op": "align", "element": gid, "face": spec(face), "to": op.get("to"), "gap_m": gap, "how": how,
                   "by_m": t, **({"delta_m": plan.params["delta_m"]} if how == "move" else {}),
                   **({"carry": True} if carries(op) else {}), **({"scope": "type"} if to_type(op) else {})}
    if other:
        plan.touching.add(other)
    plan.extra["how"] = how
    if meets:   # it meets the other face along one edge: clipping it to that face makes it flush all along
        plan.extra["offer"] = {"op": "clip", "element": gid, "to": op.get("to"), "gap_m": gap}
    return plan


def _first_contact(scene: IfcScene, gid: str, face: faces.Face, pa, na, pb, nb, gap: float) -> tuple[float, str]:
    """How far face A moves along its normal to meet face B's plane `gap` off it: flush all over when they are
    parallel, else at its first corner (up to 80° apart). Faces turned to each other end on B's outer side; faces
    turned the same way (level with) stay on the side A is on. Returns the distance and, when they are not parallel,
    words for where it meets."""
    cos = float(na @ nb)
    angle = float(np.degrees(np.arccos(min(abs(cos), 1.0))))
    if angle > ALIGN_MAX_DEG:
        raise edits.Unsupported(f"the faces are {angle:.0f}° apart: clip its end to that face instead")
    corners = faces.patch_vertices(scene, gid, face, pa) if abs(cos) < PARALLEL_COS else np.zeros((0, 3))
    if not len(corners):
        corners = np.asarray([pa])
    g = (corners - pb) @ nb
    if cos < 0:     # turned to each other: every corner on B's outer side, the nearest at the gap
        t = float(np.min((g - gap) / -cos))
    else:           # turned the same way: level with it, on the side A is on
        side = 1.0 if (pa - pb) @ nb > 0 else -1.0
        t = float(np.max((gap - g) / cos)) if side > 0 else float(np.min((-gap - g) / cos))
    meets = f", meeting it at one edge ({angle:.0f}° apart)" if abs(cos) < PARALLEL_COS else ""
    return t, meets


def _make_align(scene: IfcScene, plan: Plan) -> Made:
    return _make_move(scene, plan) if plan.extra.get("how") == "move" else _make_push(scene, plan)


# ----------------------------------------------------------------------------------------------------- void


def _resolve_void(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    face = face_of(scene, gid, op.get("face"))
    if "void" not in face.allows:
        raise edits.Unsupported(f"its {face.name} does not take an opening: pick one of its faces")
    n = np.asarray(face.normal, float)
    plane = plane_point(scene, gid, face)
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
        if depth is None:   # no way through found: as deep as the element is behind the face, when that is a wall's worth
            v = edits._mesh_verts(scene.entity(gid))
            behind = float(((at - v) @ n).max()) + 0.001
            if not 0.001 < behind <= edits.MAX_THROUGH_M:
                raise edits.Unsupported("it does not come out the other side here: give it a depth (a recess)")
            depth = behind
    warn = cut_warnings(scene, gid)
    if edits.misses(scene, gid, at, n, edits._outline(shape, w + 2 * edits.OPENING_EDGE_M, h + 2 * edits.OPENING_EDGE_M, u, v)):
        warn.append({"rule": "edge", "review": None,
                     "text": f"it comes within {edits.OPENING_EDGE_M * 1000:.0f} mm of the face's edge: a notch more than a hole"})
    size = f"Ø{w * 1000:.0f}" if shape == "round" else f"{w * 1000:.0f} x {h * 1000:.0f}"
    kind = f"{depth * 1000:.0f} mm recess" if blind is not None else "opening"
    params = {"op": "void", "element": gid, "face": spec(face), "at": [round(float(c), 4) for c in at], "shape": shape,
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


# ----------------------------------------------------------------------------------------------------- split, remove


def _along(scene: IfcScene, gid: str, at: np.ndarray) -> tuple[float, str]:
    """How far `at` is along the element's long axis, and from which end, in words."""
    start, d, _ = edits.long_axis(scene, gid)
    a = float((at - start) @ d)
    return a, f"{a:.2f} m from its {faces._name(scene, gid, -np.asarray(d)).split()[0]} end"


def _has_body(scene: IfcScene, gid: str) -> bool:
    try:
        return len(edits._mesh_verts(scene.entity(gid))) > 0
    except RuntimeError:
        return False


def _split(scene: IfcScene, plan: Plan, gid: str, at, axis=None) -> list[str]:
    """Split exactly where the body is one extrusion (its profile cut, its ports chained); else, or where that path
    refuses (a cut through an opening, an outline with holes), by half-space clips, saying what that leaves."""
    if axis is None:
        try:
            return edits.split(scene, gid, at, least_m=MIN_HAND_M, unique=True)
        except edits.Unsupported as e:
            if "under" in str(e):
                raise
    element = scene.entity(gid)
    joints = bool(ifcopenshell.util.system.get_ports(element))
    held = [f.RelatedBuildingElement for rel in getattr(element, "HasOpenings", None) or []
            for f in getattr(rel.RelatedOpeningElement, "HasFillings", None) or []]
    out = edits.split_by_clip(scene, gid, at, least_m=MIN_HAND_M, unique=True, axis=axis)
    rules = {w["rule"] for w in plan.warnings}
    if "clipped" not in rules:
        plan.warnings.append({"rule": "clipped", "review": None,
                              "text": "split by clips: each piece keeps the whole body, clipped where it was cut"})
    if joints and "joints_first" not in rules:
        plan.warnings.append({"rule": "joints_first", "review": "services",
                              "text": f"{label(scene, gid)}'s joints stay with its first piece: its designer must join the other"})
    if held and "fillings" not in rules:
        plan.warnings.append({"rule": "fillings", "review": "design",
                              "text": f"{', '.join(label(scene, x.GlobalId) for x in held[:3])} stay{'s' if len(held) == 1 else ''} "
                                      "with its first piece"})
    return out


def _resolve_split(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    at = _vec(op.get("at"), "at")
    if not _has_body(scene, gid):
        raise edits.Unsupported("it has no body to split")
    a, where = _along(scene, gid, at)
    return Plan("split", gid, {"op": "split", "element": gid, "at": [round(float(c), 4) for c in at]}, {scene.index_of(gid)},
                [gid], f"{label(scene, gid)} split in two, {where}", "any", warnings=structure_warnings(scene, gid, "the split"))


def _make_split(scene: IfcScene, plan: Plan) -> Made:
    gids = _split(scene, plan, plan.element, plan.params["at"])
    return Made(changed=[gids[0]], created=gids[1:], pieces=gids)


def _joined(scene: IfcScene, gid: str) -> list[str]:
    return [g for g in scene.element(gid).connected]


def _resolve_remove(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    p, q = _vec(op.get("from"), "from"), _vec(op.get("to"), "to")
    if not _has_body(scene, gid):
        raise edits.Unsupported("it has no body to take a section out of")
    (a, wa), (b, wb) = _along(scene, gid, p), _along(scene, gid, q)
    if a > b:
        (a, wa, p), (b, wb, q) = (b, wb, q), (a, wa, p)
    if b - a < 0.001:
        raise edits.Unsupported("the section is under 1 mm: pick two points along it")
    warn = structure_warnings(scene, gid, "taking out a section")
    if ifcopenshell.util.system.get_ports(scene.entity(gid)):
        warn.append({"rule": "open_ends", "review": "services",
                     "text": f"{label(scene, gid)} is left with two open ends: its designer must cap or join them"})
    return Plan("remove_section", gid, {"op": "remove_section", "element": gid, "from": [round(float(c), 4) for c in p],
                                        "to": [round(float(c), 4) for c in q]},
                {scene.index_of(gid)}, [gid], f"{(b - a) * 1000:,.0f} mm section taken out of {label(scene, gid)} "
                                              f"({wa.split(' from ')[0]} to {wb})", "any", warnings=warn)


def _make_remove(scene: IfcScene, plan: Plan) -> Made:
    gid = plan.element
    start, d, _ = edits.long_axis(scene, gid)
    if (np.asarray(plan.params["to"]) - np.asarray(plan.params["from"])) @ d < 0:
        raise edits.Unsupported("pick the section's points along the element")
    first = _split(scene, plan, gid, plan.params["from"])
    clipped = any(w["rule"] == "clipped" for w in plan.warnings)   # both cuts square to the whole's axis
    middle = _split(scene, plan, first[1], plan.params["to"], axis=(start, d) if clipped else None)
    name = scene.entity(gid).Name
    edits.remove_product_with(scene, middle[0])
    rest = scene.entity(middle[1])
    if name:
        rest.Name = f"{name} (part 2)"
    open_ends = [gid, middle[1]] if ifcopenshell.util.system.get_ports(scene.entity(gid)) else []
    return Made(changed=[gid], created=[middle[1]], pieces=[gid, middle[1]], open_ends=open_ends)


# ----------------------------------------------------------------------------------------------------- offset

TOWARD = {"up": (0.0, 0.0, 1.0), "down": (0.0, 0.0, -1.0), "north": (0.0, 1.0, 0.0), "south": (0.0, -1.0, 0.0),
          "east": (1.0, 0.0, 0.0), "west": (-1.0, 0.0, 0.0)}


def _resolve_offset(scene: IfcScene, op: dict) -> Plan:
    """A section of a straight duct, pipe or tray taken up, down or sideways (square to its run) between two points
    along it, with bends either side (edits.apply_offset, the fix kind's own geometry): its joints stay as they are."""
    gid = op["element"]
    e = scene.entity(gid)
    if not e.is_a("IfcFlowSegment"):
        raise edits.Unsupported("only a duct, pipe or cable tray segment can be offset: move or split the rest")
    _, _, _, origin, d, _, _ = edits._frames(scene, e)
    s = scene.unit_scales[scene.index_of(gid)]
    if abs(d @ edits.UP) > 1e-3:
        raise edits.Unsupported("only a level run can be offset by hand yet")
    t = op.get("toward")
    if isinstance(t, str):
        if t.lower() not in TOWARD:
            raise ValueError(f"toward is one of {', '.join(TOWARD)} or a direction")
        toward = np.asarray(TOWARD[t.lower()])
    else:
        toward = _vec(t, "toward")
        toward = toward / (np.linalg.norm(toward) or 1.0)
    by = _num(op, "by_m")
    if by < LEAST_M:
        raise edits.Unsupported("offset it at least 0.5 mm (say which way with toward)")
    side = np.cross(edits.UP, d)
    side /= np.linalg.norm(side)
    if abs(toward @ edits.UP) > PARALLEL_COS:
        up_m, side_m, vec = by * float(np.sign(toward @ edits.UP)), 0.0, edits.UP * float(np.sign(toward @ edits.UP))
    elif abs(toward @ side) > PARALLEL_COS:
        up_m, side_m, vec = 0.0, by * float(np.sign(toward @ side)), side * float(np.sign(toward @ side))
    else:
        raise edits.Unsupported("offset it up, down or sideways square to its run")
    p, q = _vec(op.get("from"), "from"), _vec(op.get("to"), "to")
    a, b = sorted((float((p - origin * s) @ d), float((q - origin * s) @ d)))
    length = float(edits._body(e)[1].Depth) * s
    if a < -LEAST_M or b > length + LEAST_M or b - a < 0.01:
        raise edits.Unsupported("pick where the offset starts and ends along it")
    bend = float(op.get("bend_deg") or 90.0)   # 45: up a slope with angled bends either end
    if not 15.0 <= bend <= 90.0:
        raise ValueError("bend_deg is between 15 and 90")
    words = connections.move_words((vec * by).tolist())
    params = {"op": "offset", "element": gid, "from": [round(float(c), 4) for c in p], "to": [round(float(c), 4) for c in q],
              "toward": [round(float(c), 6) for c in vec], "by_m": by, **({"bend_deg": bend} if bend != 90.0 else {})}
    plan = Plan("offset", gid, params, {scene.index_of(gid)}, [gid],
                f"{label(scene, gid)} offset {words} for {b - a:.2f} m, {a:.2f} m along it, with "
                f"{'bends' if bend == 90.0 else f'{bend:.0f}° bends'}", "offset", by,
                warnings=structure_warnings(scene, gid, "the offset"))
    plan.extra.update(start_m=a, end_m=b, up_m=up_m, side_m=side_m, bend_deg=bend)
    return plan


def _resolve_join(scene: IfcScene, op: dict) -> Plan:
    """Two straight segments' nearest free ends joined: in line, the first stretched to the second; square to each
    other, both brought to the corner and a 90° bend between (edits.join_plan). Their ports are connected."""
    a = op["element"]
    to = op.get("to")
    b = to.get("element") if isinstance(to, dict) else to
    if not b:
        raise ValueError("say which segment to join it to (to)")
    if scene.index_of(a) != scene.index_of(b):
        raise edits.Unsupported("join segments of one model")
    for g in (a, b):
        if not scene.entity(g).is_a("IfcFlowSegment"):
            raise edits.Unsupported(f"{label(scene, g)} is not a duct, pipe or tray segment")
    jp = edits.join_plan(scene, a, b)
    how = (f"in line ({_mm(jp.stretch_a)} {'longer' if jp.stretch_a >= 0 else 'shorter'})" if jp.kind == "line" else
           f"with a 90° bend ({jp.radius * 1000:.0f} mm radius)")
    plan = Plan("join", a, {"op": "join", "element": a, "to": {"element": b}}, {scene.index_of(a)}, [a, b],
                f"{label(scene, a)} joined to {label(scene, b)} {how}", "resize",
                max(abs(jp.stretch_a), abs(jp.stretch_b)), gated=[a, b],
                warnings=structure_warnings(scene, a, "the join"))
    plan.touching.add(b)
    plan.extra["join"] = jp
    return plan


def _make_join(scene: IfcScene, plan: Plan) -> Made:
    jp = edits.join_plan(scene, plan.element, plan.extra["join"].b)   # read again: the trial's model, not the check's
    made = edits.join_segments(scene, jp)
    return Made(changed=[jp.a, jp.b], created=made, pieces=[jp.a, *made, jp.b])


def _resolve_disconnect(scene: IfcScene, op: dict) -> Plan:
    """One of the element's port joints left open: the one to `from` (an element), else the one nearest `at`, else its
    only one. Listed with the joints the person keeps it with."""
    gid = op["element"]
    joints = []
    for port in ifcopenshell.util.system.get_ports(scene.entity(gid)):
        other = ifcopenshell.util.system.get_connected_port(port)
        owner = ifcopenshell.util.system.get_port_element(other) if other is not None else None
        if owner is not None:
            joints.append((port, owner.GlobalId))
    if not joints:
        raise edits.Unsupported("it is not joined to anything")
    if op.get("from"):
        joints = [j for j in joints if j[1] == op["from"]]
        if not joints:
            raise edits.Unsupported(f"it is not joined to {label(scene, op['from'])}")
    elif op.get("at") is not None:
        at = _vec(op["at"], "at")
        joints = [min(joints, key=lambda j: float(np.linalg.norm(scene.placement(j[0].GlobalId)[:3, 3] - at)))]
    elif len(joints) > 1:
        raise edits.Unsupported("it has several joints: say which (from an element, or at a point)")
    port, other = joints[0]
    opened = [{"element": other, "name": label(scene, other), "port": port.GlobalId}]
    plan = Plan("disconnect", gid, {"op": "disconnect", "element": gid, "from": other}, {scene.index_of(gid)}, [gid],
                f"{label(scene, gid)} disconnected from {label(scene, other)}", "any",
                warnings=[_open_joint_words(scene, gid, opened)])
    plan.extra["open_joints"] = opened
    return plan


def _make_disconnect(scene: IfcScene, plan: Plan) -> Made:
    model = scene.models[scene.index_of(plan.element)]
    (j,) = plan.extra["open_joints"]
    ifcopenshell.api.run("system.disconnect_port", model, port=model.by_guid(j["port"]))
    return Made(changed=[plan.element, j["element"]], open_ends=[plan.element, j["element"]])


def _make_offset(scene: IfcScene, plan: Plan) -> Made:
    x = plan.extra
    off = edits.apply_offset(scene, plan.element, x["start_m"], x["end_m"], x["up_m"], lateral_m=x["side_m"],
                             bend_deg=x.get("bend_deg", 90.0))
    return Made(changed=[plan.element], created=[g for g in off.pieces if g != plan.element], pieces=list(off.pieces))


def _axis_of(scene: IfcScene, gid: str) -> np.ndarray:
    return edits.long_axis(scene, gid)[1]


def _standing_on(scene: IfcScene, gid: str) -> list[str]:
    """Elements standing on this one (their base at its top, over it): what a delete leaves in the air."""
    boxes = scene.bounds()
    hb = boxes.get(gid)
    if hb is None:
        return []
    out = []
    for g, b in boxes.items():
        if g == gid or abs(b[0][2] - hb[1][2]) > 0.005:
            continue
        if (b[0][:2] < hb[1][:2] - 1e-3).all() and (b[1][:2] > hb[0][:2] + 1e-3).all():
            out.append(g)
    return out


def _resolve_delete(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    e = scene.entity(gid)
    warn = structure_warnings(scene, gid, "removing it")
    held = [f.RelatedBuildingElement for rel in getattr(e, "HasOpenings", None) or []
            for f in getattr(rel.RelatedOpeningElement, "HasFillings", None) or []]
    if held:
        warn.append({"rule": "fillings", "review": "design", "text": f"{', '.join(label(scene, x.GlobalId) for x in held[:3])} "
                                                                     f"in its openings go{'es' if len(held) == 1 else ''} with it"})
    joined = _joined(scene, gid)
    if joined:
        warn.append({"rule": "open_ends", "review": "services",
                     "text": f"{', '.join(label(scene, g) for g in joined[:3])} would be left with an open end"})
    on = _standing_on(scene, gid)
    if on:
        warn.append({"rule": "support", "review": "structure",
                     "text": f"{', '.join(label(scene, g) for g in on[:3])} stand{'s' if len(on) == 1 else ''} on it"})
    return Plan("delete", gid, {"op": "delete", "element": gid}, {scene.index_of(gid)}, [gid], f"{label(scene, gid)} deleted",
                "any", warnings=warn)


def _make_delete(scene: IfcScene, plan: Plan) -> Made:
    joined = _joined(scene, plan.element)
    gone = edits.remove_product_with(scene, plan.element)
    return Made(removed=gone, open_ends=joined)


# ----------------------------------------------------------------------------------------------------- clip


def _resolve_clip(scene: IfcScene, op: dict) -> Plan:
    gid = op["element"]
    pb, nb, target, other = _target_plane(scene, op.get("to") or {})
    if other == gid:
        raise edits.Unsupported("clip it to another element's face")
    gap = _num(op, "gap_m", 0.0)
    if gap < 0:
        raise edits.Unsupported("the gap is not negative")
    nb = nb / np.linalg.norm(nb)
    plane = pb + nb * gap
    v = edits._mesh_verts(scene.entity(gid))
    side = (v - plane) @ (-nb)
    if side.max() <= 1e-4:
        raise edits.Unsupported(f"it does not reach the {target}: nothing to clip")
    if side.min() >= -1e-4:
        raise edits.Unsupported(f"all of it is past the {target}")
    axis = _axis_of(scene, gid)
    angle = f", {np.degrees(np.arccos(min(abs(float(axis @ nb)), 1.0))):.0f}° off square" if axis is not None else ""
    where = "flush with" if gap == 0 else f"{_mm(gap)} off"
    return Plan("clip", gid, {"op": "clip", "element": gid, "to": op.get("to"), "gap_m": gap,
                              "plane": {"point": [round(float(c), 5) for c in plane], "normal": [round(float(c), 6) for c in -nb]}},
                {scene.index_of(gid)}, [gid], f"{label(scene, gid)} clipped {where} the {target}{angle}", "trim",
                touching={other} if other and gap == 0 else set(), warnings=structure_warnings(scene, gid, "the clip"))


def _make_clip(scene: IfcScene, plan: Plan) -> Made:
    edits.clip_to_plane(scene, plan.element, plan.params["plane"]["point"], plan.params["plane"]["normal"],
                        least_m=MIN_HAND_M, unique=True)
    return Made(changed=[plan.element])


OPS: dict[str, Op] = {
    "push_pull": Op(_resolve_push, _make_push, "push or pull one face: a length, a width, a radius, a wall's end"),
    "align": Op(_resolve_align, _make_align, "make one face flush with another face (or a gap off it), by stretching or moving"),
    "move": Op(_resolve_move, _make_move, "move an element by a vector (with carry, the straight run it is in)"),
    "offset": Op(_resolve_offset, _make_offset, "take a section of a duct, pipe or tray up, down or sideways, with bends"),
    "join": Op(_resolve_join, _make_join, "join two segments' free ends: in line, or square with a 90° bend"),
    "disconnect": Op(_resolve_disconnect, _make_disconnect, "leave one of an element's joints open (split a run at a fitting)"),
    "void": Op(_resolve_void, _make_void, "cut a rectangular or round opening through a face (or a recess to a depth)"),
    "cut_by": Op(_resolve_cut_by, _make_cut_by, "cut an element where another element is, with a gap all round"),
    "split": Op(_resolve_split, _make_split, "split an element in two at a point along it"),
    "remove_section": Op(_resolve_remove, _make_remove, "take a section out of an element between two points along it"),
    "delete": Op(_resolve_delete, _make_delete, "delete an element (with what fills its openings and what it aggregates)"),
    "clip": Op(_resolve_clip, _make_clip, "clip an element's end to another element's face (any angle), with a gap"),
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
    if to_type(op) and name not in TYPE_OPS:
        raise edits.Unsupported("only a push, pull or align changes what its type gives: leave Apply to the type off")
    if op.get("scope") not in (None, "element", "type"):
        raise ValueError("scope is element (the default) or type")
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



def key_of(op: dict, revision: int) -> str:
    raw = json.dumps({"op": op, "revision": revision, "requirements": requirements.current_id()}, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _sync(scene: IfcScene, plan: Plan, made: Made, was: dict) -> parametric.Synced:
    """After the edit, inside its transaction: what the model says besides the shape follows the body (parametric.py),
    the same in the trial and when kept."""
    return parametric.sync(scene, was, made.changed, made.created, made_from=plan.element, label=label)


def _left_words(scene: IfcScene, synced: parametric.Synced) -> list[dict]:
    if not synced.left:
        return []
    names = ", ".join(q.split(".", 1)[1] for q in synced.left[:4]) + (" …" if len(synced.left) > 4 else "")
    return [{"rule": "quantities", "review": "design",
             "text": f"{len(synced.left)} base quantit{'y' if len(synced.left) == 1 else 'ies'} ORCA does not work out "
                     f"were left as they were ({names})"}]


def check(ws, scene_id: str, op: dict, preview: bool = True) -> dict:
    """Make the edit in a trial and measure it; nothing is kept. Refusals come back as `blocked` with why."""
    scene = ws.scene(scene_id)
    with ws.lock:
        try:
            plan = resolve(scene, op)
        except Offered as e:
            return {"op": op, "passed": False, "blocked": str(e), "warnings": [], "clashes": 0, "offer": e.offer,
                    "offer_words": e.words}
        except (edits.Unsupported, KeyError, ValueError, TypeError) as e:
            return {"op": op, "passed": False, "blocked": str(e).strip("'\""), "warnings": [], "clashes": 0}
        refused = gate(scene, plan)
        base = {"op": plan.params, "summary": plan.summary,
                "face": {**plan.face.to_dict(), "label": label(scene, plan.element)} if plan.face else None,
                "warnings": plan.warnings, "revision": scene.revision, "key": key_of(plan.params, scene.revision),
                "targets": plan.targets, "joints": [{k: j[k] for k in ("element", "name")} for j in plan.extra.get("open_joints", [])],
                **({"offer": plan.extra["offer"], "offer_words": "Clip it flush"} if plan.extra.get("offer") else {})}
        if refused:
            return {**base, "passed": False, "blocked": refused, "clashes": 0}
        clearance = ws.clearance(scene_id)
        boxes = scene.bounds()
        targets = [g for g in plan.targets if g in boxes]
        before = {h.other: h for h in verify.check(scene, targets, clearance_m=clearance).hits} if targets else {}
        shapes_before = edits.meshes(scene, [g for g in plan.targets if scene.has(g)]) if preview else None
        readings = consistency.measure(scene, plan.targets, label)   # what the model says besides the shape, before
        was = parametric.snapshot(scene, plan.targets)
        try:
            with edits.trial_files(scene, plan.files):
                made = OPS[plan.op].make(scene, plan)
                synced = _sync(scene, plan, made, was)
                boxes = scene.bounds()
                mine = [g for g in dict.fromkeys([*made.changed, *made.created]) if g in boxes]
                issues = consistency.compare(scene, readings, consistency.measure(scene, [
                    g for g in dict.fromkeys([*plan.targets, *made.changed, *made.created]) if scene.has(g)], label),
                    made_from=plan.element, allow=frozenset(plan.extra.get("consistent", ())))
                v = (verify.check(scene, mine, clearance_m=clearance, ignore=set(mine), touching=plan.touching)
                     if mine else verify.Verdict(True, [], None, 0))
                shapes = edits.meshes(scene, [g for g in dict.fromkeys([*made.changed, *made.created])
                                              if scene.has(g) and not not_physical(scene.entity(g))]) if preview else None
        except edits.Unsupported as e:
            return {**base, "passed": False, "blocked": str(e), "clashes": 0}
        blocks = [i for i in issues if i.severity == "block"]
        if blocks:   # the model would say two things: refused, in words (docs/editing-parity.md)
            more = f" (and {len(blocks) - 1} more)" if len(blocks) > 1 else ""
            return {**base, "passed": False, "blocked": blocks[0].text + more, "clashes": 0,
                    "consistency": [i.to_dict() for i in issues]}
        base["warnings"] = [*base["warnings"], *({"rule": i.rule, "review": "design", "text": i.text}
                                                  for i in issues if i.severity == "warn"), *_left_words(scene, synced)]
        if synced.opened:   # path joins the edit leaves open, kept only when said (as port joints are)
            base["joints"] = [*base["joints"], *synced.opened]
            base["warnings"].append(_open_joint_words(scene, plan.element, synced.opened))
        if synced.notes:
            base["summary"] = f"{base['summary']}; {'; '.join(synced.notes)}"
        hits = [h for h in v.hits if not (h.other in plan.touching and h.distance_m > -WORSE_M)]
        new = [h for h in hits if h.other not in before]
        worse = [h for h in hits if h.other in before and h.distance_m < before[h.other].distance_m - WORSE_M]
        still = {h.other for h in v.hits if h.kind == "collision"}   # closer than the clearance is no longer a clash
        cleared = [{"other": g, "name": label(scene, g) if scene.has(g) else g, "was_m": before[g].distance_m}
                   for g in before if g not in still and before[g].kind == "collision"]
        clashes = [h for h in new + worse if h.kind == "collision"]
        return {**base, "passed": not clashes and not base["joints"], "blocked": None, "clashes": len(clashes),
                "close": len([h for h in new + worse if h.kind != "collision"]),
                "new": [_hit(scene, h) for h in new], "worse": [_hit(scene, h) for h in worse], "cleared": cleared,
                "min_clearance_m": v.min_clearance_m, "checked_against": v.checked_against,
                "changed": made.changed, "created": made.created, "removed": made.removed, "open_ends": made.open_ends,
                "preview": shapes, "before": shapes_before}


def apply(ws, scene_id: str, op: dict, *, key: str | None = None, accept_clashes: int = 0, source: str = "you",
          actor: str | None = None, clash_id: str | None = None, pair: list[str] | None = None,
          accept_joints: int = 0) -> dict:
    """Keep a hand edit: checked again first, here and now; refused (NotKept) when the requirements forbid it, the
    model changed since its check (`key`), or it would make more clashes than `accept_clashes` or leave more joints
    open than `accept_joints`. Kept through the edit log, tied to the clash (`clash_id`, `pair`) and to any fix it
    follows; the clash is measured again after."""
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
        if len(r["joints"]) > max(int(accept_joints or 0), 0):
            n = len(r["joints"])
            raise NotKept(f"it would leave {n} joint{'s' if n > 1 else ''} open ({', '.join(j['name'] for j in r['joints'][:3])}): "
                          f"keep it with {n} open joint{'s' if n > 1 else ''} to go ahead")
        plan = resolve(scene, op)
        clashes = [{"id": clash_id, "pair": list(pair)}] if pair and len(pair) == 2 else (
            [{"id": clash_id, "pair": None}] if clash_id else [])
        if pair and len(pair) == 2:   # the clash on screen only when the edit touches its elements (or what a fix made of them)
            near = {*log.made_from(pair[0]), *log.made_from(pair[1])}
            if near.isdisjoint(plan.targets):
                clashes = []
        was = parametric.snapshot(scene, plan.targets)
        with log.record(scene, source, plan.op, actor=actor, requirements=requirements.current_id()) as rec, \
                edits.kept_files(scene, plan.files):
            made = OPS[plan.op].make(scene, plan)
            _sync(scene, plan, made, was)
            scene._edited.update(plan.files)   # export writes these files
            scene.bump(plan.files)
            rec.changed, rec.summary, rec.title = list(made.changed), r["summary"], plan.summary
            rec.params, rec.clashes, rec.warnings = plan.params, clashes, list(r["warnings"])
            rec.check = {"verified": False, "cleared": r["cleared"], "new": r["new"], "worse": r["worse"],
                         "accepted_clashes": r["clashes"], "min_clearance_m": r["min_clearance_m"],
                         **({"open_joints": r["joints"]} if r["joints"] else {})}
        entry = rec.entry
        if entry is not None:
            entry.status = _status(scene, log, entry)
    return {"entry": entry.to_dict() if entry else None, "files": sorted(plan.files),
            "changed": list(dict.fromkeys([*made.changed, *made.created])), "created": made.created,
            "removed": made.removed, "pieces": made.pieces, "check": {k: v for k, v in r.items() if k not in ("preview", "before")}}


def _status(scene: IfcScene, log, entry) -> dict | None:
    """Where the entry's clash stands now: its elements, and everything a fix made from them, measured again."""
    states = clash_states(scene, log, entry)
    return states[0] if states else None


def clash_states(scene: IfcScene, log, entry) -> list[dict]:
    """Where each of the entry's clashes (with its pair) stands now, measured again over its two elements and everything
    a fix made from them, one index for all: what undo and redo tell the page, whoever kept the entry."""
    boxes = scene.bounds()
    out = []
    for c in entry.clashes:
        pair = c.get("pair")
        if not pair or len(pair) != 2:
            continue
        left = [g for g in log.made_from(pair[0]) if g in boxes]
        right = [g for g in log.made_from(pair[1]) if g in boxes]
        depths = list(detect.measure_pairs(scene, left, right).values())
        worst = min(depths) if depths else None
        out.append({"clash": c.get("id"), "pair": pair, "resolved": worst is None, "depth_m": worst})
    return out


def describe() -> str:
    """The edits there are, one line each, for Muse's tool notes."""
    return "; ".join(f"{name}: {op.words}" for name, op in OPS.items())
