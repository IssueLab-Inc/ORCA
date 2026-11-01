"""The faces of an element's body, as a person points at them and names them (docs/manual-edits.md).

A pick on the page is a point and a normal on the element's triangles. ORCA edits parameters where it can, so the pick
is resolved to a face of one solid of the body (`edits.solids`):

- `cap:start` / `cap:end`: an extrusion's ends (a beam's or duct's ends, a wall's two big faces, a slab's top and
  bottom). Push/pull changes the extrusion's depth.
- `side:+x` / `side:-x` / `side:+y` / `side:-y`: the sides of a rectangle profile (push/pull changes its width), and an
  I, U, C, L or T section's outer sides (its overall width or depth: a section change).
- `radial`: a circle profile's round face. Push/pull changes its radius.
- `flank`: an I, U, C, L or T section's inner faces (its web, its flanges inside), or any side of a profile ORCA does
  not size. Aligned by moving, or cut; only a pick places one.
- `edge:k`: one straight edge of an outline (a wall drawn as its elevation: its ends and top; a slab's edges).
  Push/pull moves that edge and the edges either side follow.
- `plane:j`: a flat face of a mesh (a triangulated fitting, a faceted body). Push/pull moves its corners.
- `clip:j`: a clip's plane (a clipped end). Push/pull moves the plane: it takes less or more away.

A body of several solids (a fitting's pieces, a door's frame and leaf, a desk) lists each solid's faces, their ids
prefixed with its place in the body (`i1:cap:end`); a body of one solid keeps plain ids. Each face gets a name in words
from its world normal and the element's box, so Muse and the log can say it: "top", "bottom", or a compass direction and
"end" (along its longest size), "face" (a plate's or wall's big face) or "side". A body ORCA cannot read (a swept disk,
a type's mapped shape) can still be moved and aligned by moving (`kind` "other").
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

ALLOWS = {   # clip takes any face: the element is clipped where the other face is, whichever of its faces was picked
    "cap": ["push_pull", "align", "clip", "void"],
    "side": ["push_pull", "align", "clip", "void"],
    "radial": ["push_pull", "align", "clip"],
    "flank": ["align", "clip", "void"],
    "edge": ["push_pull", "align", "clip", "void"],
    "plane": ["push_pull", "align", "clip", "void"],
    "clip": ["push_pull", "align", "clip", "void"],
    "other": ["align", "clip"],
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
    """The extrusion's frame: file index, unit scale, item, its world matrix (file units). Under a hand edit's clip,
    the extrusion it clips."""
    i, place, item, *_ = edits._frames(scene, element, clipped=True)
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
    return curve_points(getattr(profile, "OuterCurve", None))


def curve_points(curve) -> list[np.ndarray] | None:
    """A closed curve of straight edges as 2D points (no closing repeat): a polyline or an indexed poly curve of
    lines; None for anything else (arcs, a composite curve)."""
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


def split_id(face_id: str) -> tuple[int | None, str]:
    """A face id's solid and its own id: "i2:cap:end" → (2, "cap:end"); "cap:end" → (None, "cap:end")."""
    if face_id.startswith("i") and ":" in face_id and face_id[1:face_id.index(":")].isdigit():
        k = face_id.index(":")
        return int(face_id[1:k]), face_id[k + 1:]
    return None, face_id


def _section(prof) -> tuple[float, float] | None:
    """An I, U, C, L or T section's overall width and depth (profile x, y; file units), or None."""
    dims = edits.SECTION_DIMS.get(prof.is_a())
    return None if dims is None else (edits._section_dim(prof, dims[0]), edits._section_dim(prof, dims[1]))


