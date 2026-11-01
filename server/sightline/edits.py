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
import re
from contextlib import contextmanager
from dataclasses import dataclass

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.system
import numpy as np

from .scene import MESH_KERNEL, STEP_PSET, IfcScene, is_provision, meshes_only, step_source
from .requirements import DEFAULT_CLEARANCE_M

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


@dataclass
class Route:
    element: str          # the segment that was split; it keeps the first piece
    steps: list[dict]     # [{"from_m", "to_m", "up_m", "side_m"}], sorted, as applied
    pieces: list[str]     # GlobalIds in run order, the original first
    corners: str = "bends"


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


def _body(element, clipped: bool = False, item: int | None = None):
    """The element's Body representation and its one straight extrusion. With `clipped`, an extrusion cut by
    half-space clips (a hand edit's clip) counts too: the extrusion under the clips is returned. With `item`, the
    body may hold several solids and that one (by its place in the Body) is returned (a hand edit's face on a fitting,
    a door, a desk)."""
    rep = element.Representation
    bodies = [r for r in (rep.Representations if rep else []) if r.RepresentationIdentifier == "Body"]
    if item is not None:
        items = bodies[0].Items if len(bodies) == 1 else ()
        item = items[item] if 0 <= item < len(items) else None
    else:
        item = bodies[0].Items[0] if len(bodies) == 1 and len(bodies[0].Items) == 1 else None
    while clipped and item is not None and item.is_a("IfcBooleanClippingResult"):
        item = item.FirstOperand
    if item is None or not item.is_a("IfcExtrudedAreaSolid"):
        raise Unsupported("only a body made of one straight extrusion can be split")
    if np.linalg.norm(np.asarray(item.ExtrudedDirection.DirectionRatios) - (0, 0, 1)) > 1e-9:
        raise Unsupported("the extrusion is not along its own axis")
    return bodies[0], item


def _frames(scene: IfcScene, element, clipped: bool = False, item: int | None = None):
    """Element placement (file units) and the extrusion's world frame: origin, run direction, profile X, profile Y."""
    i = scene.index_of(element.GlobalId)
    place = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    _, item = _body(element, clipped, item)
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
OFFSET_AXIS_TOL = 1e-9   # numerical residue, metres; shared by validation and generation


def offset_components(dz_m: float, lateral_m: float) -> tuple[float, float]:
    """Discard negligible axes before selecting a detour plane or reporting its delta."""
    return tuple(0.0 if abs(v) <= OFFSET_AXIS_TOL else float(v) for v in (dz_m, lateral_m))


def default_corners() -> str:
    """How offsets turn: "bends" (radiused 90° fittings, as Northbank's Rev04 does) or "square" (SIGHTLINE_OFFSET_CORNERS)."""
    return "square" if os.environ.get("SIGHTLINE_OFFSET_CORNERS", "bends").lower().startswith("sq") else "bends"


def bend_radius(depth_m: float, dz_m: float, bend_deg: float = 90.0) -> float | None:
    """Centreline radius of an offset's bends: one profile depth, smaller when the rise is too short for two bends and
    a riser (Rev04: duct 300 deep rising 400 mm gets 180 mm). Two bends of `bend_deg` rise 2 r (1 − cos θ) between
    them (2 r at 90°), the riser the rest. None when even that would fold the inside of the bend."""
    th = np.radians(bend_deg)
    k = 2 * (1 - np.cos(th))     # the rise two bends of radius 1 make
    r = min(depth_m, (abs(dz_m) - RISER_MIN_M * np.sin(th)) / k)
    if r - depth_m / 2 < 0.005:  # the inside radius: below 5 mm the bend would fold on itself
        r = abs(dz_m) / k         # no riser: two bends meet
    return float(r) if r - depth_m / 2 >= 0.005 else None


