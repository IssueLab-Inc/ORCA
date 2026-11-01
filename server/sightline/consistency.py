"""Model consistency: what an edit must keep true besides the shape (docs/editing-parity.md).

Real models say how big an element is apart from its body: a wall's material layers add up to its thickness, a beam's
material profile is its section, its `Axis` runs its length, a path join says where two walls meet, its base
quantities give its sizes, and a body drawn from a type is every element of that type. An edit that changes the body
and not that data leaves the model saying two things.

`measure` reads, per element and rule, the numbers an edit keeps when it is consistent (a layered wall: its layers'
sum less its body's thickness); `compare` takes a reading before an edit and one after: a rule whose numbers changed is
an issue. Comparing the model with itself, never with an ideal, means a model that was already inconsistent never
blocks an edit; only what the edit makes worse does. `block` issues refuse the edit (`manual.check`); `warn` issues
are listed with it and kept in the log.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import numpy as np

from .scene import IfcScene

LENGTH_TOL_M = 0.001     # a layer sum, an axis end or a profile size this much off is a change
JOIN_TOL_M = 0.005       # a path join's end this much further from the other element no longer meets it
VOLUME_TOL = 0.001       # a body whose volume changed by this share has new sizes for its quantities

AXES = {"AXIS1": 0, "AXIS2": 1, "AXIS3": 2}
PROFILE_SIZES = ("XDim", "YDim", "Radius", "OverallWidth", "OverallDepth", "WebThickness", "FlangeThickness",
                 "Depth", "Width", "Thickness", "FlangeWidth", "WallThickness")


@dataclass
class Issue:
    element: str
    rule: str          # layers, profile, axis, joins, type, quantities
    severity: str      # block or warn
    text: str

    def to_dict(self) -> dict:
        return {"element": self.element, "rule": self.rule, "severity": self.severity, "text": self.text}


@dataclass
class Reading:
    element: str
    rule: str
    values: tuple
    words: dict


def _label(scene: IfcScene, gid: str) -> str:
    e = scene.entity(gid)
    return f"'{e.Name}'" if getattr(e, "Name", None) else e.is_a()


def _local_verts(entity) -> np.ndarray | None:
    """The body's vertices in the element's own placement, in metres; None when it cannot be built."""
    settings = ifcopenshell.geom.settings()
    try:
        shape = ifcopenshell.geom.create_shape(settings, entity)
    except Exception:
        return None
    v = np.asarray(shape.geometry.verts, float).reshape(-1, 3)
    return v if len(v) else None


def _volume(entity) -> float | None:
    try:
        shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), entity)
        return float(ifcopenshell.util.shape.get_volume(shape.geometry))
    except Exception:
        return None


def _body(entity):
    rep = entity.Representation
    for r in (rep.Representations if rep else []):
        if r.RepresentationIdentifier == "Body":
            return r
    return None


def _swept_area(entity):
    """The profile of the body's one extrusion (through any clips), or None."""
    body = _body(entity)
    if body is None or len(body.Items) != 1:
        return None
    item = body.Items[0]
    while item.is_a("IfcBooleanResult"):
        item = item.FirstOperand
    return item.SweptArea if item.is_a("IfcSweptAreaSolid") else None


def _profile_sizes(profile, scale: float) -> tuple:
    return (profile.is_a(), *(round(float(getattr(profile, a)) * scale, 6) for a in PROFILE_SIZES
                              if getattr(profile, a, None) is not None))


def _axis_points(entity, scale: float) -> np.ndarray | None:
    """The `Axis` representation's first and last points in the element's placement, in metres."""
    rep = entity.Representation
    for r in (rep.Representations if rep else []):
        if r.RepresentationIdentifier != "Axis" or not r.Items:
            continue
        curve = r.Items[0]
        if curve.is_a("IfcPolyline"):
            pts = [p.Coordinates for p in curve.Points]
        elif curve.is_a("IfcIndexedPolyCurve"):
            pts = list(curve.Points.CoordList)
        else:
            continue
        if len(pts) < 2:
            continue
        ends = np.zeros((2, 3))
        for k, p in enumerate((pts[0], pts[-1])):
            ends[k, :len(p)] = np.asarray(p, float) * scale
        return ends
    return None


def _digest(model, roots) -> str:
    """Everything under some entities, as a digest: changed when any of it changed."""
    h = hashlib.sha1()
    for root in roots:
        for e in sorted(model.traverse(root), key=lambda x: x.id()):
            h.update(str(e).encode())
    return h.hexdigest()


def _type_digest(model, rtype) -> str:
    """What a type's maps draw, as a digest."""
    return _digest(model, rtype.RepresentationMaps or [])


