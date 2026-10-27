"""Small synthetic IFC models for tests and spikes.

Northbank is the real demo set; this exists so tests and the day-1 spikes run anywhere,
in seconds, without it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.unit


def _box(model, body, element, size, origin):
    """Give `element` a rectangular extrusion of `size` (x, y, z, project units) whose min corner is at `origin`."""
    sx, sy, sz = size
    profile = model.create_entity(
        "IfcRectangleProfileDef", ProfileType="AREA", XDim=sx, YDim=sy,
        Position=model.create_entity(
            "IfcAxis2Placement2D",
            Location=model.create_entity("IfcCartesianPoint", (sx / 2, sy / 2)),
        ),
    )
    rep = ifcopenshell.api.run("geometry.add_profile_representation", model,
                               context=body, profile=profile,
                               # depth is the one argument this API takes in SI (metres)
                               depth=sz * ifcopenshell.util.unit.calculate_unit_scale(model))
    ifcopenshell.api.run("geometry.assign_representation", model, product=element, representation=rep)
    matrix = np.eye(4)
    matrix[:3, 3] = origin
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=element, matrix=matrix, is_si=False)


def build_clash_fixture(path: Path, millimetres: bool = False,
                        only: tuple[str, ...] = ("beam", "duct", "pipe")) -> Path:
    """A steel beam, a duct crossing through it, and a pipe just below the beam.

    Moving the duct down 0.40 m clears the beam but hits the pipe; moving it down 0.80 m clears both.
    That gives the agent loop a realistic "first try fails" case. Dimensions below are metres; with
    `millimetres=True` the file is written in mm, like most authoring-tool exports. `only` writes a subset,
    so a structure file and a services file can be federated like real discipline models.
    """
    k = 1000.0 if millimetres else 1.0
    model = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="Sightline fixture")
    length = ifcopenshell.api.run("unit.add_si_unit", model, unit_type="LENGTHUNIT",
                                  prefix="MILLI" if millimetres else None)
    ifcopenshell.api.run("unit.assign_unit", model, units=[length])
    ctx = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", model, context_type="Model",
                                context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
    site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding", name="Building")
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 03")
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[site])
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=site, products=[building])
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=building, products=[storey])

    def element(ifc_class, name, size, origin):
        e = ifcopenshell.api.run("root.create_entity", model, ifc_class=ifc_class, name=name)
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[e])
        _box(model, body, e, tuple(v * k for v in size), tuple(v * k for v in origin))
        return e

    # Beam along X: 6 m long, 0.2 m wide, 0.4 m deep, top at z = 3.0
    if "beam" in only:
        element("IfcBeam", "UB 406x178 beam", (6.0, 0.2, 0.4), (0.0, -0.1, 2.6))
    # Duct along Y crossing the beam: 0.4 x 0.3 section, centred in the beam depth
    if "duct" in only:
        element("IfcDuctSegment", "Supply duct 400x300", (0.4, 4.0, 0.3), (2.8, -2.0, 2.65))
    # Pipe along Y below the beam, where a 0.40 m drop of the duct lands on it
    if "pipe" in only:
        element("IfcPipeSegment", "LTHW pipe DN50", (0.1, 4.0, 0.1), (2.9, -2.0, 2.25))

    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return path


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "../samples/fixture-clash.ifc")
    print(build_clash_fixture(out))
