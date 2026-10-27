"""The geometry check. It is the authority for every clearance number Sightline shows.

The browser triangulates with web-ifc and this side with IfcOpenShell, so the two can differ by a
millimetre or so; the UI always displays these numbers, never its own.
"""
from __future__ import annotations

from dataclasses import dataclass

import ifcopenshell.geom

from .scene import IfcScene

# How far to look for the nearest neighbour, so a passing fix can still report its real clearance.
SEARCH_M = 0.5


@dataclass
class Hit:
    other: str          # GlobalId of the element hit
    other_class: str
    kind: str           # "collision" (hard) or "clearance" (closer than required)
    distance_m: float   # signed: negative = penetration depth, positive = gap


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


def check(scene: IfcScene, moved: list[str], clearance_m: float = 0.025,
          ignore: set[str] | None = None) -> Verdict:
    """Check the moved elements against every other element in the model.

    A fix passes when nothing penetrates the moved elements and nothing sits closer than
    `clearance_m`. `ignore` holds elements that are meant to touch (e.g. the rest of the moved run).
    """
    ignore = set(ignore or ()) | set(moved)
    others = [p for p in scene.products() if p.GlobalId not in ignore]
    targets = [scene.entity(g) for g in moved]

    # The default "opencascade.brep" tree has no *_many clash queries; the triangle BVH tree does.
    tree = ifcopenshell.geom.tree(backend="opencascade.trianglebvh")
    tree.add_iterator(ifcopenshell.geom.iterator(_settings(), scene.model, include=others + targets))

    def other_of(c):
        return c.b if c.a.GlobalId in moved else c.a

    hits: dict[str, Hit] = {}
    # Intersection, not collision: collision only sees crossing triangles and misses one element
    # sitting wholly inside another (a pipe inside a duct), which intersection reports with its depth.
    for c in tree.clash_intersection_many(targets, others, tolerance=0.002, check_all=True):
        o = other_of(c)
        hits[o.GlobalId] = Hit(o.GlobalId, o.is_a(), "collision", -abs(float(c.distance)))

    nearest = None
    for c in tree.clash_clearance_many(targets, others, clearance=SEARCH_M, check_all=True):
        o = other_of(c)
        if o.GlobalId in hits:
            continue
        gap = float(c.distance)
        nearest = gap if nearest is None else min(nearest, gap)
        if gap < clearance_m:
            hits[o.GlobalId] = Hit(o.GlobalId, o.is_a(), "clearance", gap)

    return Verdict(passed=not hits, hits=sorted(hits.values(), key=lambda h: h.distance_m),
                   min_clearance_m=nearest, checked_against=len(others))
