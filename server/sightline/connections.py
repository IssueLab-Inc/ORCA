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

import os
from dataclasses import dataclass, field

import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.system as system
import numpy as np

from . import edits
from .scene import FIXED_CLASSES, IfcScene, step_source

TOUCH_M = 0.002       # two faces of a joint meet within this (as context_eval.TOL)
FACING = 0.95         # and face each other: normals opposed within about 18°
MODES = ("carry", "refuse", "off")
FLOW = "IfcDistributionFlowElement"
INLINE = ("IfcValve", "IfcDamper", "IfcFlowMeter")              # controllers that sit in a run and move with it
INLINE_TYPES = ("IfcValveType", "IfcDamperType", "IfcFlowMeterType")   # IFC2X3: an IfcFlowController by its type


def mode() -> str:
    """How moves treat joints (SIGHTLINE_CONNECTED_MOVES): "refuse" a move that would leave one apart, "carry" the
    parts beyond it along, or "off" (moves as before joints were known: a run up to its fittings, joints ignored)."""
    m = os.environ.get("SIGHTLINE_CONNECTED_MOVES", "refuse").strip().lower()
    return m if m in MODES else "refuse"


@dataclass(frozen=True)
class Joint:
    a: str                      # the element asked about (joints_of(a))
    b: str                      # what it is joined to
    point_m: tuple | None       # where, world metres (None: a port with no placement)
    source: str                 # "ports" | "geometry"
    end_a: str | None = None    # a straight segment's "start" / "end" cap, or "side"; None for anything else
    end_b: str | None = None


@dataclass
class MovePlan:
    moved: list[str]                                   # what is translated
    delta_m: list[float]
    kept: list[Joint] = field(default_factory=list)    # joints the move keeps (all inside what moves)
    refused: str | None = None                         # why the move can't keep its joints, in plain words
    refused_at: list[str] = field(default_factory=list)  # the elements whose joints it would break

    @property
    def ok(self) -> bool:
        return self.refused is None


# ---------------------------------------------------------------------------------------------------- classes

def is_flow(scene: IfcScene, gid: str) -> bool:
    return scene.entity(gid).is_a(FLOW)


def classify(scene: IfcScene, gid: str) -> str:
    """"straight", "rigid" or "stays" (see the module's docstring)."""
    ent = scene.entity(gid)
    if not ent.is_a(FLOW) or any(ent.is_a(c) for c in FIXED_CLASSES):
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


def plan_move(scene: IfcScene, moved: list[str], delta_m) -> MovePlan:
    """Plan moving `moved` by `delta_m` with its joints: a joint between something that moves and something that
    doesn't would come apart, so the move is refused, naming those joints ("refuse"; "carry" takes such parts along
    in a later slice). Nothing is edited."""
    moved = list(dict.fromkeys(moved))
    delta = [float(v) for v in delta_m]
    plan = MovePlan(moved, delta)
    if mode() == "off" or not any(abs(v) >= 0.0005 for v in delta):
        return plan
    inside = set(moved)
    breaks: list[str] = []
    for g in moved:
        for j in joints_of(scene, g):
            if j.b in inside:
                plan.kept.append(j)
            elif j.b not in breaks:
                breaks.append(j.b)
    if breaks:
        what = _names(scene, moved[:1]) + (f" (with {len(moved) - 1} more)" if len(moved) > 1 else "")
        one = len(breaks) == 1
        plan.refused = (f"moving {what} {move_words(delta)} would pull it apart from {_names(scene, breaks)}, "
                        f"joined to it, which stay{'s' if one else ''} where {'it is' if one else 'they are'} (split "
                        f"it with an offset or a route so its ends stay put)")
        plan.refused_at = breaks
    return plan


def describe(scene: IfcScene, label: str, gid: str, memo: dict | None = None) -> list[str]:
    """What Muse reads about an element's joints: what it is joined to, and whether a whole move keeps them."""
    if memo is not None and ("joints", gid) in memo:
        return memo[("joints", gid)]
    lines: list[str] = []
    if mode() != "off" and is_flow(scene, gid):
        mine = run(scene, gid)
        inside = set(mine)
        ends = []
        for g in mine:
            for j in joints_of(scene, g):
                if j.b not in inside:
                    ends.append(f"{kind_words(scene, j.b)} '{scene.element(j.b).name}'")
        ends = [e + (f" (x{ends.count(e)})" if ends.count(e) > 1 else "") for e in dict.fromkeys(ends)]
        if ends:
            run_words = "" if len(mine) == 1 else f" (with the {len(mine) - 1} straight segment(s) joined to it)"
            lines.append(f"Element {label}{run_words} is joined to {', '.join(ends)}. A whole move would pull those "
                         f"joints apart, so it is refused: use an offset or a route, which keep its ends where they "
                         f"are.")
    if memo is not None:
        memo[("joints", gid)] = lines
    return lines
