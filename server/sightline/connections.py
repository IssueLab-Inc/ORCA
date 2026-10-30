"""What is joined to what, and what a move does to those joints (docs/connections.md).

A joint is where two elements meet so that something passes through: two ports connected in the model (an IFC
author's), or, for parts converted from STEP, which have no ports, two flow parts of the same STEP group meeting face
to face (a pipe's end against its bend's). A move that leaves a joint apart is not a fix anyone would build, so a move
is planned with its joints (`plan_move`): it keeps them, or it is refused with the joint named.

Classes of element, for a move: a "straight" segment (a flow segment that is one straight extrusion), "rigid" parts
(fittings, in-line valves and dampers, segments that are not straight), and parts that "stay" (equipment, terminals,
other controllers, anything that is not a flow element).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.system as system
import numpy as np

from . import context_eval, edits, verify
from .scene import IfcScene, step_source

TOUCH_M = 0.002       # two faces of a joint meet within this (as context_eval.TOL)
FACING = 0.95         # and face each other: normals opposed within about 18°
PARALLEL_M = 0.0005   # a move runs along a segment when it leaves less than this across it (1° would leave 4 mm at
                      # 250 mm: more than a joint may open)
COVER = 0.8           # a part covering this much of a rectangular segment's side is joined to it end-on (a ladder bend
                      # sat on a riser); less is a branch off its side
CARRY_MAX = int(os.environ.get("SIGHTLINE_CARRY_MAX", "12"))   # parts a move may take along
MODES = ("carry", "refuse", "off")
FLOW = "IfcDistributionFlowElement"
INLINE = ("IfcValve", "IfcDamper", "IfcFlowMeter")              # controllers that sit in a run and move with it
INLINE_TYPES = ("IfcValveType", "IfcDamperType", "IfcFlowMeterType")   # IFC2X3: an IfcFlowController by its type


def mode() -> str:
    """How moves treat joints (SIGHTLINE_CONNECTED_MOVES): "carry" the parts beyond a joint along (or stretch the
    segment there), "refuse" a move that would leave one apart, or "off" (moves as before joints were known: a run up
    to its fittings, joints ignored)."""
    m = os.environ.get("SIGHTLINE_CONNECTED_MOVES", "carry").strip().lower()
    return m if m in MODES else "carry"


@dataclass(frozen=True)
class Joint:
    a: str                      # the element asked about (joints_of(a))
    b: str                      # what it is joined to
    point_m: tuple | None       # where, world metres (None: a port with no placement)
    source: str                 # "ports" | "geometry"
    end_a: str | None = None    # a straight segment's "start" / "end" cap, or "side"; None for anything else
    end_b: str | None = None


@dataclass
class Stretch:
    global_id: str
    face: str                  # "start" / "end" cap, or "side" (a rectangular segment taken end-on)
    by_m: float                # longer (+) or shorter (-) across that face
    normal: tuple              # the face's outward normal, world
    size_m: float              # its length (a cap) or its size across (a side), after


@dataclass
class MovePlan:
    moved: list[str]                                   # what is translated: what was asked, then what it carries
    delta_m: list[float]
    carried: list[str] = field(default_factory=list)   # parts taken along so their joints hold
    stretched: list[Stretch] = field(default_factory=list)  # segments made longer or shorter at one face
    kept: list[Joint] = field(default_factory=list)    # joints the move keeps
    partners: dict[str, set[str]] = field(default_factory=dict)  # every changed element's joints before, to check
    refused: str | None = None                         # why the move can't keep its joints, in plain words
    refused_at: list[str] = field(default_factory=list)  # the elements whose joints it would break
    code: str | None = None                            # "stays" | "short" | "branch" | "many" | "joined" (refuse mode)

    @property
    def ok(self) -> bool:
        return self.refused is None

    @property
    def plain(self) -> bool:
        """Nothing taken along or stretched: a move as it always was."""
        return not self.carried and not self.stretched

    def changed(self) -> list[str]:
        return self.moved + [st.global_id for st in self.stretched]

    def key(self) -> str:
        return json.dumps([sorted(self.moved), [round(v, 4) for v in self.delta_m],
                           sorted([st.global_id, st.face, round(st.by_m, 4)] for st in self.stretched)])

    def edit(self, scene: IfcScene, run: list[str] | None = None) -> dict | None:
        """What an option carries about a move that takes parts along or stretches segments (None: a plain move)."""
        if self.plain:
            return None
        return {"summary": summary(scene, self), "key": self.key(), "run": list(run or []),
                "carried": list(self.carried), "joints": len(self.kept),
                "stretched": [{"global_id": st.global_id, "face": st.face, "by_m": round(st.by_m, 4),
                               "size_m": round(st.size_m, 4), "normal": [round(v, 6) for v in st.normal]}
                              for st in self.stretched]}


# ---------------------------------------------------------------------------------------------------- classes

def is_flow(scene: IfcScene, gid: str) -> bool:
    return scene.entity(gid).is_a(FLOW)


def classify(scene: IfcScene, gid: str) -> str:
    """"straight", "rigid" or "stays" (see the module's docstring)."""
    ent = scene.entity(gid)
    if not ent.is_a(FLOW) or scene.stays(gid):
        return "stays"
    if ent.is_a("IfcFlowSegment"):
        try:
            edits.run_of(scene, gid)
            return "straight"
        except (edits.Unsupported, AttributeError, TypeError, ValueError):
            return "rigid"
    if ent.is_a("IfcFlowFitting"):
        return "rigid"
    if ent.is_a("IfcFlowController"):
        kind = ifcopenshell.util.element.get_type(ent)
        if any(ent.is_a(c) for c in INLINE) or (kind is not None and any(kind.is_a(c) for c in INLINE_TYPES)):
            return "rigid"
    return "stays"


def kind_words(scene: IfcScene, gid: str) -> str:
    """What an element is, for a sentence: "pipe fitting", "valve", "filter"."""
    cls = scene.entity(gid).is_a()[3:]
    words = "".join(f" {c.lower()}" if c.isupper() else c for c in cls).strip()
    return words.replace(" segment", "").replace("flow ", "")


# ---------------------------------------------------------------------------------------------------- joints

def _end(scene: IfcScene, gid: str, point) -> str | None:
    """Where on a straight segment a joint sits: its "start" or "end" cap, else its "side"; None if not straight."""
    if point is None or classify(scene, gid) != "straight":
        return None
    run = edits.run_of(scene, gid)
    p = np.asarray(point, float)
    d = np.asarray(run.direction, float)
    for name, cap in (("start", run.start), ("end", run.end)):
        if abs(float((p - np.asarray(cap)) @ d)) <= TOUCH_M:
            return name
    return "side"


def _port_joints(scene: IfcScene, gid: str) -> list[Joint]:
    out = []
    for p in system.get_ports(scene.entity(gid)):
        rels = list(getattr(p, "ConnectedTo", None) or []) + list(getattr(p, "ConnectedFrom", None) or [])
        for rel in rels:
            q = rel.RelatedPort if rel.RelatingPort == p else rel.RelatingPort
            other = system.get_port_element(q) if q is not None else None
            if other is None or other.GlobalId == gid:
                continue
            point = tuple(float(v) for v in scene.placement(p.GlobalId)[:3, 3]) if p.ObjectPlacement else None
            out.append(Joint(gid, other.GlobalId, point, "ports", _end(scene, gid, point),
                             _end(scene, other.GlobalId, point)))
    return out


def _tris(scene: IfcScene, gid: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """World triangles (T, 3, 3) in metres, their unit normals and areas."""
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, scene.entity(gid), geometry_library=edits._kernel(scene.entity(gid)))
    v = np.asarray(shape.geometry.verts, float).reshape(-1, 3)
    t = v[np.asarray(shape.geometry.faces, int).reshape(-1, 3)]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    area = np.linalg.norm(n, axis=1)
    keep = area > 1e-12
    return t[keep], n[keep] / area[keep, None], area[keep] / 2


def _faces(scene: IfcScene, gid: str, tris) -> list[tuple[np.ndarray, np.ndarray, str | None]]:
    """The faces a part can be joined by: (centroid, outward normal, its end). A straight segment offers its two
    caps; anything else its large planar faces (triangles of one plane, at least a fifth of the largest such face:
    a bend's end discs, a box fitting's sides, never a bend's thin facets)."""
    if classify(scene, gid) == "straight":
        run = edits.run_of(scene, gid)
        d = np.asarray(run.direction, float)
        return [(np.asarray(run.start, float), -d, "start"), (np.asarray(run.end, float), d, "end")]
    t, n, area = tris
    groups: list[tuple[np.ndarray, float, list[int]]] = []
    for i in range(len(t)):
        off = float(n[i] @ t[i, 0])
        for g in groups:
            if g[0] @ n[i] > np.cos(np.radians(2.5)) and abs(g[1] - off) <= 0.0005:
                g[2].append(i)
                break
        else:
            groups.append((n[i], off, [i]))
    sized = [(n0, idx, float(area[idx].sum())) for n0, _, idx in groups]
    big = max((s for *_, s in sized), default=0.0)
    out = []
    for n0, idx, s in sized:
        if s >= 0.2 * big:
            centroid = (t[idx].mean(axis=1) * area[idx, None]).sum(axis=0) / area[idx].sum()
            out.append((centroid, n0, None))
    return out


def _on_surface(point: np.ndarray, normal: np.ndarray, tris) -> bool:
    """Whether `point` lies on a face of `tris` that faces back at `normal` (within TOUCH_M of its plane, inside it)."""
    t, n, _ = tris
    facing = n @ normal < -FACING
    if not facing.any():
        return False
    t, n = t[facing], n[facing]
    dist = np.einsum("ij,ij->i", point - t[:, 0], n)
    near = np.abs(dist) <= TOUCH_M
    if not near.any():
        return False
    t, n, dist = t[near], n[near], dist[near]
    p = point - dist[:, None] * n
    v0, v1, v2 = t[:, 1] - t[:, 0], t[:, 2] - t[:, 0], p - t[:, 0]
    d00, d01, d11 = np.einsum("ij,ij->i", v0, v0), np.einsum("ij,ij->i", v0, v1), np.einsum("ij,ij->i", v1, v1)
    d20, d21 = np.einsum("ij,ij->i", v2, v0), np.einsum("ij,ij->i", v2, v1)
    den = d00 * d11 - d01 * d01
    ok = np.abs(den) > 1e-18
    v = np.where(ok, (d11 * d20 - d01 * d21) / np.where(ok, den, 1), -1)
    w = np.where(ok, (d00 * d21 - d01 * d20) / np.where(ok, den, 1), -1)
    return bool(((v >= -0.02) & (w >= -0.02) & (v + w <= 1.02)).any())


def _group_members(scene: IfcScene, i: int, group: str) -> list[str]:
    cache = getattr(scene, "_joint_groups", None)
    key = (scene.revision, len(scene.bounds()))
    if cache is None or cache[0] != key:
        groups: dict[tuple[int, str], list[str]] = {}
        for j, model in enumerate(scene.models):
            for e in model.by_type(FLOW):
                g = step_source(e).get("Group")
                if isinstance(g, str) and g:
                    groups.setdefault((j, g), []).append(e.GlobalId)
        cache = (key, groups)
        scene._joint_groups = cache
    return cache[1].get((i, group), [])


def _geometry_joints(scene: IfcScene, gid: str) -> list[Joint]:
    """Joints of a part converted from STEP with the flow parts of its own group it meets face to face."""
    ent = scene.entity(gid)
    group = step_source(ent).get("Group") if ent.is_a(FLOW) else None
    if not isinstance(group, str) or not group:
        return []
    boxes = scene.bounds()
    box = boxes.get(gid)
    if box is None:
        return []
    near = [m for m in _group_members(scene, scene.index_of(gid), group) if m != gid and m in boxes
            and np.all(boxes[m][0] <= box[1] + TOUCH_M) and np.all(boxes[m][1] >= box[0] - TOUCH_M)]
    cache = getattr(scene, "_joint_tris", None)
    if cache is None:
        cache = scene._joint_tris = {}

    def tris(g):
        sig = boxes[g].tobytes()
        if g not in cache or cache[g][0] != sig:
            cache[g] = (sig, _tris(scene, g))
        return cache[g][1]

    out = []
    for other in near:
        mine, theirs = tris(gid), tris(other)
        point = None
        for c, n, _ in _faces(scene, gid, mine):
            if _on_surface(c, n, theirs):
                point = c
                break
        if point is None:
            for c, n, _ in _faces(scene, other, theirs):
                if _on_surface(c, n, mine):
                    point = c
                    break
        if point is not None:
            p = tuple(float(v) for v in point)
            out.append(Joint(gid, other, p, "geometry", _end(scene, gid, p), _end(scene, other, p)))
    return out


def joints_of(scene: IfcScene, gid: str) -> list[Joint]:
    """Everything `gid` is joined to: its connected ports, and for a STEP part the flow parts of its group it meets
    face to face (a pair already joined by ports is not counted twice)."""
    out = _port_joints(scene, gid)
    if step_source(scene.entity(gid)):
        seen = {j.b for j in out}
        out += [j for j in _geometry_joints(scene, gid) if j.b not in seen]
    return out


def run(scene: IfcScene, gid: str) -> list[str]:
    """What moves as one with `gid` before its joints are looked at: straight segments joined cap to cap (a run up to
    its fittings, valves, branches and equipment), `gid` first, then as they are joined. A part that is not a flow
    element keeps what it moved with before (a STEP part: the parts of its group it touches), never flow parts."""
    if mode() == "off":
        return scene.connected_run(gid)
    if not is_flow(scene, gid):
        return sorted(g for g in scene.connected_run(gid) if g == gid or not is_flow(scene, g))
    if classify(scene, gid) != "straight":
        return [gid]
    seen, todo = [gid], [gid]
    while todo:
        for j in joints_of(scene, todo.pop(0)):
            if (j.b not in seen and j.end_a in ("start", "end") and j.end_b in ("start", "end")
                    and classify(scene, j.b) == "straight"):
                seen.append(j.b)
                todo.append(j.b)
    return seen


# ---------------------------------------------------------------------------------------------------- moves

def move_words(delta_m) -> str:
    """A move in words, on the model's axes (+X east, +Y north, +Z up): "north 250 mm", "east 100 mm, up 400 mm"."""
    names = (("east", "west"), ("north", "south"), ("up", "down"))
    out = [f"{names[k][0 if v > 0 else 1]} {abs(round(v * 1000))} mm" for k, v in enumerate(delta_m) if abs(v) >= 0.0005]
    return ", ".join(out) or "0 mm"


def _names(scene: IfcScene, gids) -> str:
    """"'bend 2' and 'bend 3'"; elements with the same name once, counted ("'tee 600x300' (2)")."""
    counts: dict[str, int] = {}
    for g in gids:
        name = f"'{scene.element(g).name or scene.entity(g).is_a()[3:]}'"
        counts[name] = counts.get(name, 0) + 1
    names = [n + (f" ({k})" if k > 1 else "") for n, k in counts.items()]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _side_normal(scene: IfcScene, gid: str, point) -> np.ndarray | None:
    """The outward normal of a straight segment's side where `point` is (its profile's X or Y axis, signed)."""
    i, place, item, origin, d, px, py = edits._frames(scene, scene.entity(gid))
    s = scene.unit_scales[i]
    v = np.asarray(point, float) - origin * s
    v -= d * (v @ d)
    axis = px if abs(v @ px) >= abs(v @ py) else py
    return axis * (1.0 if v @ axis >= 0 else -1.0)


def _covered(scene: IfcScene, seg: str, normal: np.ndarray, point, by: str) -> bool:
    """Whether `by` covers the side of `seg` it is joined to there (a 5 x 5 grid of points on that face, COVER of
    them on `by`'s facing surface): end-on, as a ladder bend sits on its riser, not a branch off it."""
    i, place, item, origin, d, px, py = edits._frames(scene, scene.entity(seg))
    s = scene.unit_scales[i]
    prof = item.SweptArea
    if prof.is_a() != "IfcRectangleProfileDef":
        return False
    across = px if abs(normal @ px) < 0.5 else py           # the face spans the run and the other profile axis
    half_w = (prof.XDim if across is px else prof.YDim) * s / 2
    face_c = origin * s + d * (item.Depth * s / 2)
    face_c = face_c + normal * ((prof.YDim if across is px else prof.XDim) * s / 2)
    tris = _tris(scene, by)
    hits = 0
    for a in np.linspace(-0.4, 0.4, 5):
        for b in np.linspace(-0.4, 0.4, 5):
            p = face_c + d * (a * item.Depth * s) + across * (b * 2 * half_w)
            hits += _on_surface(p, normal, tris)
    return hits >= COVER * 25


def plan_move(scene: IfcScene, moved: list[str], delta_m) -> MovePlan:
    """Plan moving `moved` by `delta_m` with its joints. Each element ends up translated, stretched at one face, or
    where it is, and both sides of every joint must move alike. Going out from what moves ("carry"): a fitting or
    in-line valve is taken along; a straight segment the move runs along is made longer or shorter at the joined end
    (a riser a bend sits on, taller); any other straight segment is taken along; equipment, terminals, structure,
    anything kept fixed, a branch off a segment's side, a segment that would get too short, or more than CARRY_MAX
    parts taken along: refused, naming the joint. "refuse" refuses at the first joint that would come apart. Nothing
    is edited."""
    moved = list(dict.fromkeys(moved))
    asked = list(moved)
    delta = np.asarray([float(v) for v in delta_m])
    plan = MovePlan(moved, delta.tolist())
    if mode() == "off" or not np.any(np.abs(delta) >= 0.0005):
        return plan
    carry = mode() == "carry"
    inside = set(moved)
    stretched: dict[str, Stretch] = {}
    via: dict[str, str] = {}             # what took a part along (for the words of a refusal)
    queue = list(moved)
    breaks: list[str] = []

    def refuse(at: str, code: str, why: str) -> MovePlan:
        plan.refused, plan.refused_at, plan.code = why, [at], code
        return plan

    def chain(x: str) -> list[str]:
        out = []
        while x in via:
            out.append(x)
            x = via[x]
        return out[::-1]

    def lead(x: str) -> str:
        what = _names(scene, asked[:1]) + (f" (with {len(asked) - 1} more)" if len(asked) > 1 else "")
        took = chain(x)
        return f"moving {what} {move_words(delta)}" + (f" would take {_names(scene, took)} along, and" if took else "")

    while queue:
        x = queue.pop(0)
        plan.partners.setdefault(x, set())
        for j in joints_of(scene, x):
            n = j.b
            plan.partners[x].add(n)
            if n in inside:
                plan.kept.append(j)
                continue
            if not carry:
                if n not in breaks:
                    breaks.append(n)
                continue
            cls = classify(scene, n)
            if cls != "stays" and context_eval.element_constraints(scene, n):
                cls = "stays"
            st = stretched.get(n)
            if st is not None:
                face = j.end_b if j.end_b in ("start", "end") else "side"
                same = st.face == face and (face != "side" or np.allclose(st.normal, _side_normal(scene, n, j.point_m)))
                if same:
                    plan.kept.append(j)
                    continue
                del stretched[n]               # reached at a second face: it moves whole
                cls = "rigid"
            if cls == "stays":
                kind = kind_words(scene, n)
                return refuse(n, "stays", f"{lead(x)} would pull {_names(scene, [x])} apart from {kind} "
                                          f"{_names(scene, [n])}, which stays where it is (an offset or a route keeps "
                                          f"the run's ends where they are)")
            if cls == "straight" and j.point_m is not None:
                run = edits.run_of(scene, n)
                d = np.asarray(run.direction, float)
                if j.end_b in ("start", "end"):
                    normal = -d if j.end_b == "start" else d
                    across = np.linalg.norm(delta - d * (delta @ d))
                    if across <= PARALLEL_M:
                        by = float(delta @ normal)
                        size = run.length_m + by
                        if size < edits.MIN_PIECE_M:
                            return refuse(n, "short", f"{lead(x)} would make {_names(scene, [n])} "
                                                      f"{max(size, 0) * 1000:.0f} mm long (it can lose at most "
                                                      f"{(run.length_m - edits.MIN_PIECE_M) * 1000:.0f} mm)")
                        stretched[n] = Stretch(n, j.end_b, by, tuple(normal.tolist()), size)
                        plan.kept.append(j)
                        continue
                elif j.end_b == "side":
                    normal = _side_normal(scene, n, j.point_m)
                    if not _covered(scene, n, normal, j.point_m, x):
                        return refuse(n, "branch", f"{lead(x)} would pull {_names(scene, [x])} along the side of "
                                                   f"{_names(scene, [n])}, which it branches off (an offset or a "
                                                   f"route keeps it where it is)")
                    if np.linalg.norm(delta - normal * (delta @ normal)) <= PARALLEL_M:
                        by = float(delta @ normal)
                        across = (run.depth_m if abs(normal[2]) > 0.5 else run.width_m) + by
                        if across < edits.MIN_PIECE_M:
                            return refuse(n, "short", f"{lead(x)} would make {_names(scene, [n])} "
                                                      f"{max(across, 0) * 1000:.0f} mm across")
                        stretched[n] = Stretch(n, "side", by, tuple(normal.tolist()), across)
                        plan.kept.append(j)
                        continue
            # taken along: a fitting, a valve, or a segment the move does not run along
            inside.add(n)
            via[n] = x
            plan.moved.append(n)
            plan.carried.append(n)
            plan.kept.append(j)
            queue.append(n)
            if len(plan.carried) > CARRY_MAX:
                what = _names(scene, asked[:1]) + (f" (with {len(asked) - 1} more)" if len(asked) > 1 else "")
                return refuse(n, "many", f"moving {what} {move_words(delta)} would take more than {CARRY_MAX} parts "
                                         f"along to keep its joints, starting with {_names(scene, plan.carried[:3])} "
                                         f"(an offset or a route changes less)")
    if breaks:
        what = _names(scene, asked[:1]) + (f" (with {len(asked) - 1} more)" if len(asked) > 1 else "")
        one = len(breaks) == 1
        plan.refused = (f"moving {what} {move_words(delta)} would pull it apart from {_names(scene, breaks)}, "
                        f"joined to it, which stay{'s' if one else ''} where {'it is' if one else 'they are'} (split "
                        f"it with an offset or a route so its ends stay put)")
        plan.refused_at, plan.code = breaks, "joined"
        return plan
    plan.stretched = list(stretched.values())
    for st in plan.stretched:
        plan.partners[st.global_id] = {j.b for j in joints_of(scene, st.global_id)}
    return plan


def summary(scene: IfcScene, plan: MovePlan) -> str:
    """"move north 250 mm; takes 'bend 2' and 'bend 3' along; 'segment 2' and 'segment 4' 250 mm shorter"."""
    parts = [f"move {move_words(plan.delta_m)}"]
    if plan.carried:
        parts.append(f"takes {_names(scene, plan.carried)} along")
    by_change: dict[tuple, list[str]] = {}
    for st in plan.stretched:
        by_change.setdefault((st.by_m > 0, round(abs(st.by_m) * 1000)), []).append(st.global_id)
    for (longer, mm), gids in by_change.items():
        parts.append(f"{_names(scene, gids)} {mm} mm {'longer' if longer else 'shorter'}")
    return "; ".join(parts)


def apply_move(scene: IfcScene, plan: MovePlan) -> dict[str, list[float]]:
    """Make a planned move (inside a trial, or for good): translate what moves, stretch what stretches. Returns the
    new world placements of what was translated."""
    placements = scene.translate(plan.moved, tuple(plan.delta_m))
    for st in plan.stretched:
        edits.stretch(scene, st.global_id, st.face, st.by_m, st.normal if st.face == "side" else None)
    return placements


def check_joints(scene: IfcScene, plan: MovePlan) -> list[tuple[str, str, str]]:
    """After a planned move: every joint the changed elements had still meets (ports within TOUCH_M, STEP parts still
    face to face). Returns the ones that don't: (element, what it was joined to, in words)."""
    broken: dict[tuple[str, str], str] = {}
    for g, before in plan.partners.items():
        now = {j.b for j in joints_of(scene, g)}
        for p in system.get_ports(scene.entity(g)):
            q = system.get_connected_port(p)
            if q is None or p.ObjectPlacement is None or q.ObjectPlacement is None:
                continue
            gap = float(np.linalg.norm(scene.placement(p.GlobalId)[:3, 3] - scene.placement(q.GlobalId)[:3, 3]))
            other = system.get_port_element(q)
            if gap > TOUCH_M and other is not None:
                broken[(g, other.GlobalId)] = (f"{_names(scene, [g])} and {_names(scene, [other.GlobalId])} "
                                               f"{gap * 1000:.0f} mm apart")
        for b in before - now:
            broken.setdefault((g, b), f"{_names(scene, [g])} no longer meets {_names(scene, [b])}")
    return [(a, b, words) for (a, b), words in broken.items()]


BASELINE_M = 0.1   # what a stretched segment comes this close to before a move is noted, for any clearance up to it


def baseline(scene: IfcScene, plan: MovePlan, clearance_m: float = BASELINE_M) -> dict[str, float]:
    """What the segments a move stretches touch or come close to now (a riser on its gland plate): only contacts new or
    worse than these count against the move."""
    stretched = [st.global_id for st in plan.stretched]
    if not stretched:
        return {}
    joined = {b for g in stretched for b in plan.partners.get(g, ())}
    v = verify.check(scene, stretched, clearance_m=clearance_m, ignore=set(plan.changed()) | joined)
    return {h.other: h.distance_m for h in v.hits}


def check_applied(scene: IfcScene, plan: MovePlan, clearance_m: float,
                  base: dict[str, float]) -> tuple[list[verify.Hit], float | None, int]:
    """Check a planned move in place (`apply_move` done): what moves against everything but what it changes and what
    those are joined to (their joints hold: `check_joints`), and the stretched segments for anything new or worse than
    `base`. Broken joints come back as "joint" hits. → (hits, least clearance, elements checked against)."""
    joined = {b for g in plan.changed() for b in plan.partners.get(g, ())}
    ignore = set(plan.changed()) | joined
    v = verify.check(scene, plan.moved, clearance_m=clearance_m, ignore=ignore)
    hits, least, checked = list(v.hits), v.min_clearance_m, v.checked_against
    stretched = [st.global_id for st in plan.stretched]
    if stretched:   # what they touched already (a riser on its plate) is neither a hit nor this move's clearance
        already = {o for o, gap in base.items() if gap < clearance_m}   # too close before the move: not its doing
        w = verify.check(scene, stretched, clearance_m=clearance_m, ignore=ignore, touching=already)
        hits += [h for h in w.hits if h.other not in base or h.distance_m < base[h.other] - 0.002]
        checked = max(checked, w.checked_against)
        if w.min_clearance_m is not None:
            least = w.min_clearance_m if least is None else min(least, w.min_clearance_m)
    for a, b, _ in check_joints(scene, plan):
        hits.append(verify.Hit(b, scene.entity(b).is_a(), "joint", 0.0))
    return hits, least, checked


@dataclass
class MoveTrial:
    hits: list
    least: float | None
    checked: int
    placements: dict
    preview: list | None      # the stretched segments as they would be (world triangles), when asked for


def trial_move(scene: IfcScene, plan: MovePlan, clearance_m: float, on_trial=None, preview: bool = False) -> MoveTrial:
    """Try a planned move that takes parts along or stretches segments, check it, undo it."""
    stretched = [st.global_id for st in plan.stretched]
    base = baseline(scene, plan)
    with edits.trial_files(scene, {scene.index_of(g) for g in plan.changed()}):
        placements = apply_move(scene, plan)
        shape = edits.meshes(scene, stretched) if stretched and (on_trial or preview) else None
        if on_trial:
            on_trial({"kind": "move", "moved": plan.moved, "delta_m": plan.delta_m, "pieces": shape,
                      "summary": summary(scene, plan)})
        hits, least, checked = check_applied(scene, plan, clearance_m, base)
    return MoveTrial(hits, least, checked, placements, shape)


DIRECTIONS = (("north", (0, 1, 0)), ("south", (0, -1, 0)), ("east", (1, 0, 0)), ("west", (-1, 0, 0)),
              ("up", (0, 0, 1)), ("down", (0, 0, -1)))


def _outcome(scene: IfcScene, plan: MovePlan) -> str:
    """A dry plan's outcome, in a few words for Muse."""
    if plan.ok:
        bits = []
        if plan.carried:
            bits.append(f"takes {_names(scene, plan.carried)} along")
        shorter = [st for st in plan.stretched if st.by_m < 0]
        if plan.stretched:
            one = len(plan.stretched) == 1
            bits.append(f"{_names(scene, [st.global_id for st in plan.stretched])} get{'s' if one else ''} longer or shorter")
        if shorter:   # how far before the first of them gets too short
            room = min(st.size_m - edits.MIN_PIECE_M for st in shorter) + abs(shorter[0].by_m)
            bits.append(f"up to {room:.2f} m")
        return "keeps its joints" + (f" ({'; '.join(bits)})" if bits else "")
    n = plan.refused_at[0] if plan.refused_at else None
    name = _names(scene, [n]) if n else "a joint"
    why = {"stays": f"{kind_words(scene, n)} {name} beyond it stays where it is" if n else "a joint would break",
           "short": f"{name} would get too short", "branch": f"it would slide along {name}, which it branches off",
           "many": f"it would take more than {CARRY_MAX} parts along"}.get(plan.code or "", plan.refused or "")
    return f"cannot ({why})"


def describe(scene: IfcScene, label: str, gid: str, memo: dict | None = None) -> list[str]:
    """What Muse reads about an element's joints: what its run is joined to, and for each direction whether a whole
    move keeps them (and what it takes along or stretches) or why it can't."""
    if memo is not None and ("joints", gid) in memo:
        return memo[("joints", gid)]
    lines: list[str] = []
    if mode() != "off" and is_flow(scene, gid):
        mine = run(scene, gid)
        inside = set(mine)
        ends = [f"{kind_words(scene, j.b)} '{scene.element(j.b).name}'"
                for g in mine for j in joints_of(scene, g) if j.b not in inside]
        ends = [e + (f" (x{ends.count(e)})" if ends.count(e) > 1 else "") for e in dict.fromkeys(ends)]
        if ends:
            run_words = "" if len(mine) == 1 else f" (with the {len(mine) - 1} straight segment(s) joined to it)"
            if mode() == "refuse":
                lines.append(f"Element {label}{run_words} is joined to {', '.join(ends)}. A whole move would pull "
                             f"those joints apart, so it is refused: use an offset or a route, which keep its ends "
                             f"where they are.")
            else:
                by_outcome: dict[str, list[str]] = {}
                for name, vec in DIRECTIONS:
                    plan = plan_move(scene, mine, np.asarray(vec, float) * 0.1)
                    by_outcome.setdefault(_outcome(scene, plan), []).append(name)
                lines.append(f"Element {label}{run_words} is joined to {', '.join(ends)}. A move keeps its joints: "
                             f"fittings and valves beyond it go along, and a straight segment beyond them gets longer "
                             f"or shorter when the move runs along it; equipment, terminals and structure never "
                             f"move, so a move that would pull them is refused.")
                lines.append(f"Moving {label} (tried at 100 mm): " + "; ".join(
                    f"{' / '.join(dirs)}: {what}" for what, dirs in by_outcome.items()))
    if memo is not None:
        memo[("joints", gid)] = lines
    return lines


# ---------------------------------------------------------------------------------------------------- the graph

KINDS = ("joint", "assembly", "hosted", "rests_on", "contact")
RESTS_M = 0.005     # a foot within this of a top, overlapping in plan, rests on it (as hosts.STANDS_ON_M)
PROVISION_PSET = "ORCA_Provision"


def graph(scene: IfcScene, contacts=()) -> dict:
    """Everything joined to anything in the open models, for the viewer and for describing an element: edges
    [a, b, kind, source], kind one of
    - "joint": connected ports, or STEP flow parts face to face ("ports" / "geometry");
    - "assembly": an element and its parts (aggregated or nested elements), when the whole has a body of its own;
    - "hosted": a door or window in the wall whose opening it fills, a provision for void and the service and host it
      is for;
    - "rests_on": a's foot within 5 mm of b's top, overlapping in plan ([a, b]: a rests on b);
    - "contact": pairs the last check found touching (`contacts`), not already linked.
    Also `stops` (flow elements a run ends at: equipment, terminals), `systems` (element → system names),
    `assemblies` (whole → {name, parts}: a curtain wall's mullions and plates, a stair's flights; the whole often has
    no body of its own) and `names` (every linked element's name, for the hover label). Cached on the scene until it
    changes."""
    key = (scene.revision, hash(tuple(sorted(tuple(c) for c in contacts))), len(scene.bounds()))
    cached = getattr(scene, "_joint_graph", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    boxes = scene.bounds()
    edges: dict[frozenset, list] = {}
    assemblies: dict[str, dict] = {}

    def add(a, b, kind, source=""):
        if a != b and a in boxes and b in boxes and frozenset((a, b)) not in edges:
            edges[frozenset((a, b))] = [a, b, kind, source]

    for m in scene.models:
        for rel in m.by_type("IfcRelConnectsPorts"):
            owners = [system.get_port_element(p) for p in (rel.RelatingPort, rel.RelatedPort)]
            if all(o is not None for o in owners):
                add(owners[0].GlobalId, owners[1].GlobalId, "joint", "ports")
        for e in m.by_type(FLOW):
            if step_source(e).get("Group"):
                for j in _geometry_joints(scene, e.GlobalId):
                    add(j.a, j.b, "joint", "geometry")
        for rel in list(m.by_type("IfcRelAggregates")) + list(m.by_type("IfcRelNests")):
            whole = rel.RelatingObject
            if whole.is_a("IfcElement"):
                parts = [p.GlobalId for p in rel.RelatedObjects if p.is_a("IfcElement") and p.GlobalId in boxes]
                for part in parts:
                    add(whole.GlobalId, part, "assembly")
                if parts:
                    entry = assemblies.setdefault(whole.GlobalId, {"name": whole.Name or whole.is_a()[3:], "parts": []})
                    entry["parts"] += parts
        for rel in m.by_type("IfcRelFillsElement"):
            for voids in rel.RelatingOpeningElement.VoidsElements or ():
                add(rel.RelatedBuildingElement.GlobalId, voids.RelatingBuildingElement.GlobalId, "hosted")
        for e in m.by_type("IfcBuildingElementProxy"):
            pset = ifcopenshell.util.element.get_pset(e, PROVISION_PSET) or {}
            for other in (pset.get("Service"), pset.get("Host")):
                if isinstance(other, str):
                    edges.setdefault(frozenset((e.GlobalId, other)), [e.GlobalId, other, "hosted", "provision"])
    # Resting: sort tops, then for each foot look up the tops at its height.
    gids = list(boxes)
    if gids:
        lo = np.array([boxes[g][0] for g in gids])
        hi = np.array([boxes[g][1] for g in gids])
        order = np.argsort(hi[:, 2])
        tops = hi[order, 2]
        for i, g in enumerate(gids):
            first = np.searchsorted(tops, lo[i, 2] - RESTS_M, "left")
            last = np.searchsorted(tops, lo[i, 2] + RESTS_M, "right")
            for k in order[first:last]:
                if k != i and np.all(lo[i, :2] < hi[k, :2] - 0.001) and np.all(hi[i, :2] > lo[k, :2] + 0.001):
                    add(g, gids[k], "rests_on")
    for a, b in contacts:
        add(a, b, "contact")
    stops, systems = [], {}
    for m in scene.models:
        for e in m.by_type(FLOW):
            if e.GlobalId not in boxes:
                continue
            if classify(scene, e.GlobalId) == "stays":
                stops.append(e.GlobalId)
            names = [s.Name for s in system.get_element_systems(e) if s.Name]
            if names:
                systems[e.GlobalId] = names
    linked = {g for edge in edges.values() for g in edge[:2]}
    names = {}
    for g in linked:
        e = scene.entity(g)
        names[g] = e.Name or e.is_a()[3:]
    out = {"revision": scene.revision, "edges": list(edges.values()), "stops": stops, "systems": systems,
           "assemblies": assemblies, "names": names, "kinds": list(KINDS)}
    scene._joint_graph = (key, out)
    return out


def links_of(scene: IfcScene, gid: str, contacts=()) -> dict[str, list[str]]:
    """An element's direct links by kind ("rests_on" are what it rests on; "supports" what rests on it)."""
    out: dict[str, list[str]] = {}
    for a, b, kind, _ in graph(scene, contacts)["edges"]:
        if gid not in (a, b):
            continue
        other = b if a == gid else a
        name = "supports" if kind == "rests_on" and b == gid else kind
        out.setdefault(name, []).append(other)
    return out
