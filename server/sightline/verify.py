"""The geometry check. It is the authority for every clearance number ORCA shows.

The browser triangulates with web-ifc and this side with IfcOpenShell, so the two can differ by a
millimetre or so; the UI always displays these numbers, never its own.
"""
from __future__ import annotations

from dataclasses import dataclass

import ifcopenshell.geom
import numpy as np

from .scene import IfcScene, opacity
from .requirements import DEFAULT_CLEARANCE_M

# How far to look for the nearest neighbour, so a passing fix can still report its real clearance.
SEARCH_M = 0.5


@dataclass
class Hit:
    other: str          # GlobalId of the element hit
    other_class: str
    kind: str           # "collision" (hard) or "clearance" (closer than required)
    distance_m: float   # signed: negative = penetration depth, positive = gap
    location: list[float] | None = None


@dataclass
class Verdict:
    passed: bool
    hits: list[Hit]
    min_clearance_m: float | None  # nearest gap to anything within SEARCH_M; None = nothing that close
    checked_against: int


def _settings():
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    return s


def check(scene: IfcScene, moved: list[str], clearance_m: float = DEFAULT_CLEARANCE_M,
          ignore: set[str] | None = None, *, exclude_connected: bool = True,
          touching: set[str] | None = None) -> Verdict:
    """Check the moved elements against every other element in the model.

    A fix passes when nothing penetrates the moved elements and nothing sits closer than
    `clearance_m`. `ignore` holds elements that are meant to touch (e.g. the rest of the moved run);
    elements joined to the moved ones through ports are always ignored, since they touch by design.
    Only the neighbourhood (cached boxes within SEARCH_M) is triangulated, so a check takes well
    under a second on a building-sized federation.

    Context evaluation calls this for each changed piece with `exclude_connected=False`.
    Its validated `touching` pairs waive clearance only, never penetration checks.
    """
    if not moved:
        return Verdict(True, [], None, 0)
    connected = {c for g in moved for c in scene.element(g).connected} if exclude_connected else set()
    ignore = set(ignore or ()) | set(moved) | connected
    nearby = scene.near(moved, SEARCH_M + clearance_m)
    others = [p for p in scene.products() if p.GlobalId in nearby and p.GlobalId not in ignore]
    if not others:
        # Nothing nearby, so nothing to hit. Also required: IfcOpenShell's clash queries crash on an empty set.
        return Verdict(passed=True, hits=[], min_clearance_m=None, checked_against=0)
    targets = [scene.entity(g) for g in moved]

    # The default "opencascade.brep" tree has no *_many clash queries; the triangle BVH tree does.
    tree = ifcopenshell.geom.tree(backend="opencascade.trianglebvh")
    by_file: dict[int, list] = {}
    for e in others + targets:  # one iterator per federated file, over just the elements we need
        by_file.setdefault(scene.index_of(e.GlobalId), []).append(e)
    for i, include in by_file.items():
        tree.add_iterator(ifcopenshell.geom.iterator(_settings(), scene.models[i], include=include))

    def other_of(c):
        return c.b if c.a.GlobalId in moved else c.a

    def location_of(c):
        return [(float(c.p1[k]) + float(c.p2[k])) / 2 for k in range(3)]

    hits: dict[str, Hit] = {}
    # Intersection, not collision: collision only sees crossing triangles and misses one element
    # sitting wholly inside another (a pipe inside a duct), which intersection reports with its depth.
    for c in tree.clash_intersection_many(targets, others, tolerance=0.002, check_all=True):
        o = other_of(c)
        hits[o.GlobalId] = Hit(o.GlobalId, o.is_a(), "collision", -abs(float(c.distance)), location_of(c))
    # The intersection query misses some real overlaps: two boxes with flush faces (a curtain-wall transom running
    # 30 mm into a mullion, tops level) come back as nothing, and the clearance query calls them a 0 mm gap.
    # Collision without touching sees them; the depth is then the boxes' smallest overlap, exact for boxes.
    for c in tree.clash_collision_many(targets, others, allow_touching=False):
        o = other_of(c)
        if o.GlobalId in hits:
            continue
        mine = c.a.GlobalId if c.a.GlobalId in moved else c.b.GlobalId
        depth = _box_overlap(scene, mine, o.GlobalId)
        if depth > 0.002:
            hits[o.GlobalId] = Hit(o.GlobalId, o.is_a(), "collision", -depth, location_of(c))

    if not exclude_connected:
        # BVH queries can also miss coplanar overlapping prisms (identical profile faces).
        # For actual rectangular solids, SAT is exact; never infer a collision from an
        # arbitrary element's world box, which would invent hits inside curved bends.
        for target in targets:
            for other in others:
                if other.GlobalId in hits or _box_overlap(scene, target.GlobalId, other.GlobalId) <= .002:
                    continue
                depth = _rectangular_penetration(scene, target.GlobalId, other.GlobalId)
                if depth is not None and depth > .002:
                    hits[other.GlobalId] = Hit(other.GlobalId, other.is_a(), "collision", -depth)

    nearest = None
    for c in tree.clash_clearance_many(targets, others, clearance=SEARCH_M, check_all=True):
        o = other_of(c)
        if o.GlobalId in hits:
            continue
        gap = float(c.distance)
        if o.GlobalId not in (touching or set()):
            nearest = gap if nearest is None else min(nearest, gap)
        if gap < clearance_m and o.GlobalId not in (touching or set()):
            hits[o.GlobalId] = Hit(o.GlobalId, o.is_a(), "clearance", gap, location_of(c))

    return Verdict(passed=not hits, hits=sorted(hits.values(), key=lambda h: h.distance_m),
                   min_clearance_m=nearest, checked_against=len(others))