def _extrusion_faces(scene: IfcScene, gid: str, so: edits.Solid, s: float, pre: str) -> list[Face]:
    world = so.world
    R, T = world[:3, :3], world[:3, 3]
    d = R[:, 2] / np.linalg.norm(R[:, 2])
    item = so.item
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
    out.append(Face(gid, f"{pre}cap:start", "cap", "", (-d).tolist(), w(centre, 0.0), depth * s, list(ALLOWS["cap"])))
    out.append(Face(gid, f"{pre}cap:end", "cap", "", d.tolist(), w(centre, depth), depth * s, list(ALLOWS["cap"])))
    box = (prof.XDim, prof.YDim) if prof.is_a() == "IfcRectangleProfileDef" else _section(prof)
    if box is not None:
        for axis, half, size in (("x", box[0] / 2, box[0]), ("y", box[1] / 2, box[1])):
            for sign in (1, -1):
                k = 0 if axis == "x" else 1
                n2 = pf[:2, k] * sign
                p2 = pf[:2, 2] + n2 * half
                out.append(Face(gid, f"{pre}side:{'+' if sign > 0 else '-'}{axis}", "side", "", wn(n2), w(p2, depth / 2),
                                size * s, list(ALLOWS["side"])))
        if prof.is_a() != "IfcRectangleProfileDef":   # a section's web and flanges inside: aligned or cut, by a pick
            out.append(Face(gid, f"{pre}flank", "flank", "", wn(pf[:2, 1]), w(pf[:2, 2], depth / 2), None, list(ALLOWS["flank"])))
    elif prof.is_a("IfcCircleProfileDef"):
        out.append(Face(gid, f"{pre}radial", "radial", "", wn(pf[:2, 0]), w(pf[:2, 2] + pf[:2, 0] * prof.Radius, depth / 2),
                        2 * prof.Radius * s, list(ALLOWS["radial"])))
    elif pts is not None:
        anti = ccw(pts)
        for k, (a, b) in enumerate(zip(pts, pts[1:] + pts[:1])):
            if np.linalg.norm(b - a) < 1e-9:
                continue
            n2 = edge_normal(a, b, anti)
            out.append(Face(gid, f"{pre}edge:{k}", "edge", "", wn(n2), w((a + b) / 2, depth / 2),
                            float(np.linalg.norm(b - a) * s), list(ALLOWS["edge"])))
    else:
        out.append(Face(gid, f"{pre}flank", "flank", "", wn(pf[:2, 1]), w(pf[:2, 2], depth / 2), None, list(ALLOWS["flank"])))
    return out


def _clip_faces(scene: IfcScene, gid: str, so: edits.Solid, pre: str, out: list[Face]) -> list[Face]:
    """A clipped solid: each clip's plane is a face (pushed or pulled, it takes less or more away); an end it cut away
    is gone from the list."""
    element = scene.entity(gid)
    v = edits.item_verts(scene, element, so.top)
    planes = edits.clip_planes(scene, element, so)
    kept = []
    for f in out:
        if f.kind == "cap":
            n, p = np.asarray(f.normal), np.asarray(f.point)
            if ((v - p) @ n).max() < -NEAR_M:   # nothing reaches that end now
                continue
        kept.append(f)
    c = v.mean(axis=0)
    for j, (res, P, n) in enumerate(planes):
        on = c - ((c - P) @ n) * n
        thick = float(((P - v) @ n).max())
        kept.append(Face(gid, f"{pre}clip:{j}", "clip", "", n.tolist(), on.tolist(), thick, list(ALLOWS["clip"])))
    return kept


def _mesh_faces(scene: IfcScene, gid: str, so: edits.Solid, pre: str) -> list[Face]:
    """A mesh's big flat faces (each at least 3% of its area, the 12 biggest), outward from its middle."""
    _, world, tris = edits.mesh_world(scene, scene.entity(gid), so)
    patches = edits.mesh_patches(world, tris)
    total = sum(x["area"] for x in patches) or 1.0
    c = world.mean(axis=0)
    out = []
    for j, x in enumerate([x for x in patches if x["area"] >= 0.03 * total][:12]):
        n = x["normal"] if x["normal"] @ (x["point"] - c) >= 0 else -x["normal"]
        thick = float(((x["point"] - world) @ n).max())
        out.append(Face(gid, f"{pre}plane:{j}", "plane", "", n.tolist(), x["point"].tolist(), thick, list(ALLOWS["plane"])))
    return out


def faces(scene: IfcScene, gid: str) -> list[Face]:
    """Every face of the element's body there is to edit, with its name (numbered when two share one). A body of
    several solids lists each one's faces, their ids prefixed with the solid's place in it ("i1:cap:end")."""
    element = scene.entity(gid)
    sol = edits.solids(scene, element)
    s = scene.unit_scales[scene.index_of(gid)]
    out: list[Face] = []
    for so in sol:
        pre = f"i{so.k}:" if so.k is not None else ""
        try:
            if so.kind == "extrusion":
                listed = _extrusion_faces(scene, gid, so, s, pre)
                out += _clip_faces(scene, gid, so, pre, listed) if so.clipped else listed
            elif so.kind == "mesh":
                out += _mesh_faces(scene, gid, so, pre)
        except (RuntimeError, edits.Unsupported, AttributeError, TypeError):
            continue
    if not out:
        why = ("it has no body to edit" if not sol else
               "its body is not extrusions or a mesh ORCA reads: it can be moved or aligned by moving")
        return [Face(gid, "other", "other", "the element", [0.0, 0.0, 1.0], [], None, list(ALLOWS["other"]), why)]
    names: dict[str, int] = {}
    for f in out:
        if f.kind == "flank":
            base = "inner faces" if _has_section(scene, gid, f.id) else "sides"
        else:
            base = "round side" if f.kind == "radial" else _name(scene, gid, np.asarray(f.normal))
        names[base] = names.get(base, 0) + 1
        f.name = base if names[base] == 1 else f"{base} {names[base]}"
    return out


