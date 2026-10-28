"""Model edits beyond moving whole elements: the local offset, and trimming a member's end at a joint.

A local offset is what a designer does when a straight run meets an obstacle it cannot move (a beam, say): split the
segment either side of the obstacle, take the middle piece up or down, and join the ends with short vertical pieces.
Northbank's Rev04 fixes #042, #057 and #061 this way, with radiused bends.

    first piece (the original element, shortened) ─┐            ┌─ last piece
                                                    riser ─ middle ─ riser

The original element keeps its GlobalId and its first port; the new pieces are copies of it (class, type, properties,
container, system), chained port to port, with the last piece taking over the original's far connection.

Supported: a segment whose body is one extruded profile along a horizontal axis, offset vertically or laterally. Anything else
raises `Unsupported` with the reason, so the agent can say why it fell back to moves.

A trim is a connection fix: where one member's end runs into another (a curtain-wall transom 60 mm into the corner
mullion, a beam end into a column), cut the end back to the other's face so the two butt. Nothing moves; the joint
changes. Any straight extrusion can be trimmed, at either end, whatever its profile.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.system
import numpy as np

from .scene import IfcScene

UP = np.array([0.0, 0.0, 1.0])
MIN_PIECE_M = 0.05  # shortest straight piece left either side of a riser
SLENDER = 3.0       # a trim needs a member at least this many times longer than it is across (beams, transoms, braces)


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
class Trim:
    element: str
    end: str              # "start" or "end" of the extrusion
    by_m: float           # shortened by (positive), metres


@dataclass
class Offset:
    element: str          # the segment that was split; it keeps the first piece
    start_m: float        # split points, metres along the run from its start (riser centrelines)
    end_m: float
    dz_m: float           # middle piece up (+) or down (-)
    pieces: list[str]     # GlobalIds in run order: first, (bend,) riser, (bend,) middle, ..., last
    corners: str = "square"  # "bends" (90° bend fittings) or "square"
    lateral_m: float = 0.0


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


def _place_port(model, port, point_file_units, scale, direction=None, ref=None):
    m = np.eye(4)
    if direction is not None:
        z = np.array(direction, dtype=float)
        if port.FlowDirection == 'SINK':
            z *= -1
        z /= np.linalg.norm(z)
        x = np.array(ref, dtype=float) if ref is not None else np.cross(
            UP if abs(z @ UP) < .9 else np.array([1., 0., 0.]), z)
        x -= z * (x @ z)
        x /= np.linalg.norm(x)
        m[:3, :3] = np.column_stack([x, np.cross(z, x), z])
    m[:3, 3] = np.asarray(point_file_units) * scale
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=m, is_si=True)


def _ports(element):
    return sorted(ifcopenshell.util.system.get_ports(element), key=lambda p: p.Name or "")


# Fittings for a segment's bends, by segment class (IFC4). Anything else gets square corners.
FITTING_CLASS = {"IfcDuctSegment": "IfcDuctFitting", "IfcPipeSegment": "IfcPipeFitting",
                 "IfcCableCarrierSegment": "IfcCableCarrierFitting", "IfcCableSegment": "IfcCableFitting"}
RISER_MIN_M = 0.04       # straight riser left between two bends when the rise allows (Rev04: 40-172 mm)
BEND_STEPS = 8           # facets per 90° bend


def default_corners() -> str:
    """How offsets turn: "bends" (radiused 90° fittings, as Northbank's Rev04 does) or "square" (SIGHTLINE_OFFSET_CORNERS)."""
    return "square" if os.environ.get("SIGHTLINE_OFFSET_CORNERS", "bends").lower().startswith("sq") else "bends"


def bend_radius(depth_m: float, dz_m: float) -> float | None:
    """Centreline radius of an offset's bends: one profile depth, smaller when the rise is too short for two bends and
    a riser (Rev04: duct 300 deep rising 400 mm gets 180 mm). None when even that would fold the inside of the bend."""
    r = min(depth_m, (abs(dz_m) - RISER_MIN_M) / 2)
    if r - depth_m / 2 < 0.005:  # the inside radius: below 5 mm the bend would fold on itself
        r = abs(dz_m) / 2         # no riser: two bends meet
    return r if r - depth_m / 2 >= 0.005 else None


def apply_offset(scene: IfcScene, global_id: str, start_m: float, end_m: float, dz_m: float,
                 corners: str | None = None, *, lateral_m: float = 0.0) -> Offset:
    """Split `global_id` at `start_m` and `end_m` (metres along it) and take the middle piece `dz_m` up or down.
    Alternatively, `lateral_m` offsets along cross(world Z, run direction); the two offsets cannot be combined.
    Edits the model in place; wrap in `trial` to try it and undo.

    `corners` "bends" (default): each turn is a 90° bend fitting (IfcDuctFitting, IfcPipeFitting... of type BEND)
    with a radius of about one profile depth, joined by short risers, the way Northbank's Rev04 does it. "square":
    risers overlap the straight pieces at square corners. Bends fall back to square corners when the segment has no
    fitting class or the rise is too small to bend."""
    element = scene.entity(global_id)
    i, place, item, origin, d, px, py = _frames(scene, element)
    model, s = scene.models[i], scene.unit_scales[i]
    if abs(d @ UP) > 1e-3:
        raise Unsupported("the segment is not horizontal")
    if not np.isfinite([start_m, end_m, dz_m, lateral_m]).all():
        raise Unsupported("offset values must be finite")
    if abs(dz_m) > 1e-9 and abs(lateral_m) > 1e-9:
        raise Unsupported("choose vertical or lateral, not a compound offset")
    amount = lateral_m if lateral_m else dz_m
    offset_axis = np.cross(UP, d) if lateral_m else UP
    offset_axis = offset_axis / np.linalg.norm(offset_axis)
    if abs(amount) < 1e-3:
        raise Unsupported("the offset height is zero")
    sx, sy = _profile_size(item.SweptArea)
    if abs(py @ UP) > 0.999:      # profile Y is up: risers keep profile X across the run
        t, w = sy, sx
    elif abs(px @ UP) > 0.999:    # profile X is up (a tray drawn on its side): keep profile Y across the run
        t, w = sx, sy
    else:
        raise Unsupported("the profile is tilted")
    if lateral_m:
        t, w = w, t
    profile_x = px.copy()
    profile_position = getattr(item.SweptArea,'Position',None)
    if profile_position is not None and profile_position.RefDirection is not None:
        local_x = np.asarray(profile_position.RefDirection.DirectionRatios,dtype=float)
        local_x /= np.linalg.norm(local_x)
        profile_x = px*local_x[0] + py*local_x[1]

    def section_ref(axis, reference=px):
        """Transport the actual profile X axis in the detour plane, without section roll."""
        normal = np.cross(d, axis)
        sine, cosine = np.linalg.norm(normal), float(d @ axis)
        if sine < 1e-9:
            return reference.copy()
        normal /= sine
        return reference*cosine + np.cross(normal,reference)*sine + normal*(normal @ reference)*(1-cosine)
    a, b, dz, L = start_m / s, end_m / s, amount / s, item.Depth
    if a > b:
        a, b = b, a
    sign = 1.0 if dz > 0 else -1.0
    u = offset_axis * sign

    r_m = bend_radius(t * s, amount) if (corners or default_corners()) == "bends" and element.is_a() in FITTING_CLASS else None
    if r_m is not None:
        R = r_m / s
        if a - R < MIN_PIECE_M / s or L - b - R < MIN_PIECE_M / s or b - a - 2 * R < MIN_PIECE_M / s:
            raise Unsupported(f"the split points leave a piece shorter than {MIN_PIECE_M * 1000:.0f} mm "
                              f"(run {L * s:.2f} m, each bend takes {R * s:.2f} m of run)")
        rise = abs(dz) - 2 * R
        risers = rise > 1e-3 / s
        # World (file units) pieces in run order: straights (start, axis, length) and bends (start, from, to, radius).
        pieces = [("straight", origin, d, a - R),
                  ("bend", origin + d * (a - R), d, u, R)]
        pieces += [("straight", origin + d * a + u * R, u, rise)] if risers else []
        pieces += [("bend", origin + d * a + u * (abs(dz) - R), u, d, R),
                   ("straight", origin + d * (a + R) + offset_axis * dz, d, b - a - 2 * R),
                   ("bend", origin + d * (b - R) + offset_axis * dz, d, -u, R)]
        pieces += [("straight", origin + d * b + offset_axis * dz - u * R, -u, rise)] if risers else []
        pieces += [("bend", origin + d * b + u * R, -u, d, R),
                   ("straight", origin + d * (b + R), d, L - b - R)]
        used = "bends"
    else:
        if a - t / 2 < MIN_PIECE_M / s or L - b - t / 2 < MIN_PIECE_M / s or b - a - t < MIN_PIECE_M / s:
            raise Unsupported(f"the split points leave a piece shorter than {MIN_PIECE_M * 1000:.0f} mm "
                              f"(run {L * s:.2f} m, riser footprint {t * s * 1000:.0f} mm)")
        # Risers overlap the straights by half a depth at each square corner.
        pieces = [
            ("straight", origin, d, a - t / 2),
            ("straight", origin + d * a - u * t / 2, u, abs(dz) + t),
            ("straight", origin + d * (a + t / 2) + offset_axis * dz, d, b - a - t),
            ("straight", origin + d * b + offset_axis * (dz + sign * t / 2), -u, abs(dz) + t),
            ("straight", origin + d * (b + t / 2), d, L - b - t / 2),
        ]
        used = "square"
    inv = np.linalg.inv(place)
    body, _ = _body(element)
    styles = [x for x in model.get_inverse(item) if x.is_a("IfcStyledItem")]
    round_ = item.SweptArea.is_a("IfcCircleProfileDef")

    first_ports = _ports(element)
    if len(first_ports) > 2:
        raise Unsupported('a branched segment with more than two ports cannot be offset')
    first_ports.sort(key=lambda p: float(scene.placement(p.GlobalId)[:3, 3] @ d) if p.ObjectPlacement else 0.)
    original_flows = [p.FlowDirection for p in first_ports] if len(first_ports) == 2 else ['NOTDEFINED','NOTDEFINED']
    external_frames = [scene.placement(p.GlobalId) if p.ObjectPlacement else None
                       for p in (first_ports[0], first_ports[-1])] if len(first_ports) >= 2 else []
    external_flows = {peer.GlobalId:peer.FlowDirection for port in first_ports
                      if (peer := ifcopenshell.util.system.get_connected_port(port)) is not None}
    far = ifcopenshell.util.system.get_connected_port(first_ports[-1]) if len(first_ports) > 1 else None
    if far is not None:
        ifcopenshell.api.run("system.disconnect_port", model, port=first_ports[-1])

    item.Depth = pieces[0][3]
    chain, ends = [element], [(pieces[0][1], pieces[0][1] + pieces[0][2] * pieces[0][3])]
    straights = bends = 0
    for piece in pieces[1:]:
        if piece[0] == "straight":
            _, start, axis, length = piece
            straights += 1
            part = ifcopenshell.api.run("root.copy_class", model, product=element)
            if element.Tag:
                part.Tag = f"{element.Tag}-SL{straights}"
            local_start = (inv @ np.append(start, 1.0))[:3]
            ref = section_ref(axis)
            position = model.createIfcAxis2Placement3D(
                _point(model, local_start), _dir(model, inv[:3, :3] @ axis), _dir(model, inv[:3, :3] @ ref))
            solid = model.createIfcExtrudedAreaSolid(item.SweptArea, position, model.createIfcDirection((0.0, 0.0, 1.0)),
                                                     float(length))
            rep = model.createIfcShapeRepresentation(body.ContextOfItems, "Body", "SweptSolid", [solid])
            ends.append((start, start + axis * length))
        else:
            _, start, t0, t1, R = piece
            bends += 1
            part = _new_fitting(model, element, place, f"{element.Name or 'Segment'} bend", 
                                f"{element.Tag}-BR{bends}" if element.Tag else None)
            verts, faces = _bend_mesh(start, t0, t1, R, w, t, round_)
            local = (inv @ np.c_[verts, np.ones(len(verts))].T).T[:, :3]
            solid = model.createIfcTriangulatedFaceSet(
                model.createIfcCartesianPointList3D([[float(c) for c in v] for v in local]), None, True,
                [[int(x) + 1 for x in f] for f in faces], None)
            rep = model.createIfcShapeRepresentation(body.ContextOfItems, "Body", "Tessellation", [solid])
            ends.append((start, start + (t0 + t1) * R))
        part.Representation = model.createIfcProductDefinitionShape(None, None, [rep])
        for st in styles:
            model.createIfcStyledItem(solid, st.Styles, st.Name)
        chain.append(part)

    # Ports: one at each end of every piece, joined in run order; the last piece takes the far connection.
    chain_ports = []
    for (p0, p1), piece, shape_piece in zip(ends, chain, pieces):
        ports = first_ports if piece == element else _ports(piece)
        if piece != element and shape_piece[0] == 'straight':
            ports.sort(key=lambda p: float(scene.placement(p.GlobalId)[:3, 3] @ d) if p.ObjectPlacement else 0.)
        while len(ports) < 2:
            port = ifcopenshell.api.run('system.add_port', model, element=piece)
            port.Name = f'Port {len(ports)}'
            port.FlowDirection = 'NOTDEFINED'
            ports.append(port)
        chain_ports.append(ports)
        for port, flow in zip(ports,original_flows):
            port.FlowDirection = flow
    for px_, py_ in zip(chain_ports, chain_ports[1:]):
        if len(px_) >= 2 and len(py_) >= 2:
            ifcopenshell.api.run("system.connect_port", model, port1=px_[-1], port2=py_[0],
                                 direction=px_[-1].FlowDirection or "NOTDEFINED")
    last = chain_ports[-1]
    if far is not None and len(last) >= 2:
        ifcopenshell.api.run("system.connect_port", model, port1=last[-1], port2=far,
                             direction=last[-1].FlowDirection or "NOTDEFINED")
    # IFC copying/disconnection can clear the near peer as well as the far peer.
    # Restore both authored flows; never manufacture knowledge on an untouched peer.
    for gid,flow in external_flows.items():
        scene.entity(gid).FlowDirection = flow

    # connect_port assigns final flow directions. IFC SINK axes point into the
    # product, SOURCE axes outward; references follow the physical profile X.
    for (p0,p1), ports, shape_piece in zip(ends,chain_ports,pieces):
        t0 = shape_piece[2]
        t1 = shape_piece[3] if shape_piece[0] == 'bend' else t0
        _place_port(model,ports[0],p0,s,-t0,section_ref(t0,profile_x))
        _place_port(model,ports[-1],p1,s,t1,section_ref(t1,profile_x))
    if external_frames:
        for port, frame in zip((chain_ports[0][0], chain_ports[-1][-1]), external_frames):
            if frame is not None:
                ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=frame, is_si=True)

    gids = [p.GlobalId for p in chain]
    scene.refresh_bounds(gids)
    return Offset(global_id, start_m, end_m, dz_m, gids, used, lateral_m)


