"""Which elements can take an opening for a service, and how big (docs/edits.md "Which hosts").

A wall or a floor is opened for services all the time; a transfer girder never; a steel beam's web sometimes, within
limits; a machine panel's gland plate is made to be drilled. Three layers decide, strictest first:

1. **Hard rules** (`hard_rule`, no model call, nothing overrides them): columns, doors, windows, glazing, piles,
   footings, stairs, services and equipment, see-through zones, anything not physical, and any beam or member a
   column or wall stands on (a transfer element, found from the geometry).
2. **The coordination requirements** (`penetrations` rules per group: allowed, review or never, and a largest size).
3. **Muse's reading of each kind of host** (`read`, on the triage model, cached by kind): allowed, with review, not
   advised or never; who reviews; whether the service passes with clearance round it (a sleeve, fire-stopping) or
   through a fitted gland; limits (deepest hole for the host's depth, distance from its ends and edges, the middle
   third of a beam's depth); conditions. Facts only, as text: class, type, name, material, size, the standard
   properties and the discipline. Nothing from a project's own property sets (a demo model's answer key lives there).

Then the geometry checks the actual hole against the reading's limits (`check_hole`), and the option shows the
numbers. Without a reading (no model, or it failed), walls and slabs take an opening as before and nothing else does.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

import ifcopenshell.util.element
import numpy as np

from . import edits
from .scene import IfcScene, not_physical, step_source

PROMPT = Path(__file__).parent / "domain_packs" / "penetrations.md"
VERDICTS = ("allowed", "with_review", "not_advised", "never")
REVIEWERS = ("structure", "architecture", "fire", "safety", "services")
NEVER = {
    "IfcColumn": "a column is never cut for a service",
    "IfcDoor": "a door is never cut for a service", "IfcWindow": "a window is never cut for a service",
    "IfcCurtainWall": "a curtain wall is never cut for a service",
    "IfcPile": "a pile is never cut for a service", "IfcFooting": "a footing is never cut for a service",
    "IfcStair": "a stair is never cut for a service", "IfcStairFlight": "a stair is never cut for a service",
    "IfcRamp": "a ramp is never cut for a service", "IfcRampFlight": "a ramp is never cut for a service",
    "IfcRailing": "a railing is never cut for a service",
    "IfcTransportElement": "a lift or conveyor is never cut for a service",
    "IfcDistributionElement": "a service or a piece of equipment is never cut for another service: use its own "
                              "cable entry, gland plate or connection",
}
STANDS_ON_M = 0.005   # a column or wall whose foot is this close to a beam's top stands on it


@dataclass
class Reading:
    verdict: str                      # allowed | with_review | not_advised | never
    reviewer: str | None = None       # structure | architecture | fire | safety | services
    fit: str = "annular"              # "annular": clearance all round (sleeve, fire-stopping); "fitted": a gland fits it
    limits: dict = field(default_factory=dict)  # max_depth_ratio, keep_from_ends_depths, keep_from_edges_m, zone
    conditions: list[str] = field(default_factory=list)
    reasoning: str = ""
    source: str = "muse"              # rule | requirements | muse | default
    kind: str = ""                    # the kind of host, in words

    @property
    def refuses(self) -> bool:
        return self.verdict in ("not_advised", "never")


SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["readings"],
    "properties": {"readings": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "verdict", "reviewer", "fit", "limits", "conditions", "reasoning"],
        "properties": {
            "kind": {"type": "string"},
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "reviewer": {"type": "string", "enum": [*REVIEWERS, "none"]},
            "fit": {"type": "string", "enum": ["annular", "fitted"]},
            "limits": {"type": "object", "additionalProperties": False,
                       "required": ["max_depth_ratio", "keep_from_ends_depths", "keep_from_edges_m", "zone"],
                       "properties": {"max_depth_ratio": {"type": ["number", "null"]},
                                      "keep_from_ends_depths": {"type": ["number", "null"]},
                                      "keep_from_edges_m": {"type": ["number", "null"]},
                                      "zone": {"type": "string", "enum": ["any", "middle_third"]}}},
            "conditions": {"type": "array", "items": {"type": "string"}},
            "reasoning": {"type": "string"}}}}},
}

_cache: dict[str, Reading] = {}
_cache_lock = threading.Lock()


# ------------------------------------------------------------------------------------------------- hard rules

def _alpha(element) -> float:
    """The element's style opacity (1 when it has none): see-through volumes are zones, not things."""
    rep = element.Representation
    for r in (rep.Representations if rep else []):
        for item in r.Items:
            for styled in item.StyledByItem or []:
                for st in styled.Styles:
                    for s in (st.Styles if st.is_a("IfcPresentationStyleAssignment") else [st]):
                        for x in getattr(s, "Styles", None) or []:
                            t = getattr(x, "Transparency", None)
                            if t is not None:
                                return 1.0 - float(t)
    return 1.0