def users(model, mset) -> set:
    """Every element a material set reaches: through its usages, and through the types it is assigned to."""
    out = set()
    for inv in model.get_inverse(mset):
        if inv.is_a("IfcMaterialLayerSetUsage") or inv.is_a("IfcMaterialProfileSetUsage"):
            for rel in model.get_inverse(inv):
                if rel.is_a("IfcRelAssociatesMaterial"):
                    out.update(rel.RelatedObjects)
        elif inv.is_a("IfcRelAssociatesMaterial"):
            for o in inv.RelatedObjects:
                out.update(ifcopenshell.util.element.get_types(o) if o.is_a("IfcTypeObject") else [o])
    return {o for o in out if not o.is_a("IfcTypeObject")}


def _material_set(mat):
    if mat is None:
        return None
    if mat.is_a("IfcMaterialLayerSetUsage"):
        return mat.ForLayerSet
    if mat.is_a("IfcMaterialProfileSetUsage"):
        return mat.ForProfileSet
    return mat if mat.is_a("IfcMaterialLayerSet") or mat.is_a("IfcMaterialProfileSet") else None


def measure(scene: IfcScene, gids, label: Callable[[IfcScene, str], str] = _label) -> dict[tuple, Reading]:
    """Per element and rule, the numbers a consistent edit keeps (see the module's docstring); `label` names elements
    in the words the issues use."""
    out: dict[tuple, Reading] = {}
    seen_rels: set[int] = set()
    for gid in dict.fromkeys(gids):
        if not scene.has(gid):
            continue
        e = scene.entity(gid)
        model = scene.models[scene.index_of(gid)]
        s = scene.unit_scales[scene.index_of(gid)]
        name = label(scene, gid)
        verts = None

        def local():
            nonlocal verts
            if verts is None:
                verts = _local_verts(e)
            return verts

        mat = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
        if mat is not None and mat.is_a("IfcMaterialLayerSetUsage") and mat.ForLayerSet is not None:
            total = sum(float(l.LayerThickness or 0) for l in mat.ForLayerSet.MaterialLayers) * s
            v = local()
            if v is not None and mat.LayerSetDirection in AXES:
                k = AXES[mat.LayerSetDirection]
                thick = float(v[:, k].max() - v[:, k].min())
                out[(gid, "layers")] = Reading(gid, "layers", (round(total - thick, 6),),
                                               {"name": name, "sum": total, "thick": thick})
        if mat is not None and mat.is_a("IfcMaterialProfileSetUsage") and mat.ForProfileSet is not None:
            ps = mat.ForProfileSet
            prof = ps.CompositeProfile or (ps.MaterialProfiles[0].Profile if ps.MaterialProfiles else None)
            swept = _swept_area(e)
            if prof is not None and swept is not None:
                a, b = _profile_sizes(swept, s), _profile_sizes(prof, s)
                diff = tuple(round(x - y, 6) for x, y in zip(a[1:], b[1:])) if a[0] == b[0] and len(a) == len(b) else a
                out[(gid, "profile")] = Reading(gid, "profile", diff, {"name": name, "profile": prof.ProfileName or prof.is_a()})
        ends = _axis_points(e, s)
        if ends is not None:
            v = local()
            run = np.linalg.norm(ends[1] - ends[0])
            if v is not None and run > 1e-9:
                u = (ends[1] - ends[0]) / run
                t = (v - ends[0]) @ u
                out[(gid, "axis")] = Reading(gid, "axis", (round(float(t.min()), 6), round(float(t.max() - run), 6)),
                                             {"name": name, "axis": run, "body": float(t.max() - t.min())})
        for rel in [*getattr(e, "ConnectedTo", []), *getattr(e, "ConnectedFrom", [])]:
            if rel.is_a("IfcRelConnectsPathElements") and rel.id() not in seen_rels:
                seen_rels.add(rel.id())
                gap = _join_gap(scene, rel)
                if gap is not None:
                    a, b = rel.RelatingElement.GlobalId, rel.RelatedElement.GlobalId
                    out[(gid, "joins", rel.id())] = Reading(gid, "joins", (round(gap, 6),),
                                                           {"name": label(scene, a), "other": label(scene, b)})
        mset = _material_set(mat)
        if mset is not None:
            out[(gid, "shared")] = Reading(gid, "shared", (mset.id(), _digest(model, [mset])),
                                           {"name": name, "others": len(users(model, mset) - {e}),
                                            "set": "layer" if mset.is_a("IfcMaterialLayerSet") else "profile"})
        rtype = ifcopenshell.util.element.get_type(e)
        if rtype is not None and getattr(rtype, "RepresentationMaps", None):
            out[(gid, "type", rtype.id())] = Reading(gid, "type", (_type_digest(model, rtype),),
                                                    {"name": name, "type": rtype.Name or rtype.is_a()})
        qtos = {k: v for k, v in ifcopenshell.util.element.get_psets(e, qtos_only=True).items()
                if k.startswith("Qto_") and k.endswith("BaseQuantities")}
        if qtos:
            values = tuple(sorted((f"{q}.{n}", round(float(x), 6)) for q, d in qtos.items() for n, x in d.items()
                                  if n != "id" and isinstance(x, (int, float))))
            out[(gid, "quantities")] = Reading(gid, "quantities", (_volume(e), values),
                                               {"name": name, "qtos": ", ".join(sorted(qtos))})
    return out


