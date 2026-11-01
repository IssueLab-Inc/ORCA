"""The faces of an element's body, as a person points at them and names them (docs/manual-edits.md).

A pick on the page is a point and a normal on the element's triangles. ORCA edits parameters, not triangles, so the
pick is resolved to a face of the body's one straight extrusion (`edits._frames`):

- `cap:start` / `cap:end`: the extrusion's ends (a beam's or duct's ends, a wall's two big faces, a slab's top and
  bottom). Push/pull changes the extrusion's depth.
- `side:+x` / `side:-x` / `side:+y` / `side:-y`: the sides of a rectangle profile. Push/pull changes its width.
- `radial`: a circle profile's round face. Push/pull changes its radius.
- `flank`: any face of an I, U, C, L or T section's side. Its ends only are edited; it can be aligned by moving.
- `edge:k`: one straight edge of an outline (a wall drawn as its elevation: its ends and top; a slab's edges).
  Push/pull moves that edge and the edges either side follow.

Each face gets a name in words from its world normal and the element's box, so Muse and the log can say it: "top",
"bottom", or a compass direction and "end" (along its longest size), "face" (a plate's or wall's big face) or "side".
A body that is not one straight extrusion (fittings, terminals, meshes) has no faces to edit; it can still be moved
and aligned by moving (`kind` "other").
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import ifcopenshell.util.placement
import numpy as np

from . import edits
from .scene import IfcScene

CAP_COS = np.cos(np.radians(5))      # a normal within 5° of the extrusion is on a cap
SIDE_COS = 0.99                      # a normal within ~8° of a profile axis (or an edge's normal) is on that side
NEAR_M = 0.005                       # a pick this close to a face's plane is on it

ALLOWS = {
    "cap": ["push_pull", "align", "clip", "void"],
    "side": ["push_pull", "align", "void"],
    "radial": ["push_pull", "align"],
    "flank": ["align", "void"],
    "edge": ["push_pull", "align"],
    "other": ["align"],
}


@dataclass
class Face:
    element: str
    id: str                  # cap:start, cap:end, side:+x, ..., radial, flank, edge:3, other
    kind: str                # cap, side, radial, flank, edge, other
    name: str                # "east end", "top", "north face"
    normal: list[float]      # world, outward
    point: list[float]       # world metres, on the face (its middle for a listed face, the pick for a resolved one)
    size_m: float | None     # what push/pull changes: the length (cap), the width across (side), the diameter (radial)
    allows: list[str] = field(default_factory=list)
    why_not: str | None = None   # why it has nothing to edit but a move

    def to_dict(self) -> dict:
        return asdict(self)


def _world(scene: IfcScene, element):
    """The extrusion's frame: file index, unit scale, item, its world matrix (file units)."""
    i, place, item, *_ = edits._frames(scene, element)
    world = place @ ifcopenshell.util.placement.get_axis2placement(item.Position)
    return i, scene.unit_scales[i], item, world


def _profile_frame(profile) -> np.ndarray:
    """A parametric profile's own 2D placement in the solid's XY (3x3), or the identity."""
    pos = getattr(profile, "Position", None)
    m = np.eye(3)
    if pos is not None:
        loc = np.asarray(pos.Location.Coordinates[:2], float)
        x = np.asarray(pos.RefDirection.DirectionRatios[:2], float) if pos.RefDirection is not None else np.array([1.0, 0.0])
        x = x / np.linalg.norm(x)
        m[:2, 0], m[:2, 1], m[:2, 2] = x, [-x[1], x[0]], loc
    return m


def outline(profile) -> list[np.ndarray] | None:
    """An arbitrary profile's outer outline as 2D points (no closing repeat), or None when it is not straight edges."""
    curve = getattr(profile, "OuterCurve", None)
    if curve is None:
        return None
    if curve.is_a("IfcPolyline"):
        pts = [np.asarray(p.Coordinates[:2], float) for p in curve.Points]
    elif curve.is_a("IfcIndexedPolyCurve"):
        if curve.Segments and any(not s.is_a("IfcLineIndex") for s in curve.Segments):
            return None
        coords = [np.asarray(c[:2], float) for c in curve.Points.CoordList]
        if curve.Segments:
            order = []
            for s in curve.Segments:
                for k in s.wrappedValue:
                    if not order or order[-1] != k - 1:
                        order.append(k - 1)
            pts = [coords[k] for k in order]
        else:
            pts = coords
    else:
        return None
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    return pts if len(pts) >= 3 else None


