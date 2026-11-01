"""Keep what the model says besides the shape true after an edit (docs/editing-parity.md, Tier 1).

An edit changes an element's body; this brings the rest of what the model says about its size along: a layered wall or
slab's layers, a profile set's section, its `Axis`, its base quantities, and its path joins. It works from a reading
before the edit (`snapshot`) and the body after it (`sync`), so data that was already out of line stays as it was:
only what the edit moved is moved with it.

Shared data is copied for the edited element first (owner decision, Nov 1): a layer or profile set its type gives
other elements too means a copy of the type ("… (ORCA)") with the element reassigned to it; a set shared some other
way, a copy of the set. Other elements of the type never change.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import ifcopenshell.api
import ifcopenshell.util.element
import numpy as np

from . import consistency, edits, quantities
from .scene import IfcScene

MIN_LAYER_M = 0.001    # the least a layer keeps when a face is pulled in through it


@dataclass
class Before:
    """What an element's body and data said before the edit."""
    extent: dict[int, tuple[float, float]] = field(default_factory=dict)   # body's min and max along local x, y, z
    axis: tuple[float, float] | None = None       # where the body starts and ends along its Axis, from its ends
    volume: float | None = None
    joins: dict[int, float] = field(default_factory=dict)                  # path join id: its gap in plan


@dataclass
class Synced:
    notes: list[str] = field(default_factory=list)      # what was brought along, in words, for the summary
    opened: list[dict] = field(default_factory=list)    # path joins left open: {"element", "name"}
    left: list[str] = field(default_factory=list)       # base quantities left as they were


def snapshot(scene: IfcScene, gids) -> dict[str, Before]:
    """Read each element's body and data before an edit, for `sync` (elements with nothing to keep are skipped)."""
    out = {}
    readings = consistency.measure(scene, gids)
    for gid in dict.fromkeys(gids):
        if not scene.has(gid):
            continue
        e = scene.entity(gid)
        mine = {k: r for k, r in readings.items() if k[0] == gid}
        if not mine:
            continue
        b = Before()
        v = consistency._local_verts(e)
        if v is not None:
            b.extent = {k: (float(v[:, k].min()), float(v[:, k].max())) for k in range(3)}
        if (gid, "axis") in mine:
            b.axis = mine[(gid, "axis")].values
        if (gid, "quantities") in mine:
            b.volume = mine[(gid, "quantities")].values[0]
        b.joins = {k[2]: r.values[0] for k, r in mine.items() if k[1] == "joins"}
        out[gid] = b
    return out


def sync(scene: IfcScene, before: dict[str, Before], changed, created=(), made_from: str | None = None,
         label=consistency._label) -> Synced:
    """After an edit (inside its transaction): bring each changed or made element's data along with its body. An element
    the edit made is read against the element it was made from. Raises `edits.Unsupported` when it cannot (a layer
    pulled in past its thickness)."""
    done = Synced()
    todo = []
    for gid in dict.fromkeys([*changed, *created]):
        if not scene.has(gid):
            continue
        was = before.get(gid) or (before.get(made_from) if made_from else None)
        if was is None:
            continue
        e = scene.entity(gid)
        if gid not in before and was.axis is not None and made_from and scene.has(made_from):
            _give_axis(scene, scene.entity(made_from), e)   # a piece drawn with its body only: its source's axis
        v = consistency._local_verts(e)
        if v is None:
            continue
        now = {k: (float(v[:, k].min()), float(v[:, k].max())) for k in range(3)}
        _layers(scene, gid, was, now, done, label)
        _profile(scene, gid, done, label)
        _axis(scene, gid, was, v, done)
        todo.append((gid, was))
        if was.volume is not None:
            vol = consistency._volume(e)
            if gid not in before or (vol is not None and abs(vol - was.volume) > consistency.VOLUME_TOL * abs(was.volume)):
                written, left = quantities.recompute(scene, gid)
                if written:
                    done.notes.append(f"base quantities of {label(scene, gid)} worked out again")
                done.left += left
    pieces = [g for g in created if scene.has(g)]
    for gid, was in todo:   # every axis is where it ends up first: a join may go to the piece that holds its end
        _joins(scene, gid, was, done, label, pieces)
    return done


# ----------------------------------------------------------------------------------------------------- own copies


