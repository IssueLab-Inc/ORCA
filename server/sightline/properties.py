"""An element's properties as the page's Properties panel shows them (GET /api/scenes/{id}/elements/{gid}/properties).

What the model says about one element, read with IfcOpenShell from the scene's current state (so a kept fix's new
pieces have theirs): its attributes, its type, its materials, its property sets (with what its type gives it), its
quantities in SI units, and its size from the scene's cached box. Values are made safe for JSON; nothing is computed
or guessed.
"""
from __future__ import annotations

import math

import ifcopenshell
import ifcopenshell.util.element

from . import demos
from .scene import IfcScene

ATTRIBUTES = ("Name", "Description", "ObjectType", "Tag", "PredefinedType")

# The demo models carry their own notes in a property set named for the tool that generated them. The page shows the
# set as "Model data", and leaves out the scripting note on the clash host (it says the answer key was planted).
RENAMED = demos.PSET_NAMES      # the demo models' own set, by a plain name
HIDDEN = demos.HIDDEN_PROPERTIES

# Quantities are in the file's units: lengths scale once, areas twice, volumes three times. The others are SI already
# or have no unit.
QUANTITY = {"IfcQuantityLength": ("LengthValue", 1, "m"), "IfcQuantityArea": ("AreaValue", 2, "m²"),
            "IfcQuantityVolume": ("VolumeValue", 3, "m³"), "IfcQuantityWeight": ("WeightValue", 0, "kg"),
            "IfcQuantityCount": ("CountValue", 0, ""), "IfcQuantityTime": ("TimeValue", 0, "s")}


def value(v):
    """A property's value as JSON: numbers rounded to a micro-unit, entities by name, lists kept."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if not math.isfinite(v) else round(v, 6)
    if isinstance(v, (list, tuple)):
        return [value(x) for x in v]
    if isinstance(v, ifcopenshell.entity_instance):
        return getattr(v, "Name", None) or v.is_a()
    return str(v)


def _sets(psets: dict) -> dict[str, dict]:
    out = {}
    for name, props in psets.items():
        shown = {k: value(v) for k, v in props.items() if k != "id" and k not in HIDDEN}
        if shown:
            out[RENAMED.get(name, name)] = shown
    return out


def _quantities(element, scale: float) -> dict[str, dict]:
    """Each quantity set on the element, converted to SI, with the unit beside each value."""
    out: dict[str, dict] = {}
    for rel in getattr(element, "IsDefinedBy", None) or []:
        qto = rel.RelatingPropertyDefinition if rel.is_a("IfcRelDefinesByProperties") else None
        if qto is None or not qto.is_a("IfcElementQuantity"):
            continue
        shown = {}
        for q in qto.Quantities or []:
            kind = next((k for k in QUANTITY if q.is_a(k)), None)
            if kind is None:
                continue
            attr, power, unit = QUANTITY[kind]
            v = getattr(q, attr, None)
            if v is None:
                continue
            shown[q.Name] = {"value": round(float(v) * scale ** power, 6) if power else value(v), "unit": unit}
        if shown:
            out[RENAMED.get(qto.Name, qto.Name)] = shown
    return out


def properties(scene: IfcScene, global_id: str) -> dict:
    """Everything the model says about one element. Raises KeyError for an element the scene doesn't have."""
    i = scene.index_of(global_id)
    e = scene.models[i].by_guid(global_id)
    kind = ifcopenshell.util.element.get_type(e)
    box = scene.bounds().get(global_id)
    size = [round(float(hi - lo), 4) for lo, hi in zip(box[0], box[1])] if box is not None else None
    return {
        "global_id": global_id,
        "ifc_class": e.is_a(),
        "attributes": {a: value(getattr(e, a)) for a in ATTRIBUTES if getattr(e, a, None) not in (None, "")},
        "type": {"ifc_class": kind.is_a(), "name": getattr(kind, "Name", None)} if kind is not None else None,
        "materials": [m.Name for m in ifcopenshell.util.element.get_materials(e) if getattr(m, "Name", None)],
        "psets": _sets(ifcopenshell.util.element.get_psets(e, psets_only=True)),
        "quantities": _quantities(e, scene.unit_scales[i]),
        "size_m": size,
        "source": scene.paths[i].name,
    }