def apply_offset(scene: IfcScene, global_id: str, start_m: float, end_m: float, dz_m: float,
                 corners: str | None = None, *, lateral_m: float = 0.0, bend_deg: float = 90.0) -> Offset:
    """Split `global_id` at `start_m` and `end_m` (metres along it) and take the middle piece `dz_m` up or down.
    Alternatively, `lateral_m` offsets along cross(world Z, run direction); the two offsets cannot be combined.
    `bend_deg` under 90 (15 to 90) takes it there along a slope, with bends of that angle either end of it: Rev04's
    "short angled pieces with bends either side". Edits the model in place; wrap in `trial` to try it and undo.

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
    dz_m, lateral_m = offset_components(dz_m, lateral_m)
    if dz_m and lateral_m:
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
    a, b, dz, L = start_m / s, end_m / s, amount / s, item.Depth
    if a > b:
        a, b = b, a
    sign = 1.0 if dz > 0 else -1.0
    u = offset_axis * sign

    angled = abs(bend_deg - 90.0) > 1e-6
    if angled and not 15.0 <= bend_deg < 90.0:
        raise Unsupported("bends turn between 15° and 90°")
    r_m = (bend_radius(t * s, amount, bend_deg) if (corners or default_corners()) == "bends" and element.is_a() in FITTING_CLASS
           else None)
    if angled and r_m is None:
        raise Unsupported(f"the offset is too small for {bend_deg:.0f}° bends of this section")
    if r_m is not None and angled:
        # Each side: a bend of θ onto the slope, a straight riser along it, a bend of θ back; the run it takes (2 R sin θ +
        # the riser's run) centred on the split point. The riser runs (A − 2 R (1 − cos θ)) / sin θ.
        R, th = r_m / s, np.radians(bend_deg)
        rise_run = max((abs(dz) - 2 * R * (1 - np.cos(th))) / np.sin(th), 0.0)
        half = (2 * R * np.sin(th) + rise_run * np.cos(th)) / 2
        if a - half < MIN_PIECE_M / s or L - b - half < MIN_PIECE_M / s or b - a - 2 * half < MIN_PIECE_M / s:
            raise Unsupported(f"the split points leave a piece shorter than {MIN_PIECE_M * 1000:.0f} mm "
                              f"(run {L * s:.2f} m, each {bend_deg:.0f}° slope takes {2 * half * s:.2f} m of run)")
        up_slope, down_slope = np.cos(th) * d + np.sin(th) * u, np.cos(th) * d - np.sin(th) * u
        pieces, p = [("straight", origin, d, a - half)], origin + d * (a - half)
        for go, back, run_to in ((up_slope, d, b - half), (down_slope, d, L)):
            pieces.append(("bend", p, d, go, R, w, t))
            p = bend_end(p, d, go, R)
            if rise_run > 1e-3 / s:
                pieces.append(("straight", p, go, rise_run))
                p = p + go * rise_run
            pieces.append(("bend", p, go, back, R, w, t))
            p = bend_end(p, go, back, R)
            here = float((p - origin) @ d)
            pieces.append(("straight", p, d, run_to - here))
            p = p + d * (run_to - here)
        used = f"bends {bend_deg:.0f}°"
    elif r_m is not None:
        R = r_m / s
        if a - R < MIN_PIECE_M / s or L - b - R < MIN_PIECE_M / s or b - a - 2 * R < MIN_PIECE_M / s:
            raise Unsupported(f"the split points leave a piece shorter than {MIN_PIECE_M * 1000:.0f} mm "
                              f"(run {L * s:.2f} m, each bend takes {R * s:.2f} m of run)")
        rise = abs(dz) - 2 * R
        risers = rise > 1e-3 / s
        # World (file units) pieces in run order: straights (start, axis, length) and bends (start, from, to, radius).
        pieces = [("straight", origin, d, a - R),
                  ("bend", origin + d * (a - R), d, u, R, w, t)]
        pieces += [("straight", origin + d * a + u * R, u, rise)] if risers else []
        pieces += [("bend", origin + d * a + u * (abs(dz) - R), u, d, R, w, t),
                   ("straight", origin + d * (a + R) + offset_axis * dz, d, b - a - 2 * R),
                   ("bend", origin + d * (b - R) + offset_axis * dz, d, -u, R, w, t)]
        pieces += [("straight", origin + d * b + offset_axis * dz - u * R, -u, rise)] if risers else []
        pieces += [("bend", origin + d * b + u * R, -u, d, R, w, t),
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
    gids = _build_chain(scene, element, place, item, d, px, profile_x, pieces)
    return Offset(global_id, start_m, end_m, dz_m, gids, used, lateral_m)


JOG_STUB_M = 0.15   # what a re-fit moves with the joint, before its first bend


def apply_jog(scene: IfcScene, global_id: str, end: str, delta_m) -> Offset:
    """Re-fit a level straight segment to what its `end` ("start" or "end") is joined to, moved `delta_m` square to it
    (up, down or sideways, one at a time): a short piece at that end (JOG_STUB_M) goes the same way, a pair of bends
    and a riser take it back to the rest, which stays where it is with its far joint (docs/editing-parity.md, "A
    carried move re-fits"). Edits the model in place; wrap in a trial to undo."""
    element = scene.entity(global_id)
    place, item, d, px, profile_x, pieces, shift, at, dz_m, lateral_m = _jog(scene, global_id, end, delta_m)
    model = scene.models[scene.index_of(global_id)]
    if end == "start":   # the segment keeps the first piece: it starts where the joint went
        local = ifcopenshell.util.placement.get_axis2placement(item.Position)
        local[:3, 3] = (np.linalg.inv(place) @ np.append(pieces[0][1], 1.0))[:3]
        item.Position = model.createIfcAxis2Placement3D(
            _point(model, local[:3, 3]), _dir(model, local[:3, 2]), _dir(model, local[:3, 0]))
    gids = _build_chain(scene, element, place, item, d, px, profile_x, pieces, shift_ends=shift)
    return Offset(global_id, at, at, dz_m, gids, "bends", lateral_m)


def jog_fits(scene: IfcScene, global_id: str, end: str, delta_m) -> str | None:
    """Why `apply_jog` cannot re-fit this segment, in words, or None when it can. Edits nothing."""
    try:
        _jog(scene, global_id, end, delta_m)
    except Unsupported as e:
        return str(e)
    return None


def _jog(scene: IfcScene, global_id: str, end: str, delta_m):
    """A re-fit's pieces, read from the model without editing it (see `apply_jog`)."""
    element = scene.entity(global_id)
    if element.is_a() not in FITTING_CLASS:
        raise Unsupported(f"a {element.is_a()} has no bend fittings to re-fit it with")
    if len(_ports(element)) > 2:
        raise Unsupported("a branched segment cannot be re-fitted")
    i, place, item, origin, d, px, py = _frames(scene, element)
    model, s = scene.models[i], scene.unit_scales[i]
    delta = np.asarray(delta_m, float)
    if abs(d @ UP) > 1e-3:
        raise Unsupported("the segment is not level")
    if abs(delta @ d) > 1e-4:
        raise Unsupported("the move runs along it")
    side = np.cross(UP, d)
    side /= np.linalg.norm(side)
    dz_m, lateral_m = offset_components(float(delta @ UP), float(delta @ side))
    if dz_m and lateral_m:
        raise Unsupported("a move both up and across cannot be re-fitted with one pair of bends")
    if not (dz_m or lateral_m):
        raise Unsupported("nothing to re-fit")
    amount = lateral_m or dz_m
    offset_axis = side if lateral_m else UP
    sx, sy = _profile_size(item.SweptArea)
    if abs(py @ UP) > 0.999:
        t, w = sy, sx
    elif abs(px @ UP) > 0.999:
        t, w = sx, sy
    else:
        raise Unsupported("the profile is tilted")
    if lateral_m:
        t, w = w, t
    profile_x = px.copy()
    pos = getattr(item.SweptArea, "Position", None)
    if pos is not None and pos.RefDirection is not None:
        lx = np.asarray(pos.RefDirection.DirectionRatios, float)
        lx /= np.linalg.norm(lx)
        profile_x = px * lx[0] + py * lx[1]
    r_m = bend_radius(t * s, amount)
    if r_m is None:
        raise Unsupported(f"{abs(amount) * 1000:.0f} mm is too little for a pair of bends of this section")
    R, dz, L, m = r_m / s, amount / s, item.Depth, JOG_STUB_M / s
    if L - m - 2 * R < MIN_PIECE_M / s:
        raise Unsupported(f"it is too short to re-fit ({L * s:.2f} m; the bends and the piece moved take "
                          f"{(m + 2 * R) * s:.2f} m)")
    u = offset_axis * (1.0 if dz > 0 else -1.0)
    rise = abs(dz) - 2 * R
    riser = rise > 1e-3 / s
    if end == "start":
        pieces = [("straight", origin + offset_axis * dz, d, m),
                  ("bend", origin + d * m + offset_axis * dz, d, -u, R, w, t)]
        pieces += [("straight", origin + d * (m + R) + offset_axis * dz - u * R, -u, rise)] if riser else []
        pieces += [("bend", origin + d * (m + R) + u * R, -u, d, R, w, t),
                   ("straight", origin + d * (m + 2 * R), d, L - m - 2 * R)]
        shift = (delta, None)
    elif end == "end":
        a = L - m - R
        pieces = [("straight", origin, d, a - R), ("bend", origin + d * (a - R), d, u, R, w, t)]
        pieces += [("straight", origin + d * a + u * R, u, rise)] if riser else []
        pieces += [("bend", origin + d * a + u * (abs(dz) - R), u, d, R, w, t),
                   ("straight", origin + d * (a + R) + offset_axis * dz, d, m)]
        shift = (None, delta)
    else:
        raise Unsupported(f"no end called {end!r}")
    at = JOG_STUB_M + r_m if end == "start" else L * s - JOG_STUB_M - r_m
    return place, item, d, px, profile_x, pieces, shift, at, dz_m, lateral_m


ROUTE_STEPS = 3                      # most steps one route may take
ROUTE_SLOPE = np.sin(np.radians(15))  # steepest run a route may take, as |sin| of its slope
GRAVITY_SYSTEMS = {"DRAINAGE", "RAINWATER", "SEWAGE", "STORMWATER", "WASTEWATER"}
GRAVITY_WORDS = re.compile(r"drain|waste|soil|sewer|sewage|storm|rain ?water|condensate|gutter", re.I)


def run_frame(direction) -> tuple[np.ndarray, np.ndarray]:
    """A run's own "up" (world Z made square to it) and "side" (cross(up, run): left of it, seen from above): the axes
    a route's offsets are measured on. For a level run, up is Z and side is today's lateral."""
    d = np.asarray(direction, float)
    up = UP - d * float(UP @ d)
    if np.linalg.norm(up) < 1e-6:
        raise Unsupported("a vertical run cannot be rerouted yet")
    up /= np.linalg.norm(up)
    return up, np.cross(up, d)


def is_gravity(element) -> bool:
    """A gravity drainage pipe: its systems say so, or its names do (drain, waste, soil, storm...). Such a pipe must
    keep falling: stepping it up or down would trap what it carries."""
    if not element.is_a("IfcPipeSegment") and not element.is_a("IfcFlowSegment"):
        return False
    if getattr(element, "PredefinedType", None) in ("GUTTER", "CULVERT"):
        return True
    systems = ifcopenshell.util.system.get_element_systems(element)
    if any(getattr(x, "PredefinedType", None) in GRAVITY_SYSTEMS for x in systems):
        return True
    words = [element.Name, getattr(element, "ObjectType", None), *[x.Name for x in systems]]
    return any(w and GRAVITY_WORDS.search(w) for w in words)


def route_steps(steps, length_m: float) -> list[dict]:
    """Check and sort a route's steps: [{"from_m", "to_m", "up_m", "side_m"}], metres along and off the run. Raises
    `Unsupported` with what is wrong, in words Muse can act on."""
    if not isinstance(steps, list) or not steps:
        raise Unsupported('a route needs steps: [{"from_m", "to_m", "up_m", "side_m"}]')
    if len(steps) > ROUTE_STEPS:
        raise Unsupported(f"a route takes at most {ROUTE_STEPS} steps")
    out = []
    for st in steps:
        try:
            a, b = float(st["from_m"]), float(st["to_m"])
            u, v = float(st.get("up_m", 0) or 0), float(st.get("side_m", 0) or 0)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise Unsupported('each step needs from_m and to_m, and up_m and/or side_m (metres)')
        if not np.isfinite([a, b, u, v]).all():
            raise Unsupported("route values must be finite")
        a, b = min(a, b), max(a, b)
        if a <= 0 or b >= length_m:
            raise Unsupported(f"a step must lie inside the run (0 to {length_m:.2f} m), not {a:.2f}-{b:.2f} m")
        if abs(u) < 1e-3 and abs(v) < 1e-3:
            raise Unsupported("a step must go up, down or sideways")
        out.append({"from_m": round(a, 4), "to_m": round(b, 4), "up_m": round(u, 4), "side_m": round(v, 4)})
    out.sort(key=lambda st: st["from_m"])
    for x, y in zip(out, out[1:]):
        if y["from_m"] < x["to_m"] - 1e-3:
            raise Unsupported(f"steps overlap ({x['from_m']:.2f}-{x['to_m']:.2f} and {y['from_m']:.2f}-{y['to_m']:.2f} m)")
    return out


def _transitions(steps: list[dict]) -> list[tuple[float, float, float]]:
    """Where a route changes its offset: (metres along, change up, change sideways), in order. Steps that share a
    boundary change straight from one offset to the next; otherwise the route returns to the line between them."""
    out, cur, at = [], (0.0, 0.0), None
    for st in steps:
        if at is not None and st["from_m"] > at + 1e-3:   # back to the line before this step
            out.append((at, -cur[0], -cur[1]))
            cur = (0.0, 0.0)
        out.append((st["from_m"], st["up_m"] - cur[0], st["side_m"] - cur[1]))
        cur, at = (st["up_m"], st["side_m"]), st["to_m"]
    out.append((at, -cur[0], -cur[1]))
    return [t for t in out if abs(t[1]) > 1e-4 or abs(t[2]) > 1e-4]


def route_summary(steps: list[dict], side_world=None) -> str:
    """A route in a few words: "200 mm north at 0.30-1.20 m, then 200 mm north at 2.80-3.70 m"."""
    def compass(sign: float) -> str:
        if side_world is None:
            return "sideways" if sign > 0 else "the other way"
        v = np.asarray(side_world, float) * sign
        return ("east" if v[0] > 0 else "west") if abs(v[0]) > abs(v[1]) else ("north" if v[1] > 0 else "south")
    parts = []
    for st in steps:
        moves = []
        if abs(st["up_m"]) >= 1e-3:
            moves.append(f"{abs(st['up_m']) * 1000:.0f} mm {'up' if st['up_m'] > 0 else 'down'}")
        if abs(st["side_m"]) >= 1e-3:
            moves.append(f"{abs(st['side_m']) * 1000:.0f} mm {compass(1 if st['side_m'] > 0 else -1)}")
        parts.append(f"{' and '.join(moves)} at {st['from_m']:.2f}-{st['to_m']:.2f} m")
    return "reroute " + ", then ".join(parts)


def apply_route(scene: IfcScene, global_id: str, steps: list[dict], corners: str | None = None) -> Route:
    """Reroute a stretch of a straight segment: hold it at an offset (up and/or sideways, on the run's own axes,
    `run_frame`) over each step's stretch, and join the offsets with 90° bends and short risers, each transition
    changing one axis (so "up, then sideways" is two steps; a round pipe may change both at once, a rolling offset).
    A level or mildly sloped run (up to 15°) keeps its fall
    on every piece parallel to it. Gravity drainage may only step sideways, and only when level.

    The element keeps the first piece (its GlobalId and first port); the rest are copies and bend fittings, chained
    port to port (`_build_chain`). Edits the model in place; wrap in `trial` to try it and undo."""
    element = scene.entity(global_id)
    i, place, item, origin, d, px, py = _frames(scene, element)
    s = scene.unit_scales[i]
    slope = abs(float(d @ UP))
    up, side = run_frame(d)
    if slope > ROUTE_SLOPE:
        raise Unsupported(f"the run slopes {np.degrees(np.arcsin(min(slope, 1.0))):.0f}°: a route takes runs up to 15°")
    length_m = item.Depth * s
    steps = route_steps(steps, length_m)
    if is_gravity(element):
        if slope > 1e-3:
            raise Unsupported("a falling drainage pipe cannot be rerouted here: its fall is the designer's to keep")
        if any(abs(st["up_m"]) >= 1e-3 for st in steps):
            raise Unsupported("drainage cannot step up or down (it would trap what it carries): go sideways")
    sx, sy = _profile_size(item.SweptArea)
    round_ = item.SweptArea.is_a("IfcCircleProfileDef")
    if round_:
        vertical, across = sx, sx
    elif abs(py @ up) > 0.999:
        vertical, across = sy, sx
    elif abs(px @ up) > 0.999:
        vertical, across = sx, sy
    else:
        raise Unsupported("the profile is tilted against the run's up direction")
    profile_x = px.copy()
    position = getattr(item.SweptArea, "Position", None)
    if position is not None and position.RefDirection is not None:
        local_x = np.asarray(position.RefDirection.DirectionRatios, dtype=float)
        local_x /= np.linalg.norm(local_x)
        profile_x = px * local_x[0] + py * local_x[1]

    moves = []   # (metres along, unit axis, jump metres, (width, depth) of the section in that bend plane, file units)
    for at, du, dv in _transitions(steps):
        if abs(du) > 1e-4 and abs(dv) > 1e-4:
            if not round_:   # a rectangular section would twist through a bend in a tilted plane
                if all(abs(at - st["from_m"]) > 1e-3 for st in steps):   # it is coming back to its line
                    raise Unsupported(f"at {at:.2f} m the route comes back to its line up and sideways at once: come "
                                      "back one axis at a time too (end with a step that keeps the up offset without "
                                      "the sideways one, sharing the boundary, so it steps back sideways, then down)")
                raise Unsupported(f"at {at:.2f} m the route changes up and sideways at once: change one axis at a time "
                                  "(go up in one step, then sideways in the next, sharing the boundary; come back the "
                                  "same way: a step back sideways only, then down)")
            jump = float(np.hypot(du, dv))   # a round pipe takes a rolling offset: one bend plane, on the diagonal
            moves.append((at, (up * du + side * dv) / jump, jump, (sx, sx)))
        elif abs(du) > 1e-4:
            moves.append((at, up * np.sign(du), abs(du), (across, vertical)))
        else:
            moves.append((at, side * np.sign(dv), abs(dv), (vertical, across)))
    use_bends = (corners or default_corners()) == "bends" and element.is_a() in FITTING_CLASS
    radii = [bend_radius(wt[1] * s, jump) for _, _, jump, wt in moves] if use_bends else []
    use_bends = use_bends and all(r is not None for r in radii)
    # Room along the run: each transition takes its bend radius (or half the section, square) before and after it.
    reach = [r for r in radii] if use_bends else [wt[1] * s / 2 for _, _, _, wt in moves]
    ends = [0.0] + [x for (at, _, _, _), r in zip(moves, reach) for x in (at - r, at + r)] + [length_m]
    for lo, hi in zip(ends[::2], ends[1::2]):
        if hi - lo < MIN_PIECE_M - 1e-9:
            raise Unsupported(f"the steps leave a straight piece shorter than {MIN_PIECE_M * 1000:.0f} mm at "
                              f"{lo:.2f}-{hi:.2f} m (run {length_m:.2f} m; each turn takes "
                              f"{max(reach) * 1000:.0f} mm of run either side)")

    pieces, along, cur = [], 0.0, np.zeros(3)
    for (at, axis, jump, (w, t)), r in zip(moves, reach):
        b, J, rr = at / s, axis * (jump / s), r / s
        if use_bends:
            pieces.append(("straight", origin + d * along + cur, d, b - rr - along))
            pieces.append(("bend", origin + d * (b - rr) + cur, d, axis, rr, w, t))
            if jump / s - 2 * rr > 1e-3 / s:
                pieces.append(("straight", origin + d * b + cur + axis * rr, axis, jump / s - 2 * rr))
            pieces.append(("bend", origin + d * b + cur + J - axis * rr, axis, d, rr, w, t))
            along = b + rr
        else:   # square corners: risers overlap the straights by half the section
            half = t / 2
            pieces.append(("straight", origin + d * along + cur, d, b - half - along))
            pieces.append(("straight", origin + d * b + cur - axis * half, axis, jump / s + 2 * half))
            along = b + half
        cur = cur + J
    pieces.append(("straight", origin + d * along + cur, d, item.Depth - along))
    gids = _build_chain(scene, element, place, item, d, px, profile_x, pieces)
    return Route(global_id, steps, gids, "bends" if use_bends else "square")


# ------------------------------------------------------------------------------------------------- resize

RESIZABLE = ("IfcDuctSegment", "IfcCableCarrierSegment")
TRANSITION_TYPE = {"IfcDuctSegment": "TRANSITION", "IfcCableCarrierSegment": "REDUCER", "IfcPipeSegment": "TRANSITION",
                   "IfcCableSegment": "NOTDEFINED"}
TRANSITION_ANGLE = np.radians(30)   # each face of a transition turns at most this much from the run
MAX_ASPECT = 4.0                    # a rectangular duct no flatter than 4:1 (losses and noise climb past it)
MIN_TRAY_DEPTH_M = 0.05             # a cable tray keeps sides at least this high
SIZE_STEP_M = 0.005                 # new sizes to 5 mm


@dataclass
class Resize:
    element: str          # the segment that was split; it keeps the first piece
    split_m: list[float]  # the resized stretch, metres along the run from its start
    width_m: float        # the new section, across and up
    depth_m: float
    keep: str             # the face that stays level: "bottom", "top" or "centre"
    before: list[float]   # [width, depth] before
    performance: str      # what the new section keeps: "equivalent diameter 100%, 3.3:1"
    pieces: list[str]     # GlobalIds in run order: the original, transition, resized middle, transition, end


def equivalent_diameter(width: float, depth: float) -> float:
    """A rectangular duct's equivalent diameter (Huebscher): the round duct with the same friction loss at the same
    airflow."""
    return 1.30 * (width * depth) ** 0.625 / (width + depth) ** 0.25


def _resizable(scene: IfcScene, element):
    """(file index, placement, item, origin, run direction, profile X, profile Y, width m, depth m, up, side) of a
    level, straight, rectangular duct or tray; else Unsupported with why."""
    if not any(element.is_a(c) for c in RESIZABLE):
        what = "a pipe's size is set by its flow" if element.is_a("IfcPipeSegment") else f"{element.is_a()} is not a duct or tray"
        raise Unsupported(f"only rectangular ducts and cable trays are resized here ({what})")
    if step_source(element):
        raise Unsupported("a part from STEP keeps its section (its file has no profile to change)")
    i, place, item, origin, d, px, py = _frames(scene, element)
    kind = item.SweptArea.is_a()
    if kind != "IfcRectangleProfileDef":   # exactly: the resized middle is written as a plain rectangle
        why = {"IfcCircleProfileDef": "a round duct keeps its size",
               "IfcRectangleHollowProfileDef": "a hollow section would lose its wall",
               "IfcRoundedRectangleProfileDef": "a rounded or flat-oval section is sized another way",
               "IfcUShapeProfileDef": "a channel-shaped tray keeps its profile",
               }.get(kind, f"its section is an {kind}")
        raise Unsupported(f"only a plain rectangular section is resized here ({why})")
    if abs(float(d @ UP)) > 1e-3:
        raise Unsupported("only a level run is resized here")
    s = scene.unit_scales[i]
    sx, sy = _profile_size(item.SweptArea)
    if abs(py @ UP) > 0.999:
        width, depth, up, side = sx * s, sy * s, py * np.sign(py @ UP), px
    elif abs(px @ UP) > 0.999:
        width, depth, up, side = sy * s, sx * s, px * np.sign(px @ UP), py
    else:
        raise Unsupported("the section is tilted: only an upright one is resized")
    return i, place, item, origin, d, px, py, width, depth, up, side


def resize_size(scene: IfcScene, global_id: str, depth_m: float) -> dict:
    """The section a duct or tray takes at a new, smaller depth, keeping what it carries: a duct keeps its equivalent
    diameter (the width solved to the next 5 mm), at most 4:1; a tray keeps its cross-section, at least 50 mm deep.
    Returns {"width_m", "depth_m", "before": [w, d], "performance"}; Unsupported when it cannot."""
    element = scene.entity(global_id)
    *_, width, depth, _, _ = _resizable(scene, element)
    if not np.isfinite(float(depth_m)):
        raise Unsupported("resize values must be finite")
    depth_m = round(float(depth_m), 4)
    if not 0 < depth_m < depth - 1e-4:
        raise Unsupported(f"a resize makes it shallower: {depth_m * 1000:.0f} mm is not less than its {depth * 1000:.0f} mm")
    step = lambda x: round(float(np.ceil(round(x / SIZE_STEP_M, 6)) * SIZE_STEP_M), 4)
    if element.is_a("IfcCableCarrierSegment"):
        if depth_m < MIN_TRAY_DEPTH_M - 1e-6:
            raise Unsupported(f"a tray keeps sides at least {MIN_TRAY_DEPTH_M * 1000:.0f} mm high")
        w = step(width * depth / depth_m)
        return {"width_m": w, "depth_m": depth_m, "before": [round(width, 4), round(depth, 4)],
                "performance": f"cross-section {w * depth_m / (width * depth):.0%} of before"}
    target = equivalent_diameter(width, depth)
    w = step(width_for(width, depth, depth_m))
    aspect = w / depth_m
    if aspect > MAX_ASPECT + 1e-6:
        least = depth_m
        while least < depth and width_for(width, depth, least) / least > MAX_ASPECT:
            least += SIZE_STEP_M
        raise Unsupported(f"{w * 1000:.0f} x {depth_m * 1000:.0f} mm would be {aspect:.1f}:1, flatter than "
                          f"{MAX_ASPECT:.0f}:1 (no shallower than about {least * 1000:.0f} mm)")
    return {"width_m": w, "depth_m": depth_m, "before": [round(width, 4), round(depth, 4)],
            "performance": f"equivalent diameter {equivalent_diameter(w, depth_m) / target:.0%} of before, {aspect:.1f}:1"}


def width_for(width: float, depth: float, depth_m: float) -> float:
    """The width that keeps a duct's equivalent diameter at a new depth (unrounded)."""
    target, lo, hi = equivalent_diameter(width, depth), width, width * 20
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if equivalent_diameter(mid, depth_m) < target else (lo, mid)
    return hi


def face_move(h0: float, h1: float, keep: str) -> float:
    """How far a resize's moving face goes (+ up) from depth `h0` to `h1`: the whole change when the bottom or top
    stays level, half of it at each face when the centre does. What the requirements' largest move measures."""
    return {"bottom": h1 - h0, "top": h0 - h1}.get(keep, (h1 - h0) / 2)


def _size_mm(w: float, h: float) -> str:
    return f"{w * 1000:.0f}x{h * 1000:.0f}"


def _resized_name(name: str | None, before: tuple[float, float], after: str) -> str:
    """`name` with its size written in (a "600x300" in it, either way round, becomes the new size), else the size
    added: what the properties card, the exported IFC and the PDF show the reviewer."""
    w, h = (round(v * 1000) for v in before)
    for m in re.finditer(r"(?<!\d)(\d{2,5})\s*[x×X]\s*(\d{2,5})(?!\d)", name or ""):
        if {int(m.group(1)), int(m.group(2))} == {w, h}:
            return name[:m.start()] + after + name[m.end():]
    return f"{name or 'Segment'} {after}"


def transition_length(w0: float, h0: float, w1: float, h1: float, keep: str) -> float:
    """How long a transition from w0 x h0 to w1 x h1 (keeping the `keep` face level) is, so no face turns more than
    30° from the run (at least 50 mm)."""
    off = {"bottom": (h1 - h0) / 2, "top": (h0 - h1) / 2}.get(keep, 0.0)
    moves = [abs(off + h1 / 2 - h0 / 2), abs(off - h1 / 2 + h0 / 2), abs(w1 - w0) / 2]
    return max(max(moves) / np.tan(TRANSITION_ANGLE), MIN_PIECE_M)


def resize_summary(split_m: list[float], width_m: float, depth_m: float, keep: str) -> str:
    return (f"resize {split_m[0]:.2f}-{split_m[1]:.2f} m to {width_m * 1000:.0f} x {depth_m * 1000:.0f} mm"
            + (f" ({keep} kept level)" if keep in ("bottom", "top") else ""))


def _loft(p0, d, length, side, up, a: tuple, b: tuple) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """A closed lofted transition between two rectangles square to `d`: `a` = (width, depth, centre offset up) at
    `p0`, `b` at p0 + d·length. Faces point outward."""
    corners = ((-1, -1), (1, -1), (1, 1), (-1, 1))
    verts = np.array([p0 + d * t + side * (sx * w / 2) + up * (off + sy * h / 2)
                      for t, (w, h, off) in ((0.0, a), (length, b)) for sx, sy in corners])
    faces = [(k, (k + 1) % 4, 4 + (k + 1) % 4) for k in range(4)] + [(k, 4 + (k + 1) % 4, 4 + k) for k in range(4)]
    faces += [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
    centre = verts.mean(axis=0)
    out = []
    for f in faces:   # convex: a face points outward when its normal leaves the centre
        n = np.cross(verts[f[1]] - verts[f[0]], verts[f[2]] - verts[f[0]])
        out.append(f if n @ (verts[list(f)].mean(axis=0) - centre) > 0 else (f[0], f[2], f[1]))
    return verts, out


@dataclass
class Section:
    """A straight segment's section where it runs (world metres): its centreline ends, direction, profile axes and size
    (width along profile X, depth along profile Y; a circle's diameter both)."""
    start: np.ndarray
    end: np.ndarray
    d: np.ndarray
    px: np.ndarray
    py: np.ndarray
    w: float
    h: float
    round_: bool


def section_of(scene: IfcScene, global_id: str) -> Section:
    """The section of a straight segment of one rectangular or round extrusion; else Unsupported."""
    element = scene.entity(global_id)
    i, _, item, origin, d, px, py = _frames(scene, element)
    s = scene.unit_scales[i]
    prof = item.SweptArea
    if prof.is_a("IfcCircleProfileDef"):
        w = h = 2 * prof.Radius * s
    elif prof.is_a() == "IfcRectangleProfileDef":
        w, h = prof.XDim * s, prof.YDim * s
    else:
        raise Unsupported("only a rectangular or round section takes a transition")
    c = prof.Position.Location.Coordinates if getattr(prof, "Position", None) is not None else (0.0, 0.0)
    start = (origin + px * c[0] + py * c[1]) * s
    return Section(start, start + d * item.Depth * s, d, px, py, w, h, prof.is_a("IfcCircleProfileDef"))


def _loft_any(p0, d, length, side, up, a: tuple, b: tuple, round_: bool) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """A closed lofted transition between two sections square to `d`, rectangles or circles (16-gons): `a` = (width
    across `side`, depth along `up`, centre offset up, centre offset across) at `p0`, `b` at p0 + d·length. Faces
    point outward."""
    if round_:
        ang = np.linspace(0, 2 * np.pi, 16, endpoint=False)
        unit = list(zip(np.cos(ang), np.sin(ang)))
    else:
        unit = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    m = len(unit)
    verts = np.array([p0 + d * t + side * (off_s + ux * w / 2) + up * (off_u + uy * h / 2)
                      for t, (w, h, off_u, off_s) in ((0.0, a), (length, b)) for ux, uy in unit])
    faces = [(k, (k + 1) % m, m + (k + 1) % m) for k in range(m)] + [(k, m + (k + 1) % m, m + k) for k in range(m)]
    faces += [(0, j, j + 1) for j in range(1, m - 1)] + [(m, m + j, m + j + 1) for j in range(1, m - 1)]
    centre = verts.mean(axis=0)
    out = []
    for f in faces:   # convex: a face points outward when its normal leaves the centre
        n = np.cross(verts[f[1]] - verts[f[0]], verts[f[2]] - verts[f[0]])
        out.append(f if n @ (verts[list(f)].mean(axis=0) - centre) > 0 else (f[0], f[2], f[1]))
    return verts, out


def joined_caps(scene: IfcScene, global_id: str) -> list[str]:
    """Which ends ("start", "end") of a straight segment are joined by a port to something."""
    try:
        sec = section_of(scene, global_id)
    except Unsupported:
        return []
    out = []
    for port in ifcopenshell.util.system.get_ports(scene.entity(global_id)):
        if ifcopenshell.util.system.get_connected_port(port) is None or port.ObjectPlacement is None:
            continue
        at = scene.placement(port.GlobalId)[:3, 3]
        for end, p in (("start", sec.start), ("end", sec.end)):
            if np.linalg.norm(at - p) <= 0.005 and end not in out:
                out.append(end)
    return out


def add_transitions(scene: IfcScene, global_id: str, before: Section, ends: list[str]) -> list[str]:
    """After a segment's section changed (a side pushed out, a radius grown): at each joined end in `ends`, the segment
    shortened by a transition's length (no face turning more than 30°) and a transition fitting from its new section
    back to the one it had, joined between it and what that end was joined to, so the joint still meets the same size.
    Returns the transitions' GlobalIds."""
    element = scene.entity(global_id)
    i = scene.index_of(global_id)
    model, s = scene.models[i], scene.unit_scales[i]
    place = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    inv = np.linalg.inv(place)
    made = []
    for end in ends:
        cur = section_of(scene, global_id)
        out = cur.d if end == "end" else -cur.d
        old_c = before.end if end == "end" else before.start
        new_line = cur.end if end == "end" else cur.start
        shift = new_line - old_c - out * float((new_line - old_c) @ out)   # the new centreline off the old one
        moves = [abs(cur.w - before.w) / 2 + abs(float(shift @ cur.px)), abs(cur.h - before.h) / 2 + abs(float(shift @ cur.py))]
        lt = max(max(moves) / np.tan(TRANSITION_ANGLE), MIN_PIECE_M)
        if np.linalg.norm(cur.end - cur.start) - lt < MIN_PIECE_M:
            raise Unsupported(f"it is too short for a {lt * 1000:.0f} mm transition at its {end}")
        port = next((p for p in ifcopenshell.util.system.get_ports(element) if p.ObjectPlacement is not None
                     and np.linalg.norm(scene.placement(p.GlobalId)[:3, 3] - old_c) <= 0.005), None)
        peer = ifcopenshell.util.system.get_connected_port(port) if port is not None else None
        if peer is not None:
            ifcopenshell.api.run("system.disconnect_port", model, port=port)
        stretch(scene, global_id, end, -lt, unique=True)
        cur = section_of(scene, global_id)
        new_c = cur.end if end == "end" else cur.start
        verts, tris = _loft_any((old_c - out * lt) / s, out, lt / s, cur.px, cur.py,
                                (cur.w / s, cur.h / s, float(shift @ cur.py) / s, float(shift @ cur.px) / s),
                                (before.w / s, before.h / s, 0.0, 0.0), cur.round_)
        part = _new_fitting(model, element, place, f"{element.Name or 'Segment'} transition",
                            f"{element.Tag}-TR{end[0].upper()}" if element.Tag else None, TRANSITION_TYPE[element.is_a()])
        local = (inv @ np.c_[verts, np.ones(len(verts))].T).T[:, :3]
        solid = model.createIfcTriangulatedFaceSet(model.createIfcCartesianPointList3D([[float(c) for c in v] for v in local]),
                                                   None, True, [[int(x) + 1 for x in f] for f in tris], None)
        body = next(r for r in element.Representation.Representations if r.RepresentationIdentifier == "Body")
        part.Representation = model.createIfcProductDefinitionShape(None, None, [model.createIfcShapeRepresentation(
            body.ContextOfItems, "Body", "Tessellation", [solid])])
        for st in [x for it in body.Items for x in model.get_inverse(it) if x.is_a("IfcStyledItem")]:
            model.createIfcStyledItem(solid, st.Styles, st.Name)
        near, far = _ports(part)
        _place_port(model, near, new_c / s, s, -out, cur.px)   # its end at the segment, its other at the old joint
        _place_port(model, far, old_c / s, s, out, cur.px)
        if port is not None:
            _place_port(model, port, new_c / s, s, out, cur.px)   # the segment's own end port, on its new centreline
            ifcopenshell.api.run("system.connect_port", model, port1=port, port2=near, direction=port.FlowDirection or "NOTDEFINED")
        if peer is not None:
            ifcopenshell.api.run("system.connect_port", model, port1=far, port2=peer, direction=far.FlowDirection or "NOTDEFINED")
        made.append(part.GlobalId)
    scene.refresh_bounds([global_id, *made])
    return made


def apply_resize(scene: IfcScene, global_id: str, split_m: list[float], depth_m: float, keep: str = "bottom") -> Resize:
    """Resize a stretch of a level rectangular duct or tray: from `split_m[0]` to `split_m[1]` (metres along it) it
    takes the section `resize_size` gives at `depth_m`, with the `keep` face level ("bottom", "top" or "centre") and
    the same centreline across, joined to the rest by transition fittings whose faces turn at most 30°. The element
    keeps the first piece; the resized middle has a profile of its own (never the shared one). Edits the model in
    place; wrap in `trial` to try it and undo."""
    element = scene.entity(global_id)
    i, place, item, origin, d, px, py, w0, h0, up, side = _resizable(scene, element)
    s = scene.unit_scales[i]
    size = resize_size(scene, global_id, depth_m)
    w1, h1 = size["width_m"], size["depth_m"]
    if keep not in ("bottom", "top", "centre"):
        raise Unsupported("say which face stays level: bottom, top or centre")
    off = {"bottom": (h1 - h0) / 2, "top": (h0 - h1) / 2, "centre": 0.0}[keep]
    lt = transition_length(w0, h0, w1, h1, keep)
    try:
        a, b = sorted(float(x) for x in split_m)
    except (TypeError, ValueError):
        raise Unsupported("a resize needs two split points") from None
    if not np.isfinite([a, b]).all():   # checked before anything is edited: a NaN would fail half-way through
        raise Unsupported("resize values must be finite")
    length = item.Depth * s
    if a - lt < MIN_PIECE_M - 1e-9 or b + lt > length - MIN_PIECE_M + 1e-9 or b - a < MIN_PIECE_M:
        raise Unsupported(f"the resized stretch {a:.2f}-{b:.2f} m leaves too little run: each transition takes "
                          f"{lt:.2f} m and {MIN_PIECE_M * 1000:.0f} mm must remain at each end (run {length:.2f} m)")
    profile_x = px.copy()
    position = getattr(item.SweptArea, "Position", None)
    if position is not None and position.RefDirection is not None:
        local_x = np.asarray(position.RefDirection.DirectionRatios, dtype=float)
        local_x /= np.linalg.norm(local_x)
        profile_x = px * local_x[0] + py * local_x[1]
    prof = item.SweptArea
    across_x = abs(px @ side) > 0.999   # the profile's X runs across (width), else up (depth)
    xdim, ydim = (w1, h1) if across_x else (h1, w1)
    old_size, new_size = _size_mm(w0, h0), _size_mm(w1, h1)
    resized = scene.models[i].createIfcRectangleProfileDef(prof.ProfileType, new_size, prof.Position,
                                                           float(xdim / s), float(ydim / s))
    A, B, LT = a / s, b / s, lt / s
    lift = up * (off / s)
    v1, f1 = _loft(origin + d * (A - LT), d, LT, side, up, (w0 / s, h0 / s, 0.0), (w1 / s, h1 / s, off / s))
    v2, f2 = _loft(origin + d * B, d, LT, side, up, (w1 / s, h1 / s, off / s), (w0 / s, h0 / s, 0.0))
    still = np.zeros(3)
    pieces = [("straight", origin, d, A - LT),
              ("transition", origin + d * (A - LT), d, LT, v1, f1, (still, lift)),
              ("straight", origin + d * A + lift, d, B - A, resized),
              ("transition", origin + d * B, d, LT, v2, f2, (lift, still)),
              ("straight", origin + d * (B + LT), d, item.Depth - B - LT)]
    name = element.Name
    gids = _build_chain(scene, element, place, item, d, px, profile_x, pieces)
    _label_resize(scene, gids, name, (w0, h0), old_size, new_size, keep, size["performance"])
    return Resize(global_id, [a, b], w1, h1, keep, size["before"], size["performance"], gids)


def _label_resize(scene: IfcScene, gids: list[str], name: str | None, before: tuple[float, float], old_size: str,
                  new_size: str, keep: str, performance: str) -> None:
    """Say the new size on the resized middle (its name, the properties it copied from the original where they held
    the old size, and an ORCA_Resize property set) and on the transitions, so the reviewer reads what changed."""
    model = scene.models[scene.index_of(gids[0])]
    middle = scene.entity(gids[2])
    middle.Name = _resized_name(name, before, new_size)
    for gid in (gids[1], gids[3]):
        scene.entity(gid).Name = f"{name or 'Segment'} transition to {new_size}"
    olds = {old_size, old_size.replace("x", " x "), old_size.replace("x", "×")}
    for rel in list(getattr(middle, "IsDefinedBy", None) or []):
        pset = rel.RelatingPropertyDefinition if rel.is_a("IfcRelDefinesByProperties") else None
        if pset is None or not pset.is_a("IfcPropertySet") or len(rel.RelatedObjects) > 1:   # never the original's
            continue
        for prop in pset.HasProperties or []:
            value = getattr(prop, "NominalValue", None)
            if value is not None and isinstance(value.wrappedValue, str) and value.wrappedValue.strip() in olds:
                prop.NominalValue = model.create_entity(value.is_a(), new_size)
    pset = ifcopenshell.api.run("pset.add_pset", model, product=middle, name="ORCA_Resize")
    ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties={
        "ResizedFrom": old_size, "Size": new_size, "KeepLevel": keep, "Performance": performance})


def _build_chain(scene: IfcScene, element, place, item, d, px, profile_x, pieces: list[tuple],
                 shift_ends: tuple = (None, None)) -> list[str]:
    """Turn `element` into the chain of `pieces` (world, file units): the first piece is the element itself, shortened
    (it must be the straight from its origin along `d`); straights are copies of it with the same profile, bends are
    new fittings. Ports are added and chained in order, the last piece takes over the element's far connection, and
    the authored external port frames and flows are kept. Pieces: ("straight", start, axis, length[, profile]) (a
    profile of its own: a resized stretch), ("bend", start, from, to, radius, width, depth) (width across the bend's
    plane, depth in it) and ("transition", start, axis, length, verts, faces) (a lofted change of section, world
    triangles in file units[, (start shift, end shift)]: where its ends' centres sit off the run's line). Returns the
    GlobalIds in order."""
    i = scene.index_of(element.GlobalId)
    model, s = scene.models[i], scene.unit_scales[i]
    L = item.Depth
    origin = (ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
              @ ifcopenshell.util.placement.get_axis2placement(item.Position))[:3, 3]

    def section_ref(axis, reference=px):
        """Transport the actual profile X axis in the detour plane, without section roll."""
        normal = np.cross(d, axis)
        sine, cosine = np.linalg.norm(normal), float(d @ axis)
        if sine < 1e-9:
            return reference.copy()
        normal /= sine
        return reference*cosine + np.cross(normal,reference)*sine + normal*(normal @ reference)*(1-cosine)
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
                       for p in (first_ports[0], first_ports[-1])] if len(first_ports) >= 2 else [None, None]
    external_flows = {peer.GlobalId:peer.FlowDirection for port in first_ports
                      if (peer := ifcopenshell.util.system.get_connected_port(port)) is not None}
    single_far = None
    if len(first_ports) == 1:
        port = first_ports[0]
        if port.ObjectPlacement is None:
            raise Unsupported('a single port needs a physical endpoint placement')
        frame = scene.placement(port.GlobalId)
        endpoint_distances = [np.linalg.norm(frame[:3,3] - point*s) for point in (origin, origin+d*L)]
        if min(endpoint_distances) > .002:
            raise Unsupported('a single port does not align with either physical endpoint')
        endpoint = int(np.argmin(endpoint_distances))
        external_frames[endpoint] = frame
        flow = port.FlowDirection
        opposite = {'SOURCE': 'SINK', 'SINK': 'SOURCE'}.get(flow, flow or 'NOTDEFINED')
        original_flows[endpoint], original_flows[1-endpoint] = flow, opposite
        if endpoint == 1:
            # Keep the authored identity and external relationship on the last piece.
            # Unassign before copying so copies cannot inherit this external port.
            single_far = port
            ifcopenshell.api.run('system.unassign_port', model, element=element, port=port)
            first_ports = []
    far = ifcopenshell.util.system.get_connected_port(first_ports[-1]) if len(first_ports) > 1 else None
    if far is not None:
        ifcopenshell.api.run("system.disconnect_port", model, port=first_ports[-1])

    item.Depth = pieces[0][3]
    chain, ends = [element], [(pieces[0][1], pieces[0][1] + pieces[0][2] * pieces[0][3])]
    straights = bends = transitions = 0
    for piece in pieces[1:]:
        if piece[0] == "straight":
            _, start, axis, length, *own = piece
            straights += 1
            part = ifcopenshell.api.run("root.copy_class", model, product=element)
            if element.Tag:
                part.Tag = f"{element.Tag}-SL{straights}"
            local_start = (inv @ np.append(start, 1.0))[:3]
            ref = section_ref(axis)
            position = model.createIfcAxis2Placement3D(
                _point(model, local_start), _dir(model, inv[:3, :3] @ axis), _dir(model, inv[:3, :3] @ ref))
            solid = model.createIfcExtrudedAreaSolid(own[0] if own else item.SweptArea, position,
                                                     model.createIfcDirection((0.0, 0.0, 1.0)), float(length))
            rep = model.createIfcShapeRepresentation(body.ContextOfItems, "Body", "SweptSolid", [solid])
            ends.append((start, start + axis * length))
        elif piece[0] == "transition":
            _, start, axis, length, verts, faces, *shift = piece
            shift = shift[0] if shift else (np.zeros(3), np.zeros(3))
            transitions += 1
            part = _new_fitting(model, element, place, f"{element.Name or 'Segment'} transition",
                                f"{element.Tag}-TR{transitions}" if element.Tag else None,
                                TRANSITION_TYPE[element.is_a()])
            local = (inv @ np.c_[verts, np.ones(len(verts))].T).T[:, :3]
            solid = model.createIfcTriangulatedFaceSet(
                model.createIfcCartesianPointList3D([[float(c) for c in v] for v in local]), None, True,
                [[int(x) + 1 for x in f] for f in faces], None)
            rep = model.createIfcShapeRepresentation(body.ContextOfItems, "Body", "Tessellation", [solid])
            ends.append((start + shift[0], start + axis * length + shift[1]))
        else:
            _, start, t0, t1, R, w, t = piece
            bends += 1
            part = _new_fitting(model, element, place, f"{element.Name or 'Segment'} bend", 
                                f"{element.Tag}-BR{bends}" if element.Tag else None)
            verts, faces = _bend_mesh(start, t0, t1, R, w, t, round_)
            local = (inv @ np.c_[verts, np.ones(len(verts))].T).T[:, :3]
            solid = model.createIfcTriangulatedFaceSet(
                model.createIfcCartesianPointList3D([[float(c) for c in v] for v in local]), None, True,
                [[int(x) + 1 for x in f] for f in faces], None)
            rep = model.createIfcShapeRepresentation(body.ContextOfItems, "Body", "Tessellation", [solid])
            ends.append((start, bend_end(start, t0, t1, R)))   # start + (t0 + t1) R at 90°
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
    if single_far is not None:
        replacement = chain_ports[-1][-1]
        ifcopenshell.api.run('root.remove_product', model, product=replacement)
        ifcopenshell.api.run('system.assign_port', model, element=chain[-1], port=single_far)
        chain_ports[-1][-1] = single_far
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
        # An end the chain moves with what it is joined to (a re-fit, `apply_jog`): its frame goes the same way
        for port, frame, shift in zip((chain_ports[0][0], chain_ports[-1][-1]), external_frames, shift_ends):
            if frame is not None:
                if shift is not None:
                    frame = frame.copy()
                    frame[:3, 3] += np.asarray(shift, float)
                ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=frame, is_si=True)

    gids = [p.GlobalId for p in chain]
    scene.refresh_bounds(gids)
    return gids