def own_usage(scene: IfcScene, gid: str, label=consistency._label):
    """The element's material set usage, with a set of its own: a set its type gives other elements too becomes a copy
    of the type ("… (ORCA)") with the element reassigned to it; a set shared another way, a copy of the set. Returns
    (usage, words or None)."""
    e = scene.entity(gid)
    model = scene.models[scene.index_of(gid)]
    usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
    layered = usage.is_a("IfcMaterialLayerSetUsage")
    mset = usage.ForLayerSet if layered else usage.ForProfileSet
    if not (consistency.users(model, mset) - {e}):
        return usage, None
    keep = {a: getattr(usage, a) for a in ("LayerSetDirection", "DirectionSense", "OffsetFromReferenceLine",
                                           "ReferenceExtent", "CardinalPoint") if hasattr(usage, a)}
    rtype = ifcopenshell.util.element.get_type(e)
    if rtype is not None and ifcopenshell.util.element.get_material(rtype, should_skip_usage=True) == mset:
        mine = ifcopenshell.api.run("root.copy_class", model, product=rtype)
        mine.Name = f"{rtype.Name or rtype.is_a()} (ORCA)"
        ifcopenshell.api.run("type.assign_type", model, related_objects=[e], relating_type=mine,
                             should_map_representations=False)   # its own body stays: only the type changes
        copy = ifcopenshell.util.element.get_material(mine, should_skip_usage=True)
        words = f"{label(scene, gid)} given its own type {mine.Name}"
    else:
        copy = ifcopenshell.api.run("material.copy_material", model, material=mset)
        words = f"{label(scene, gid)} given its own {'layer' if layered else 'profile'} set"
    if copy is None or copy == mset:
        raise edits.Unsupported("its material set could not be copied for it alone")
    # The element's own usage of its own set (assigning the type does not move the usage when bodies stay as they are)
    ifcopenshell.api.run("material.assign_material", model, products=[e], type=usage.is_a(), material=copy)
    usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
    if (usage.ForLayerSet if layered else usage.ForProfileSet) != copy:
        raise edits.Unsupported("its material set could not be copied for it alone")
    for a, val in keep.items():
        setattr(usage, a, val)
    return usage, words


# ----------------------------------------------------------------------------------------------------- the rules


def _layers(scene, gid, was: Before, now, done: Synced, label):
    e = scene.entity(gid)
    usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
    if usage is None or not usage.is_a("IfcMaterialLayerSetUsage") or usage.LayerSetDirection not in consistency.AXES:
        return
    k = consistency.AXES[usage.LayerSetDirection]
    if k not in was.extent:
        return
    (lo0, hi0), (lo1, hi1) = was.extent[k], now[k]
    d_lo, d_hi = lo1 - lo0, hi1 - hi0
    if abs(d_lo) <= consistency.LENGTH_TOL_M and abs(d_hi) <= consistency.LENGTH_TOL_M:
        return
    s = scene.unit_scales[scene.index_of(gid)]
    usage, words = own_usage(scene, gid, label)
    layers = list(usage.ForLayerSet.MaterialLayers)
    positive = usage.DirectionSense != "NEGATIVE"
    first, last = (layers[0], layers[-1]) if positive else (layers[-1], layers[0])   # the layer at lo, at hi
    grow = {}
    grow[first.id()] = grow.get(first.id(), 0.0) - d_lo
    grow[last.id()] = grow.get(last.id(), 0.0) + d_hi
    for layer in layers:
        if layer.id() in grow:
            t = float(layer.LayerThickness) * s + grow[layer.id()]
            if t < MIN_LAYER_M:
                name = layer.Material.Name if layer.Material else "a layer"
                raise edits.Unsupported(f"its {name} layer would be {max(t, 0) * 1000:.0f} mm: pull it in less")
            layer.LayerThickness = t / s
    usage.OffsetFromReferenceLine = float(usage.OffsetFromReferenceLine or 0) + (d_lo if positive else d_hi) / s
    if words:
        done.notes.append(words)
    done.notes.append(f"layers of {label(scene, gid)} follow its new thickness")


def _profile(scene, gid, done: Synced, label):
    e = scene.entity(gid)
    usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
    if usage is None or not usage.is_a("IfcMaterialProfileSetUsage") or usage.ForProfileSet is None:
        return
    swept = consistency._swept_area(e)
    ps = usage.ForProfileSet
    if swept is None or ps.CompositeProfile is not None or not ps.MaterialProfiles:
        return
    if ps.MaterialProfiles[0].Profile == swept:
        return
    s = scene.unit_scales[scene.index_of(gid)]
    if consistency._profile_sizes(swept, s) == consistency._profile_sizes(ps.MaterialProfiles[0].Profile, s):
        return
    usage, words = own_usage(scene, gid, label)
    _set_swept(e, swept)   # assigning a profile set usage puts the set's profile on the body: the edit's goes back
    usage.ForProfileSet.MaterialProfiles[0].Profile = swept
    if words:
        done.notes.append(words)
    done.notes.append(f"material profile of {label(scene, gid)} is its new section")


