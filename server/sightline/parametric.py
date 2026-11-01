"""Keep what the model says besides the shape true after an edit (docs/editing-parity.md, Tier 1).

An edit changes an element's body; this brings the rest of what the model says about its size along: a layered wall or
slab's layers, a profile set's section, its `Axis`, its base quantities, and its path joins. It works from a reading
before the edit (`snapshot`) and the body after it (`sync`), so data that was already out of line stays as it was:
only what the edit moved is moved with it.

Shared data is copied for the edited element first (owner decision, Nov 1): a layer or profile set its type gives
other elements too means a copy of the type ("… (ORCA)") with the element reassigned to it; a set shared some other
way, a copy of the set. Other elements of the type never change, unless the person chose to apply the edit to the type
(`scope: "type"`, `type_share` and `to_type`): then the type's shape or section is what the edit made of this element's,
and every element of the type follows.
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
    cardinal: tuple[float, float] | None = None   # its cardinal point from its axis, across its section


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
        if (gid, "cardinal") in mine:
            b.cardinal = mine[(gid, "cardinal")].values
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
        _cardinal(scene, gid, was, v, done, label)
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


# ----------------------------------------------------------------------------------------------------- the type itself


@dataclass
class TypeShare:
    """What an edit applied to the element's type (`scope: "type"`) changes for every element of it."""
    kind: str               # "map": the shape its type draws; "profile": its profile set's section; "layers": its
                            # layer set's thickness
    type_name: str
    others: list[str]       # the type's other elements in the scene: they follow


def _maps_from(e, rmap) -> bool:
    body = consistency._body(e)
    return body is not None and any(it.is_a("IfcMappedItem") and it.MappingSource == rmap for it in body.Items)


def type_share(scene: IfcScene, gid: str, face, label=consistency._label) -> TypeShare:
    """What of its type an edit to this face would change, when the person applies it to the type: the shape the type
    draws (a mapped body: any face), the type's profile set (a side or radius: the section) or its layer set (a face
    square to the layers: the thickness). Raises `edits.Unsupported` in words when the edit changes nothing the type
    gives."""
    face_kind = face.kind
    e = scene.entity(gid)
    model = scene.models[scene.index_of(gid)]
    rtype = ifcopenshell.util.element.get_type(e)
    if rtype is None:
        raise edits.Unsupported(f"{label(scene, gid)} has no type: the edit can only be its own")
    name = rtype.Name or rtype.is_a()
    usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
    if usage is not None and usage.is_a("IfcMaterialLayerSetUsage") and usage.LayerSetDirection in consistency.AXES:
        across = scene.placement(gid)[:3, consistency.AXES[usage.LayerSetDirection]]
        if abs(float(np.asarray(face.normal, float) @ across)) > 0.99:   # a face square to its layers: its thickness
            lset = usage.ForLayerSet
            if ifcopenshell.util.element.get_material(rtype, should_skip_usage=True) != lset:
                raise edits.Unsupported("its layer set is its own, not its type's: leave Apply to the type off")
            others = [o.GlobalId for o in consistency.users(model, lset) if o != e and scene.has(o.GlobalId)]
            unsaid = [o for o in others if not _says_which_way(scene.entity(o))]
            if unsaid:   # Revit gives some walls of a type its layers but no usage: which face holds which is unknown
                n = len(unsaid)
                raise edits.Unsupported(f"{n} other element{'s' if n > 1 else ''} of {name} (such as "
                                        f"{label(scene, unsaid[0])}) {'have' if n > 1 else 'has'} its layers without "
                                        f"saying which way they run, so {'they' if n > 1 else 'it'} cannot follow: "
                                        "leave Apply to the type off to change this one alone")
            return TypeShare("layers", name, others)
    body = consistency._body(e)
    mapped = [it for it in (body.Items if body is not None else ()) if it.is_a("IfcMappedItem")]
    if mapped:
        if len(body.Items) != 1 or mapped[0].MappingSource not in (rtype.RepresentationMaps or ()):
            raise edits.Unsupported(f"its body is more than the shape its type {name} draws: leave Apply to the type off")
        edits.mapping(mapped[0])   # refused when its type's shape is scaled where it is placed
        rmap = mapped[0].MappingSource
        others = [o.GlobalId for o in ifcopenshell.util.element.get_types(rtype)
                  if o != e and scene.has(o.GlobalId) and _maps_from(o, rmap)]
        return TypeShare("map", name, others)
    if usage is not None and usage.is_a("IfcMaterialProfileSetUsage") and face_kind in ("side", "radial"):
        ps = usage.ForProfileSet
        if ps is None or ifcopenshell.util.element.get_material(rtype, should_skip_usage=True) != ps:
            raise edits.Unsupported("its profile set is its own, not its type's: leave Apply to the type off")
        if ps.CompositeProfile is not None or len(ps.MaterialProfiles) != 1:
            raise edits.Unsupported(f"{name} has a section of several profiles: ORCA changes one profile only")
        others = [o.GlobalId for o in consistency.users(model, ps) if o != e and scene.has(o.GlobalId)]
        return TypeShare("profile", name, others)
    own = ", and a length is each element's own" if usage is not None else ""
    raise edits.Unsupported(f"this edit changes nothing its type {name} gives (its shape is its own{own}): leave "
                            "Apply to the type off")