def stands_on(scene: IfcScene, host_gid: str) -> str | None:
    """A column or wall standing on `host` (a beam or member): the name of the first, or None."""
    boxes = scene.bounds()
    hb = boxes.get(host_gid)
    if hb is None:
        return None
    for p in scene.products():
        if not (p.is_a("IfcColumn") or p.is_a("IfcWall")) or p.GlobalId == host_gid or p.GlobalId not in boxes:
            continue
        b = boxes[p.GlobalId]
        if abs(b[0][2] - hb[1][2]) <= STANDS_ON_M and (b[0][:2] < hb[1][:2] - 1e-3).all() and (b[1][:2] > hb[0][:2] + 1e-3).all():
            return p.Name or p.is_a()
    return None


def hard_rule(scene: IfcScene, host_gid: str) -> str | None:
    """Why `host` may never take an opening, whatever anyone says, or None."""
    e = scene.entity(host_gid)
    if not_physical(e) or host_gid not in scene.bounds():
        return "it is not a physical element"
    for cls, why in NEVER.items():
        if e.is_a(cls):
            return why
    mat = ifcopenshell.util.element.get_material(e, should_skip_usage=True)
    words = " ".join(filter(None, [e.Name, getattr(e, "ObjectType", None), getattr(mat, "Name", None)])).lower()
    if (e.is_a("IfcPlate") or e.is_a("IfcWindow")) and ("glaz" in words or "glass" in words or "vision" in words):
        return "glazing is never cut for a service"   # an opaque spandrel panel is Muse's to read
    if _alpha(e) < 0.5 and e.is_a("IfcBuildingElementProxy"):
        return "it is a zone (a clearance or working space), not a thing to cut"
    if e.is_a("IfcBeam") or e.is_a("IfcMember"):
        above = stands_on(scene, host_gid)
        if above:
            return f"it is a transfer element: {above} stands on it"
    return None


# ------------------------------------------------------------------------------------------------- what Muse reads

STANDARD = ("LoadBearing", "IsExternal", "FireRating", "AcousticRating", "Combustible", "Status", "Reference")


def profile(scene: IfcScene, host_gid: str) -> dict:
    """The facts Muse reads about a host, and the key of its kind (hosts alike in everything but their place and
    number read once). Only standard `Pset_*Common` properties: a project's own property sets can hold anything."""
    e = scene.entity(host_gid)
    psets = ifcopenshell.util.element.get_psets(e)
    props = {k: v for name, d in psets.items() if name.startswith("Pset_") and name.endswith("Common")
             for k, v in d.items() if k in STANDARD and v not in (None, "")}
    materials = []
    mat = ifcopenshell.util.element.get_material(e, should_skip_usage=True)
    if mat is not None:
        for m in (getattr(mat, "Materials", None) or [getattr(mat, "Material", None) or mat]):
            if getattr(m, "Name", None):
                materials.append(m.Name)
        for layer in getattr(mat, "MaterialLayers", None) or []:
            if layer.Material is not None:
                materials.append(f"{layer.Material.Name} {layer.LayerThickness * scene.unit_scales[scene.index_of(host_gid)] * 1000:.0f} mm")
    box = scene.bounds()[host_gid]
    size = sorted((box[1] - box[0]) * 1000)
    from .requirements import _file_teams
    team = _file_teams(scene)[scene.index_of(host_gid)]
    kind = {"class": e.is_a(), "type": getattr(e, "PredefinedType", None) or None,
            "object_type": getattr(e, "ObjectType", None) or None,
            "name": re.sub(r"\s+", " ", re.sub(r"[\d.]+(?:\s*mm)?|[-–/,()]", " ", e.Name or "")).strip().lower()[:60],
            "materials": sorted(set(materials)), "thinnest_mm": round(size[0] / 10) * 10, "properties": props,
            "discipline": team, "assembly": step_source(e).get("Group", "")}
    facts = {**kind, "name": e.Name or "", "box_mm": [round(v) for v in size]}
    return {"key": hashlib.sha256(json.dumps(kind, sort_keys=True, default=str).encode()).hexdigest()[:16],
            "facts": facts}