def _box_overlap(scene: IfcScene, a: str, b: str) -> float:
    """How far two elements' world boxes overlap on their least-overlapping axis (0 when apart or touching)."""
    boxes = scene.bounds()
    if a not in boxes or b not in boxes:
        return 0.0
    (amin, amax), (bmin, bmax) = boxes[a], boxes[b]
    return float(max(0.0, min(min(amax[k], bmax[k]) - max(amin[k], bmin[k]) for k in range(3))))


def _rectangular_penetration(scene: IfcScene, a: str, b: str) -> float | None:
    """Exact separating-axis overlap for two uncut rectangular extruded solids."""
    from . import edits
    boxes = []
    for gid in (a,b):
        entity = scene.entity(gid)
        if getattr(entity, 'HasOpenings', ()):
            return None
        try:
            _, _, solid, _, direction, px, py = edits._frames(scene, entity)
        except edits.Unsupported:
            return None
        if solid.SweptArea.is_a() != 'IfcRectangleProfileDef':
            return None
        position = solid.SweptArea.Position
        if position is not None and position.RefDirection is not None:
            x, y = position.RefDirection.DirectionRatios
            norm = float(np.hypot(x, y))
            px, py = (px*x + py*y)/norm, (-px*y + py*x)/norm
        shape = ifcopenshell.geom.create_shape(_settings(), entity)
        verts = np.asarray(shape.geometry.verts).reshape(-1,3)
        axes = np.array([px,py,direction])
        local = verts @ axes.T
        centre = ((local.max(axis=0)+local.min(axis=0))/2) @ axes
        half = (local.max(axis=0)-local.min(axis=0))/2
        boxes.append((centre,half,axes))
    (ca,ha,aa),(cb,hb,ab) = boxes
    minimum = float('inf')
    for axis in list(aa)+list(ab)+[np.cross(x,y) for x in aa for y in ab]:
        norm = np.linalg.norm(axis)
        if norm < 1e-8:
            continue
        axis = axis / norm
        overlap = float(ha @ np.abs(aa @ axis) + hb @ np.abs(ab @ axis) - abs((cb-ca) @ axis))
        if overlap <= 0:
            return 0.
        minimum = min(minimum,overlap)
    return minimum


# ---------------------------------------------------------------------------------------------- what a move stands on

# How deep a base may sit in what carries it and still stand on it: a post's anchors cast 70 mm into a slab, a plinth.
EMBED_M = 0.3
# Runs hang from above or are carried along their length (ducts, pipes, trays, their fittings): they stand on nothing.
RUNS = ("IfcFlowSegment", "IfcFlowFitting")


def is_run(scene: IfcScene, gid: str) -> bool:
    """A run (it stands on nothing), or a see-through zone (it is not a thing that stands, nor one stood on)."""
    ent = scene.entity(gid)
    return any(ent.is_a(c) for c in RUNS) or (ent.is_a("IfcBuildingElementProxy") and opacity(ent) < 0.5)


