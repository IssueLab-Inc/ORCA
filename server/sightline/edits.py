"""Model edits beyond moving whole elements. Today: the local offset.

A local offset is what a designer does when a straight run meets an obstacle it cannot move (a beam, say): split the
segment either side of the obstacle, take the middle piece up or down, and join the ends with short vertical pieces.
Northbank's Rev04 fixes #042, #057 and #061 this way (with bends; Sightline uses square corners for now).

    first piece (the original element, shortened) ─┐            ┌─ last piece
                                                    riser ─ middle ─ riser

The original element keeps its GlobalId and its first port; the new pieces are copies of it (class, type, properties,
container, system), chained port to port, with the last piece taking over the original's far connection.

Supported: a segment whose body is one extruded profile along a horizontal axis, offset vertically. Anything else
raises `Unsupported` with the reason, so the agent can say why it fell back to moves.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.geom
import ifcopenshell.util.placement
import ifcopenshell.util.system
import numpy as np

from .scene import IfcScene

UP = np.array([0.0, 0.0, 1.0])
MIN_PIECE_M = 0.05  # shortest straight piece left either side of a riser


class Unsupported(ValueError):
    """The element's shape cannot take this edit; the message says why."""


@dataclass
class Run:
    """A straight segment in world metres, Z up."""
    global_id: str
    start: list[float]
    end: list[float]
    direction: list[float]
    length_m: float
    depth_m: float     # the profile's vertical size: a riser's footprint along the run
    width_m: float     # the profile's horizontal size across the run


@dataclass
class Offset:
    element: str          # the segment that was split; it keeps the first piece
    start_m: float        # split points, metres along the run from its start (riser centrelines)
    end_m: float
    dz_m: float           # middle piece up (+) or down (-)
    pieces: list[str]     # GlobalIds in run order: first, riser, middle, riser, last


def _profile_size(profile) -> tuple[float, float]:
    """(X, Y) extent of a parametric profile in its own axes; profiles here are centred on their position."""
    pos = getattr(profile, "Position", None)
    if pos is not None and (any(abs(c) > 1e-9 for c in pos.Location.Coordinates) or
                            (pos.RefDirection is not None and abs(pos.RefDirection.DirectionRatios[1]) > 1e-9)):
        raise Unsupported("the profile is not centred on the segment's axis")
    if profile.is_a("IfcRectangleProfileDef"):
        return profile.XDim, profile.YDim
    if profile.is_a("IfcCircleProfileDef"):
        return 2 * profile.Radius, 2 * profile.Radius
    if profile.is_a("IfcUShapeProfileDef") or profile.is_a("IfcCShapeProfileDef"):
        return getattr(profile, "FlangeWidth", None) or profile.Width, profile.Depth
    if profile.is_a("IfcIShapeProfileDef") or profile.is_a("IfcLShapeProfileDef"):
        return getattr(profile, "OverallWidth", None) or profile.Width, getattr(profile, "OverallDepth", None) or profile.Depth
    raise Unsupported(f"{profile.is_a()} profiles are not supported yet")


def _body(element):
    rep = element.Representation
    bodies = [r for r in (rep.Representations if rep else []) if r.RepresentationIdentifier == "Body"]
    if len(bodies) != 1 or len(bodies[0].Items) != 1 or not bodies[0].Items[0].is_a("IfcExtrudedAreaSolid"):
        raise Unsupported("only a body made of one straight extrusion can be split")
    item = bodies[0].Items[0]
    if np.linalg.norm(np.asarray(item.ExtrudedDirection.DirectionRatios) - (0, 0, 1)) > 1e-9:
        raise Unsupported("the extrusion is not along its own axis")
    return bodies[0], item


def _frames(scene: IfcScene, element):
    """Element placement (file units) and the extrusion's world frame: origin, run direction, profile X, profile Y."""
    i = scene.index_of(element.GlobalId)
    place = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    _, item = _body(element)
    world = place @ ifcopenshell.util.placement.get_axis2placement(item.Position)
    return i, place, item, world[:3, 3], world[:3, 2], world[:3, 0], world[:3, 1]


def run_of(scene: IfcScene, global_id: str) -> Run:
    element = scene.entity(global_id)
    i, _, item, origin, d, px, py = _frames(scene, element)
    s = scene.unit_scales[i]
    sx, sy = _profile_size(item.SweptArea)
    depth, width = (sy, sx) if abs(py @ UP) > abs(px @ UP) else (sx, sy)
    start = origin * s
    end = (origin + d * item.Depth) * s
    return Run(global_id, start.tolist(), end.tolist(), d.tolist(), item.Depth * s, depth * s, width * s)


def _point(model, p):
    return model.createIfcCartesianPoint([float(v) for v in p])


def _dir(model, v):
    return model.createIfcDirection([float(x) for x in v / np.linalg.norm(v)])