def _new_fitting(model, segment, place, name: str, tag: str | None):
    """A bend fitting for `segment`: its fitting class, type BEND, in the same storey and systems, with two ports and
    its own placement (the segment's frame, so bend vertices share the segment's local coordinates)."""
    fitting = ifcopenshell.api.run("root.create_entity", model, ifc_class=FITTING_CLASS[segment.is_a()],
                                   predefined_type="BEND", name=name)
    if tag:
        fitting.Tag = tag
    container = ifcopenshell.util.element.get_container(segment)
    if container is not None:
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=container, products=[fitting])
    for system in ifcopenshell.util.system.get_element_systems(segment):
        ifcopenshell.api.run("system.assign_system", model, products=[fitting], system=system)
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=fitting, matrix=place, is_si=False)
    old = _ports(segment)
    for n in range(2):
        port = ifcopenshell.api.run("system.add_port", model, element=fitting)
        port.Name = f"Port {n}"
        if len(old) >= 2:
            port.FlowDirection = old[n].FlowDirection
            port.PredefinedType = old[n].PredefinedType
            port.SystemType = old[n].SystemType
    return fitting


def _bend_mesh(p0, t0, t1, r, width, depth, round_: bool) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """A closed triangulated 90° bend (world coordinates): the section swept from `p0` going along `t0` round a radius
    `r` until it runs along `t1`. Width stays across the bend plane; depth lies in it. Faces point outward."""
    t0, t1 = np.asarray(t0, float), np.asarray(t1, float)
    side = np.cross(t0, t1)
    side /= np.linalg.norm(side)
    centre = np.asarray(p0, float) + r * t1
    if round_:
        ang = np.linspace(0, 2 * np.pi, 16, endpoint=False)
        section = np.c_[np.cos(ang) * width / 2, np.sin(ang) * depth / 2]
    else:
        section = np.array([[-width / 2, -depth / 2], [width / 2, -depth / 2], [width / 2, depth / 2], [-width / 2, depth / 2]])
    m = len(section)
    rings = []
    for k in range(BEND_STEPS + 1):
        th = (np.pi / 2) * k / BEND_STEPS
        p = centre - r * np.cos(th) * t1 + r * np.sin(th) * t0
        tangent = np.cos(th) * t0 + np.sin(th) * t1
        across = np.cross(tangent, side)
        rings.append([p + x * side + y * across for x, y in section])
    verts = np.array([v for ring in rings for v in ring])
    sides, caps0, caps1 = [], [], []
    for k in range(BEND_STEPS):
        for j in range(m):
            a_, b_ = k * m + j, k * m + (j + 1) % m
            c_, d_ = (k + 1) * m + (j + 1) % m, (k + 1) * m + j
            sides += [(a_, b_, c_), (a_, c_, d_)]
    base = BEND_STEPS * m
    caps0 = [(0, j + 1, j) for j in range(1, m - 1)]
    caps1 = [(base, base + j, base + j + 1) for j in range(1, m - 1)]

    def normal(f):
        a_, b_, c_ = verts[list(f)]
        return np.cross(b_ - a_, c_ - a_)

    def facing(tris, outward):
        return tris if normal(tris[0]) @ outward >= 0 else [(f[0], f[2], f[1]) for f in tris]

    mid = rings[0]
    sides = facing(sides, verts[sides[0][0]] + verts[sides[0][1]] - 2 * np.mean(mid, axis=0))
    caps0 = facing(caps0, -t0)
    caps1 = facing(caps1, t1)
    return verts, sides + caps0 + caps1


