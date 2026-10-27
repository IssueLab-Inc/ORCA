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


def build_run_fixture(path: Path, millimetres: bool = False) -> Path:
    """A duct run along X that crosses a beam, under a slab: the case for a local offset.

    The supply main is one straight segment (0-6 m, 400 wide x 300 deep, centreline z = 2.8) extruded along its own
    axis, with ports at both ends; the far port joins a 1 m end segment. The beam (along Y at x = 3, z 2.6-3.0) blocks
    it and the slab soffit is at z = 3.4, so an offset up must be 0.375-0.425 m to keep 25 mm both sides; 0.40 m
    leaves 50 mm.
    """
    k = 1000.0 if millimetres else 1.0
    model = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="Sightline offset fixture")
    length = ifcopenshell.api.run("unit.add_si_unit", model, unit_type="LENGTHUNIT",
                                  prefix="MILLI" if millimetres else None)
    ifcopenshell.api.run("unit.assign_unit", model, units=[length])
    ctx = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", model, context_type="Model",
                                context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 02")
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[storey])

    def element(ifc_class, name):
        e = ifcopenshell.api.run("root.create_entity", model, ifc_class=ifc_class, name=name)
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[e])
        return e

    _box(model, body, element("IfcBeam", "Transfer beam"), (0.2 * k, 3.0 * k, 0.4 * k), (2.9 * k, -1.5 * k, 2.6 * k))
    _box(model, body, element("IfcSlab", "Level 03 slab"), (8.0 * k, 3.0 * k, 0.2 * k), (-0.5 * k, -1.5 * k, 3.4 * k))

    def duct(name, x0, run):
        e = element("IfcDuctSegment", name)
        ifcopenshell.api.run("geometry.edit_object_placement", model, product=e)
        profile = model.createIfcRectangleProfileDef("AREA", None, None, 0.4 * k, 0.3 * k)
        position = model.createIfcAxis2Placement3D(model.createIfcCartesianPoint((x0 * k, 0.0, 2.8 * k)),
                                                   model.createIfcDirection((1.0, 0.0, 0.0)),
                                                   model.createIfcDirection((0.0, 1.0, 0.0)))
        solid = model.createIfcExtrudedAreaSolid(profile, position, model.createIfcDirection((0.0, 0.0, 1.0)), run * k)
        e.Representation = model.createIfcProductDefinitionShape(
            None, None, [model.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])])
        ports = []
        for n, x in enumerate((x0, x0 + run)):
            port = ifcopenshell.api.run("system.add_port", model, element=e)
            port.Name = f"Port {n}"
            port.FlowDirection = "SINK" if n == 0 else "SOURCE"
            matrix = np.eye(4)
            matrix[:3, 3] = (x * k, 0.0, 2.8 * k)
            ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=matrix)
            ports.append(port)
        return e, ports

    main, (_, main_far) = duct("Supply main 400x300", 0.0, 6.0)
    main.Tag = "SA-1"
    _, (end_near, _) = duct("Supply main 400x300", 6.0, 1.0)
    ifcopenshell.api.run("system.connect_port", model, port1=main_far, port2=end_near, direction="SOURCE")

    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return path