def ccw(pts: list[np.ndarray]) -> bool:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) > 0


def edge_normal(a: np.ndarray, b: np.ndarray, anticlockwise: bool) -> np.ndarray:
    d = (b - a) / np.linalg.norm(b - a)
    return np.array([d[1], -d[0]]) if anticlockwise else np.array([-d[1], d[0]])


def _name(scene: IfcScene, gid: str, n: np.ndarray) -> str:
    """A face in words from its world normal: top or bottom, else a compass direction and end, face or side."""
    if n[2] > 0.9:
        return "top"
    if n[2] < -0.9:
        return "bottom"
    compass = ("east" if n[0] > 0 else "west") if abs(n[0]) >= abs(n[1]) else ("north" if n[1] > 0 else "south")
    box = scene.bounds().get(gid)
    if box is None:
        return f"{compass} side"
    size = box[1] - box[0]
    along = abs(n[0]) * size[0] + abs(n[1]) * size[1]      # how big the element is along the normal
    across = abs(n[1]) * size[0] + abs(n[0]) * size[1]     # and across it, horizontally
    if along >= across and along >= size[2] * 0.999:
        return f"{compass} end"
    if along * 3 <= min(across, size[2]):
        return f"{compass} face"
    return f"{compass} side"


def faces(scene: IfcScene, gid: str) -> list[Face]:
    """Every face of the element's body there is to edit, with its name (numbered when two share one)."""
    element = scene.entity(gid)
    try:
        i, s, item, world = _world(scene, element)
    except edits.Unsupported:
        return [Face(gid, "other", "other", "the element", [0.0, 0.0, 1.0], [], None, list(ALLOWS["other"]),
                     "its body is several solids or a mesh, not one straight extrusion: it can be moved or aligned by moving")]
    R, T = world[:3, :3], world[:3, 3]
    d = R[:, 2] / np.linalg.norm(R[:, 2])
    depth = item.Depth
    prof = item.SweptArea
    pf = _profile_frame(prof)

    def w(p2, z):   # profile point (solid XY) and height → world metres
        return ((R @ np.array([p2[0], p2[1], z]) + T) * s).tolist()

    def wn(n2):
        v = R @ np.array([n2[0], n2[1], 0.0])
        return (v / np.linalg.norm(v)).tolist()

    centre = pf[:2, 2]
    out: list[Face] = []
    pts = outline(prof)
    if pts is not None:
        centre = np.mean(pts, axis=0)
    out.append(Face(gid, "cap:start", "cap", "", (-d).tolist(), w(centre, 0.0), depth * s, list(ALLOWS["cap"])))
    out.append(Face(gid, "cap:end", "cap", "", d.tolist(), w(centre, depth), depth * s, list(ALLOWS["cap"])))
    if prof.is_a() == "IfcRectangleProfileDef":
        for axis, half, size in (("x", prof.XDim / 2, prof.YDim), ("y", prof.YDim / 2, prof.XDim)):
            for sign in (1, -1):
                k = 0 if axis == "x" else 1
                n2 = pf[:2, k] * sign
                p2 = pf[:2, 2] + n2 * half
                out.append(Face(gid, f"side:{'+' if sign > 0 else '-'}{axis}", "side", "", wn(n2), w(p2, depth / 2),
                                (prof.XDim if axis == "x" else prof.YDim) * s, list(ALLOWS["side"])))
    elif prof.is_a("IfcCircleProfileDef"):
        out.append(Face(gid, "radial", "radial", "", wn(pf[:2, 0]), w(pf[:2, 2] + pf[:2, 0] * prof.Radius, depth / 2),
                        2 * prof.Radius * s, list(ALLOWS["radial"])))
    elif pts is not None:
        anti = ccw(pts)
        for k, (a, b) in enumerate(zip(pts, pts[1:] + pts[:1])):
            if np.linalg.norm(b - a) < 1e-9:
                continue
            n2 = edge_normal(a, b, anti)
            out.append(Face(gid, f"edge:{k}", "edge", "", wn(n2), w((a + b) / 2, depth / 2),
                            float(np.linalg.norm(b - a) * s), list(ALLOWS["edge"])))
    else:
        out.append(Face(gid, "flank", "flank", "", wn(pf[:2, 1]), w(pf[:2, 2], depth / 2), None, list(ALLOWS["flank"])))
    names: dict[str, int] = {}
    for f in out:
        base = {"flank": "sides", "radial": "round side"}.get(f.kind) or _name(scene, gid, np.asarray(f.normal))
        names[base] = names.get(base, 0) + 1
        f.name = base if names[base] == 1 else f"{base} {names[base]}"
    return out


