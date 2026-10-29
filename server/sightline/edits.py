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
OFFSET_AXIS_TOL = 1e-9   # numerical residue, metres; shared by validation and generation


def offset_components(dz_m: float, lateral_m: float) -> tuple[float, float]:
    """Discard negligible axes before selecting a detour plane or reporting its delta."""
    return tuple(0.0 if abs(v) <= OFFSET_AXIS_TOL else float(v) for v in (dz_m, lateral_m))


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


def _build_chain(scene: IfcScene, element, place, item, d, px, profile_x, pieces: list[tuple]) -> list[str]:
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
        for port, frame in zip((chain_ports[0][0], chain_ports[-1][-1]), external_frames):
            if frame is not None:
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
    clearance_m: float = 0.025
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


def penetration(scene: IfcScene, service_gid: str, host_gid: str, clearance_m: float = 0.025,
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
    boxes included) and is raised again. Never nest it inside `trial` or `trial_files`."""
    before = dict(scene.bounds())
    models = [scene.models[i] for i in sorted(indexes)]
    for m in models:
        m.begin_transaction()
    try:
        yield
    except BaseException:
        for m in models:
            m.end_transaction()
            m.undo()
        scene._bounds = before
        raise
    for m in models:
        m.end_transaction()


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


def free_bands(scene: IfcScene, run_gid: str, obstacles: list[str], axis: str = "side", clearance_m: float = 0.025,
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