def _new_fitting(model, segment, place, name: str, tag: str | None, predefined: str = "BEND"):
    """A fitting for `segment` (a bend, or a transition): its fitting class, in the same storey and systems, with two
    ports and its own placement (the segment's frame, so the fitting's vertices share the segment's local coordinates)."""
    fitting = ifcopenshell.api.run("root.create_entity", model, ifc_class=FITTING_CLASS[segment.is_a()],
                                   predefined_type=predefined, name=name)
    if tag:
        fitting.Tag = tag
    container = ifcopenshell.util.element.get_container(segment)
    if container is not None:
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=container, products=[fitting])
    for system in ifcopenshell.util.system.get_element_systems(segment):
        ifcopenshell.api.run("system.assign_system", model, products=[fitting], system=system)
    # A segment converted from STEP carries where it came from (step.py); its bends belong to the same STEP group.
    source = step_source(segment)
    if source:
        pset = ifcopenshell.api.run("pset.add_pset", model, product=fitting, name=STEP_PSET)
        ifcopenshell.api.run("pset.edit_pset", model, pset=pset,
                             properties={k: v for k, v in source.items() if k in ("Group", "Label", "Source")})
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


def bend_turn(t0, t1) -> tuple[np.ndarray, float]:
    """A bend from `t0` to `t1`: the unit direction square to `t0` it turns towards (in their plane), and its angle."""
    t0, t1 = np.asarray(t0, float), np.asarray(t1, float)
    n = t1 - t0 * float(t1 @ t0)
    return n / np.linalg.norm(n), float(np.arccos(np.clip(t0 @ t1, -1.0, 1.0)))


def bend_end(p0, t0, t1, r) -> np.ndarray:
    """Where a bend of centreline radius `r` from `p0` along `t0` ends, running along `t1` (any angle under 180°)."""
    n, th = bend_turn(t0, t1)
    return np.asarray(p0, float) + r * np.sin(th) * np.asarray(t0, float) + r * (1.0 - np.cos(th)) * n


def _bend_mesh(p0, t0, t1, r, width, depth, round_: bool) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """A closed triangulated bend (world coordinates): the section swept from `p0` going along `t0` round a radius `r`
    until it runs along `t1`, at whatever angle they make (90° in an offset's square bends, 45° in an angled one).
    Width stays across the bend plane; depth lies in it. Faces point outward."""
    t0, t1 = np.asarray(t0, float), np.asarray(t1, float)
    side = np.cross(t0, t1)
    side /= np.linalg.norm(side)
    n, turn = bend_turn(t0, t1)
    centre = np.asarray(p0, float) + r * n
    if round_:
        ang = np.linspace(0, 2 * np.pi, 16, endpoint=False)
        section = np.c_[np.cos(ang) * width / 2, np.sin(ang) * depth / 2]
    else:
        section = np.array([[-width / 2, -depth / 2], [width / 2, -depth / 2], [width / 2, depth / 2], [-width / 2, depth / 2]])
    m = len(section)
    rings = []
    for k in range(BEND_STEPS + 1):
        th = turn * k / BEND_STEPS
        p = centre - r * np.cos(th) * n + r * np.sin(th) * t0
        tangent = np.cos(th) * t0 + np.sin(th) * n
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


def apply_trim(scene: IfcScene, global_id: str, end: str, by_m: float, least_m: float = MIN_PIECE_M) -> Trim:
    """Shorten (or, with a negative `by_m`, lengthen) a member at one end of its long axis (`member_axis`). Edits the
    model in place; wrap in `trial` to try it and undo. A port at that end moves with it."""
    element = scene.entity(global_id)
    i, place, item, origin, d, _, _ = _frames(scene, element)
    model, s = scene.models[i], scene.unit_scales[i]
    axis, _, _, length = member_axis(scene, element)
    by = by_m / s
    if end not in ("start", "end"):
        raise Unsupported("say which end to trim: start or end")
    if length / s - by < least_m / s:
        raise Unsupported(f"trimming {by_m * 1000:.0f} mm would leave less than {least_m * 1000:.0f} mm of it")
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


# ------------------------------------------------------------------------------------------------- penetrations

# Walls and slabs take openings for services as a matter of course; whether anything else may (a beam's web, a
# machine panel's gland plate) is `hosts.decide`'s call. This module only needs the host's body to be extrusions, so
# the opening can be cut reliably.
PENETRABLE = ("IfcWall", "IfcSlab")
OPENING_MARGIN_M = 0.005  # beyond the clearance, all round: tessellated circles and site tolerance
OPENING_ROUND_M = 0.01    # opening sizes are rounded up to this
FITTED_MARGIN_M = 0.001   # a fitted opening (a cable gland, a grommet): this much round the service, to the mm
OPENING_PROUD_M = 0.01    # the void runs this far past each face of the host
OPENING_EDGE_M = 0.05     # the host must surround the opening by this much: a hole at its edge is a notch
MAX_THROUGH_M = 1.0       # deeper than any wall or slab: the run lies along the host, not across it
PFV_COLOUR, PFV_ALPHA = (0.96, 0.55, 0.12), 0.35
STOPS_INSIDE_M = 0.005    # a service ending this close to a face still passes through
PROVISION_PSET = "ORCA_Provision"   # on a provision for void ORCA wrote: the service and host it is for


@dataclass
class Penetration:
    service: str           # the run that passes through
    host: str              # the wall or slab it passes through
    shape: str             # "rect" or "round"
    width_m: float         # along the service profile's X (the diameter when round)
    height_m: float        # along its Y (the diameter when round)
    depth_m: float         # along the service: through the host, and 10 mm proud of each face
    start: list[float]     # world metres: where the void starts, on the service's axis
    axis: list[float]      # the service's direction (the void's)
    xdir: list[float]      # the service profile's X
    clearance_m: float = DEFAULT_CLEARANCE_M
    gap_m: float = 0.0             # the least gap between the service and the opening's edge, by construction
    fit: str = "annular"           # "annular" (clearance round it) or "fitted" (a gland fits it)
    provision: str | None = None   # the provision for void's GlobalId, once applied
    opening: str | None = None     # the host's new opening, when it was cut


def not_penetrable(host) -> str | None:
    """Why the geometry of `host` cannot take an opening here, or None (whether it may is `hosts.decide`'s call)."""
    rep = host.Representation
    bodies = [r for r in (rep.Representations if rep else []) if r.RepresentationIdentifier == "Body"]
    if not bodies or not all(i.is_a("IfcExtrudedAreaSolid") for b in bodies for i in b.Items):
        return "only a host whose body is extrusions can be cut here"
    return None


def size_text(pen: Penetration) -> str:
    if pen.shape == "round":
        return f"Ø{pen.width_m * 1000:.0f} mm"
    return f"{pen.width_m * 1000:.0f} x {pen.height_m * 1000:.0f} mm"


def _host_tris(scene: IfcScene, host_gid: str) -> np.ndarray:
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, scene.entity(host_gid))
    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    return verts[np.asarray(shape.geometry.faces).reshape(-1, 3)]


def _outline(shape: str, w: float, h: float, px, py, step_m: float = 0.03) -> list[np.ndarray]:
    """Offsets (world) round an opening's outline every `step_m`, and its centre."""
    if shape == "round":
        n = max(12, int(np.ceil(np.pi * w / step_m)))
        return [np.zeros(3)] + [px * np.cos(a) * w / 2 + py * np.sin(a) * w / 2
                                for a in np.linspace(0, 2 * np.pi, n, endpoint=False)]
    xs = np.linspace(-w / 2, w / 2, max(2, int(np.ceil(w / step_m)) + 1))
    ys = np.linspace(-h / 2, h / 2, max(2, int(np.ceil(h / step_m)) + 1))
    return ([np.zeros(3)] + [px * x + py * y for x in xs for y in (-h / 2, h / 2)]
            + [px * x + py * y for y in ys[1:-1] for x in (-w / 2, w / 2)])