def resolve(scene: IfcScene, gid: str, point, normal) -> Face:
    """The face under a pick: world metres and the world normal of the triangle picked."""
    element = scene.entity(gid)
    P, N = np.asarray(point, float), np.asarray(normal, float)
    N = N / (np.linalg.norm(N) or 1.0)
    listed = faces(scene, gid)
    if listed[0].kind == "other":
        f = listed[0]
        return Face(gid, "other", "other", _name(scene, gid, N), N.tolist(), P.tolist(), None, f.allows, f.why_not)
    i, s, item, world = _world(scene, element)
    inv = np.linalg.inv(world)
    q = (inv @ np.append(P / s, 1.0))[:3]
    nl = world[:3, :3].T @ N
    nl = nl / (np.linalg.norm(nl) or 1.0)
    near = NEAR_M / s

    def pick(face_id: str) -> Face:
        f = next(x for x in listed if x.id == face_id)
        return Face(gid, f.id, f.kind, f.name, f.normal, P.tolist(), f.size_m, f.allows, f.why_not)

    if abs(nl[2]) > CAP_COS:
        return pick("cap:end" if nl[2] > 0 else "cap:start")
    prof = item.SweptArea
    pf = _profile_frame(prof)
    n2 = np.array([nl[0], nl[1]]) / (np.linalg.norm(nl[:2]) or 1.0)
    if prof.is_a() == "IfcRectangleProfileDef":
        nx, ny = n2 @ pf[:2, 0], n2 @ pf[:2, 1]
        if max(abs(nx), abs(ny)) > SIDE_COS:
            return pick(f"side:{'+' if (nx if abs(nx) > abs(ny) else ny) > 0 else '-'}{'x' if abs(nx) > abs(ny) else 'y'}")
    elif prof.is_a("IfcCircleProfileDef"):
        return pick("radial")
    pts = outline(prof)
    if pts is not None:
        anti, q2 = ccw(pts), q[:2]
        best = None
        for k, (a, b) in enumerate(zip(pts, pts[1:] + pts[:1])):
            if np.linalg.norm(b - a) < 1e-9:
                continue
            en = edge_normal(a, b, anti)
            off = abs((q2 - a) @ en)
            if en @ n2 > SIDE_COS and off <= near and (best is None or off < best[0]):
                best = (off, k)
        if best is not None:
            return pick(f"edge:{best[1]}")
        inner = getattr(prof, "InnerCurves", None)
        why = "a face of a hole in its outline" if inner else "a face ORCA does not edit"
        return Face(gid, "other", "other", _name(scene, gid, N), N.tolist(), P.tolist(), None, ["align"], why)
    if not prof.is_a("IfcRectangleProfileDef"):
        f = pick("flank")
        f.normal, f.name = N.tolist(), _name(scene, gid, N)
        return f
    return Face(gid, "other", "other", _name(scene, gid, N), N.tolist(), P.tolist(), None, ["align"],
                "a face ORCA does not edit")


def by_name(scene: IfcScene, gid: str, name: str) -> Face:
    """A face by its id ("cap:end") or its name ("east end"), as Muse or a person says it."""
    want = name.strip().lower()
    listed = faces(scene, gid)
    for f in listed:
        if f.id == want or f.name == want:
            return f
    for f in listed:   # "the east end" / "east" / "end"
        if want.replace("the ", "") == f.name or (want in f.name.split()):
            return f
    raise KeyError(f"no face called {name!r}: its faces are {', '.join(f.name for f in listed)}")