def _facts_text(kind: str, facts: dict) -> str:
    bits = [f"{facts['class']}" + (f" {facts['type']}" if facts["type"] not in (None, "NOTDEFINED", "USERDEFINED") else "")
            + (f" ({facts['object_type']})" if facts["object_type"] else ""),
            f"named '{facts['name']}'", f"box {' x '.join(str(v) for v in facts['box_mm'])} mm",
            f"from the {facts['discipline']} model"]
    if facts["materials"]:
        bits.append("material " + ", ".join(facts["materials"]))
    if facts["properties"]:
        bits.append("properties " + ", ".join(f"{k}={v}" for k, v in facts["properties"].items()))
    if facts["assembly"]:
        bits.append(f"part of assembly '{facts['assembly']}'")
    return f"- kind {kind}: " + "; ".join(bits)


def read(model, profiles: list[dict]) -> dict[str, Reading]:
    """Muse's reading of each kind of host not read before (one call for all of them); cached by kind."""
    with _cache_lock:
        todo = {p["key"]: p for p in profiles if p["key"] not in _cache}
    if todo and model is not None:
        text = "Hosts a service would pass through:\n" + "\n".join(_facts_text(k, p["facts"]) for k, p in todo.items())
        reply = model.complete_json(PROMPT.read_text(), text, [], schema=SCHEMA)  # type: ignore[call-arg]
        got = {}
        for r in reply.get("readings") or []:
            k = r.get("kind", "")
            if k not in todo or r.get("verdict") not in VERDICTS:
                continue
            limits = {x: v for x, v in (r.get("limits") or {}).items() if v is not None}
            got[k] = Reading(r["verdict"], r.get("reviewer") if r.get("reviewer") in REVIEWERS else None,
                             "fitted" if r.get("fit") == "fitted" else "annular", limits,
                             [c for c in r.get("conditions") or [] if c], r.get("reasoning", ""), "muse",
                             todo[k]["facts"]["name"])
        with _cache_lock:
            _cache.update(got)
    with _cache_lock:
        return {p["key"]: _cache[p["key"]] for p in profiles if p["key"] in _cache}


def cached(scene: IfcScene, host_gid: str) -> Reading | None:
    key = profile(scene, host_gid)["key"]
    with _cache_lock:
        return _cache.get(key)


def default(scene: IfcScene, host_gid: str) -> Reading:
    """Without a reading: walls and slabs take an opening (a slab or load-bearing wall reviewed by structure), nothing
    else does."""
    e = scene.entity(host_gid)
    if any(e.is_a(c) for c in edits.PENETRABLE):
        common = ifcopenshell.util.element.get_psets(e).get("Pset_SlabCommon" if e.is_a("IfcSlab") else "Pset_WallCommon", {})
        reviewer = "structure" if e.is_a("IfcSlab") or common.get("LoadBearing") else "architecture"
        rating = common.get("FireRating")
        return Reading("with_review", reviewer, "annular", {},
                       [f"fire-stopping to the host's {rating} rating"] if rating else [], "", "default")
    return Reading("not_advised", None, "annular", {}, [], f"No reading of this kind of host ({e.is_a()}): only walls and "
                   "slabs take an opening without one.", "default")


def decide(scene: IfcScene, host_gid: str, doc=None, matcher=None) -> Reading:
    """What may be done to `host`: a hard rule, else the requirements' rule for its group, else Muse's reading (from
    the cache: `read` first), else the default."""
    why = hard_rule(scene, host_gid)
    if why:
        return Reading("never", None, "annular", {}, [], why[0].upper() + why[1:] + ".", "rule")
    base = cached(scene, host_gid) or default(scene, host_gid)
    rule = None
    if doc is not None and getattr(doc, "penetrations", None):
        from . import requirements
        rule = requirements.penetration_rule(doc, matcher or requirements.Matcher(scene, doc), host_gid)
    if rule is None:
        return base
    verdict = {"allowed": "allowed", "review": "with_review", "never": "never"}[rule.rule]
    limits = {**base.limits, **({"max_size_m": rule.max_mm / 1000} if rule.max_mm else {})}
    return Reading(verdict, rule.reviewer or base.reviewer, base.fit, limits, base.conditions,
                   f"Requirements: {rule.group_name} {rule.rule}" + (f", up to {rule.max_mm} mm" if rule.max_mm else "")
                   + (f". Muse's reading: {base.reasoning}" if base.reasoning else "."), "requirements", base.kind)


# ------------------------------------------------------------------------------------------------- the actual hole

