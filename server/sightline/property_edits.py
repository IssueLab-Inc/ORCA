"""Edit what the model says about an element, not its shape (docs/editing-parity.md, Tier 3): its name and other
attributes, a property in one of its own sets, its type, its material, a classification, the storey it is on.

Every change goes through `ifcopenshell.api`, is kept through the edit log as one entry (kind "property", undone and
redone as any edit), and stamps the export's `ORCA_Edit` like any other. Nothing here changes a body, so nothing is
checked against the model's geometry; what would leave the model saying two things is refused in words: base
quantities follow the body (ORCA works them out), a layered or profiled element's material comes from its set, a value
given by its type belongs to every element of the type.
"""
from __future__ import annotations

import ifcopenshell.api
import ifcopenshell.guid
import ifcopenshell.util.attribute
import ifcopenshell.util.classification
import ifcopenshell.util.element
import ifcopenshell.util.type

from . import edits, properties
from .scene import IfcScene

ATTRIBUTES = ("Name", "Description", "ObjectType", "Tag", "PredefinedType")


def _label(scene: IfcScene, gid: str) -> str:
    from .manual import label   # manual imports the editing modules; read its words at call time
    return label(scene, gid)


def _words(v) -> str:
    return "nothing" if v in (None, "") else f"'{v}'" if isinstance(v, str) else str(v)


def _enum(entity, name: str) -> list[str]:
    decl = entity.declaration   # the schema's entity (an attribute in IfcOpenShell 0.9)
    for a in decl.all_attributes():
        if a.name() == name:
            try:
                return list(ifcopenshell.util.attribute.get_enum_items(a))
            except Exception:
                return []
    return []


def choices(scene: IfcScene, gid: str) -> dict:
    """What an element's properties can be set to from its own model: the attributes it has, its predefined types, the
    types of its kind, the materials, storeys and spaces, the classification references; each with the current one."""
    e = scene.entity(gid)
    model = scene.models[scene.index_of(gid)]
    current_type = ifcopenshell.util.element.get_type(e)
    try:
        kinds = set(ifcopenshell.util.type.get_applicable_types(e.is_a(), schema=model.schema))
    except Exception:
        kinds = set()
    types = sorted(({"global_id": t.GlobalId, "name": t.Name or t.is_a(), "ifc_class": t.is_a()}
                    for t in model.by_type("IfcTypeObject") if t.is_a() in kinds), key=lambda t: t["name"])
    mat = ifcopenshell.util.element.get_material(e, should_skip_usage=True)
    layered = mat is not None and (mat.is_a("IfcMaterialLayerSet") or mat.is_a("IfcMaterialProfileSet"))
    container = ifcopenshell.util.element.get_container(e)
    refs = {r.id() for r in ifcopenshell.util.classification.get_references(e)}
    return {
        "attributes": [a for a in ATTRIBUTES if hasattr(e, a)],
        "predefined": _enum(e, "PredefinedType") if hasattr(e, "PredefinedType") else [],
        "types": types, "type": current_type.GlobalId if current_type is not None else None,
        "materials": sorted(({"id": m.id(), "name": m.Name} for m in model.by_type("IfcMaterial")), key=lambda m: m["name"]),
        "material": None if layered or mat is None else (mat.id() if mat.is_a("IfcMaterial") else None),
        "material_fixed": "its material is its type's layers or profile" if layered else None,
        "containers": [{"global_id": c.GlobalId, "name": c.Name or c.is_a(), "ifc_class": c.is_a()}
                       for c in [*model.by_type("IfcBuildingStorey"), *model.by_type("IfcSpace")]],
        "container": container.GlobalId if container is not None else None,
        "classifications": [{"id": r.id(), "identification": r.Identification, "name": r.Name,
                             "system": getattr(r.ReferencedSource, "Name", None) if r.ReferencedSource else None,
                             "on": r.id() in refs} for r in model.by_type("IfcClassificationReference")],
    }