def penetration(scene: IfcScene, service_gid: str, host_gid: str, clearance_m: float = DEFAULT_CLEARANCE_M,
                fit: str = "annular") -> Penetration:
    """The opening a straight service needs through a host: its section plus the clearance and 5 mm all round, rounded
    up to 10 mm ("annular": a sleeve or fire-stopping fills the gap), or plus 1 mm, to the mm ("fitted": a cable gland
    or grommet); rectangular or round like the service, square to it, through the host's whole depth (found by rays
    from both sides round the opening's outline) and 10 mm proud of each face. Reads the model only;
    `apply_penetration` writes it."""
    host = scene.entity(host_gid)
    why = not_penetrable(host)
    if why:
        raise Unsupported(why)
    service = scene.entity(service_gid)
    i, _, item, origin, d, px, py = _frames(scene, service)
    s = scene.unit_scales[i]
    sx, sy = _profile_size(item.SweptArea)
    round_ = item.SweptArea.is_a("IfcCircleProfileDef")
    fitted = fit == "fitted"
    margin, step = (FITTED_MARGIN_M, 0.001) if fitted else (clearance_m + OPENING_MARGIN_M, OPENING_ROUND_M)

    def up(x: float) -> float:
        return round(float(np.ceil(round(x / step, 6)) * step), 4)
    w, h = up(sx * s + 2 * margin), up(sy * s + 2 * margin)
    shape = "round" if round_ else "rect"
    start, length = origin * s, item.Depth * s
    box = scene.bounds().get(host_gid)
    if box is None:
        raise Unsupported("the host has no geometry")
    corners = np.array([[x, y, z] for x in box[:, 0] for y in box[:, 1] for z in box[:, 2]])
    along = (corners - start) @ d
    lo, hi = float(along.min()), float(along.max())
    if hi < 0 or lo > length:
        raise Unsupported("the service does not reach it")
    tris = _host_tris(scene, host_gid)
    ring = np.array(_outline(shape, w, h, px, py))
    front, back = start + d * (lo - 0.5), start + d * (hi + 0.5)
    t_in = _first_hit(front + ring, d, tris)
    t_out = _first_hit(back + ring, -d, tris)
    if not np.isfinite(t_in).any() or not np.isfinite(t_out).any():
        raise Unsupported("the service does not pass through it")
    entry = lo - 0.5 + float(t_in[np.isfinite(t_in)].min())
    exit_ = hi + 0.5 - float(t_out[np.isfinite(t_out)].min())
    if entry < -STOPS_INSIDE_M or exit_ > length + STOPS_INSIDE_M:
        raise Unsupported("the service stops inside it: an opening is for a service that passes through (shorten or "
                          "move it instead)")
    through = exit_ - entry
    if through > MAX_THROUGH_M:
        raise Unsupported(f"the service runs {through:.2f} m inside it: along it, not through it")
    # The host must surround the opening: rays just outside it, every way, must still meet the host.
    middle = start + d * (entry + exit_) / 2
    for name, v, half in (("above", py, h), ("below", -py, h), ("to one side", px, w), ("to the other side", -px, w)):
        probe = middle + v * (half / 2 + OPENING_EDGE_M) - d * (through / 2 + 0.5)
        if not np.isfinite(_first_hit(probe[None], d, tris)).any():
            raise Unsupported(f"the opening would break out of its edge {name}: it needs {OPENING_EDGE_M * 1000:.0f} mm of "
                              "host all round (route the service instead, or ask its designer)")
    a = entry - OPENING_PROUD_M
    gap = min((w - sx * s) / 2, (h - sy * s) / 2)
    return Penetration(service_gid, host_gid, shape, w, h, round(through + 2 * OPENING_PROUD_M, 4),
                       np.round(start + d * a, 5).tolist(), np.asarray(d).tolist(), np.asarray(px).tolist(), clearance_m,
                       round(float(gap), 4), "fitted" if fitted else "annular")


def _void_rep(model, s: float, pen: Penetration, context):
    """The void as one extrusion along +Z of its own placement, in the file's units."""
    if pen.shape == "round":
        profile = model.createIfcCircleProfileDef("AREA", None, model.createIfcAxis2Placement2D(_point(model, (0, 0)), None),
                                                  float(pen.width_m / 2 / s))
    else:
        profile = model.createIfcRectangleProfileDef("AREA", None, model.createIfcAxis2Placement2D(_point(model, (0, 0)), None),
                                                     float(pen.width_m / s), float(pen.height_m / s))
    solid = model.createIfcExtrudedAreaSolid(profile, model.createIfcAxis2Placement3D(_point(model, (0, 0, 0)), None, None),
                                             model.createIfcDirection((0.0, 0.0, 1.0)), float(pen.depth_m / s))
    return model.createIfcShapeRepresentation(context, "Body", "SweptSolid", [solid]), solid


def _void_place(model, product, s: float, pen: Penetration) -> None:
    z, x = np.asarray(pen.axis, float), np.asarray(pen.xdir, float)
    m = np.eye(4)
    m[:3, :3] = np.column_stack([x, np.cross(z, x), z])
    m[:3, 3] = np.asarray(pen.start, float) / s
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=product, matrix=m, is_si=False)


def _body_context(element):
    rep = element.Representation
    return next(r.ContextOfItems for r in rep.Representations if r.RepresentationIdentifier == "Body")


def _see_through(model, solid) -> None:
    rgb = model.createIfcColourRgb(None, *PFV_COLOUR)
    rendering = model.createIfcSurfaceStyleRendering(rgb, 1 - PFV_ALPHA, None, None, None, None, None, None, "NOTDEFINED")
    style = model.createIfcSurfaceStyle("ORCA provision for void", "BOTH", [rendering])
    if model.schema == "IFC2X3":   # IFC2X3 wraps styles in an assignment
        model.createIfcStyledItem(solid, [model.createIfcPresentationStyleAssignment([style])], None)
    else:
        model.createIfcStyledItem(solid, [style], None)


def provision_for(scene: IfcScene, service_gid: str, host_gid: str):
    """The provision for void already written for this service through this host, or None."""
    model = scene.models[scene.index_of(service_gid)]
    for e in model.by_type("IfcBuildingElementProxy"):
        if is_provision(e):
            mine = ifcopenshell.util.element.get_psets(e).get(PROVISION_PSET, {})
            if mine.get("Service") == service_gid and mine.get("Host") == host_gid:
                return e
    return None


def apply_penetration(scene: IfcScene, pen: Penetration, cut: bool) -> Penetration:
    """Request the opening: always a provision for void in the service's model (an IfcBuildingElementProxy,
    PROVISIONFORVOID, with Pset_ProvisionForVoid, see-through orange, in the service's storey), and, when `cut`, the
    opening itself in the host (an IfcOpeningElement voiding it). Edits the models in place; wrap in `trial_files`
    (both files) to try it and undo."""
    service, host = scene.entity(pen.service), scene.entity(pen.host)
    existing = provision_for(scene, pen.service, pen.host)
    if existing is not None:   # asked for before (its team had not cut it): one request, not two
        pen.provision, pen.opening = existing.GlobalId, None
    else:
        _write_provision(scene, pen, service, host)
    if cut:
        _cut_opening(scene, pen, service, host)
    return pen


def _write_provision(scene: IfcScene, pen: Penetration, service, host) -> None:
    i = scene.index_of(pen.service)
    ms, ss = scene.models[i], scene.unit_scales[i]
    four = ms.schema != "IFC2X3"
    pfv = ifcopenshell.api.run("root.create_entity", ms, ifc_class="IfcBuildingElementProxy",
                               name=f"Provision for void: {service.Name or service.is_a()[3:]}")
    if four:
        pfv.PredefinedType = "PROVISIONFORVOID"
    else:
        pfv.ObjectType = "ProvisionForVoid"
    pfv.Description = f"{size_text(pen)} for {service.Name or service.is_a()[3:]} through {host.Name or host.is_a()[3:]}"
    container = ifcopenshell.util.element.get_container(service)
    if container is not None:
        ifcopenshell.api.run("spatial.assign_container", ms, relating_structure=container, products=[pfv])
    rep, solid = _void_rep(ms, ss, pen, _body_context(service))
    _see_through(ms, solid)
    ifcopenshell.api.run("geometry.assign_representation", ms, product=pfv, representation=rep)
    _void_place(ms, pfv, ss, pen)
    systems = ifcopenshell.util.system.get_element_systems(service)
    props = {"Shape": "Round" if pen.shape == "round" else "Rectangle", "Depth": pen.depth_m / ss,
             "System": (systems[0].Name if systems and systems[0].Name else service.is_a()[3:])}
    if pen.shape == "round":
        props["Diameter"] = pen.width_m / ss
    else:
        props.update(Width=pen.width_m / ss, Height=pen.height_m / ss)
    pset = ifcopenshell.api.run("pset.add_pset", ms, product=pfv, name="Pset_ProvisionForVoid")
    ifcopenshell.api.run("pset.edit_pset", ms, pset=pset, properties=props)
    mine = ifcopenshell.api.run("pset.add_pset", ms, product=pfv, name=PROVISION_PSET)
    ifcopenshell.api.run("pset.edit_pset", ms, pset=mine, properties={"Service": pen.service, "Host": pen.host})
    source = step_source(service)   # from STEP: the provision is written back as a part of the service's group
    if source:
        sp = ifcopenshell.api.run("pset.add_pset", ms, product=pfv, name=STEP_PSET)
        ifcopenshell.api.run("pset.edit_pset", ms, pset=sp,
                             properties={k: v for k, v in source.items() if k in ("Group", "Label", "Source")})
    pen.provision, pen.opening = pfv.GlobalId, None


def _cut_opening(scene: IfcScene, pen: Penetration, service, host) -> None:
    """The opening itself, in the host's model, voiding the host."""
    j = scene.index_of(pen.host)
    mh, sh = scene.models[j], scene.unit_scales[j]
    opening = ifcopenshell.api.run("root.create_entity", mh, ifc_class="IfcOpeningElement",
                                   name=f"Opening for {service.Name or service.is_a()[3:]}")
    if mh.schema != "IFC2X3":
        opening.PredefinedType = "OPENING"
    rep, _ = _void_rep(mh, sh, pen, _body_context(host))
    ifcopenshell.api.run("geometry.assign_representation", mh, product=opening, representation=rep)
    _void_place(mh, opening, sh, pen)
    ifcopenshell.api.run("feature.add_feature", mh, feature=opening, element=host)
    pen.opening = opening.GlobalId
    scene.refresh_bounds([pen.host])


# --------------------------------------------------------------------------------------------- seats (docs/edits.md)

SEAT_ABOVE_M = 0.05   # a seated element must stand at least this far above its support's top: what bears on it
SEAT_BELOW_M = 0.10   # and its foot reach no more than this below the support's bottom: it lands in the support,
                      # it does not pass it (a wall running down past a footing is the footing's to notch)
SEAT_MAX_SHARE = 0.5  # nor may the cut take more than this share of it: an element mostly inside its support is
                      # modelled in the wrong place, not seated
SEAT_JOINT_M = 0.001  # the recess clears the support by this all round: a bedding joint. Exactly flush faces are
                      # numerically fragile in the clash queries (Northbank's pit wall read as -500 mm after a flush seat)
SEAT_PSET = "ORCA_Seat"   # on the recess ORCA writes: the support it bears on


@dataclass
class Seat:
    element: str             # what is cut: it then bears on `support`
    support: str             # what it bears on
    top_m: float             # the support's top (world z): where the element now bears
    cut: list[list[float]]   # the cut's box, world metres ([min], [max]): the element inside the support's footprint,
                             # from its foot up to the support's top
    share: float             # of the element's own box
    footprint: list[list[float]]   # the support's footprint at its top (world x, y), the recess's outline
    recess: str | None = None      # the recess's GlobalId, once applied

    @property
    def size_m(self) -> list[float]:
        lo, hi = np.asarray(self.cut[0]), np.asarray(self.cut[1])
        return [round(float(v), 3) for v in hi - lo]


def _top_outline(scene: IfcScene, gid: str, top: float) -> tuple[list[list[float]], float]:
    """The outline of an element's top face (world x, y, in order), from its triangles: the boundary of the faces that
    look up at its top; and the element's volume. Raises Unsupported when it has none (a sloped or curved top)."""
    m = meshes(scene, [gid])[0]
    v = np.asarray(m["verts"], float).reshape(-1, 3)
    f = np.asarray(m["faces"], int).reshape(-1, 3)
    p0, p1, p2 = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    volume = abs(float(np.einsum("ij,ij->i", p0, np.cross(p1, p2)).sum()) / 6)
    n = np.cross(p1 - p0, p2 - p0)
    length = np.linalg.norm(n, axis=1)
    up = (length > 1e-12) & (n[:, 2] > 0.999 * np.maximum(length, 1e-12)) & (np.abs((p0[:, 2] + p1[:, 2] + p2[:, 2]) / 3 - top) < 0.002)
    if not up.any():
        raise Unsupported("its top is not one flat face to bear on")
    key = lambda i: tuple(np.round(v[i, :2], 4))   # noqa: E731 (vertices welded by plan position)
    count: dict[tuple, int] = {}
    for tri in f[up]:
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            e = tuple(sorted((key(a), key(b))))
            count[e] = count.get(e, 0) + 1
    edges = [e for e, k in count.items() if k == 1]
    nxt: dict[tuple, list[tuple]] = {}
    for a, b in edges:
        nxt.setdefault(a, []).append(b)
        nxt.setdefault(b, []).append(a)
    loops, seen = [], set()
    for start in nxt:
        if start in seen:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            choices = [q for q in nxt[cur] if q != prev and (q not in seen or (q == start and len(loop) > 2))]
            if not choices:
                break
            prev, cur = cur, choices[0]
            if cur == start:
                break
            loop.append(cur)
            seen.add(cur)
        if len(loop) >= 3:
            loops.append(loop)
    if not loops:
        raise Unsupported("its top face has no outline")
    area = lambda lp: abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(lp, lp[1:] + lp[:1]))) / 2  # noqa: E731
    outer = max(loops, key=area)
    # Drop points on a straight line (a tessellated face's interior edge ends): the outline's corners only.
    pts = [np.asarray(q, float) for q in outer]
    cross = lambda u, w: u[0] * w[1] - u[1] * w[0]  # noqa: E731
    keep = [q for i, q in enumerate(pts) if abs(cross(q - pts[i - 1], pts[(i + 1) % len(pts)] - q)) > 1e-7]
    return [[float(q[0]), float(q[1])] for q in (keep if len(keep) >= 3 else pts)], volume


def seat(scene: IfcScene, element: str, support: str) -> Seat:
    """How `element` would bear on `support`: it comes down into the support (its top stands above the support's top,
    its foot lands in it), and the part of it inside the support's footprint below the support's top is cut away, so
    what is left sits on the support's top. From the geometry alone: which kinds of element may be seated is the
    requirements' and Muse's call. Raises Unsupported, saying why, when it cannot bear on it that way."""
    b = scene.bounds()
    if element not in b or support not in b:
        raise Unsupported("it has no geometry to cut")
    e, s = np.asarray(b[element], float), np.asarray(b[support], float)
    lo, hi = np.maximum(e[0], s[0]), np.minimum(e[1], s[1])
    if np.any(hi - lo <= 0.001):
        raise Unsupported("it does not run into the other element")
    top, name = float(s[1][2]), scene.element(support).name or scene.entity(support).is_a()[3:]
    for rel in getattr(scene.entity(element), "HasOpenings", None) or ():   # its box still reaches in: ask the recess
        if (ifcopenshell.util.element.get_psets(rel.RelatedOpeningElement).get(SEAT_PSET) or {}).get("Support") == support:
            raise Unsupported(f"it already bears on {name}")
    if e[1][2] < top + SEAT_ABOVE_M:
        raise Unsupported(f"it does not stand above {name}'s top (z {top:.3f} m), so nothing of it would bear on it")
    if e[0][2] >= top - 0.001:
        raise Unsupported(f"its foot is not below {name}'s top: it already bears on it")
    if e[0][2] < s[0][2] - SEAT_BELOW_M:
        raise Unsupported(f"it runs {(s[0][2] - e[0][2]) * 1000:.0f} mm below {name}: it passes the element rather than "
                          "landing in it")
    outline, volume = _top_outline(scene, support, top)
    xy = np.asarray(outline)
    # The support must be a straight prism under its top (as wide all the way down): then the cut, its footprint from
    # the foot up to its top, leaves nothing of the element inside it, by construction.
    area = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(outline, outline[1:] + outline[:1]))) / 2
    prism = area * (top - s[0][2])
    if prism <= 0 or abs(volume - prism) > 0.01 * prism:
        raise Unsupported(f"{name} is not as wide below its top as at it, so a seat on its top would leave part of the "
                          "element inside it")
    cut_lo = np.array([max(e[0][0], xy[:, 0].min()), max(e[0][1], xy[:, 1].min()), e[0][2]])
    cut_hi = np.array([min(e[1][0], xy[:, 0].max()), min(e[1][1], xy[:, 1].max()), top])
    if np.any(cut_hi - cut_lo <= 0.001):
        raise Unsupported(f"it does not stand over {name}'s top")
    share = float(np.prod(cut_hi - cut_lo) / max(np.prod(e[1] - e[0]), 1e-12))
    if share > SEAT_MAX_SHARE:
        raise Unsupported(f"the cut would take {share:.0%} of it: it is mostly inside {name}, which is not a seat")
    return Seat(element, support, round(top, 4), [np.round(cut_lo, 4).tolist(), np.round(cut_hi, 4).tolist()],
                round(share, 3), outline)


def seat_summary(scene: IfcScene, st: Seat) -> str:
    """"seat 'Upstand U1' on 'Base B2': its foot cut where it is inside (0.50 x 0.20 x 0.65 m), so it bears on the top"."""
    w, d, h = st.size_m
    return (f"seat '{scene.element(st.element).name}' on '{scene.element(st.support).name}': its foot cut where it is "
            f"inside ({w:.2f} x {d:.2f} x {h:.2f} m), so it bears on the top")


def _grown(outline: list[list[float]], by: float) -> list[list[float]]:
    """A closed outline (x, y) moved outward by `by` square to each edge (each corner along its mitre)."""
    q = np.asarray(outline, float)
    ccw = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(q, np.roll(q, -1, axis=0))) > 0
    out = []
    for k in range(len(q)):
        normals = []
        for a, b in ((q[k - 1], q[k]), (q[k], q[(k + 1) % len(q)])):
            d = (b - a) / max(np.linalg.norm(b - a), 1e-12)
            normals.append(np.array([d[1], -d[0]]) if ccw else np.array([-d[1], d[0]]))
        mitre = normals[0] + normals[1]
        mitre /= max(np.linalg.norm(mitre), 1e-12)
        out.append((q[k] + mitre * by / max(float(np.dot(mitre, normals[0])), 0.2)).tolist())
    return out


def _footprint_profile(m, sc: float, outline: list[list[float]]):
    """A footprint (world x, y) as a profile and where its placement goes (world x, y and the profile's X direction):
    a rectangle centred in its own placement when it is one (what most supports are; STEP export cuts it as a prism,
    as it cuts a penetration's opening), else the outline as a polyline in a placement at the world origin."""
    q = np.asarray(outline, float)
    if len(q) == 4:
        e = [q[(k + 1) % 4] - q[k] for k in range(4)]
        if all(abs(float(np.dot(e[k], e[(k + 1) % 4]))) < 1e-6 * max(np.linalg.norm(e[k]) * np.linalg.norm(e[(k + 1) % 4]), 1e-12)
               for k in range(4)):
            x = e[0] / np.linalg.norm(e[0])
            at = m.createIfcAxis2Placement2D(_point(m, (0.0, 0.0)), None)
            profile = m.createIfcRectangleProfileDef("AREA", None, at, float(np.linalg.norm(e[0]) / sc),
                                                     float(np.linalg.norm(e[1]) / sc))
            return profile, q.mean(axis=0), x
    pts = [_point(m, (x / sc, y / sc)) for x, y in outline]
    return m.createIfcArbitraryClosedProfileDef("AREA", None, m.createIfcPolyline([*pts, pts[0]])), np.zeros(2), np.array([1.0, 0.0])