def _says_which_way(e) -> bool:
    usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
    return usage is not None and usage.is_a("IfcMaterialLayerSetUsage") and usage.LayerSetDirection in consistency.AXES


def hold(scene: IfcScene, gid: str, share: TypeShare) -> dict:
    """Before the edit, inside its transaction: what `to_type` needs of the shape the type draws for the element (the
    map, where it puts it, a copy of its target: the edit replaces the mapped body with the element's own)."""
    if share.kind == "layers":
        e = scene.entity(gid)
        usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
        k = consistency.AXES[usage.LayerSetDirection]
        v = consistency._local_verts(e)
        if v is None:
            raise edits.Unsupported("its body cannot be read: its type's layers cannot follow it")
        return {"extent": (float(v[:, k].min()), float(v[:, k].max()))}
    if share.kind != "map":
        return {}
    e = scene.entity(gid)
    model = scene.models[scene.index_of(gid)]
    (mi,) = consistency._body(e).Items
    target = ifcopenshell.util.element.copy_deep(model, mi.MappingTarget) if mi.MappingTarget is not None else None
    return {"map": mi.MappingSource, "m": edits.mapping(mi), "target": target}


def _drop(model, root) -> None:
    """Remove a representation or item and what only it uses, with the styles on its items."""
    items = root.Items if root.is_a("IfcShapeRepresentation") else [root]
    for it in items:
        for st in [x for x in model.get_inverse(it) if x.is_a("IfcStyledItem")]:
            model.remove(st)
    ifcopenshell.util.element.remove_deep2(model, root)


def _side_face(scene: IfcScene, gid: str, k: int, sign: int):
    """A point in the middle of an element's face square to its local axis `k` (the high side for +1) and its outward
    normal, world metres."""
    v = consistency._local_verts(scene.entity(gid))
    if v is None:
        raise edits.Unsupported(f"the body of {consistency._label(scene, gid)} cannot be read")
    p = (v.min(axis=0) + v.max(axis=0)) / 2
    p[k] = v[:, k].max() if sign > 0 else v[:, k].min()
    m = scene.placement(gid)
    return m[:3, :3] @ p + m[:3, 3], m[:3, k] * sign


def _grow_layers(scene, gid, share: TypeShare, held: dict, push) -> list[str]:
    """The layer on each face the edit moved grows in the type's own set (its reference line kept, as for one wall),
    and every other wall of the set has the face holding that layer pushed by as much, its reference line kept too."""
    e = scene.entity(gid)
    usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
    lset = usage.ForLayerSet
    k = consistency.AXES[usage.LayerSetDirection]
    s = scene.unit_scales[scene.index_of(gid)]
    v = consistency._local_verts(e)
    (lo0, hi0), lo1, hi1 = held["extent"], float(v[:, k].min()), float(v[:, k].max())
    d_lo, d_hi = lo1 - lo0, hi1 - hi0
    layers = list(lset.MaterialLayers)
    positive = usage.DirectionSense != "NEGATIVE"
    at_lo, at_hi = (layers[0], layers[-1]) if positive else (layers[-1], layers[0])
    grow: dict[int, float] = {}
    grow[at_lo.id()] = grow.get(at_lo.id(), 0.0) - d_lo
    grow[at_hi.id()] = grow.get(at_hi.id(), 0.0) + d_hi
    for layer in layers:
        if layer.id() in grow:
            t = float(layer.LayerThickness) * s + grow[layer.id()]
            if t < MIN_LAYER_M:
                n = layer.Material.Name if layer.Material else "a layer"
                raise edits.Unsupported(f"its {n} layer would be {max(t, 0) * 1000:.0f} mm: pull it in less")
            layer.LayerThickness = t / s
    done = {usage.id()}
    usage.OffsetFromReferenceLine = float(usage.OffsetFromReferenceLine or 0) + (d_lo if positive else d_hi) / s
    # Each other wall: the face holding the first layer of the set grows by what that layer grew, the last likewise
    g_first, g_last = grow.get(layers[0].id(), 0.0), grow.get(layers[-1].id(), 0.0)
    if len(layers) == 1:   # one layer: on the side the edit moved, for every wall alike
        g_first, g_last = (-d_lo if positive else d_hi), (d_hi if positive else -d_lo)
    for other in share.others:
        o = scene.entity(other)
        ou = ifcopenshell.util.element.get_material(o, should_skip_usage=False)
        ko, so = consistency.AXES[ou.LayerSetDirection], scene.unit_scales[scene.index_of(other)]
        o_pos = ou.DirectionSense != "NEGATIVE"
        g_lo, g_hi = (g_first, g_last) if o_pos else (g_last, g_first)
        for sign, g in ((-1, g_lo), (1, g_hi)):
            if abs(g) > consistency.LENGTH_TOL_M:
                point, normal = _side_face(scene, other, ko, sign)
                push(other, point, normal, g)
        if ou.id() not in done:
            done.add(ou.id())
            ou.OffsetFromReferenceLine = float(ou.OffsetFromReferenceLine or 0) + (-g_lo if o_pos else g_hi) / so
    return list(share.others)