def member_axis(scene: IfcScene, element) -> tuple[str, np.ndarray, np.ndarray, float]:
    """A member's long axis in world metres: ("depth" | "x" | "y", start point, unit direction, length).

    Usually the extrusion ("depth"), but framing is often drawn the other way: Northbank's curtain-wall transoms are a
    1.65 m x 120 mm rectangle extruded 60 mm up, so their length is the profile's X."""
    i, _, item, origin, d, px, py = _frames(scene, element)
    s = scene.unit_scales[i]
    lengths = {"depth": item.Depth}
    prof = item.SweptArea
    centre = np.zeros(2)  # the profile's centre in the solid's XY: profiles can be offset, but not turned
    pos = getattr(prof, "Position", None)
    turned = pos is not None and pos.RefDirection is not None and (abs(pos.RefDirection.DirectionRatios[1]) > 1e-9
                                                                   or pos.RefDirection.DirectionRatios[0] < 0)
    if prof.is_a("IfcRectangleProfileDef") and not turned:
        lengths.update(x=prof.XDim, y=prof.YDim)
        if pos is not None:
            centre = np.asarray(pos.Location.Coordinates[:2], dtype=float)
    axis = max(lengths, key=lengths.get)
    if axis == "depth":
        return axis, origin * s, d / np.linalg.norm(d), item.Depth * s
    u, v = (px, py) if axis == "x" else (py, px)
    cu, cv = (centre[0], centre[1]) if axis == "x" else (centre[1], centre[0])
    start = origin + u * (cu - lengths[axis] / 2) + v * cv
    return axis, start * s, u / np.linalg.norm(u), lengths[axis] * s