def apply_seat(scene: IfcScene, st: Seat) -> Seat:
    """Seat the element: a recess (an IfcOpeningElement, RECESS, voiding it) shaped as the support's footprint, from
    below the element's foot up to the support's top. The element keeps its body and GlobalId; anything that draws
    or checks it subtracts the recess. Edits the element's model in place; wrap in `trial` to try it and undo."""
    i = scene.index_of(st.element)
    m, sc = scene.models[i], scene.unit_scales[i]
    element, support = scene.entity(st.element), scene.entity(st.support)
    recess = ifcopenshell.api.run("root.create_entity", m, ifc_class="IfcOpeningElement",
                                  name=f"Seat on {support.Name or support.is_a()[3:]}")
    if m.schema != "IFC2X3":
        recess.PredefinedType = "RECESS"
    else:
        recess.ObjectType = "Recess"
    bottom = st.cut[0][2] - 0.01   # past the foot, so no sliver of it is left under the support
    profile, centre, x = _footprint_profile(m, sc, _grown(st.footprint, SEAT_JOINT_M))
    solid = m.createIfcExtrudedAreaSolid(profile, m.createIfcAxis2Placement3D(_point(m, (0.0, 0.0, 0.0)), None, None),
                                         m.createIfcDirection((0.0, 0.0, 1.0)),
                                         float((st.top_m + SEAT_JOINT_M - bottom) / sc))
    rep = m.createIfcShapeRepresentation(_body_context(element), "Body", "SweptSolid", [solid])
    ifcopenshell.api.run("geometry.assign_representation", m, product=recess, representation=rep)
    at = np.eye(4)
    at[:3, 0], at[:3, 1] = [x[0], x[1], 0.0], [-x[1], x[0], 0.0]
    at[:3, 3] = [centre[0] / sc, centre[1] / sc, bottom / sc]
    ifcopenshell.api.run("geometry.edit_object_placement", m, product=recess, matrix=at, is_si=False)
    ifcopenshell.api.run("feature.add_feature", m, feature=recess, element=element)
    pset = ifcopenshell.api.run("pset.add_pset", m, product=recess, name=SEAT_PSET)
    ifcopenshell.api.run("pset.edit_pset", m, pset=pset, properties={"Support": st.support, "Top": st.top_m / sc})
    st.recess = recess.GlobalId
    scene.refresh_bounds([st.element])
    return st


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


@contextmanager
def kept_files(scene: IfcScene, indexes: set[int]):
    """Edit several files of a scene for good, all or nothing: an error part way undoes every edit made so far (cached
    boxes, the files marked edited and the scene's revision included) and is raised again. Inside another
    `kept_files`, a file the outer one holds is left to it (the outer one undoes it). Never nest it inside `trial` or
    `trial_files`."""
    before = dict(scene.bounds())
    marks = (set(scene._edited), scene.revision, list(scene.history))
    models = [scene.models[i] for i in sorted(indexes) if scene.models[i].transaction is None]
    for m in models:
        m.begin_transaction()
    try:
        yield
    except BaseException:
        for m in models:
            m.end_transaction()
            m.undo()
        scene._bounds = before
        scene._edited, scene.revision, scene.history = marks
        raise
    for m in models:
        m.end_transaction()


@contextmanager
def scratch(scene: IfcScene, indexes: set[int]):
    """Edits that never stay (a move there and back): inside a transaction that is always undone, so they do not
    break the undo of kept edits (an untracked placement change leaves the history pointing at entities that are
    gone). A file already holding a transaction is left to it. Boxes are put back."""
    before = dict(scene.bounds())
    models = [scene.models[i] for i in sorted(indexes) if scene.models[i].transaction is None]
    for m in models:
        m.begin_transaction()
    try:
        yield
    finally:
        for m in models:
            m.end_transaction()
            m.undo()
        scene._bounds = before


@contextmanager
def trial_files(scene: IfcScene, indexes: set[int]):
    """Edit several files of a scene (a plan, or one fix that changes two models), then undo every edit, cached boxes
    included. Never nest it inside `trial`: a file holds one transaction at a time."""
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


@dataclass
class Stretched:
    element: str
    face: str             # "start" / "end" (a cap) or "side" (a rectangular segment's side, taken end-on)
    by_m: float           # how much longer (+) or shorter (-) it got across that face
    size_m: float         # its length (a cap) or its size across that side, after


def stretch(scene: IfcScene, global_id: str, face: str, by_m: float, normal=None, clipped: bool = False,
            item: int | None = None, least_m: float = MIN_PIECE_M, unique: bool = False,
            sections: bool = False) -> Stretched:
    """Make a straight segment longer (+) or shorter (-) by moving one face outward by `by_m` metres: its "start" or
    "end" cap (the extrusion's depth, and its start when the start moves), or, for a rectangular one, a "side" whose
    outward world `normal` is given (the profile grows to that side: a ladder riser a bend sits on). Ports at that face
    move with it without turning. Edits the model in place; wrap in a trial to undo. Hand edits (manual.py) name the
    `item` of a body of several solids, keep `least_m` (5 mm), give a shared body its own copy (`unique`), and may
    push an I, U, C, L or T section's outer side (`sections`: its overall width or depth, the opposite side held)."""
    element = scene.entity(global_id)
    k = item
    i = scene.index_of(global_id)
    model = scene.models[i]
    if unique:
        make_unique(model, element)
    i, place, item, origin, d, px, py = _frames(scene, element, clipped, k)
    s = scene.unit_scales[i]
    by_m = float(by_m)
    if not np.isfinite(by_m):
        raise Unsupported("a stretch must be a finite length")
    body, _ = _body(element, clipped, k)
    if shared(model, element, body, item):   # another element's shape would change too
        raise Unsupported("its body is shared with other elements")
    inv = np.linalg.inv(place)
    if face in ("start", "end"):
        size = item.Depth * s + by_m
        if size < least_m - 1e-9:
            raise Unsupported(f"it would be {size * 1000:.0f} mm long (at least {least_m * 1000:.0f} mm stays)")
        out = -d if face == "start" else d
        old_centre = (origin if face == "start" else origin + d * item.Depth) * s
        if face == "start":   # the start moves out: a new place for the extrusion (placements can be shared)
            local = ifcopenshell.util.placement.get_axis2placement(item.Position)
            local[:3, 3] = (inv @ np.append(origin - d * (by_m / s), 1.0))[:3]
            item.Position = model.createIfcAxis2Placement3D(
                _point(model, local[:3, 3]), _dir(model, local[:3, 2]), _dir(model, local[:3, 0]))
        item.Depth = float(item.Depth + by_m / s)
    elif face == "side":
        prof = item.SweptArea
        dims_of = {"IfcRectangleProfileDef": ("XDim", "YDim"), **(SECTION_DIMS if sections else {})}
        if prof.is_a() not in dims_of:
            raise Unsupported("only a rectangular section grows sideways")
        xa, ya = dims_of[prof.is_a()]
        # A rectangle may sit off the solid's axis (a box drawn from its corner) and be turned in its plane: its own
        # axes are the solid's turned by its RefDirection.
        loc = np.asarray(prof.Position.Location.Coordinates[:2], float) if prof.Position is not None else np.zeros(2)
        ref = (np.asarray(prof.Position.RefDirection.DirectionRatios[:2], float)
               if prof.Position is not None and prof.Position.RefDirection is not None else np.array([1.0, 0.0]))
        ref = ref / np.linalg.norm(ref)
        ax = px * ref[0] + py * ref[1]
        ay = -px * ref[1] + py * ref[0]
        out = np.asarray(normal, float)
        out /= np.linalg.norm(out)
        if abs(out @ ax) > 0.999:
            attr = xa
        elif abs(out @ ay) > 0.999:
            attr = ya
        else:
            raise Unsupported("that side is not square to the segment's profile")
        across = _section_dim(prof, attr)
        size = across * s + by_m
        if size < least_m - 1e-9:
            raise Unsupported(f"it would be {size * 1000:.0f} mm across (at least {least_m * 1000:.0f} mm stays)")
        inner = _section_least(prof, attr)
        if size <= inner * s + 1e-6:
            raise Unsupported(f"its {'flanges' if attr in ('OverallDepth', 'Depth') else 'web'} would not fit: at least "
                              f"{inner * s * 1000:.0f} mm stays")
        mid = (origin + px * loc[0] + py * loc[1]) * s + d * (item.Depth * s / 2)
        old_centre = mid + out * (across * s / 2)
        if prof.is_a() == "IfcRectangleProfileDef":
            dims = {"XDim": prof.XDim, "YDim": prof.YDim, attr: float(size / s)}
            item.SweptArea = model.createIfcRectangleProfileDef(prof.ProfileType, prof.ProfileName, prof.Position,
                                                                dims["XDim"], dims["YDim"])
        else:   # a copy (profiles are shared, often by every beam of a size), the one size changed
            new = ifcopenshell.util.element.copy(model, prof)
            if prof.is_a("IfcLShapeProfileDef") and new.Width is None:
                new.Width = new.Depth
            setattr(new, attr, float(size / s))
            item.SweptArea = new
        local = ifcopenshell.util.placement.get_axis2placement(item.Position)
        local[:3, 3] = (inv @ np.append(origin + out * (by_m / s / 2), 1.0))[:3]
        item.Position = model.createIfcAxis2Placement3D(
            _point(model, local[:3, 3]), _dir(model, local[:3, 2]), _dir(model, local[:3, 0]))
    else:
        raise Unsupported(f"no face called {face!r}")
    for port in ifcopenshell.util.system.get_ports(element):   # ports at that face go with it, turned as they were
        if port.ObjectPlacement is None:
            continue
        m = scene.placement(port.GlobalId)
        if np.linalg.norm(m[:3, 3] - old_centre) <= 0.002:
            m[:3, 3] += out * by_m
            ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=m, is_si=True)
    scene.refresh_bounds([global_id])
    return Stretched(global_id, face, by_m, float(size))


def meshes(scene: IfcScene, global_ids: list[str], render: bool = False) -> list[dict]:
    """World-space triangles (metres, Z up) for previewing new or changed elements in the browser.

    `render`: for drawing them into the viewer's own batches after a fix is kept, instead of an overlay: unwelded
    (IfcOpenShell 0.9 welds by default, which smooths normals across sharp edges), with normals, the first style's
    colour and opacity ([r, g, b, a], or None) and the element's file."""
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    if render:
        settings.set("weld-vertices", False)
        # No per-class default colours: an unstyled element must stay as the page drew it (web-ifc: white), not turn
        # IfcOpenShell's grey or brown, or see-through for a window, when a fix is kept.
        settings.set("apply-default-materials", False)
    out = []
    for gid in global_ids:
        shape = ifcopenshell.geom.create_shape(settings, scene.entity(gid))
        verts = np.round(np.asarray(shape.geometry.verts, dtype=float), 4)
        item = {"global_id": gid, "verts": verts.tolist(), "faces": list(shape.geometry.faces)}
        if render:
            item["normals"] = np.round(np.asarray(shape.geometry.normals, dtype=float), 3).tolist()
            styles = shape.geometry.materials
            if styles:
                d, t = styles[0].diffuse, styles[0].transparency
                alpha = 1.0 - (float(t) if np.isfinite(t) else 0.0)
                item["color"] = [round(float(c), 4) for c in (d.r(), d.g(), d.b(), alpha)]
            else:
                item["color"] = None
            item["file"] = scene.index_of(gid)
        out.append(item)
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


def _hits(origins: np.ndarray, d: np.ndarray, tris: np.ndarray, length: float | None = None) -> np.ndarray:
    """Which rays (origins + t·d, t > 0, and t < `length` when given) hit any triangle (Möller–Trumbore, vectorised
    over rays and triangles)."""
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
    near = (t < length) if length is not None else True
    return np.any((u >= 0) & (u <= 1) & (v >= 0) & (u + v <= 1) & (t > 1e-9) & near, axis=1)


