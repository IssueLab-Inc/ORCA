"""Base quantities after an edit (docs/editing-parity.md, Tier 1): the `Qto_*BaseQuantities` an element already
carries, worked out again from its body. Only quantities already there are written, and only those whose meaning the
body settles (lengths, widths, heights, volumes and the areas that follow from them); the rest are named, so the log can
say they were left as they were. No quantity is ever added.
"""
from __future__ import annotations

import ifcopenshell.api
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import ifcopenshell.util.unit
import numpy as np

from .scene import IfcScene

WALLS = ("IfcWall", "IfcCurtainWall")
PLATES = ("IfcSlab", "IfcPlate", "IfcCovering", "IfcRoof", "IfcFooting")


def base_sets(entity) -> dict[str, dict]:
    """The element's own base quantity sets, by name: {name: {quantity: value, "id": ...}}."""
    return {k: v for k, v in ifcopenshell.util.element.get_psets(entity, qtos_only=True).items()
            if k.startswith("Qto_") and k.endswith("BaseQuantities")}


def _shape(entity, openings: bool):
    settings = ifcopenshell.geom.settings()
    if not openings:
        settings.set("disable-opening-subtractions", True)
    return ifcopenshell.geom.create_shape(settings, entity)


def measured(scene: IfcScene, gid: str) -> dict[str, float] | None:
    """What the body says, in metres, square metres and cubic metres: the quantities this module can work out."""
    e = scene.entity(gid)
    try:
        net, gross = _shape(e, True), _shape(e, False)
    except Exception:
        return None
    v = np.asarray(gross.geometry.verts, float).reshape(-1, 3)
    if not len(v):
        return None
    size = v.max(axis=0) - v.min(axis=0)
    out = {"GrossVolume": float(ifcopenshell.util.shape.get_volume(gross.geometry)),
           "NetVolume": float(ifcopenshell.util.shape.get_volume(net.geometry))}
    if any(e.is_a(c) for c in WALLS):
        length, width, height = (float(x) for x in size)
        out.update(Length=length, Width=width, Height=height, GrossSideArea=length * height)
        if width > 1e-9:
            out["NetSideArea"] = out["NetVolume"] / width
    elif any(e.is_a(c) for c in PLATES):
        depth = float(size[2])
        out.update(Width=depth, Depth=depth, Length=float(max(size[0], size[1])))
        if depth > 1e-9:
            out.update(GrossArea=out["GrossVolume"] / depth, NetArea=out["NetVolume"] / depth)
    else:   # a linear member: a beam, column, member, pile or flow segment runs along its longest size
        length = float(size.max())
        out["Length"] = length
        if length > 1e-9:
            out["CrossSectionArea"] = out["GrossVolume"] / length
    return out


def recompute(scene: IfcScene, gid: str) -> tuple[list[str], list[str]]:
    """Write the element's base quantities again from its body. Returns the quantities written and those left as they
    were (what this module cannot work out: weights, surface areas, perimeters…), each as "Qto_X.Name"."""
    e = scene.entity(gid)
    sets = base_sets(e)
    if not sets:
        return [], []
    got = measured(scene, gid)
    if got is None:
        return [], [f"{q}.{n}" for q, d in sets.items() for n in d if n != "id"]
    model = scene.models[scene.index_of(gid)]
    scale = {"L": ifcopenshell.util.unit.calculate_unit_scale(model),
             "A": ifcopenshell.util.unit.calculate_unit_scale(model, "AREAUNIT"),
             "V": ifcopenshell.util.unit.calculate_unit_scale(model, "VOLUMEUNIT")}
    written, left = [], []
    for q, values in sets.items():
        props = {}
        for name in values:
            if name == "id":
                continue
            if name in got:
                kind = "V" if name.endswith("Volume") else "A" if name.endswith("Area") else "L"
                props[name] = got[name] / scale[kind]
                written.append(f"{q}.{name}")
            else:
                left.append(f"{q}.{name}")
        if props:
            ifcopenshell.api.run("pset.edit_qto", model, qto=model.by_id(values["id"]), properties=props)
    return written, left