def _place_port(model, port, point_file_units, scale):
    m = np.eye(4)
    m[:3, 3] = np.asarray(point_file_units) * scale
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=m, is_si=True)


def _ports(element):
    return sorted(ifcopenshell.util.system.get_ports(element), key=lambda p: p.Name or "")


def apply_offset(scene: IfcScene, global_id: str, start_m: float, end_m: float, dz_m: float) -> Offset:
    """Split `global_id` at `start_m` and `end_m` (metres along it) and take the middle piece `dz_m` up or down.
    Edits the model in place; wrap in `trial` to try it and undo."""
    element = scene.entity(global_id)
    i, place, item, origin, d, px, py = _frames(scene, element)
    model, s = scene.models[i], scene.unit_scales[i]
    if abs(d @ UP) > 1e-3:
        raise Unsupported("the segment is not horizontal")
    if abs(dz_m) < 1e-3:
        raise Unsupported("the offset height is zero")
    sx, sy = _profile_size(item.SweptArea)
    if abs(py @ UP) > 0.999:      # profile Y is up: risers keep profile X across the run
        t, riser_ref = sy, (lambda axis: px)
    elif abs(px @ UP) > 0.999:    # profile X is up (a tray drawn on its side): keep profile Y across the run
        t, riser_ref = sx, (lambda axis: np.cross(py, axis))
    else:
        raise Unsupported("the profile is tilted")
    a, b, dz, L = start_m / s, end_m / s, dz_m / s, item.Depth
    if a > b:
        a, b = b, a
    if a - t / 2 < MIN_PIECE_M / s or L - b - t / 2 < MIN_PIECE_M / s or b - a - t < MIN_PIECE_M / s:
        raise Unsupported(f"the split points leave a piece shorter than {MIN_PIECE_M * 1000:.0f} mm "
                          f"(run {L * s:.2f} m, riser footprint {t * s * 1000:.0f} mm)")
    sign = 1.0 if dz > 0 else -1.0
    # World (file units) start, axis, length of every piece. Risers keep the profile's X across the run.
    pieces = [
        (origin, d, a - t / 2),
        (origin + d * a - UP * sign * t / 2, UP * sign, abs(dz) + t),
        (origin + d * (a + t / 2) + UP * dz, d, b - a - t),
        (origin + d * b + UP * (dz + sign * t / 2), -UP * sign, abs(dz) + t),
        (origin + d * (b + t / 2), d, L - b - t / 2),
    ]
    inv = np.linalg.inv(place)
    body, _ = _body(element)
    styles = [x for x in model.get_inverse(item) if x.is_a("IfcStyledItem")]

    first_ports = _ports(element)
    far = ifcopenshell.util.system.get_connected_port(first_ports[-1]) if len(first_ports) > 1 else None
    if far is not None:
        ifcopenshell.api.run("system.disconnect_port", model, port=first_ports[-1])

    item.Depth = pieces[0][2]
    chain = [element]
    for n, (start, axis, length) in enumerate(pieces[1:], start=1):
        copy = ifcopenshell.api.run("root.copy_class", model, product=element)
        if element.Tag:
            copy.Tag = f"{element.Tag}-SL{n}"
        local_start = (inv @ np.append(start, 1.0))[:3]
        ref = px if abs(axis @ UP) < 0.5 else riser_ref(axis)
        position = model.createIfcAxis2Placement3D(
            _point(model, local_start), _dir(model, inv[:3, :3] @ axis), _dir(model, inv[:3, :3] @ ref))
        solid = model.createIfcExtrudedAreaSolid(item.SweptArea, position, model.createIfcDirection((0.0, 0.0, 1.0)),
                                                 float(length))
        rep = model.createIfcShapeRepresentation(body.ContextOfItems, "Body", "SweptSolid", [solid])
        copy.Representation = model.createIfcProductDefinitionShape(None, None, [rep])
        for st in styles:
            model.createIfcStyledItem(solid, st.Styles, st.Name)
        chain.append(copy)

    # Ports: one at each end of every piece, joined in run order; the last piece takes the far connection.
    for (start, axis, length), piece in zip(pieces, chain):
        ports = _ports(piece)
        if len(ports) >= 2:
            _place_port(model, ports[0], start, s)
            _place_port(model, ports[-1], start + axis * length, s)
    for u, v in zip(chain, chain[1:]):
        pu, pv = _ports(u), _ports(v)
        if len(pu) >= 2 and len(pv) >= 2:
            ifcopenshell.api.run("system.connect_port", model, port1=pu[-1], port2=pv[0],
                                 direction=pu[-1].FlowDirection or "NOTDEFINED")
    last = _ports(chain[-1])
    if far is not None and len(last) >= 2:
        ifcopenshell.api.run("system.connect_port", model, port1=last[-1], port2=far,
                             direction=last[-1].FlowDirection or "NOTDEFINED")

    gids = [p.GlobalId for p in chain]
    scene.refresh_bounds(gids)
    return Offset(global_id, start_m, end_m, dz_m, gids)