def _first_hit(origins: np.ndarray, d: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """How far each ray (origins + t·d) goes before it hits a triangle (inf when it hits none)."""
    v0, e1, e2 = tris[:, 0], tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    p = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-12
    v0, e1, e2, p, det = v0[ok], e1[ok], e2[ok], p[ok], det[ok]
    inv = 1.0 / det
    s = origins[:, None, :] - v0[None]
    u = np.einsum("rtk,tk->rt", s, p) * inv
    q = np.cross(s, e1[None])
    v = (q @ d) * inv
    t = np.einsum("rtk,tk->rt", q, e2) * inv
    t = np.where((u >= 0) & (u <= 1) & (v >= 0) & (u + v <= 1) & (t > 1e-9), t, np.inf)
    return t.min(axis=1) if t.shape[1] else np.full(len(origins), np.inf)


FREE_BANDS_MAX_TRIS = 200_000   # past this many triangles in the stretch, the room beside an obstacle is not told
def _kernel(p) -> str:
    """The geometry kernel to triangulate `p` with: CGAL for a body of meshes only (scene.meshes_only), else
    OpenCASCADE, so curved and cut shapes are as before."""
    return MESH_KERNEL if meshes_only(p) else "opencascade"


def free_bands(scene: IfcScene, run_gid: str, obstacles: list[str], axis: str = "side", clearance_m: float = DEFAULT_CLEARANCE_M,
               reach_m: float = 1.0, step_m: float = 0.01) -> list[dict]:
    """Offsets of a straight segment, on its own "up" or "side" axis (`run_frame`), at which its profile (with
    `clearance_m` all round) passes the stretch where `obstacles` sit along it without touching anything there: the
    room a route has beside or above them. Rays run along the segment through that stretch, round the profile's
    outline and at its centre, against every physical element nearby (not only the obstacles: a fence beside a column
    counts), and only bands the run can reach from its line at both ends of the stretch count. Returns
    [{"from_m", "to_m"}] offset bands (of the centreline), not counting where it is now."""
    run = run_of(scene, run_gid)
    start, d = np.asarray(run.start), np.asarray(run.direction)
    up, side = run_frame(d)
    a, c = (side, up) if axis == "side" else (up, side)
    half_a = (run.width_m if axis == "side" else run.depth_m) / 2 + clearance_m
    half_c = (run.depth_m if axis == "side" else run.width_m) / 2 + clearance_m
    boxes = scene.bounds()
    spans = []
    for o in obstacles:
        if o in boxes:
            corners = np.array([[x, y, z] for x in boxes[o][:, 0] for y in boxes[o][:, 1] for z in boxes[o][:, 2]])
            along = (corners - start) @ d
            spans.append((max(along.min(), 0.0), min(along.max(), run.length_m)))
    if not spans:
        return []
    lo, hi = min(x for x, _ in spans) - 0.05, max(y for _, y in spans) + 0.05
    # Everything physical near that stretch, except the segment and what it is joined to.
    own = {run_gid, *scene.element(run_gid).connected}
    corridor = np.array([start + d * t + a * ra + c * rc for t in (lo, hi) for ra in (-reach_m - half_a, reach_m + half_a)
                         for rc in (-half_c, half_c)])
    cmin, cmax = corridor.min(axis=0), corridor.max(axis=0)
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    tris, solids = [], []
    for p in scene.products():
        g = p.GlobalId
        if g in own or g not in boxes or (boxes[g][1] < cmin).any() or (boxes[g][0] > cmax).any():
            continue
        solids.append(boxes[g])
        try:
            shape = ifcopenshell.geom.create_shape(settings, p, geometry_library=_kernel(p))
        except RuntimeError:
            continue
        verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
        tris.append(verts[np.asarray(shape.geometry.faces).reshape(-1, 3)])
    if not tris:
        return []
    tris = np.concatenate(tris)
    # Only triangles that reach the stretch along the run, and the band the rays sweep across it, can be hit. A dense
    # mesh nearby (a meshed motor, a detailed fitting) is cut down to the part that matters, or, past a budget, the
    # room is not told at all: this runs while the scene is locked.
    rel = tris - start
    tt, ta, tc = rel @ d, rel @ a, rel @ c
    eps = 1e-6   # a triangle touching a ray's edge still counts, as it does in the ray test
    keep = ((tt.max(1) >= lo - eps) & (tt.min(1) <= hi + eps) & (tc.max(1) >= -half_c - eps) & (tc.min(1) <= half_c + eps)
            & (ta.max(1) >= -reach_m - half_a - eps) & (ta.min(1) <= reach_m + half_a + eps))
    tris, ta, tc = tris[keep], ta[keep], tc[keep]
    if len(tris) > FREE_BANDS_MAX_TRIS:
        return []
    # Each ray runs along the run at one point of the cross-section (a, c): it can only meet triangles whose own
    # cross-section span covers that point. Bin the triangles on a grid there, so a ray tests only its own cell.
    a0, c0, cell = -reach_m - half_a - 2 * eps, -half_c - 2 * eps, 0.03
    na = int(np.ceil((2 * (reach_m + half_a) + 4 * eps) / cell)) + 1
    nc = int(np.ceil((2 * half_c + 4 * eps) / cell)) + 1
    ia0 = np.clip(np.floor((ta.min(1) - eps - a0) / cell).astype(int), 0, na - 1)
    ia1 = np.clip(np.floor((ta.max(1) + eps - a0) / cell).astype(int), 0, na - 1)
    ic0 = np.clip(np.floor((tc.min(1) - eps - c0) / cell).astype(int), 0, nc - 1)
    ic1 = np.clip(np.floor((tc.max(1) + eps - c0) / cell).astype(int), 0, nc - 1)
    wc = ic1 - ic0 + 1
    count = (ia1 - ia0 + 1) * wc
    owner = np.repeat(np.arange(len(tris)), count)
    k = np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count)
    cells = (np.repeat(ia0, count) + k // np.repeat(wc, count)) * nc + np.repeat(ic0, count) + k % np.repeat(wc, count)
    order = np.argsort(cells, kind="stable")
    cells, owner = cells[order], owner[order]
    solids = np.array(solids) if solids else np.zeros((0, 2, 3))
    offsets = np.arange(-reach_m, reach_m + 1e-9, step_m)
    # The profile's outline every 30 mm, and its centre: anything that crosses the stretch crosses the outline (a 100 mm
    # post between the corners of a 400 mm duct would slip past corner rays alone). The centre goes first: one hit is
    # enough to rule an offset out.
    along_a = np.linspace(-half_a, half_a, max(2, int(np.ceil(2 * half_a / 0.03)) + 1))
    along_c = np.linspace(-half_c, half_c, max(2, int(np.ceil(2 * half_c / 0.03)) + 1))
    samples = np.array([(0.0, 0.0)] + [(sa, sc) for sa in along_a for sc in (-half_c, half_c)]
                       + [(sa, sc) for sc in along_c[1:-1] for sa in (-half_a, half_a)])
    base = start + d * lo
    free = np.ones(len(offsets), dtype=bool)
    for k, v in enumerate(offsets):
        ray_a, ray_c = v + samples[:, 0], samples[:, 1]
        origins = base + np.outer(ray_a, a) + np.outer(ray_c, c)
        # A ray wholly inside a solid (along a wall) crosses none of its faces: its middle inside an element's box counts.
        middles = origins + d * (hi - lo) / 2
        if len(solids) and ((middles[:, None, :] > solids[None, :, 0]) & (middles[:, None, :] < solids[None, :, 1])).all(2).any():
            free[k] = False
            continue
        ray_cells = (np.clip(np.floor((ray_a - a0) / cell).astype(int), 0, na - 1) * nc
                     + np.clip(np.floor((ray_c - c0) / cell).astype(int), 0, nc - 1))
        first = np.searchsorted(cells, ray_cells, side="left")
        last = np.searchsorted(cells, ray_cells, side="right")
        for r in range(len(samples)):
            if last[r] > first[r] and _hits(origins[r:r + 1], d, tris[owner[first[r]:last[r]]], hi - lo).any():
                free[k] = False
                break
    # And the route must get there: from the line, square to it, at both ends of the stretch, nothing in the way.
    for sign in (1.0, -1.0):
        starts = np.array([start + d * t + c * sc for t in (lo, hi) for sc in (-half_c, 0.0, half_c)])
        room = (_first_hit(starts, a * sign, tris).min() if len(tris) else np.inf) - half_a
        for bmin, bmax in solids:   # a solid the line itself starts in leaves no room that way
            if ((starts > bmin) & (starts < bmax)).all(axis=1).any():
                room = 0.0
        free &= ~((np.sign(offsets) == sign) & (np.abs(offsets) > room))
    out, i = [], 0
    while i < len(offsets):
        if free[i]:
            j = i
            while j + 1 < len(offsets) and free[j + 1]:
                j += 1
            if not (offsets[i] <= 0 <= offsets[j]):
                out.append({"from_m": round(float(offsets[i]), 3), "to_m": round(float(offsets[j]), 3)})
            i = j + 1
        else:
            i += 1
    return out


def passages(scene: IfcScene, run_gid: str, obstacle_gid: str, clearance_m: float = DEFAULT_CLEARANCE_M,
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


# ----------------------------------------------------------------------------------------- hand edits (manual.py)

MIN_EDGE_M = 0.01   # an outline edge left shorter than this by moving its neighbour is refused


def shared(model, element, body, item) -> bool:
    """Whether editing this solid would change another element's shape too (a shared item, body or representation)."""
    return max(len([x for x in model.get_inverse(item) if x.is_a("IfcShapeRepresentation") or x.is_a("IfcBooleanResult")]),
               len([x for x in model.get_inverse(body) if x.is_a("IfcProductRepresentation") or x.is_a("IfcRepresentationMap")]),
               len([x for x in model.get_inverse(element.Representation) if x.is_a("IfcProduct")])) > 1


def make_unique(model, element) -> bool:
    """Give the element its own copy of a shape other elements share (copy_deep, contexts kept), its styles copied
    onto the new solids so it keeps its colour. Returns whether it copied. A body drawn from its type (a mapped item)
    becomes the element's own copy of the type's shape where its map puts it (`unmap`): the type, and every other
    element of it, stay as they were (docs/editing-parity.md)."""
    rep = element.Representation
    bodies = [r for r in (rep.Representations if rep else []) if r.RepresentationIdentifier == "Body"]
    if not bodies:
        return False
    if any(it.is_a("IfcMappedItem") for it in bodies[0].Items):
        unmap(model, element)
        return True
    if not any(shared(model, element, bodies[0], it) for it in bodies[0].Items):
        return False
    import ifcopenshell.util.element as ue
    new = ue.copy_deep(model, rep, exclude=["IfcGeometricRepresentationContext"])
    for old_r, new_r in zip(rep.Representations, new.Representations):
        for old_i, new_i in zip(old_r.Items, new_r.Items):
            for st in [x for x in model.get_inverse(old_i) if x.is_a("IfcStyledItem")]:
                model.createIfcStyledItem(new_i, st.Styles, st.Name)
    element.Representation = new
    return True


def mapping(item) -> np.ndarray:
    """Where a mapped item puts its type's shape in the element's frame (file units): its target after its origin.
    Refused when the target scales it (the copy would need its sizes scaled too)."""
    target = item.MappingTarget
    if target is not None and (not target.is_a("IfcCartesianTransformationOperator3D")
                               or abs(float(target.Scale if target.Scale is not None else 1.0) - 1.0) > 1e-9
                               or target.is_a("IfcCartesianTransformationOperator3DnonUniform")):
        raise Unsupported("its type's shape is scaled where it is placed: ORCA cannot copy it for this element alone")
    return np.asarray(ifcopenshell.util.placement.get_mappeditem_transformation(item), float)


def unmap(model, element) -> None:
    """Replace the mapped items of the element's Body by its own copy of what they draw, where they draw it (`mapping`
    composed into each solid's position, a mesh's points or a brep's points), styles copied: the element keeps its type,
    and the type keeps its shape. Refused for a solid drawn some other way."""
    import ifcopenshell.util.element as ue
    rep = element.Representation
    body = next(r for r in rep.Representations if r.RepresentationIdentifier == "Body")
    items, kind = [], body.RepresentationType
    for it in body.Items:
        if not it.is_a("IfcMappedItem"):
            items.append(it)
            continue
        m = mapping(it)
        source = it.MappingSource.MappedRepresentation
        kind = source.RepresentationType if kind == "MappedRepresentation" else kind
        for inner in source.Items:
            copy = ue.copy_deep(model, inner, exclude=["IfcGeometricRepresentationContext"])
            _move_item(model, copy, m)
            for st in [x for x in model.get_inverse(inner) if x.is_a("IfcStyledItem")]:
                model.createIfcStyledItem(copy, st.Styles, st.Name)
            items.append(copy)
    new_body = model.createIfcShapeRepresentation(body.ContextOfItems, "Body",
                                                  kind if kind != "MappedRepresentation" else "SweptSolid", items)
    element.Representation = model.createIfcProductDefinitionShape(
        rep.Name, rep.Description, [new_body if r == body else r for r in rep.Representations])
    if not model.get_inverse(rep):   # the old shape and its mapped body go; the type's map, used by its type, stays
        ue.remove_deep2(model, rep)


def _placement(model, m: np.ndarray):
    return model.createIfcAxis2Placement3D(model.createIfcCartesianPoint(tuple(float(x) for x in m[:3, 3])),
                                           _dir(model, m[:3, 2]), _dir(model, m[:3, 0]))


def _move_item(model, item, m: np.ndarray) -> None:
    """Move a solid (its own copy) by the 4 x 4 `m`, in file units."""
    if item.is_a("IfcBooleanResult"):
        _move_item(model, item.FirstOperand, m)
        _move_item(model, item.SecondOperand, m)
    elif item.is_a("IfcSweptAreaSolid") or item.is_a("IfcCsgPrimitive3D"):
        old = (ifcopenshell.util.placement.get_axis2placement(item.Position) if item.Position is not None else np.eye(4))
        item.Position = _placement(model, m @ old)
    elif item.is_a("IfcHalfSpaceSolid"):
        plane = item.BaseSurface
        plane.Position = _placement(model, m @ ifcopenshell.util.placement.get_axis2placement(plane.Position))
        if item.is_a("IfcPolygonalBoundedHalfSpace"):
            item.Position = _placement(model, m @ ifcopenshell.util.placement.get_axis2placement(item.Position))
    elif item.is_a("IfcTessellatedFaceSet"):
        pts = np.asarray(item.Coordinates.CoordList, float)
        item.Coordinates.CoordList = [tuple(float(x) for x in p) for p in (pts @ m[:3, :3].T + m[:3, 3])]
        if getattr(item, "Normals", None) is not None:
            item.Normals = None
    elif item.is_a("IfcFacetedBrep") or item.is_a("IfcShellBasedSurfaceModel"):
        for p in {e for e in model.traverse(item) if e.is_a("IfcCartesianPoint")}:
            p.Coordinates = tuple(float(x) for x in m[:3, :3] @ np.asarray(p.Coordinates, float) + m[:3, 3])
    else:
        raise Unsupported(f"its type's shape is drawn as {item.is_a()}: ORCA cannot copy it for this element alone")


# ----------------------------------------------------------------------------------------------------- join


@dataclass
class JoinPlan:
    """How two straight segments' nearest ends meet (metres, world): `line` (A's end stretched `stretch_a` to B's) or
    `bend` (both brought to where their axes meet, less `radius`, and a 90° bend fitting between)."""
    kind: str
    a: str
    b: str
    end_a: str              # "start" or "end": the cap of A that moves
    end_b: str
    stretch_a: float
    stretch_b: float
    radius: float = 0.0
    corner: list[float] | None = None


def _free_end_port(scene: IfcScene, element, point):
    """The port at a segment's end (within 5 mm of `point`, world metres): refused when it is already joined."""
    near = [p for p in ifcopenshell.util.system.get_ports(element) if p.ObjectPlacement is not None
            and np.linalg.norm(scene.placement(p.GlobalId)[:3, 3] - point) <= 0.005]
    if any(ifcopenshell.util.system.get_connected_port(p) is not None for p in near):
        raise Unsupported(f"its end at {', '.join(f'{c:.2f}' for c in point)} is already joined: disconnect it first")
    return near[0] if near else None


def _section_across(scene: IfcScene, gid: str, side) -> tuple[float, float, bool]:
    """A segment's section as (across the plane `side` is square to, in it, round), metres."""
    e = scene.entity(gid)
    _, _, item, _, _, px, py = _frames(scene, e)
    s = scene.unit_scales[scene.index_of(gid)]
    sx, sy = _profile_size(item.SweptArea)
    round_ = item.SweptArea.is_a("IfcCircleProfileDef")
    if round_ or abs(px @ side) > 0.999:
        return sx * s, sy * s, round_
    if abs(py @ side) > 0.999:
        return sy * s, sx * s, round_
    raise Unsupported("its section is turned to the bend: join it in line, or turn it first")


def join_plan(scene: IfcScene, a_gid: str, b_gid: str) -> JoinPlan:
    """How the nearest free ends of two straight segments meet, without editing anything (see `JoinPlan`)."""
    if a_gid == b_gid:
        raise Unsupported("join it to another segment")
    if FITTING_CLASS.get(scene.entity(a_gid).is_a()) != FITTING_CLASS.get(scene.entity(b_gid).is_a()):
        raise Unsupported("join segments of one kind (a duct to a duct, a pipe to a pipe)")
    ra, rb = run_of(scene, a_gid), run_of(scene, b_gid)
    da, db = np.asarray(ra.direction, float), np.asarray(rb.direction, float)
    ends_a = {"start": (np.asarray(ra.start, float), -da), "end": (np.asarray(ra.end, float), da)}
    ends_b = {"start": (np.asarray(rb.start, float), -db), "end": (np.asarray(rb.end, float), db)}
    ea, eb = min(((x, y) for x in ends_a for y in ends_b),
                 key=lambda k: float(np.linalg.norm(ends_a[k[0]][0] - ends_b[k[1]][0])))
    (pa, ta), (pb, tb) = ends_a[ea], ends_b[eb]
    _free_end_port(scene, scene.entity(a_gid), pa)
    _free_end_port(scene, scene.entity(b_gid), pb)
    cos = float(ta @ tb)
    if cos < -np.cos(np.radians(1)):     # facing each other: one line?
        gap = float((pb - pa) @ ta)
        if np.linalg.norm((pb - pa) - ta * gap) > 0.005:
            raise Unsupported("they are not on one line: offset one first, or join them square with a bend")
        if gap < -0.001:
            raise Unsupported("their ends overlap: shorten one first")
        sa, sb = run_of(scene, a_gid), run_of(scene, b_gid)
        if abs(sa.width_m - sb.width_m) > 0.001 or abs(sa.depth_m - sb.depth_m) > 0.001:
            raise Unsupported("they are not the same size: a transition is needed between them")
        return JoinPlan("line", a_gid, b_gid, ea, eb, gap, 0.0)
    if cos > np.cos(np.radians(1)):
        raise Unsupported("their ends point the same way: they run side by side, so offset one onto the other's line")
    if abs(cos) > np.sin(np.radians(1)):
        raise Unsupported("join ends in line or square to each other: other angles are not in this build")
    # Square: where the two axes meet (closest points), within 5 mm of each other to be one plane.
    w = pa - pb
    m = np.array([[ta @ ta, -(ta @ tb)], [ta @ tb, -(tb @ tb)]])
    s_, t_ = np.linalg.solve(m, [-(w @ ta), -(w @ tb)])
    xa, xb = pa + ta * s_, pb + tb * t_
    if np.linalg.norm(xa - xb) > 0.005:
        raise Unsupported("their axes do not meet: they are not in one plane")
    side = np.cross(ta, -tb)
    side /= np.linalg.norm(side)
    wa, ha, round_a = _section_across(scene, a_gid, side)
    wb, hb, _ = _section_across(scene, b_gid, side)
    if abs(wa - wb) > 0.001 or abs(ha - hb) > 0.001:
        raise Unsupported("they are not the same size: a transition is needed between them")
    radius = ha
    if s_ - radius < -0.001 or t_ - radius < -0.001:
        raise Unsupported(f"an end runs past the corner or within a bend's radius ({radius * 1000:.0f} mm) of it: "
                          "pull it back first")
    for gid, by in ((a_gid, s_ - radius), (b_gid, t_ - radius)):
        if run_of(scene, gid).length_m + by < MIN_PIECE_M:
            raise Unsupported(f"a piece would be under {MIN_PIECE_M * 1000:.0f} mm")
    return JoinPlan("bend", a_gid, b_gid, ea, eb, float(s_ - radius), float(t_ - radius), float(radius),
                    ((xa + xb) / 2).tolist())


def join_segments(scene: IfcScene, plan: JoinPlan) -> list[str]:
    """Make a `join_plan`: stretch the ends, add the bend, connect the ports. Returns the bend's GlobalId, if any."""
    a, b = scene.entity(plan.a), scene.entity(plan.b)
    model = scene.models[scene.index_of(plan.a)]
    s = scene.unit_scales[scene.index_of(plan.a)]
    if abs(plan.stretch_a) > 1e-6:
        stretch(scene, plan.a, plan.end_a, plan.stretch_a, unique=True)
    if abs(plan.stretch_b) > 1e-6:
        stretch(scene, plan.b, plan.end_b, plan.stretch_b, unique=True)
    ra, rb = run_of(scene, plan.a), run_of(scene, plan.b)
    pa = np.asarray(ra.end if plan.end_a == "end" else ra.start, float)
    pb = np.asarray(rb.end if plan.end_b == "end" else rb.start, float)
    port_a, port_b = _free_end_port(scene, a, pa), _free_end_port(scene, b, pb)
    made = []
    if plan.kind == "bend":
        ta = np.asarray(ra.direction, float) * (1 if plan.end_a == "end" else -1)
        tb = np.asarray(rb.direction, float) * (1 if plan.end_b == "end" else -1)
        side = np.cross(ta, -tb)
        side /= np.linalg.norm(side)
        width, depth, round_ = _section_across(scene, plan.a, side)
        i, place, item, _, _, px, _ = _frames(scene, a)
        part = _new_fitting(model, a, place, f"{a.Name or 'Segment'} bend", f"{a.Tag}-BJ" if a.Tag else None)
        verts, tris = _bend_mesh(pa / s, ta, -tb, plan.radius / s, width / s, depth / s, round_)
        local = (np.linalg.inv(place) @ np.c_[verts, np.ones(len(verts))].T).T[:, :3]
        solid = model.createIfcTriangulatedFaceSet(model.createIfcCartesianPointList3D([[float(c) for c in v] for v in local]),
                                                   None, True, [[int(x) + 1 for x in f] for f in tris], None)
        body = next(r for r in a.Representation.Representations if r.RepresentationIdentifier == "Body")
        part.Representation = model.createIfcProductDefinitionShape(None, None, [model.createIfcShapeRepresentation(
            body.ContextOfItems, "Body", "Tessellation", [solid])])
        for st in [x for it in body.Items for x in model.get_inverse(it) if x.is_a("IfcStyledItem")]:
            model.createIfcStyledItem(solid, st.Styles, st.Name)
        p0, p1 = _ports(part)
        px_b = _frames(scene, b)[5]
        _place_port(model, p0, pa / s, s, -ta, px)     # as a chain's pieces: back out of its start, on out of its end
        _place_port(model, p1, pb / s, s, -tb, px_b)   # (the bend leaves along -tb, into B's end: B's section axes)
        if port_a is not None:
            ifcopenshell.api.run("system.connect_port", model, port1=port_a, port2=p0, direction=port_a.FlowDirection or "NOTDEFINED")
        if port_b is not None:
            ifcopenshell.api.run("system.connect_port", model, port1=p1, port2=port_b, direction=p1.FlowDirection or "NOTDEFINED")
        made.append(part.GlobalId)
        scene.refresh_bounds([part.GlobalId])
    elif port_a is not None and port_b is not None:
        ifcopenshell.api.run("system.connect_port", model, port1=port_a, port2=port_b, direction=port_a.FlowDirection or "NOTDEFINED")
    return made


SECTION_DIMS = {   # an I, U, C, L or T section's overall width (profile x) and depth (profile y)
    "IfcIShapeProfileDef": ("OverallWidth", "OverallDepth"), "IfcUShapeProfileDef": ("FlangeWidth", "Depth"),
    "IfcCShapeProfileDef": ("Width", "Depth"), "IfcLShapeProfileDef": ("Width", "Depth"),
    "IfcTShapeProfileDef": ("FlangeWidth", "Depth")}
MESH_ITEMS = ("IfcTriangulatedFaceSet", "IfcPolygonalFaceSet", "IfcFacetedBrep")
PLANE_COS = 0.9998     # triangles within ~1° of each other on one plane are one face of a mesh
PLANE_TOL_M = 0.001    # and within 1 mm of its plane


def _section_dim(prof, attr: str) -> float:
    v = getattr(prof, attr)
    return float(prof.Depth if v is None and prof.is_a("IfcLShapeProfileDef") else v)


def _section_least(prof, attr: str) -> float:
    """What a section's width or depth must stay above: its flanges (twice their thickness) or its web."""
    g = lambda a: float(getattr(prof, a, None) or 0.0)
    t = prof.is_a()
    if t == "IfcIShapeProfileDef":
        return 2 * g("FlangeThickness") if attr == "OverallDepth" else g("WebThickness")
    if t == "IfcUShapeProfileDef":
        return 2 * g("FlangeThickness") if attr == "Depth" else g("WebThickness")
    if t == "IfcCShapeProfileDef":
        return 2 * g("WallThickness") if attr == "Depth" else g("WallThickness")
    if t == "IfcLShapeProfileDef":
        return g("Thickness")
    if t == "IfcTShapeProfileDef":
        return g("FlangeThickness") if attr == "Depth" else g("WebThickness")
    return 0.0


@dataclass
class Solid:
    """One solid of an element's Body, as hand edits see it."""
    k: int | None          # its place in the Body; None when the Body is one solid (face ids carry no prefix)
    kind: str              # extrusion (straight, along its own axis), mesh, other
    item: object           # the extrusion or mesh, under any clips
    top: object            # the Body's item itself: a clip result when clipped
    world: np.ndarray      # file units: an extrusion's own frame, else the representation's (the element's placement)
    clipped: bool


def solids(scene: IfcScene, element, through_maps: bool = False) -> list[Solid]:
    """Every solid of the element's Body, each with what it is and its world frame. Empty without one Body.
    `through_maps` reads a body drawn from its type (mapped items) as the solids it draws, in the order `unmap` copies
    them: for listing and resolving faces only; an edit unmaps first (`make_unique`), so it never changes the type."""
    rep = element.Representation
    bodies = [r for r in (rep.Representations if rep else []) if r.RepresentationIdentifier == "Body"]
    if len(bodies) != 1:
        return []
    place = (ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
             if element.ObjectPlacement is not None else np.eye(4))
    items: list = []
    for top in bodies[0].Items:
        if through_maps and top.is_a("IfcMappedItem"):
            try:
                m = mapping(top)
            except Unsupported:
                items.append((top, place))
                continue
            items += [(inner, place @ m) for inner in top.MappingSource.MappedRepresentation.Items]
        else:
            items.append((top, place))
    out = []
    for k, (top, frame) in enumerate(items):
        item = top
        while item.is_a("IfcBooleanClippingResult"):
            item = item.FirstOperand
        key = k if len(items) > 1 else None
        if (item.is_a("IfcExtrudedAreaSolid") and item.Position is not None
                and np.linalg.norm(np.asarray(item.ExtrudedDirection.DirectionRatios) - (0, 0, 1)) <= 1e-9):
            out.append(Solid(key, "extrusion", item, top, frame @ ifcopenshell.util.placement.get_axis2placement(item.Position),
                             top is not item))
        elif any(item.is_a(c) for c in MESH_ITEMS):
            out.append(Solid(key, "mesh", item, top, frame, top is not item))
        else:
            out.append(Solid(key, "other", item, top, place, top is not item))
    return out


def solid(scene: IfcScene, element, k: int | None, through_maps: bool = False) -> Solid:
    """The solid a face id's prefix names (None: the Body's one solid); `through_maps` as `solids`, for reading."""
    sol = solids(scene, element, through_maps)
    found = next((x for x in sol if x.k == k), None) if k is not None else (sol[0] if len(sol) == 1 else None)
    if found is None:
        raise Unsupported("it has no such solid in its body")
    return found


def item_verts(scene: IfcScene, element, top) -> np.ndarray:
    """One solid's triangulated vertices, world metres (its clips applied)."""
    i = scene.index_of(element.GlobalId)
    s = scene.unit_scales[i]
    place = (ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
             if element.ObjectPlacement is not None else np.eye(4))
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), top)
    v = np.asarray(shape.verts, float).reshape(-1, 3)    # metres, in the representation's frame
    return v @ place[:3, :3].T + place[:3, 3] * s


def mesh_data(item) -> tuple[np.ndarray, np.ndarray]:
    """A mesh's vertices (file units, its representation's frame) and its triangles (index triples into them)."""
    if item.is_a("IfcTriangulatedFaceSet") or item.is_a("IfcPolygonalFaceSet"):
        pts = np.asarray(item.Coordinates.CoordList, float)
        pn = getattr(item, "PnIndex", None)
        at = (lambda k: pn[k - 1] - 1) if pn else (lambda k: k - 1)
        if item.is_a("IfcTriangulatedFaceSet"):
            tris = [tuple(at(k) for k in t) for t in item.CoordIndex]
        else:
            tris = []
            for f in item.Faces:
                loop = [at(k) for k in f.CoordIndex]
                tris += [(loop[0], loop[j], loop[j + 1]) for j in range(1, len(loop) - 1)]
        return pts, np.asarray(tris, int).reshape(-1, 3)
    index: dict[int, int] = {}
    pts, tris = [], []
    for f in item.Outer.CfsFaces:
        bounds = [b for b in f.Bounds if b.is_a("IfcFaceOuterBound")] or list(f.Bounds[:1])
        for b in bounds:
            loop = []
            for p in b.Bound.Polygon:
                if p.id() not in index:
                    index[p.id()] = len(pts)
                    pts.append(p.Coordinates)
                loop.append(index[p.id()])
            if not b.Orientation:
                loop = loop[::-1]
            tris += [(loop[0], loop[j], loop[j + 1]) for j in range(1, len(loop) - 1)]
    return np.asarray(pts, float), np.asarray(tris, int).reshape(-1, 3)