def stands_on(e: np.ndarray, h: np.ndarray, gap_m: float = 0.003) -> bool:
    """Whether box `e` stands on or in box `h` ([min, max] corners, metres, Z up): its base at, or no deeper than
    EMBED_M into, the top of `h`, which reaches below that base, with their footprints overlapping."""
    base, top = e[0][2], h[1][2]
    return bool(top - EMBED_M <= base <= top + gap_m and h[0][2] <= base
                and np.all(e[0][:2] <= h[1][:2] + gap_m) and np.all(h[0][:2] <= e[1][:2] + gap_m))


@dataclass
class Support:
    """What the moved elements stand on or in before a move (a slab, a plinth, a base below them), and how far into
    each they sit. Never a partner of the clash (what the move must clear) and never a run."""
    hosts: dict[str, float]   # host → its distance to the moved elements before the move (negative: embedded)
    standers: set[str]        # the moved elements that stand on something
    partners: set[str]
    clearance_m: float


def supports(scene: IfcScene, moved: list[str], partners: set[str], clearance_m: float,
             ignore: set[str] | None = None) -> Support:
    """Before a move: what its elements stand on, from their contacts now (`check`) and their boxes."""
    boxes = scene.bounds()
    standers = [g for g in moved if g in boxes and not is_run(scene, g)]
    if not standers:
        return Support({}, set(), set(partners), clearance_m)
    v = check(scene, moved, clearance_m=clearance_m, ignore=ignore)
    hosts: dict[str, float] = {}
    stood: set[str] = set()
    for h in v.hits:
        if h.other in partners or h.other not in boxes or is_run(scene, h.other):
            continue
        on = [g for g in standers if stands_on(boxes[g], boxes[h.other], max(clearance_m, 0.003))]
        if on:
            hosts[h.other] = min(h.distance_m, hosts.get(h.other, h.distance_m))
            stood.update(on)
    return Support(hosts, stood, set(partners), clearance_m)


def keep_supports(scene: IfcScene, sup: Support, hits: list[Hit]) -> tuple[list[Hit], set[str], str | None]:
    """After a move (the boxes moved with it): the hits that still count, the support contacts set aside, and why the
    move is refused, or None. A moved element keeps standing on what it stood on, or on something like it at no
    greater depth (a post slid along its slab, re-anchored the same way): those contacts are not new clashes. One
    that stood on something and now stands on nothing (lifted off its slab) is refused; so is one sunk deeper."""
    if not sup.standers:
        return hits, set(), None
    boxes = scene.bounds()
    gap = max(sup.clearance_m, 0.003)
    deepest = min(sup.hosts.values()) if sup.hosts else 0.0
    counted: list[Hit] = []
    held: set[str] = set()
    standing: set[str] = set()
    deeper: list[Hit] = []
    for h in hits:
        on = [g for g in sup.standers if h.other in boxes and h.other not in sup.partners
              and not is_run(scene, h.other) and stands_on(boxes[g], boxes[h.other], gap)]
        if not on:
            counted.append(h)
            continue
        if h.other in sup.hosts:            # what it stood on: kept as it was, or sunk deeper into it
            standing.update(on)
            (held.add(h.other) if h.distance_m >= min(sup.hosts[h.other], 0.0) - 0.002 else deeper.append(h))
        elif h.distance_m >= min(deepest, 0.0) - 0.002:   # something like it, no deeper (the next bay of slab)
            standing.update(on)
            held.add(h.other)
        else:                               # something else it now cuts into: a clash like any other
            counted.append(h)
    why = None
    floating = sup.standers - standing
    if floating:
        names = ", ".join(f"'{scene.element(g).name}'" for g in sorted(floating))
        under = ", ".join(f"'{scene.element(g).name}'" for g in sorted(sup.hosts))
        they = "it" if len(floating) == 1 else "they"
        why = f"would leave {names} standing on nothing ({they} stood on {under}): keep it on what carries it"
    elif deeper:
        h = min(deeper, key=lambda x: x.distance_m)
        why = f"sinks deeper into {h.other_class} '{scene.element(h.other).name}' ({h.distance_m * 1000:+.0f} mm)"
    return counted, held, why