def check_hole(scene: IfcScene, pen: "edits.Penetration", reading: Reading) -> tuple[list[str], list[str]]:
    """The hole against the reading's limits: (problems, numbers), both in plain words. The host's depth is its
    smaller size in the hole's plane (a beam's depth for a pipe through its web); its ends are those of its longer
    size there; edges are found by rays from just outside the hole."""
    box = scene.bounds()[pen.host]
    centre = np.asarray(pen.start) + np.asarray(pen.axis) * pen.depth_m / 2
    px = np.asarray(pen.xdir, float)
    py = np.cross(np.asarray(pen.axis, float), px)
    corners = np.array([[x, y, z] for x in box[:, 0] for y in box[:, 1] for z in box[:, 2]])
    problems, numbers = [], []
    sizes = {"x": pen.width_m, "y": pen.height_m}
    extent = {}
    for name, v in (("x", px), ("y", py)):
        proj = corners @ v
        extent[name] = (float(proj.min() - centre @ v), float(proj.max() - centre @ v))
    # The host's depth across the hole: its smaller extent in the hole's plane.
    depth_axis = min(extent, key=lambda n: extent[n][1] - extent[n][0])
    depth = extent[depth_axis][1] - extent[depth_axis][0]
    ratio = sizes[depth_axis] / depth if depth > 0 else 1.0
    lim = reading.limits
    numbers.append(f"hole {sizes[depth_axis] * 1000:.0f} mm in {depth * 1000:.0f} mm of host ({ratio:.0%})")
    if lim.get("max_depth_ratio") and ratio > lim["max_depth_ratio"] + 1e-6:
        problems.append(f"the hole is {ratio:.0%} of the host's {depth * 1000:.0f} mm depth (at most "
                        f"{lim['max_depth_ratio']:.0%})")
    if lim.get("max_size_m") and max(pen.width_m, pen.height_m) > lim["max_size_m"] + 1e-6:
        problems.append(f"the hole is {max(pen.width_m, pen.height_m) * 1000:.0f} mm (the requirements allow at most "
                        f"{lim['max_size_m'] * 1000:.0f} mm)")
    if lim.get("zone") == "middle_third":
        lo, hi = extent[depth_axis]
        off = -(lo + hi) / 2   # the hole's centre from the middle of the depth
        if abs(off) + sizes[depth_axis] / 2 > depth / 6 + 1e-6:
            problems.append(f"the hole is not in the middle third of the host's depth ({off * 1000:+.0f} mm off centre)")
    long_axis = max(extent, key=lambda n: extent[n][1] - extent[n][0])
    to_end = min(-extent[long_axis][0], extent[long_axis][1]) - sizes[long_axis] / 2
    if lim.get("keep_from_ends_depths"):
        need = lim["keep_from_ends_depths"] * depth
        numbers.append(f"{to_end * 1000:.0f} mm from its nearest end")
        if to_end < need - 1e-6:
            problems.append(f"the hole is {to_end * 1000:.0f} mm from the host's end (keep {need * 1000:.0f} mm: "
                            f"{lim['keep_from_ends_depths']:g} x its depth)")
    if lim.get("keep_from_edges_m"):
        need = float(lim["keep_from_edges_m"])
        tris = edits._host_tris(scene, pen.host)
        back = centre - np.asarray(pen.axis) * (pen.depth_m / 2 + 0.5)
        edge = None
        for v, half in ((px, pen.width_m / 2), (-px, pen.width_m / 2), (py, pen.height_m / 2), (-py, pen.height_m / 2)):
            probe = back + v * (half + need)
            if not np.isfinite(edits._first_hit(probe[None], np.asarray(pen.axis, float), tris)).any():
                edge = v
                break
        if edge is not None:
            problems.append(f"the hole is closer than {need * 1000:.0f} mm to the host's edge")
        else:
            numbers.append(f"at least {need * 1000:.0f} mm from its edges")
    return problems, numbers


def reading_text(r: Reading) -> str:
    """A reading in a sentence, for Muse and the option."""
    who = f", reviewed by {r.reviewer}" if r.reviewer else ""
    lim = r.limits
    parts = []
    if lim.get("max_depth_ratio"):
        parts.append(f"a hole at most {lim['max_depth_ratio']:.0%} of its depth")
    if lim.get("zone") == "middle_third":
        parts.append("in the middle third of its depth")
    if lim.get("keep_from_ends_depths"):
        parts.append(f"{lim['keep_from_ends_depths']:g} x its depth from its ends")
    if lim.get("keep_from_edges_m"):
        parts.append(f"{lim['keep_from_edges_m'] * 1000:.0f} mm from its edges")
    if lim.get("max_size_m"):
        parts.append(f"at most {lim['max_size_m'] * 1000:.0f} mm across")
    verdict = {"allowed": "allowed", "with_review": "allowed with review", "not_advised": "not advised",
               "never": "never"}[r.verdict]
    fit = "; a fitted gland, no clearance round it" if r.fit == "fitted" else ""
    return (f"{verdict}{who}" + (f" ({'; '.join(parts)})" if parts else "") + fit
            + (f"; needs {'; '.join(r.conditions)}" if r.conditions else ""))


def as_dict(r: Reading) -> dict:
    return asdict(r)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