def mesh_patches(pts: np.ndarray, tris: np.ndarray) -> list[dict]:
    """A mesh's flat faces: triangles joined through shared corners (by position) that lie on one plane, within ~1° and
    1 mm (`pts` in metres). Each: its triangles, area-weighted normal (from the winding), centroid and area."""
    if not len(tris):
        return []
    a, b, c = pts[tris[:, 0]], pts[tris[:, 1]], pts[tris[:, 2]]
    cr = np.cross(b - a, c - a)
    area = np.linalg.norm(cr, axis=1) / 2
    n = cr / np.maximum(np.linalg.norm(cr, axis=1), 1e-15)[:, None]
    cen = (a + b + c) / 3
    keys = np.round(pts / 1e-6).astype(np.int64)
    corner: dict[tuple, list[int]] = {}
    for t, tri in enumerate(tris):
        for v in tri:
            corner.setdefault(tuple(keys[v]), []).append(t)
    parent = list(range(len(tris)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for ts in corner.values():
        for x in ts:
            for y in ts:
                if x < y and area[x] > 0 and area[y] > 0 and n[x] @ n[y] > PLANE_COS \
                        and abs(n[x] @ (cen[y] - cen[x])) < PLANE_TOL_M:
                    parent[find(x)] = find(y)
    groups: dict[int, list[int]] = {}
    for t in range(len(tris)):
        if area[t] > 0:
            groups.setdefault(find(t), []).append(t)
    out = []
    for ts in groups.values():
        w = area[ts]
        nn = (n[ts] * w[:, None]).sum(axis=0)
        out.append({"tris": ts, "normal": nn / (np.linalg.norm(nn) or 1.0), "point": (cen[ts] * w[:, None]).sum(axis=0) / w.sum(),
                    "area": float(w.sum())})
    return sorted(out, key=lambda x: -x["area"])


def mesh_world(scene: IfcScene, element, so: Solid) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A mesh solid's vertices in its own frame (file units) and in the world (metres), and its triangles."""
    s = scene.unit_scales[scene.index_of(element.GlobalId)]
    local, tris = mesh_data(so.item)
    world = (local @ so.world[:3, :3].T + so.world[:3, 3]) * s
    return local, world, tris


def patch_at(world: np.ndarray, tris: np.ndarray, point, normal) -> dict:
    """The flat face of a mesh under a pick: the patch holding the triangle nearest the point, square to the normal
    (either winding). Refused on a curved surface (its patch under 1% of the mesh's area) or when nothing is there."""
    P, N = np.asarray(point, float), np.asarray(normal, float) / np.linalg.norm(normal)
    patches = mesh_patches(world, tris)
    total = sum(x["area"] for x in patches) or 1.0
    best = None
    for x in patches:
        if abs(x["normal"] @ N) < 0.99:
            continue
        off = abs((P - x["point"]) @ x["normal"])
        if off > NEAR_PICK_M:
            continue
        a, b, c = world[tris[x["tris"], 0]], world[tris[x["tris"], 1]], world[tris[x["tris"], 2]]
        d = float(np.min(np.linalg.norm((a + b + c) / 3 - P, axis=1)))
        if best is None or d < best[0]:
            best = (d, x)
    if best is None:
        raise Unsupported("there is no flat face of it under the pick")
    if best[1]["area"] < 0.01 * total:
        raise Unsupported("that is a curved surface: ORCA pushes and pulls flat faces")
    return best[1]


NEAR_PICK_M = 0.005


def push_mesh_face(scene: IfcScene, global_id: str, point, normal, by_m: float, item: int | None = None,
                   least_m: float = MIN_PIECE_M, unique: bool = False) -> float:
    """Push (+) or pull (−) a mesh's flat face along its outward `normal` (the pick's) by `by_m` metres: the face's
    corners move, the faces round it stretch. Ports on that face go with it. Refused when it would fold through the
    mesh's other side. Returns how thick it is behind the face after, metres."""
    element = scene.entity(global_id)
    i = scene.index_of(global_id)
    model, s = scene.models[i], scene.unit_scales[i]
    if unique:
        make_unique(model, element)
    so = solid(scene, element, item)
    if so.kind != "mesh":
        raise Unsupported("that solid is not a mesh")
    if shared(model, element, _body_rep(element), so.top):
        raise Unsupported("its body is shared with other elements")
    by = float(by_m)
    if not np.isfinite(by):
        raise Unsupported("a push must be a finite length")
    local, world, tris = mesh_world(scene, element, so)
    P, n = np.asarray(point, float), np.asarray(normal, float) / np.linalg.norm(normal)
    patch = patch_at(world, tris, P, n)
    plane = patch["point"]
    keys = np.round(local * s / 1e-6).astype(np.int64)    # corners by position, to the micrometre
    on = {tuple(keys[v]) for t in patch["tris"] for v in tris[t]}
    moving = np.array([tuple(k) in on for k in keys])
    depth = (plane - world) @ n
    behind = depth[~moving & (depth > 1e-4)]
    thick = float(depth.max())
    near = float(behind.min()) if len(behind) else thick
    if by < 0 and -by > near - least_m + 1e-9:
        raise Unsupported(f"it would fold through its other side: at most {max(near - least_m, 0) * 1000:.0f} mm in")
    step = (so.world[:3, :3].T @ (n * by)) / s           # the move in the mesh's own frame, file units
    if so.item.is_a("IfcFacetedBrep"):
        made: dict[tuple, object] = {}
        for f in so.item.Outer.CfsFaces:
            for b in f.Bounds:
                loop = b.Bound
                new = []
                for p in loop.Polygon:
                    k = tuple(np.round(np.asarray(p.Coordinates, float) * s / 1e-6).astype(np.int64))
                    if k in on:
                        if k not in made:
                            made[k] = model.createIfcCartesianPoint(tuple(float(c) for c in np.asarray(p.Coordinates) + step))
                        new.append(made[k])
                    else:
                        new.append(p)
                loop.Polygon = new
    else:
        moved = local.copy()
        moved[moving] += step
        so.item.Coordinates = model.createIfcCartesianPointList3D([tuple(float(c) for c in r) for r in moved])
        if getattr(so.item, "Normals", None) is not None:
            so.item.Normals = None
    for port in ifcopenshell.util.system.get_ports(element):   # ports on that face go with it
        if port.ObjectPlacement is None:
            continue
        m = scene.placement(port.GlobalId)
        if abs((m[:3, 3] - plane) @ n) <= 0.002:
            m[:3, 3] += n * by
            ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=m, is_si=True)
    scene.refresh_bounds([global_id])
    return thick + by


def _body_rep(element):
    rep = element.Representation
    return next(r for r in rep.Representations if r.RepresentationIdentifier == "Body")


def clip_chain(top) -> list:
    """The clip results over a solid, outermost first (the last clip made is first)."""
    out = []
    while top is not None and top.is_a("IfcBooleanClippingResult"):
        out.append(top)
        top = top.FirstOperand
    return out


def clip_planes(scene: IfcScene, element, so: Solid) -> list[tuple[object, np.ndarray, np.ndarray]]:
    """Each clip over a solid: the clip result, a point on its plane (world metres) and its outward normal (out of
    what is left, into what it took away)."""
    i = scene.index_of(element.GlobalId)
    s = scene.unit_scales[i]
    place = (ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
             if element.ObjectPlacement is not None else np.eye(4))
    out = []
    for res in clip_chain(so.top):
        half = res.SecondOperand
        if not half.is_a("IfcHalfSpaceSolid") or not half.BaseSurface.is_a("IfcPlane"):
            continue
        m = ifcopenshell.util.placement.get_axis2placement(half.BaseSurface.Position)
        n = m[:3, 2] * (-1.0 if half.AgreementFlag else 1.0)   # the flag: the normal points away from the half-space
        n = place[:3, :3] @ n
        out.append((res, (place @ np.append(m[:3, 3], 1.0))[:3] * s, n / np.linalg.norm(n)))
    return out


def move_clip(scene: IfcScene, global_id: str, j: int, by_m: float, item: int | None = None,
              least_m: float = MIN_PIECE_M) -> float:
    """Move a clip's plane out (+, it takes less away) or in (−, more) along its outward normal by `by_m` metres: a
    clipped end pushed or pulled. Refused when it would leave less than `least_m`. Returns the move, metres."""
    element = scene.entity(global_id)
    i = scene.index_of(global_id)
    model, s = scene.models[i], scene.unit_scales[i]
    so = solid(scene, element, item)
    planes = clip_planes(scene, element, so)
    if not 0 <= j < len(planes):
        raise Unsupported("it has no such clip")
    res, P, n = planes[j]
    by = float(by_m)
    v = item_verts(scene, element, so.top)
    left = float(((P - v) @ n).max())
    if by < 0 and left + by < least_m - 1e-9:
        raise Unsupported(f"less than {least_m * 1000:.0f} mm of it would be left")
    half = res.SecondOperand
    pos = half.BaseSurface.Position
    m = ifcopenshell.util.placement.get_axis2placement(pos)
    place = (ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
             if element.ObjectPlacement is not None else np.eye(4))
    step = place[:3, :3].T @ (n * by) / s
    loc = m[:3, 3] + step
    half.BaseSurface = model.createIfcPlane(model.createIfcAxis2Placement3D(
        _point(model, loc), pos.Axis, pos.RefDirection))
    scene.refresh_bounds([global_id])
    return by


def _sole_body(model, element, unique: bool = False, item: int | None = None):
    """The element's one extrusion (or the `item`th solid of its body), refusing a body other elements share (editing
    it would change them too) unless `unique` gives this element its own copy first (hand edits)."""
    if unique:
        make_unique(model, element)
    body, it = _body(element, item=item)
    if shared(model, element, body, it):
        raise Unsupported("its body is shared with other elements")
    return body, it


def stretch_radius(scene: IfcScene, global_id: str, by_m: float, unique: bool = False, item: int | None = None) -> float:
    """A round element's radius `by_m` larger (or smaller): a new circle profile (profiles can be shared), the axis
    and ports where they were. Returns the new diameter in metres."""
    element = scene.entity(global_id)
    i = scene.index_of(global_id)
    model, s = scene.models[i], scene.unit_scales[i]
    _, item = _sole_body(model, element, unique, item)
    prof = item.SweptArea
    if not prof.is_a("IfcCircleProfileDef"):
        raise Unsupported("only a round section changes its radius")
    r = prof.Radius + float(by_m) / s
    if not np.isfinite(r) or r * s < 0.005:
        raise Unsupported(f"it would be {max(r * s * 2000, 0):.0f} mm across (at least 10 mm stays)")
    if prof.is_a("IfcCircleHollowProfileDef"):
        if r <= prof.WallThickness:
            raise Unsupported("its wall would be thicker than its radius")
        item.SweptArea = model.createIfcCircleHollowProfileDef(prof.ProfileType, prof.ProfileName, prof.Position,
                                                               float(r), prof.WallThickness)
    else:
        item.SweptArea = model.createIfcCircleProfileDef(prof.ProfileType, prof.ProfileName, prof.Position, float(r))
    scene.refresh_bounds([global_id])
    return float(2 * r * s)


def _line_cross(p, d, q, e):
    """Where the lines p + t·d and q + u·e meet, or None when they are parallel."""
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-12:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return p + d * t


def _simple(pts: list[np.ndarray]) -> bool:
    """No two edges of the closed outline cross (neighbours share their corner)."""
    n = len(pts)
    segs = [(pts[k], pts[(k + 1) % n]) for k in range(n)]

    def cross(a, b, c, d):
        def o(p, q, r):
            return np.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]))
        return o(a, b, c) != o(a, b, d) and o(c, d, a) != o(c, d, b)

    for x in range(n):
        for y in range(x + 1, n):
            if y == x + 1 or (x == 0 and y == n - 1):
                continue
            if cross(*segs[x], *segs[y]):
                return False
    return True


def inside(pts: list[np.ndarray], q) -> bool:
    """Whether 2D point `q` lies in the closed outline (on its edge counts as inside)."""
    x, y = q
    hit = False
    n = len(pts)
    for k in range(n):
        (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % n]
        if abs((x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)) < 1e-9 and min(x0, x1) - 1e-9 <= x <= max(x0, x1) + 1e-9 \
                and min(y0, y1) - 1e-9 <= y <= max(y0, y1) + 1e-9:
            return True
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def _write_outline(model, prof, pts: list[np.ndarray], closed_repeat: bool):
    """A new outline profile with these points, keeping its kind, name and holes (profiles and curves can be shared)."""
    curve = prof.OuterCurve
    if curve.is_a("IfcIndexedPolyCurve"):
        coords = [tuple(float(c) for c in p) for p in pts]
        new = model.createIfcIndexedPolyCurve(model.createIfcCartesianPointList2D(coords + [coords[0]]), None, False)
    else:
        cps = [_point(model, p) for p in pts]
        new = model.createIfcPolyline(cps + [cps[0]] if closed_repeat else cps)
    if prof.is_a("IfcArbitraryProfileDefWithVoids"):
        return model.createIfcArbitraryProfileDefWithVoids(prof.ProfileType, prof.ProfileName, new, prof.InnerCurves)
    return model.createIfcArbitraryClosedProfileDef(prof.ProfileType, prof.ProfileName, new)


def offset_edge(scene: IfcScene, global_id: str, k: int, by_m: float, keep_inside: list[np.ndarray] = (),
                unique: bool = False, item: int | None = None) -> float:
    """Move straight edge `k` of the element's outline profile out (+) or in (−) by `by_m`, square to itself; the
    edges either side run on to meet it (a wall's end moves, its top and bottom get longer or shorter). Refused when
    a neighbour is parallel to it, would turn back or fall under 10 mm, the outline would cross itself, or a hole in
    it or any of `keep_inside` (2D points in the profile's plane, file units: an opening's corners) would be left
    outside. Returns the edge's distance moved, metres."""
    from .faces import ccw, edge_normal, outline
    element = scene.entity(global_id)
    i = scene.index_of(global_id)
    model, s = scene.models[i], scene.unit_scales[i]
    _, item = _sole_body(model, element, unique, item)
    prof = item.SweptArea
    pts = outline(prof)
    if pts is None:
        raise Unsupported("its outline is not straight edges")
    n = len(pts)
    if not 0 <= k < n:
        raise Unsupported(f"its outline has no edge {k}")
    by = float(by_m) / s
    if not np.isfinite(by) or abs(by_m) < 1e-4:
        raise Unsupported("an edge moves at least 0.1 mm")
    a, b = pts[k], pts[(k + 1) % n]
    d = b - a
    nrm = edge_normal(a, b, ccw(pts))
    prev_a, next_b = pts[k - 1], pts[(k + 2) % n]
    na = _line_cross(a + nrm * by, d, prev_a, a - prev_a)
    nb = _line_cross(a + nrm * by, d, b, next_b - b)
    if na is None or nb is None:
        raise Unsupported("an edge beside it runs the same way, so it cannot follow")
    for old_far, old, new in ((prev_a, a, na), (next_b, b, nb)):
        before, after = old - old_far, new - old_far
        if np.linalg.norm(after) * s < MIN_EDGE_M or before @ after <= 0:
            raise Unsupported(f"an edge beside it would be shorter than {MIN_EDGE_M * 1000:.0f} mm or turn back")
    new_pts = list(pts)
    new_pts[k], new_pts[(k + 1) % n] = na, nb
    if not _simple(new_pts):
        raise Unsupported("its outline would cross itself")
    from .faces import curve_points
    holes = []
    for c in getattr(prof, "InnerCurves", None) or ():   # a polyline or an indexed poly curve
        holes += curve_points(c) or []
    for q in [*holes, *keep_inside]:
        if not inside(new_pts, q):
            raise Unsupported("it would cut through an opening in it" if any(q is x for x in keep_inside)
                              else "it would cut through a hole in its outline")
    curve = prof.OuterCurve
    repeat = curve.is_a("IfcPolyline") and len(curve.Points) > n
    item.SweptArea = _write_outline(model, prof, new_pts, repeat)
    scene.refresh_bounds([global_id])
    return float(by * s)


def face_axes(n) -> tuple[np.ndarray, np.ndarray]:
    """Two axes in a face's plane: across (u, level when the face is not) and up it (v)."""
    n = np.asarray(n, float) / np.linalg.norm(n)
    z = np.array([0.0, 0.0, 1.0])
    if abs(n @ z) < 0.9:
        v = z - (z @ n) * n
        v /= np.linalg.norm(v)
        return np.cross(v, n), v
    x = np.array([1.0, 0.0, 0.0])
    u = x - (x @ n) * n
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def through_depth(scene: IfcScene, host: str, at, n, offsets: list[np.ndarray]) -> float | None:
    """How far an opening on a face at `at` (outward normal `n`, world metres) must go to pass through the host:
    from just inside each point of its outline to where it comes out, the deepest of them. None when no ray comes out
    (the host is not closed there, or deeper than MAX_THROUGH_M)."""
    tris = _host_tris(scene, host)
    n = np.asarray(n, float) / np.linalg.norm(n)
    origins = np.array([np.asarray(at, float) + o - n * 0.001 for o in offsets])
    t = _first_hit(origins, -n, tris)
    t = t[np.isfinite(t)]
    if not len(t) or t.max() + 0.001 > MAX_THROUGH_M:
        return None
    return float(t.max() + 0.001)


def misses(scene: IfcScene, host: str, at, n, offsets: list[np.ndarray]) -> bool:
    """Whether any of these points on the face (from outside, along −n) misses the host: the outline reaches its edge."""
    tris = _host_tris(scene, host)
    n = np.asarray(n, float) / np.linalg.norm(n)
    origins = np.array([np.asarray(at, float) + o + n * 0.05 for o in offsets])
    t = _first_hit(origins, -n, tris)
    return bool(np.any(~np.isfinite(t) | (t > 0.05 + 0.01)))


def cut_void(scene: IfcScene, host: str, shape: str, width_m: float, height_m: float, start, axis, xdir,
             depth_m: float, recess: bool = False, name: str | None = None) -> str:
    """An opening (or a recess) voiding `host`: a box or cylinder from `start` along `axis` for `depth_m`, its width
    along `xdir` (world metres). Returns its GlobalId."""
    i = scene.index_of(host)
    m, s = scene.models[i], scene.unit_scales[i]
    element = scene.entity(host)
    opening = ifcopenshell.api.run("root.create_entity", m, ifc_class="IfcOpeningElement", name=name or "Opening")
    if m.schema != "IFC2X3":
        opening.PredefinedType = "RECESS" if recess else "OPENING"
    elif recess:
        opening.ObjectType = "Recess"
    pen = Penetration(host, host, shape, float(width_m), float(height_m), float(depth_m), list(map(float, start)),
                      list(map(float, axis)), list(map(float, xdir)))
    rep, _ = _void_rep(m, s, pen, _body_context(element))
    ifcopenshell.api.run("geometry.assign_representation", m, product=opening, representation=rep)
    _void_place(m, opening, s, pen)
    ifcopenshell.api.run("feature.add_feature", m, feature=opening, element=element)
    scene.refresh_bounds([host])
    return opening.GlobalId


def _vertex_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    n = np.zeros_like(verts)
    fn = np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
    for k in range(3):
        np.add.at(n, faces[:, k], fn)
    length = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.where(length > 0, length, 1.0)