def plan(scene: IfcScene, gid: str, change: dict):
    """Read a change against the model without making it: (words for the log, the function that makes it). Raises
    ValueError or `edits.Unsupported` with why it cannot be made."""
    e = scene.entity(gid)
    model = scene.models[scene.index_of(gid)]
    name = _label(scene, gid)
    kind = change.get("kind")
    if kind == "attribute":
        attr = change.get("name")
        if attr not in ATTRIBUTES or not hasattr(e, attr):
            raise ValueError(f"the attributes that can be edited are {', '.join(a for a in ATTRIBUTES if hasattr(e, a))}")
        value = change.get("value")
        value = None if value in ("", None) else str(value)
        if attr == "PredefinedType" and value is not None and value not in _enum(e, "PredefinedType"):
            raise ValueError(f"its predefined type is one of {', '.join(_enum(e, 'PredefinedType'))}")
        old = getattr(e, attr)
        if old == value:
            raise edits.Unsupported(f"its {attr} is already {_words(value)}")
        return (f"{name}: {attr} {_words(old)} → {_words(value)}",
                lambda: ifcopenshell.api.run("attribute.edit_attributes", model, product=e, attributes={attr: value}))
    if kind == "property":
        pset, prop = change.get("pset"), change.get("name")
        if not pset or not prop:
            raise ValueError("say which property set and property (pset, name)")
        if pset.startswith("Qto_"):
            raise edits.Unsupported("base quantities follow its body: ORCA works them out after an edit")
        own = ifcopenshell.util.element.get_psets(e, psets_only=True, should_inherit=False)
        given = ifcopenshell.util.element.get_psets(e, psets_only=True)
        if pset not in own and pset in given and prop in given[pset]:
            raise edits.Unsupported(f"{pset} comes from its type: changing it would change every element of that type")
        old = (own.get(pset) or {}).get(prop)
        value = change.get("value")
        if isinstance(old, (int, float)) and not isinstance(old, bool) and isinstance(value, str):
            try:
                value = float(value) if "." in value or not isinstance(old, int) else int(value)
            except ValueError:
                raise ValueError(f"{prop} is a number") from None
        if isinstance(old, bool) and isinstance(value, str):
            value = value.strip().lower() in ("yes", "true", "1")
        if old == value:
            raise edits.Unsupported(f"{pset}.{prop} is already {_words(value)}")

        def make():
            target = model.by_id(own[pset]["id"]) if pset in own else ifcopenshell.api.run("pset.add_pset", model, product=e, name=pset)
            ifcopenshell.api.run("pset.edit_pset", model, pset=target, properties={prop: value})
        return (f"{name}: {pset}.{prop} {_words(old)} → {_words(value)}" if value is not None else
                f"{name}: {pset}.{prop} removed (was {_words(old)})"), make
    if kind == "type":
        t = model.by_guid(change.get("type")) if change.get("type") else None
        if t is None or not t.is_a("IfcTypeObject"):
            raise ValueError("say which type (its GlobalId, from the choices)")
        kinds = set(ifcopenshell.util.type.get_applicable_types(e.is_a(), schema=model.schema))
        if t.is_a() not in kinds:
            raise edits.Unsupported(f"a {e.is_a()} cannot be of type {t.is_a()}")
        usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
        if usage is not None and (usage.is_a("IfcMaterialLayerSetUsage") or usage.is_a("IfcMaterialProfileSetUsage")):
            raise edits.Unsupported("its layers or profile come from its type: change its thickness or section by hand, "
                                    "or its type in the authoring tool")
        old = ifcopenshell.util.element.get_type(e)
        if old == t:
            raise edits.Unsupported(f"it is already of type {t.Name}")

        def make():
            edits.make_unique(model, e)   # a body drawn from its old type becomes its own first: the shape stays
            ifcopenshell.api.run("type.assign_type", model, related_objects=[e], relating_type=t,
                                 should_map_representations=False)
        return f"{name} now of type '{t.Name}' (was {_words(old.Name if old else None)})", make
    if kind == "material":
        m = model.by_id(int(change.get("material"))) if change.get("material") is not None else None
        if m is None or not m.is_a("IfcMaterial"):
            raise ValueError("say which material (its id, from the choices)")
        current = ifcopenshell.util.element.get_material(e, should_skip_usage=True)
        if current is not None and (current.is_a("IfcMaterialLayerSet") or current.is_a("IfcMaterialProfileSet")):
            raise edits.Unsupported("its material is its type's layers or profile: give it its own in the authoring tool")
        if current == m:
            raise edits.Unsupported(f"it is already {m.Name}")
        return (f"{name}: material {_words(getattr(current, 'Name', None))} → '{m.Name}'",
                lambda: ifcopenshell.api.run("material.assign_material", model, products=[e], type="IfcMaterial", material=m))
    if kind == "classification":
        ref = model.by_id(int(change.get("reference"))) if change.get("reference") is not None else None
        if ref is None or not ref.is_a("IfcClassificationReference"):
            raise ValueError("say which classification reference (its id, from the choices)")
        words = " ".join(str(x) for x in (ref.Identification, ref.Name) if x)
        on = {r.id() for r in ifcopenshell.util.classification.get_references(e)}
        if change.get("remove"):
            if ref.id() not in on:
                raise edits.Unsupported(f"it is not classified {words}")
            return (f"{name} no longer classified {words}",
                    lambda: ifcopenshell.api.run("classification.remove_reference", model, reference=ref, products=[e]))
        old = model.by_id(int(change["replace"])) if change.get("replace") is not None else None
        if old is not None and (not old.is_a("IfcClassificationReference") or old.id() not in on):
            raise ValueError("replace names a classification reference it has")
        if ref.id() in on:
            raise edits.Unsupported(f"it is already classified {words}")

        def add():
            if old is not None:   # one change: the reference it had swapped for another
                ifcopenshell.api.run("classification.remove_reference", model, reference=old, products=[e])
            rels = [r for r in model.get_inverse(ref) if r.is_a("IfcRelAssociatesClassification")]
            if rels:
                rels[0].RelatedObjects = [*rels[0].RelatedObjects, e]
            else:
                model.createIfcRelAssociatesClassification(ifcopenshell.guid.new(), None, None, None, [e], ref)
        was = " ".join(str(x) for x in (old.Identification, old.Name) if x) if old is not None else None
        return (f"{name} classified {words}" + (f" (was {was})" if was else "")), add
    if kind == "container":
        c = model.by_guid(change.get("container")) if change.get("container") else None
        if c is None or not c.is_a("IfcSpatialStructureElement"):
            raise ValueError("say which storey or space (its GlobalId, from the choices)")
        old = ifcopenshell.util.element.get_container(e)
        if old == c:
            raise edits.Unsupported(f"it is already on {c.Name}")
        return (f"{name} now on {c.Name or c.is_a()} (was {_words(old.Name if old else None)})",
                lambda: ifcopenshell.api.run("spatial.assign_container", model, products=[e], relating_structure=c))
    raise ValueError("a change is an attribute, property, type, material, classification or container")


def edit(ws, scene_id: str, gid: str, change: dict, *, source: str = "you", actor: str | None = None) -> dict:
    """Make one change and keep it through the edit log (one entry, undone and redone as any edit). Returns the entry
    and the element's properties as they are now."""
    scene = ws.scene(scene_id)
    log = ws.journal(scene_id)
    i = scene.index_of(gid)
    with ws.lock:
        words, make = plan(scene, gid, change)
        before = scene.revision
        with log.record(scene, source, "property", actor=actor) as rec, edits.kept_files(scene, {i}):
            make()
            scene._edited.add(i)   # export writes this file
            scene.bump({i})
            rec.changed, rec.summary, rec.title = [gid], words, words
            rec.params = {"op": "property", "element": gid, **change}
        entry = rec.entry
        props = properties.properties(scene, gid)
        after = scene.revision
    # The page moves its drawn revision on when it was at `revision_before`: no shape changed, nothing to redraw.
    return {"entry": entry.to_dict() if entry else None, "properties": props, "revision_before": before, "revision": after}
