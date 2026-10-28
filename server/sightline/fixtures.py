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
            matrix[:3,:3] = np.array([[0.,0.,1.],[1.,0.,0.],[0.,1.,0.]])
            matrix[:3, 3] = (x * k, 0.0, 2.8 * k)
            ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=matrix, is_si=False)
            ports.append(port)
        return e, ports

    main, (_, main_far) = duct("Supply main 400x300", 0.0, 6.0)
    main.Tag = "SA-1"
    _, (end_near, _) = duct("Supply main 400x300", 6.0, 1.0)
    ifcopenshell.api.run("system.connect_port", model, port1=main_far, port2=end_near, direction="SOURCE")

    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return path


def build_joint_fixture(path: Path) -> Path:
    """A curtain-wall corner like Northbank's Clash7: a transom whose end runs 60 mm into a mullion, tops flush.

    The transom is drawn the way curtain-wall framing often is, a plan rectangle (1.65 m x 120 mm) extruded 60 mm up,
    so its length is the profile, not the extrusion. A spandrel panel sits on the transom (a contact that is meant to
    be there). Metres throughout.
    """
    model = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="Sightline joint fixture")
    ifcopenshell.api.run("unit.assign_unit", model, units=[ifcopenshell.api.run("unit.add_si_unit", model, unit_type="LENGTHUNIT")])
    ctx = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", model, context_type="Model",
                                context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 03")
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[storey])

    def member(ifc_class, name, xdim, ydim, depth, centre_bottom):
        """A profile centred on the element's axis (no profile offset), extruded `depth` up from `centre_bottom`."""
        e = ifcopenshell.api.run("root.create_entity", model, ifc_class=ifc_class, name=name)
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[e])
        profile = model.create_entity("IfcRectangleProfileDef", ProfileType="AREA", XDim=xdim, YDim=ydim)
        rep = ifcopenshell.api.run("geometry.add_profile_representation", model, context=body, profile=profile, depth=depth)
        ifcopenshell.api.run("geometry.assign_representation", model, product=e, representation=rep)
        m = np.eye(4)
        m[:3, 3] = centre_bottom
        ifcopenshell.api.run("geometry.edit_object_placement", model, product=e, matrix=m, is_si=True)
        return e

    # Transom: x 9.24-10.89, y -6.45 to -6.33, z 11.94-12.00. Mullion: x 10.83-10.95, y -6.36 to -6.30, z 8-12.
    member("IfcMember", "Transom 60x120", 1.65, 0.12, 0.06, (10.065, -6.39, 11.94))
    member("IfcMember", "Mullion 60x120", 0.12, 0.06, 4.0, (10.89, -6.33, 8.0))
    member("IfcPlate", "Spandrel panel", 1.4, 0.03, 0.8, (10.0, -6.39, 12.0))
    model.write(str(path))
    return path


def build_context_fixture(path: Path, millimetres: bool = False) -> Path:
    """A constrained service corridor needing a surrounding tray relocation.

    Tags CTX-DUCT/BEAM/TRAY identify the objective and enabling edit. The 400x300
    duct runs x0..6 at z2.8, joined at x6 to a fixed terminal fitting through the
    x6..7 end segment. Beam/corridor/terminal carry explicit KeepFixed constraints.
    The corridor is y +/-0.6, floor top2.4, ceiling soffit3.4; a tray at x2.8..3.2,
    y +/-0.05, z3.10..3.20 blocks the only upper route. A +0.35 y tray move enables
    a +0.4 z duct offset at along-run distances 2 and 4 m (50 mm beam/ceiling gaps).
    Straight translations break the fixed terminal; a second fixed near terminal
    prevents trimming away the objective from either end. Lower/side detours must
    cross corridor solids. This is a model-specific constraint, not a class ban.
    """
    from .scene import IfcScene
    from . import edits
    scene = IfcScene(build_run_fixture(path,millimetres))
    model, scale = scene.model, scene.unit_scale
    body = next(c for c in model.by_type('IfcGeometricRepresentationSubContext') if c.ContextIdentifier=='Body')
    storey = model.by_type('IfcBuildingStorey')[0]
    main,end = model.by_type('IfcDuctSegment')
    main.Tag, end.Tag = 'CTX-DUCT','CTX-END'
    beam = model.by_type('IfcBeam')[0]; beam.Tag = 'CTX-BEAM'
    ceiling = model.by_type('IfcSlab')[0]; ceiling.Tag = 'CTX-CEILING'

    def box(cls,tag,size,origin,fixed=True):
        element = ifcopenshell.api.run('root.create_entity',model,ifc_class=cls,name=tag)
        element.Tag = tag
        ifcopenshell.api.run('spatial.assign_container',model,products=[element],relating_structure=storey)
        _box(model,body,element,tuple(v/scale for v in size),tuple(v/scale for v in origin))
        if fixed:
            lock(element)
        return element

    def lock(element):
        pset = ifcopenshell.api.run('pset.add_pset',model,product=element,name='Pset_SightlineConstraints')
        ifcopenshell.api.run('pset.edit_pset',model,pset=pset,properties={'KeepFixed':True})

    lock(beam); lock(ceiling)
    box('IfcSlab','CTX-FLOOR',(8,3,.2),(-.5,-1.5,2.2))
    for sign in (-1,1):
        box('IfcWall',f'CTX-WALL-{sign}',(8,.2,1.4),(-.5,sign*.6-(.2 if sign<0 else 0),2.2))
    box('IfcCableCarrierSegment','CTX-TRAY',(.4,.1,.1),(2.8,-.05,3.1),False)
    # Tiny physical terminals are outside the offset span but touch the unchanged
    # ends. Real port relationships anchor translation and any trim of the duct.
    for tag,x,width,owner,index,flow in (
            ('CTX-ANCHOR',7.,.1,end,-1,'SINK'),('CTX-NEAR-ANCHOR',0.,-.1,main,0,'SOURCE')):
        anchor = box('IfcDuctFitting',tag,(abs(width),.4,.3),(min(x,x+width),-.2,2.65))
        port = ifcopenshell.api.run('system.add_port',model,element=anchor)
        port.FlowDirection = flow
        matrix = np.eye(4); matrix[:3,:3] = np.array([[0.,0.,1.],[1.,0.,0.],[0.,1.,0.]])
        matrix[:3,3] = [x,0,2.8]
        ifcopenshell.api.run('geometry.edit_object_placement',model,product=port,matrix=matrix,is_si=True)
        other = edits._ports(owner)[index]
        ifcopenshell.api.run('system.connect_port',model,port1=other,port2=port,direction=other.FlowDirection)
    service = ifcopenshell.api.run('system.add_system',model)
    ifcopenshell.api.run('system.assign_system',model,products=[main,end,*model.by_type('IfcDuctFitting')],system=service)
    model.write(str(path))
    return path