def _has_section(scene: IfcScene, gid: str, face_id: str) -> bool:
    k, _ = split_id(face_id)
    try:
        so = edits.solid(scene, scene.entity(gid), k)
    except edits.Unsupported:
        return False
    return so.kind == "extrusion" and _section(so.item.SweptArea) is not None


def _on_extrusion(scene: IfcScene, so: edits.Solid, s: float, P: np.ndarray) -> float:
    """How far a world point is outside a solid's own box (metres; 0 inside)."""
    item, prof = so.item, so.item.SweptArea
    q = (np.linalg.inv(so.world) @ np.append(P / s, 1.0))[:3]
    pts = outline(prof)
    if pts is not None:
        lo, hi = np.min(pts, axis=0), np.max(pts, axis=0)
    else:
        pf = _profile_frame(prof)
        box = ((prof.XDim, prof.YDim) if prof.is_a() == "IfcRectangleProfileDef" else _section(prof)
               or ((2 * prof.Radius,) * 2 if prof.is_a("IfcCircleProfileDef") else None))
        if box is None:
            return 0.0
        r = np.hypot(*box) / 2   # a turned profile: its circle round its middle
        lo, hi = pf[:2, 2] - r, pf[:2, 2] + r
    out = np.maximum(np.maximum(np.r_[lo, 0.0] - q, q - np.r_[hi, item.Depth]), 0.0)
    return float(np.linalg.norm(out) * s)


def _resolve_extrusion(scene: IfcScene, gid: str, so: edits.Solid, listed: list[Face], P, N) -> Face:
    s = scene.unit_scales[scene.index_of(gid)]
    pre = f"i{so.k}:" if so.k is not None else ""
    world = so.world
    inv = np.linalg.inv(world)
    q = (inv @ np.append(P / s, 1.0))[:3]
    nl = world[:3, :3].T @ N
    nl = nl / (np.linalg.norm(nl) or 1.0)
    near = NEAR_M / s
    mine = {f.id: f for f in listed if split_id(f.id)[0] == so.k}

    def pick(face_id: str) -> Face | None:
        f = mine.get(pre + face_id)
        if f is None:
            return None
        n = f.normal
        if f.kind == "radial":  # the round side's normal where it was picked: square to the axis
            ax = world[:3, 2] / np.linalg.norm(world[:3, 2])
            r = N - (N @ ax) * ax
            n = (r / np.linalg.norm(r)).tolist() if np.linalg.norm(r) > 1e-6 else f.normal
        return Face(gid, f.id, f.kind, f.name, n, P.tolist(), f.size_m, f.allows, f.why_not)

    if so.clipped:   # a pick on a clip's plane
        for f in mine.values():
            if f.kind == "clip" and np.asarray(f.normal) @ N > SIDE_COS and abs((P - np.asarray(f.point)) @ np.asarray(f.normal)) <= NEAR_M:
                return pick(split_id(f.id)[1])
    if abs(nl[2]) > CAP_COS:
        f = pick("cap:end" if nl[2] > 0 else "cap:start")
        if f is not None:
            return f
    prof = so.item.SweptArea
    pf = _profile_frame(prof)
    n2 = np.array([nl[0], nl[1]]) / (np.linalg.norm(nl[:2]) or 1.0)
    box = (prof.XDim, prof.YDim) if prof.is_a() == "IfcRectangleProfileDef" else _section(prof)
    if box is not None:
        nx, ny = n2 @ pf[:2, 0], n2 @ pf[:2, 1]
        q2 = q[:2] - pf[:2, 2]
        along = (q2 @ pf[:2, 0], q2 @ pf[:2, 1])
        if max(abs(nx), abs(ny)) > SIDE_COS:
            k = 0 if abs(nx) > abs(ny) else 1
            sign = nx if k == 0 else ny
            # a rectangle's sides are all there is; a section's outer sides only at its overall width or depth
            if prof.is_a() == "IfcRectangleProfileDef" or abs(along[k] * np.sign(sign) - box[k] / 2) <= near:
                f = pick(f"side:{'+' if sign > 0 else '-'}{'xy'[k]}")
                if f is not None:
                    return f
        if prof.is_a() != "IfcRectangleProfileDef":
            f = pick("flank")
            f.normal, f.name = N.tolist(), _name(scene, gid, N)
            return f
        return Face(gid, "other", "other", _name(scene, gid, N), N.tolist(), P.tolist(), None, list(ALLOWS["other"]),
                    "a face ORCA does not edit")
    if prof.is_a("IfcCircleProfileDef"):
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
        return Face(gid, "other", "other", _name(scene, gid, N), N.tolist(), P.tolist(), None, list(ALLOWS["other"]), why)
    f = pick("flank")
    if f is None:
        return Face(gid, "other", "other", _name(scene, gid, N), N.tolist(), P.tolist(), None, list(ALLOWS["other"]),
                    "a face ORCA does not edit")
    f.normal, f.name = N.tolist(), _name(scene, gid, N)
    return f