@contextmanager
def trial(scene: IfcScene, global_id: str):
    """Make edits to the file holding `global_id`, then undo them all, cached boxes included."""
    i = scene.index_of(global_id)
    model = scene.models[i]
    before = dict(scene.bounds())
    model.begin_transaction()
    try:
        yield
    finally:
        model.end_transaction()
        model.undo()
        scene._bounds = before


def meshes(scene: IfcScene, global_ids: list[str]) -> list[dict]:
    """World-space triangles (metres, Z up) for previewing new or changed elements in the browser."""
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    out = []
    for gid in global_ids:
        shape = ifcopenshell.geom.create_shape(settings, scene.entity(gid))
        verts = np.round(np.asarray(shape.geometry.verts, dtype=float), 4)
        out.append({"global_id": gid, "verts": verts.tolist(), "faces": list(shape.geometry.faces)})
    return out


def openings(scene: IfcScene, global_id: str) -> list[dict]:
    """Openings cut through an element (web openings in a beam, say), as world boxes in metres."""
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    out = []
    for rel in getattr(scene.entity(global_id), "HasOpenings", []) or []:
        o = rel.RelatedOpeningElement
        try:
            verts = np.asarray(ifcopenshell.geom.create_shape(settings, o).geometry.verts, dtype=float).reshape(-1, 3)
        except RuntimeError:
            continue
        out.append({"min": np.round(verts.min(axis=0), 3).tolist(), "max": np.round(verts.max(axis=0), 3).tolist()})
    return out


def _hits(origins: np.ndarray, d: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Which rays (origins + t·d, t > 0) hit any triangle (Möller–Trumbore, vectorised over rays and triangles)."""
    v0, e1, e2 = tris[:, 0], tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    p = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-12
    v0, e1, e2, p, det = v0[ok], e1[ok], e2[ok], p[ok], det[ok]
    inv = 1.0 / det
    s = origins[:, None, :] - v0[None]                       # rays x tris x 3
    u = np.einsum("rtk,tk->rt", s, p) * inv
    q = np.cross(s, e1[None])
    v = (q @ d) * inv
    t = np.einsum("rtk,tk->rt", q, e2) * inv
    return np.any((u >= 0) & (u <= 1) & (v >= 0) & (u + v <= 1) & (t > 1e-9), axis=1)


def passages(scene: IfcScene, run_gid: str, obstacle_gid: str, clearance_m: float = 0.025,
             step_m: float = 0.005) -> list[dict]:
    """Openings through `obstacle` on the line of the straight segment `run_gid`, big enough for its profile.

    Rays run along the segment's direction through the obstacle at heights `step_m` apart, at the segment's
    centreline and either side of it (half its width plus clearance). A height where none of them hits the obstacle,
    inside the obstacle's own height, is an opening. Returns each opening's bottom and top, and the range of offsets
    (dz) that puts the segment's middle piece through it with `clearance_m` all round. Openings cut into the geometry
    itself (no IfcOpeningElement) are found too, which is how Northbank's girder is modelled.
    """
    run = run_of(scene, run_gid)
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, scene.entity(obstacle_gid))
    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    tris = verts[np.asarray(shape.geometry.faces).reshape(-1, 3)]
    d = np.asarray(run.direction)
    side = np.cross(UP, d)
    side /= np.linalg.norm(side)
    start, z0 = np.asarray(run.start), run.start[2]
    behind = start + d * (((verts - start) @ d).min() - 1.0)  # a point on the run's line before the obstacle
    lo, hi = verts[:, 2].min(), verts[:, 2].max()
    zs = np.arange(lo + step_m / 2, hi, step_m)
    lateral = [-(run.width_m / 2 + clearance_m), 0.0, run.width_m / 2 + clearance_m]
    origins = np.array([behind + side * y + UP * (z - behind[2]) for z in zs for y in lateral])
    open_at = ~_hits(origins, d, tris).reshape(len(zs), len(lateral)).any(axis=1)
    out, i = [], 0
    while i < len(zs):
        if open_at[i]:
            j = i
            while j + 1 < len(zs) and open_at[j + 1]:
                j += 1
            bottom, top = zs[i] - step_m / 2, zs[j] + step_m / 2
            half = run.depth_m / 2 + clearance_m
            if top - bottom >= 2 * half:
                out.append({"bottom_m": round(float(bottom), 3), "top_m": round(float(top), 3),
                            "dz_min_m": round(float(bottom + half - z0), 3), "dz_max_m": round(float(top - half - z0), 3)})
            i = j + 1
        else:
            i += 1
    return out