def _give_axis(scene, source, piece):
    """A copy of the source's `Axis` for a piece made without one (its placement copied from the source, so the axis
    reads the same in it); `_axis` then fits it to the piece."""
    reps = piece.Representation.Representations if piece.Representation else ()
    if any(r.RepresentationIdentifier == "Axis" for r in reps):
        return
    axis = next((r for r in source.Representation.Representations if r.RepresentationIdentifier == "Axis"), None)
    model = scene.models[scene.index_of(piece.GlobalId)]
    if axis is None or piece.Representation is None or len(model.get_inverse(piece.Representation)) > 1:
        return
    copy = ifcopenshell.util.element.copy_deep(model, axis, exclude=["IfcGeometricRepresentationContext"])
    piece.Representation.Representations = [*reps, copy]


def _set_swept(e, profile):
    body = consistency._body(e)
    item = body.Items[0] if body is not None and len(body.Items) == 1 else None
    while item is not None and item.is_a("IfcBooleanResult"):
        item = item.FirstOperand
    if item is not None and item.is_a("IfcSweptAreaSolid"):
        item.SweptArea = profile


def _axis(scene, gid, was: Before, verts, done: Synced):
    if was.axis is None:
        return
    e = scene.entity(gid)
    s = scene.unit_scales[scene.index_of(gid)]
    ends = consistency._axis_points(e, s)
    if ends is None:
        return
    run = float(np.linalg.norm(ends[1] - ends[0]))
    u = (ends[1] - ends[0]) / run
    t = (verts - ends[0]) @ u
    s0, s1 = float(t.min()) - was.axis[0], float(t.max()) - was.axis[1]   # the body's ends less what they were off
    if abs(s0) <= consistency.LENGTH_TOL_M and abs(s1 - run) <= consistency.LENGTH_TOL_M:
        return
    a, b = ends[0] + u * s0, ends[0] + u * s1
    _write_axis(scene, e, a / s, b / s)


def _write_axis(scene, e, a, b):
    model = scene.models[scene.index_of(e.GlobalId)]
    for r in e.Representation.Representations:
        if r.RepresentationIdentifier != "Axis" or not r.Items:
            continue
        curve = r.Items[0]
        dims = 2 if r.RepresentationType == "Curve2D" else 3
        pts = (tuple(float(x) for x in a[:dims]), tuple(float(x) for x in b[:dims]))
        if curve.is_a("IfcIndexedPolyCurve") and len(model.get_inverse(curve.Points)) <= 1:
            curve.Points.CoordList = pts
        else:
            r.Items = [model.createIfcPolyline([model.createIfcCartesianPoint(p) for p in pts])]
        return


def _joins(scene, gid, was: Before, done: Synced, label, pieces=()):
    """A path join whose end the edit moved off the other element goes to the piece of it that now holds that end (a
    split); else it is left open: `geometry.disconnect_path`, listed with the joints the person keeps it with (owner
    decision, Nov 1: this face only)."""
    e = scene.entity(gid)
    model = scene.models[scene.index_of(gid)]
    for rel in [*getattr(e, "ConnectedTo", []), *getattr(e, "ConnectedFrom", [])]:
        if not rel.is_a("IfcRelConnectsPathElements") or rel.id() not in was.joins:
            continue
        gap = consistency._join_gap(scene, rel)
        if gap is None or gap - was.joins[rel.id()] <= consistency.JOIN_TOL_M:
            continue
        mine = "RelatingElement" if rel.RelatingElement == e else "RelatedElement"
        for piece in pieces:
            setattr(rel, mine, scene.entity(piece))
            moved = consistency._join_gap(scene, rel)
            if moved is not None and moved - was.joins[rel.id()] <= consistency.JOIN_TOL_M:
                done.notes.append(f"its join now at {label(scene, piece)}")
                break
            setattr(rel, mine, e)
        else:
            _open(scene, model, rel, e, done, label)


def _open(scene, model, rel, e, done: Synced, label):
    other = rel.RelatedElement if rel.RelatingElement == e else rel.RelatingElement
    done.opened.append({"element": other.GlobalId, "name": label(scene, other.GlobalId)})
    ifcopenshell.api.run("geometry.disconnect_path", model, relating_element=rel.RelatingElement,
                         related_element=rel.RelatedElement)