def _grown_solid(m, sx: float, item, world_y: np.ndarray, sy: float, gap: float):
    """One extrusion of the cutter, in the cut element's file (units `sx`), grown by `gap` metres all round and
    placed in world axes; None when its profile is not one ORCA grows exactly."""
    if np.linalg.norm(np.asarray(item.ExtrudedDirection.DirectionRatios) - (0, 0, 1)) > 1e-9:
        return None
    k, g = sy / sx, gap / sx
    prof = item.SweptArea
    pos2 = getattr(prof, "Position", None)
    loc = np.asarray(pos2.Location.Coordinates[:2], float) * k if pos2 is not None else np.zeros(2)
    ref = (pos2.RefDirection.DirectionRatios[:2] if pos2 is not None and pos2.RefDirection is not None else (1.0, 0.0))
    at2 = m.createIfcAxis2Placement2D(_point(m, loc), m.createIfcDirection(tuple(float(x) for x in ref)))
    if prof.is_a("IfcCircleProfileDef"):
        new = m.createIfcCircleProfileDef("AREA", None, at2, float(prof.Radius * k + g))
    elif prof.is_a() == "IfcRectangleProfileDef":
        new = m.createIfcRectangleProfileDef("AREA", None, at2, float(prof.XDim * k + 2 * g), float(prof.YDim * k + 2 * g))
    elif prof.is_a("IfcArbitraryClosedProfileDef"):
        from .faces import outline
        pts = outline(prof)
        if pts is None:
            return None
        grown = _grown([list(p * k) for p in pts], g)
        cps = [_point(m, p) for p in grown]
        new = m.createIfcArbitraryClosedProfileDef("AREA", None, m.createIfcPolyline(cps + [cps[0]]))
    else:
        try:
            w, h = _profile_size(prof)   # an I, U, C or L section: its bounding rectangle (the gap is at least that)
        except Unsupported:
            return None
        new = m.createIfcRectangleProfileDef("AREA", None, at2, float(w * k + 2 * g), float(h * k + 2 * g))
    world = world_y @ ifcopenshell.util.placement.get_axis2placement(item.Position)
    rot, origin = world[:3, :3], world[:3, 3] * k - world[:3, 2] / np.linalg.norm(world[:3, 2]) * g
    pos = m.createIfcAxis2Placement3D(_point(m, origin), _dir(m, rot[:, 2]), _dir(m, rot[:, 0]))
    return m.createIfcExtrudedAreaSolid(new, pos, m.createIfcDirection((0.0, 0.0, 1.0)), float(item.Depth * k + 2 * g))


def cut_by_shape(scene: IfcScene, element: str, cutter: str, gap_m: float) -> tuple[str, bool]:
    """Cut `element` where `cutter` is, plus `gap_m` all round: an opening shaped as the cutter's body grown by the gap
    (exact for extrusions; a mesh pushed out along its normals otherwise). Returns the opening and whether it is exact."""
    i, j = scene.index_of(element), scene.index_of(cutter)
    m, sx, sy = scene.models[i], scene.unit_scales[i], scene.unit_scales[j]
    host, tool = scene.entity(element), scene.entity(cutter)
    bodies = [r for r in (tool.Representation.Representations if tool.Representation else []) if r.RepresentationIdentifier == "Body"]
    items = list(bodies[0].Items) if bodies else []
    world_y = ifcopenshell.util.placement.get_local_placement(tool.ObjectPlacement)
    solids = [] if not items or not all(it.is_a("IfcExtrudedAreaSolid") for it in items) else \
        [_grown_solid(m, sx, it, world_y, sy, gap_m) for it in items]
    exact = bool(solids) and all(x is not None for x in solids)
    if exact:
        rep = m.createIfcShapeRepresentation(_body_context(host), "Body", "SweptSolid", solids)
    else:
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        geo = ifcopenshell.geom.create_shape(settings, tool).geometry
        verts = np.asarray(geo.verts, float).reshape(-1, 3)
        faces = np.asarray(geo.faces, int).reshape(-1, 3)
        if not len(faces):
            raise Unsupported("the cutter has no shape to cut with")
        # Weld coincident vertices first: a box's corners then push out along the corner's mean normal.
        keys, inverse = np.unique(np.round(verts, 6), axis=0, return_inverse=True)
        faces = inverse.reshape(-1)[faces]
        grown = (keys + _vertex_normals(keys, faces) * gap_m) / sx
        pts = m.createIfcCartesianPointList3D([tuple(float(c) for c in p) for p in grown])
        mesh = m.createIfcTriangulatedFaceSet(pts, None, True, [tuple(int(x) + 1 for x in f) for f in faces], None)
        rep = m.createIfcShapeRepresentation(_body_context(host), "Body", "Tessellation", [mesh])
    opening = ifcopenshell.api.run("root.create_entity", m, ifc_class="IfcOpeningElement",
                                   name=f"Cut for {tool.Name or tool.is_a()[3:]}")
    if m.schema != "IFC2X3":
        opening.PredefinedType = "OPENING"
    ifcopenshell.api.run("geometry.assign_representation", m, product=opening, representation=rep)
    ifcopenshell.api.run("geometry.edit_object_placement", m, product=opening, matrix=np.eye(4), is_si=False)
    ifcopenshell.api.run("feature.add_feature", m, feature=opening, element=host)
    scene.refresh_bounds([element])
    return opening.GlobalId, exact


def _assign_solid(model, source, part, solid) -> None:
    """Give `part` a Body of its own holding `solid`, in `source`'s context and styles."""
    body, item = _body(source, clipped=True)
    styles = [x for x in model.get_inverse(item) if x.is_a("IfcStyledItem")]
    rep = model.createIfcShapeRepresentation(body.ContextOfItems, "Body", "SweptSolid", [solid])
    part.Representation = model.createIfcProductDefinitionShape(None, None, [rep])
    for st in styles:
        model.createIfcStyledItem(solid, st.Styles, st.Name)


def _copy_part(model, element, solid, n: int):
    """A copy of `element` (class, type, properties, container, systems, placement) with `solid` as its body; the
    openings `copy_class` duplicated are dropped (the split sends each opening to the piece that holds it)."""
    part = ifcopenshell.api.run("root.copy_class", model, product=element)
    for rel in list(getattr(part, "HasOpenings", None) or []):
        ifcopenshell.api.run("root.remove_product", model, product=rel.RelatedOpeningElement)
    if element.Name:
        part.Name = f"{element.Name} (part {n})"
    if getattr(element, "Tag", None):
        part.Tag = f"{element.Tag}-P{n}"
    _assign_solid(model, element, part, solid)
    return part


def _clip_polygon(pts: list[np.ndarray], axis: int, c: float, keep_low: bool) -> list[np.ndarray]:
    """The part of a closed outline on one side of the line where coordinate `axis` is `c` (Sutherland–Hodgman)."""
    inside = (lambda p: p[axis] <= c + 1e-12) if keep_low else (lambda p: p[axis] >= c - 1e-12)
    out = []
    for k in range(len(pts)):
        a, b = pts[k - 1], pts[k]
        if inside(b):
            if not inside(a):
                out.append(a + (b - a) * ((c - a[axis]) / (b[axis] - a[axis])))
            out.append(b)
        elif inside(a):
            out.append(a + (b - a) * ((c - a[axis]) / (b[axis] - a[axis])))
    dedup = []
    for p in out:
        if not dedup or np.linalg.norm(p - dedup[-1]) > 1e-9:
            dedup.append(p)
    if len(dedup) > 1 and np.linalg.norm(dedup[0] - dedup[-1]) < 1e-9:
        dedup.pop()
    return dedup


def _opening_centres(scene: IfcScene, element) -> list[tuple]:
    out = []
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    for rel in getattr(element, "HasOpenings", None) or []:
        o = rel.RelatedOpeningElement
        try:
            v = np.asarray(ifcopenshell.geom.create_shape(settings, o).geometry.verts, float).reshape(-1, 3)
        except RuntimeError:
            continue
        out.append((rel, v.min(axis=0), v.max(axis=0)))
    return out


def split_axis(scene: IfcScene, global_id: str):
    """How an element splits: ("run", start, direction, length) along its long axis (an extrusion or a long profile),
    or ("outline", axis 0/1 in the outline's plane, world matrix) for an outline profile (a wall drawn as its
    elevation, a slab): cut square to its longer side."""
    from .faces import outline
    element = scene.entity(global_id)
    i, place, item, origin, d, px, py = _frames(scene, element)
    s = scene.unit_scales[i]
    pts = outline(item.SweptArea)
    if pts is not None:
        ext = np.ptp(np.asarray(pts), axis=0)
        world = place @ ifcopenshell.util.placement.get_axis2placement(item.Position)
        return ("outline", int(np.argmax(ext)), world)
    axis, start, direction, length = member_axis(scene, element)
    return ("run", start, direction, length)


def split(scene: IfcScene, global_id: str, at, least_m: float = MIN_PIECE_M, unique: bool = False) -> list[str]:
    """Split the element in two where the plane square to its long axis passes through `at` (world metres). The
    element keeps the first piece (and its GlobalId); the second is a copy. A run's ports are chained across the cut
    (`_build_chain`); its openings go to the piece that holds them; one the cut would pass through is refused."""
    element = scene.entity(global_id)
    i = scene.index_of(global_id)
    model, s = scene.models[i], scene.unit_scales[i]
    at = np.asarray(at, float)
    if unique:
        make_unique(model, element)
    how = split_axis(scene, global_id)
    holes = _opening_centres(scene, element)
    if how[0] == "outline":
        from .faces import outline
        _, ax, world = how
        _, item = _sole_body(model, element)
        pts = outline(item.SweptArea)
        inv = np.linalg.inv(world)
        q = (inv @ np.append(at / s, 1.0))[:2]
        c = float(q[ax])
        lo, hi = min(p[ax] for p in pts), max(p[ax] for p in pts)
        if c - lo < least_m / s or hi - c < least_m / s:
            raise Unsupported(f"a piece would be under {least_m * 1000:.0f} mm")
        sides = []
        for rel, a, b in holes:
            corners = [(inv @ np.append(np.array([x, y, z]) / s, 1.0))[ax] for x in (a[0], b[0]) for y in (a[1], b[1]) for z in (a[2], b[2])]
            if min(corners) < c < max(corners):
                raise Unsupported("the cut would pass through an opening: split it either side")
            sides.append((rel, min(corners) >= c))
        if getattr(item.SweptArea, "InnerCurves", None):
            raise Unsupported("its outline has holes: split it where there are none")
        left, right = _clip_polygon(pts, ax, c, True), _clip_polygon(pts, ax, c, False)
        if len(left) < 3 or len(right) < 3:
            raise Unsupported("the cut misses it")
        repeat = item.SweptArea.OuterCurve.is_a("IfcPolyline")
        right_prof = _write_outline(model, item.SweptArea, right, repeat)
        solid = model.createIfcExtrudedAreaSolid(right_prof, item.Position, item.ExtrudedDirection, item.Depth)
        part = _copy_part(model, element, solid, 2)
        item.SweptArea = _write_outline(model, item.SweptArea, left, repeat)
    else:
        _, start, d, length = how
        a = float((at - start) @ d)
        if a < least_m or length - a < least_m:
            raise Unsupported(f"a piece would be under {least_m * 1000:.0f} mm")
        sides = []
        for rel, lo_, hi_ in holes:
            ends = [float((np.array([x, y, z]) - start) @ d) for x in (lo_[0], hi_[0]) for y in (lo_[1], hi_[1]) for z in (lo_[2], hi_[2])]
            if min(ends) < a < max(ends):
                raise Unsupported("the cut would pass through an opening: split it either side")
            sides.append((rel, min(ends) >= a))
        axis = member_axis(scene, element)[0]
        if axis == "depth" and _ports(element):
            _, place, item, origin, dd, px, _ = _frames(scene, element)
            gids = _build_chain(scene, element, place, item, dd, px, px,
                                [("straight", origin, dd, a / s), ("straight", origin + dd * (a / s), dd, (length - a) / s)])
            part = scene.entity(gids[1])
            for rel in list(getattr(part, "HasOpenings", None) or []):
                ifcopenshell.api.run("root.remove_product", model, product=rel.RelatedOpeningElement)
            if element.Name:
                part.Name = f"{element.Name} (part 2)"
        else:
            _, item = _sole_body(model, element)
            twin = model.createIfcExtrudedAreaSolid(item.SweptArea, item.Position, item.ExtrudedDirection, item.Depth)
            part = _copy_part(model, element, twin, 2)
            scene.refresh_bounds([part.GlobalId])
            apply_trim(scene, global_id, "end", length - a, least_m)
            apply_trim(scene, part.GlobalId, "start", a, least_m)
    for rel, beyond in sides:   # each opening to the piece that holds it
        if beyond:
            rel.RelatingBuildingElement = part
    scene.refresh_bounds([global_id, part.GlobalId])
    return [global_id, part.GlobalId]


def remove_product_with(scene: IfcScene, global_id: str) -> list[str]:
    """Remove an element and what cannot stand without it: its openings and what fills them, the parts it aggregates,
    its ports. Returns every physical element removed (the element first). Peers its ports joined are left open."""
    i = scene.index_of(global_id)
    model = scene.models[i]
    element = scene.entity(global_id)
    gone = [global_id]
    for rel in list(getattr(element, "HasOpenings", None) or []):
        o = rel.RelatedOpeningElement
        for f in list(getattr(o, "HasFillings", None) or []):
            gone.append(f.RelatedBuildingElement.GlobalId)
            ifcopenshell.api.run("root.remove_product", model, product=f.RelatedBuildingElement)
        ifcopenshell.api.run("root.remove_product", model, product=o)
    for rel in list(getattr(element, "IsDecomposedBy", None) or []):
        for part in list(rel.RelatedObjects):
            if part.is_a("IfcElement"):
                gone.append(part.GlobalId)
                ifcopenshell.api.run("root.remove_product", model, product=part)
    for port in list(ifcopenshell.util.system.get_ports(element)):
        ifcopenshell.api.run("root.remove_product", model, product=port)
    ifcopenshell.api.run("root.remove_product", model, product=element)
    scene.forget(gone)
    return gone


def long_axis(scene: IfcScene, global_id: str) -> tuple[np.ndarray, np.ndarray, float]:
    """The element's long axis, world metres: a start, a unit direction and a length. Its extrusion's (`split_axis`)
    when it has one; else the axis of its placement it is longest along (a fitting, a door, a mesh)."""
    try:
        how = split_axis(scene, global_id)
    except Unsupported:
        how = None
    if how is not None and how[0] == "run":
        return np.asarray(how[1], float), np.asarray(how[2], float), float(how[3])
    v = _mesh_verts(scene.entity(global_id))
    c = v.mean(axis=0)
    if how is not None:
        d = how[2][:3, how[1]] / np.linalg.norm(how[2][:3, how[1]])
    else:
        element = scene.entity(global_id)
        place = (ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
                 if element.ObjectPlacement is not None else np.eye(4))
        axes = [place[:3, k] / np.linalg.norm(place[:3, k]) for k in range(3)]
        d = max(axes, key=lambda a: float(np.ptp(v @ a)))
    proj = (v - c) @ d
    return c + d * proj.min(), d, float(proj.max() - proj.min())


def _clip_items(scene: IfcScene, element, point, normal) -> None:
    """Clip every solid of the element's Body with the half-space on the side `normal` points to (world metres):
    meshes and extrusions alike. A solid wholly kept is left as it is; one wholly taken away is dropped."""
    i = scene.index_of(element.GlobalId)
    model, s = scene.models[i], scene.unit_scales[i]
    body = _body_rep(element)
    if any(it.is_a("IfcMappedItem") for it in body.Items):
        raise Unsupported("its shape comes from its type: editing it would change every element of that type")
    P, N = np.asarray(point, float), np.asarray(normal, float) / np.linalg.norm(normal)
    place = (ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
             if element.ObjectPlacement is not None else np.eye(4))
    inv = np.linalg.inv(place)
    loc = (inv @ np.append(P / s, 1.0))[:3] * s          # the representation's frame, SI metres
    nl = inv[:3, :3] @ N
    nl = nl / np.linalg.norm(nl)
    new = []
    for top in body.Items:
        side = (item_verts(scene, element, top) - P) @ N
        if side.max() <= 1e-6:
            new.append(top)
        elif side.min() < -1e-6:
            new.append(ifcopenshell.api.run("geometry.clip_solid", model, item=top, location=loc.tolist(), normal=nl.tolist()))
    if not new:
        raise Unsupported("the plane takes all of it away")
    body.Items = tuple(new)
    body.RepresentationType = "Clipping"


def split_by_clip(scene: IfcScene, global_id: str, at, least_m: float = MIN_PIECE_M, unique: bool = False,
                  axis: tuple | None = None) -> list[str]:
    """Split any body in two square to its long axis (`long_axis`) at `at`, by half-space clips: the element keeps the
    first piece, clipped beyond the plane; a copy (its class, properties, openings, its own body) is clipped before it.
    The copy's ports are dropped: its joints stay with the first piece. `axis` (a start and a direction) cuts square
    to another axis than its own (a section taken out of a fitting: both cuts square to the whole's axis). Returns both
    GlobalIds."""
    element = scene.entity(global_id)
    i = scene.index_of(global_id)
    model, s = scene.models[i], scene.unit_scales[i]
    if unique:
        make_unique(model, element)
    if axis is None:
        start, d, length = long_axis(scene, global_id)
    else:
        d = np.asarray(axis[1], float) / np.linalg.norm(axis[1])
        proj = _mesh_verts(element) @ d
        start, length = np.asarray(axis[0], float) + d * (proj.min() - np.asarray(axis[0], float) @ d), float(np.ptp(proj))
    a = float((np.asarray(at, float) - start) @ d)
    if a < least_m or length - a < least_m:
        raise Unsupported(f"a piece would be under {least_m * 1000:.0f} mm")
    P = start + d * a
    part = ifcopenshell.api.run("root.copy_class", model, product=element)
    import ifcopenshell.util.element as ue
    part.Representation = ue.copy_deep(model, element.Representation, exclude=["IfcGeometricRepresentationContext"])
    for old_r, new_r in zip(element.Representation.Representations, part.Representation.Representations):
        for old_i, new_i in zip(old_r.Items, new_r.Items):
            for st in [x for x in model.get_inverse(old_i) if x.is_a("IfcStyledItem")]:
                model.createIfcStyledItem(new_i, st.Styles, st.Name)
    for port in list(ifcopenshell.util.system.get_ports(part)):
        ifcopenshell.api.run("root.remove_product", model, product=port)
    if element.Name:
        part.Name = f"{element.Name} (part 2)"
    if getattr(element, "Tag", None):
        part.Tag = f"{element.Tag}-P2"
    _clip_items(scene, element, P, d)
    _clip_items(scene, part, P, -d)
    scene.refresh_bounds([global_id, part.GlobalId])
    return [global_id, part.GlobalId]


def clip_to_plane(scene: IfcScene, global_id: str, point, normal, least_m: float = MIN_PIECE_M, unique: bool = False) -> None:
    """Cut away the element's material on the side of the plane (world metres) its `normal` points to: an
    IfcBooleanClippingResult with a half-space, as authoring tools clip a beam's end to a sloping face. Refused when the
    plane misses it, or leaves less than 50 mm of its run."""
    element = scene.entity(global_id)
    i = scene.index_of(global_id)
    model, s = scene.models[i], scene.unit_scales[i]
    if unique:
        make_unique(model, element)
    P, N = np.asarray(point, float), np.asarray(normal, float) / np.linalg.norm(normal)
    v = _mesh_verts(element)
    side = (v - P) @ N
    if side.max() <= 1e-4 or side.min() >= -1e-4:
        raise Unsupported("the plane does not cross it")
    if (-side.min()) < least_m:
        raise Unsupported(f"less than {least_m * 1000:.0f} mm of it would be left")
    if shared(model, element, _body_rep(element), _body_rep(element).Items[0]):
        raise Unsupported("its body is shared with other elements")
    _clip_items(scene, element, P, N)   # every solid of its body, meshes too
    scene.refresh_bounds([global_id])


def _is_clipped(element, item: int | None = None) -> bool:
    """Whether the Body's one solid (or its `item`th) is under a clip."""
    rep = element.Representation
    bodies = [r for r in (rep.Representations if rep else []) if r.RepresentationIdentifier == "Body"]
    if not bodies:
        return False
    items = bodies[0].Items
    if item is None:
        return len(items) == 1 and items[0].is_a("IfcBooleanClippingResult")
    return 0 <= item < len(items) and items[item].is_a("IfcBooleanClippingResult")


def _mesh_verts(element) -> np.ndarray:
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    return np.asarray(ifcopenshell.geom.create_shape(settings, element).geometry.verts, float).reshape(-1, 3)