def _resolve_mesh(scene: IfcScene, gid: str, so: edits.Solid, listed: list[Face], P, N) -> tuple[float, Face] | None:
    _, world, tris = edits.mesh_world(scene, scene.entity(gid), so)
    try:
        patch = edits.patch_at(world, tris, P, N)
    except edits.Unsupported as e:
        if "curved" not in str(e):
            return None
        return 0.0, Face(gid, "other", "other", _name(scene, gid, N), N.tolist(), P.tolist(), None, list(ALLOWS["other"]), str(e))
    pre = f"i{so.k}:" if so.k is not None else ""
    n = N   # outward: the side it was picked from
    thick = float(((P - world) @ n).max())
    same = next((f for f in listed if f.kind == "plane" and split_id(f.id)[0] == so.k and np.asarray(f.normal) @ n > SIDE_COS
                 and abs((np.asarray(f.point) - P) @ n) <= NEAR_M), None)
    face_id, name = (same.id, same.name) if same else (f"{pre}plane", _name(scene, gid, n))
    tri = world[tris[patch["tris"]]].mean(axis=1)
    return float(np.min(np.linalg.norm(tri - P, axis=1))), Face(gid, face_id, "plane", name, n.tolist(), P.tolist(), thick,
                                                                 list(ALLOWS["plane"]))


def resolve(scene: IfcScene, gid: str, point, normal) -> Face:
    """The face under a pick: world metres and the world normal of the triangle picked. On a body of several solids,
    the solid the pick is on."""
    element = scene.entity(gid)
    P, N = np.asarray(point, float), np.asarray(normal, float)
    N = N / (np.linalg.norm(N) or 1.0)
    listed = faces(scene, gid)
    if listed[0].kind == "other":
        f = listed[0]
        return Face(gid, "other", "other", _name(scene, gid, N), N.tolist(), P.tolist(), None, f.allows, f.why_not)
    s = scene.unit_scales[scene.index_of(gid)]
    found: list[tuple[float, Face]] = []
    for so in edits.solids(scene, element):
        try:
            if so.kind == "extrusion":
                d = _on_extrusion(scene, so, s, P)
                if d <= NEAR_M * 2:
                    found.append((d, _resolve_extrusion(scene, gid, so, listed, P, N)))
            elif so.kind == "mesh":
                r = _resolve_mesh(scene, gid, so, listed, P, N)
                if r is not None:
                    found.append(r)
        except (RuntimeError, edits.Unsupported, AttributeError, TypeError):
            continue
    if not found:
        return Face(gid, "other", "other", _name(scene, gid, N), N.tolist(), P.tolist(), None, list(ALLOWS["other"]),
                    "a face ORCA does not edit")
    # The nearest solid; among equals, a face to edit before one only aligned by moving
    found.sort(key=lambda x: (round(x[0], 4), x[1].kind == "other"))
    return found[0][1]


def patch_vertices(scene: IfcScene, gid: str, face: Face, point) -> np.ndarray:
    """A face's corners: the vertices of its solid's mesh on its plane, within 1 mm (world metres)."""
    element = scene.entity(gid)
    k, _ = split_id(face.id)
    try:
        v = edits.item_verts(scene, element, edits.solid(scene, element, k).top) if k is not None else edits._mesh_verts(element)
    except (RuntimeError, edits.Unsupported):
        return np.zeros((0, 3))
    n = np.asarray(face.normal, float)
    return v[np.abs((v - np.asarray(point, float)) @ n) <= 0.001]


def by_name(scene: IfcScene, gid: str, name: str) -> Face:
    """A face by its id ("cap:end") or its name ("east end"), as Muse or a person says it."""
    want = name.strip().lower()
    listed = faces(scene, gid)
    for f in listed:
        if f.id == want or f.name == want:
            return f
    bare = want.removeprefix("the ").strip()
    exact = [f for f in listed if f.name == bare]
    if len(exact) == 1:
        return exact[0]
    # "east" or "end" alone: only when one face has that word, never the first of several
    found = [f for f in listed if bare in f.name.split()]
    if len(found) == 1:
        return found[0]
    if found:
        raise KeyError(f"{name!r} could be its {', '.join(f.name for f in found)}: say which")
    raise KeyError(f"no face called {name!r}: its faces are {', '.join(f.name for f in listed)}")