def _across(points: np.ndarray, d: np.ndarray) -> float:
    """The widest a shape is across direction `d` (the larger of its two extents at right angles to it)."""
    helper = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(d, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(d, e1)
    return float(max(np.ptp(points @ e1), np.ptp(points @ e2)))


def butt_trim(scene: IfcScene, global_id: str, other: str) -> Trim:
    """The trim that makes `global_id` stop at `other`'s face: which end runs into it, and by how much.

    Only an end can be trimmed: the other element has to straddle that end. An overlap part-way along (a duct crossing
    a beam) is not a joint, and raises `Unsupported`."""
    element = scene.entity(global_id)
    _, start, d, length = member_axis(scene, element)
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    # Only a slender member's end is a joint to tidy. A pad footing is as wide as it is long: cutting 900 mm off an
    # 1800 mm pad halves its bearing and moves it off its column, which no geometry check would catch.
    own = np.asarray(ifcopenshell.geom.create_shape(settings, element).geometry.verts, dtype=float).reshape(-1, 3)
    across = _across(own - start, d)
    if length < SLENDER * across:
        raise Unsupported(f"it is not a slender member ({length:.2f} m long, {across:.2f} m across): trimming would "
                          "cut its body, not tidy a joint")
    verts = np.asarray(ifcopenshell.geom.create_shape(settings, scene.entity(other)).geometry.verts, dtype=float).reshape(-1, 3)
    along = (verts - start) @ d
    lo, hi = float(along.min()), float(along.max())
    tol = 1e-4
    if lo < length - tol and hi >= length - tol and (lo + hi) / 2 > length / 2:
        end, by = "end", length - lo
    elif hi > tol and lo <= tol:
        end, by = "start", hi
    else:
        raise Unsupported("the other element is not at either end of it, so trimming cannot clear it")
    if by <= 0.001:
        raise Unsupported("its end does not run into the other element")
    if length - by < MIN_PIECE_M:
        raise Unsupported(f"trimming {by * 1000:.0f} mm would leave less than {MIN_PIECE_M * 1000:.0f} mm of it")
    return Trim(global_id, end, round(by, 4))


def apply_trim(scene: IfcScene, global_id: str, end: str, by_m: float) -> Trim:
    """Shorten (or, with a negative `by_m`, lengthen) a member at one end of its long axis (`member_axis`). Edits the
    model in place; wrap in `trial` to try it and undo. A port at that end moves with it."""
    element = scene.entity(global_id)
    i, place, item, origin, d, _, _ = _frames(scene, element)
    model, s = scene.models[i], scene.unit_scales[i]
    axis, _, _, length = member_axis(scene, element)
    by = by_m / s
    if end not in ("start", "end"):
        raise Unsupported("say which end to trim: start or end")
    if length / s - by < MIN_PIECE_M / s:
        raise Unsupported(f"trimming {by_m * 1000:.0f} mm would leave less than {MIN_PIECE_M * 1000:.0f} mm of it")
    pos = item.Position
    local = ifcopenshell.util.placement.get_axis2placement(pos)
    sign = 1.0 if end == "start" else -1.0
    if axis == "depth":
        if end == "start":  # the profile moves along the axis; a new placement, as the old one may be shared
            item.Position = model.createIfcAxis2Placement3D(
                _point(model, local[:3, 3] + local[:3, 2] * by), pos.Axis, pos.RefDirection)
        item.Depth = float(item.Depth - by)
    else:  # a shorter profile (a new one: profiles can be shared), its centre moved half the cut away from that end
        prof = item.SweptArea
        dims = {"x": prof.XDim, "y": prof.YDim}
        dims[axis] -= by
        item.SweptArea = model.createIfcRectangleProfileDef(prof.ProfileType, prof.ProfileName, prof.Position,
                                                            float(dims["x"]), float(dims["y"]))
        shift = local[:3, 0 if axis == "x" else 1] * sign * by / 2
        item.Position = model.createIfcAxis2Placement3D(_point(model, local[:3, 3] + shift), pos.Axis, pos.RefDirection)
    ports = _ports(element)
    if axis == "depth" and len(ports) >= 2:
        if end == "start":
            _place_port(model, ports[0], origin + d * by, s)
        else:
            _place_port(model, ports[-1], origin + d * item.Depth, s)
    scene.refresh_bounds([global_id])
    return Trim(global_id, end, by_m)


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
    if np.linalg.norm(side) < 1e-6:  # a vertical segment (a riser): openings "on its line" are not defined here
        return []
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