def to_type(scene: IfcScene, gid: str, share: TypeShare, held: dict, push=None) -> list[str]:
    """After the edit, inside its transaction: what the edit made of the element's shape or section becomes its type's,
    and every element of the type follows. A mapped body: the element's new solids, moved back into the map's own
    frame, are the type's shape, and the element draws it through its map again. A profile set: the new section is
    the set's, and each other element's body takes it about its own placement (its cardinal point kept). A layer set:
    the layer on the face moved grows, and each other wall's face holding that layer is pushed by as much (`push`:
    the hand edits' own push, given an element, a point and normal on its face and how far). Returns the other
    elements that changed."""
    e = scene.entity(gid)
    model = scene.models[scene.index_of(gid)]
    if share.kind == "layers":
        others = _grow_layers(scene, gid, share, held, push)
        scene.refresh_bounds([gid, *others])
        return others
    if share.kind == "map":
        body = consistency._body(e)
        rmap, inv = held["map"], np.linalg.inv(held["m"])
        items = []
        for it in body.Items:
            copy = ifcopenshell.util.element.copy_deep(model, it, exclude=["IfcGeometricRepresentationContext"])
            edits._move_item(model, copy, inv)
            for st in [x for x in model.get_inverse(it) if x.is_a("IfcStyledItem")]:
                model.createIfcStyledItem(copy, st.Styles, st.Name)
            items.append(copy)
        shape = rmap.MappedRepresentation
        old = list(shape.Items)
        shape.Items = items
        shape.RepresentationType = body.RepresentationType
        for it in old:
            if not [x for x in model.get_inverse(it) if not x.is_a("IfcStyledItem")]:
                _drop(model, it)
        mapped = model.createIfcShapeRepresentation(body.ContextOfItems, "Body", "MappedRepresentation",
                                                    [model.createIfcMappedItem(rmap, held["target"])])
        e.Representation.Representations = [mapped if r == body else r for r in e.Representation.Representations]
        _drop(model, body)
    else:
        usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
        ps = usage.ForProfileSet
        swept = consistency._swept_area(e)
        if swept is None:
            raise edits.Unsupported("its section is no longer one profile: it cannot be its type's")
        old = ps.MaterialProfiles[0].Profile
        ps.MaterialProfiles[0].Profile = swept
        for other in share.others:
            o = scene.entity(other)
            body = consistency._body(o)
            if body is not None and any(edits.shared(model, o, body, it) for it in body.Items):
                edits.make_unique(model, o)
            _set_swept(o, swept)
            if consistency._swept_area(o) != swept:
                raise edits.Unsupported(f"{consistency._label(scene, other)} is not drawn from its section: it cannot "
                                        "follow its type")
        if old is not None and old != swept and not model.get_inverse(old):
            ifcopenshell.util.element.remove_deep2(model, old)
    scene.refresh_bounds([gid, *share.others])
    return list(share.others)


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
    total = sum(float(l.LayerThickness or 0) for l in usage.ForLayerSet.MaterialLayers) * s
    if abs(total - (hi1 - lo1)) <= consistency.LENGTH_TOL_M:   # already true: an edit to its type grew them itself
        return
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


def _cardinal(scene, gid, was: Before, verts, done: Synced, label):
    """A section grown on one side (the body grows to the side pushed): the element's axis goes back to its cardinal
    point, so a tool that draws it again from its axis, profile and cardinal point draws the same body. Its placement
    moves across by the difference and its body back by as much (what is placed in it stays where it is)."""
    if was.cardinal is None:
        return
    e = scene.entity(gid)
    s = scene.unit_scales[scene.index_of(gid)]
    off = consistency.cardinal_offset(e, s, verts)
    if off is None:
        return
    now, x, y = off
    d = now - np.asarray(was.cardinal, float)
    if np.all(np.abs(d) <= consistency.LENGTH_TOL_M):
        return
    shift = x * d[0] + y * d[1]                     # metres, in the element's own frame
    body = consistency._body(e)
    if body is None or any(it.is_a("IfcMappedItem") for it in body.Items):
        return
    model = scene.models[scene.index_of(gid)]
    m = scene.placement(gid)
    m[:3, 3] += m[:3, :3] @ shift
    back = np.eye(4)
    back[:3, 3] = -shift / s
    for it in body.Items:
        edits._move_item(model, it, back)
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=e, matrix=m, is_si=True)
    scene.refresh_bounds([gid])
    usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
    done.notes.append(f"the axis of {label(scene, gid)} back at its section's cardinal point "
                      f"({int(usage.CardinalPoint or 5)})")


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