def _join_gap(scene: IfcScene, rel) -> float | None:
    """How far a path join's ends (ATSTART/ATEND) are from the other element's axis in plan (a wall's path is drawn in
    plan: one moved up still meets), in metres; None when neither side can say (no axis)."""
    sides = ((rel.RelatingElement, rel.RelatingConnectionType, rel.RelatedElement),
             (rel.RelatedElement, rel.RelatedConnectionType, rel.RelatingElement))
    worst = None
    for el, at, other in sides:
        if at not in ("ATSTART", "ATEND"):
            continue
        mine, theirs = _world_axis(scene, el), _world_axis(scene, other)
        if mine is None or theirs is None:
            continue
        p = (mine[0] if at == "ATSTART" else mine[1])[:2]
        a, b = theirs[0][:2], theirs[1][:2]
        ab = b - a
        t = float(np.clip((p - a) @ ab / max(ab @ ab, 1e-12), 0.0, 1.0))
        d = float(np.linalg.norm(p - (a + t * ab)))
        worst = d if worst is None else max(worst, d)
    return worst


def _world_axis(scene: IfcScene, entity) -> np.ndarray | None:
    gid = entity.GlobalId
    if not scene.has(gid):
        return None
    ends = _axis_points(entity, scene.unit_scales[scene.index_of(gid)])
    if ends is None:
        return None
    m = scene.placement(gid)
    return (m[:3, :3] @ ends.T).T + m[:3, 3]


def compare(scene: IfcScene, before: dict[tuple, Reading], after: dict[tuple, Reading],
            made_from: str | None = None, allow: frozenset[str] = frozenset()) -> list[Issue]:
    """The issues an edit makes: each reading after that changed from its reading before. An element the edit made
    (no reading before) is compared with the element it was made from (`made_from`), else with a consistent one.
    `allow` lists rules the edit keeps on purpose (an edit to the type itself)."""
    out: list[Issue] = []
    for key, r in after.items():
        if r.rule in allow:
            continue
        was = before.get(key)
        if was is None and made_from is not None:
            was = before.get((made_from, *key[1:]))
        issue = _changed(scene, r, was)
        if issue is not None:
            out.append(issue)
    return out


def _changed(scene: IfcScene, r: Reading, was: Reading | None) -> Issue | None:
    w = r.words
    if r.rule == "layers":
        base = was.values[0] if was else 0.0
        if abs(r.values[0] - base) > LENGTH_TOL_M:
            return Issue(r.element, "layers", "block",
                         f"the material layers of {w['name']} add up to {w['sum'] * 1000:.0f} mm but its body would be "
                         f"{w['thick'] * 1000:.0f} mm thick: a layered element's thickness cannot change by hand yet")
    elif r.rule == "profile":
        base = was.values if was else tuple(0.0 for _ in r.values)
        if len(base) != len(r.values) or any(
                (abs(a - b) > LENGTH_TOL_M if isinstance(a, float) and isinstance(b, float) else a != b)
                for a, b in zip(r.values, base)):
            return Issue(r.element, "profile", "block",
                         f"the section of {w['name']} would no longer be its material profile ({w['profile']}): a "
                         "profile set's section cannot change by hand yet")
    elif r.rule == "axis":
        base = was.values if was else (0.0, 0.0)
        if any(abs(a - b) > LENGTH_TOL_M for a, b in zip(r.values, base)):
            return Issue(r.element, "axis", "block",
                         f"the axis of {w['name']} ({w['axis']:.3f} m) would no longer run its body ({w['body']:.3f} m): "
                         "an element drawn with an axis cannot change its length by hand yet")
    elif r.rule == "joins":
        base = was.values[0] if was else 0.0
        if r.values[0] - base > JOIN_TOL_M:
            return Issue(r.element, "joins", "block",
                         f"{w['name']} and {w['other']} are joined (a path join) and would no longer meet "
                         f"({r.values[0] * 1000:.0f} mm apart): moving a joined wall's end cannot keep its join yet")
    elif r.rule == "shared":
        if was is not None and r.values[0] == was.values[0] and r.values[1] != was.values[1] and w["others"]:
            return Issue(r.element, "shared", "block",
                         f"the {w['set']} set of {w['name']} is shared by {w['others']} other "
                         f"element{'s' if w['others'] > 1 else ''}: changing it would change them too")
    elif r.rule == "type":
        if was is not None and r.values != was.values:
            return Issue(r.element, "type", "block",
                         f"the shape of {w['name']} comes from its type {w['type']}: changing it would change every "
                         "element of that type")
    elif r.rule == "quantities":
        if was is None:
            return None
        (v0, q0), (v1, q1) = was.values, r.values
        if v0 is not None and v1 is not None and abs(v1 - v0) > max(1e-9, VOLUME_TOL * abs(v0)) and q0 == q1:
            return Issue(r.element, "quantities", "warn",
                         f"the base quantities of {w['name']} ({w['qtos']}) still give its old sizes")
    return None
