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
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="ORCA fixture")
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
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="ORCA offset fixture")
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
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="ORCA joint fixture")
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


def build_detection_fixtures(folder: Path, offset: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> list[Path]:
    """A structure model and a services model with one of every case ORCA detection has to get right
    (docs/detection.md), in metres, everything shifted by `offset` (to test models far from the origin):

    Structure vs services: the duct runs 300 mm through the beam (a clash); one pipe sits on the beam (a touch), another
    0.5 mm into it (still a touch at 1 mm); a third hangs 20 mm under it (only a 25 mm clearance test sees it).
    Structure within: a strut runs 30 mm into the beam's end with every face flush (only the collision query sees it);
    a door is 20 mm larger than its wall's opening (host and filler); two curtain-wall plates overlap (one assembly);
    two identical columns (a duplicate); two crossing braces with the same box (a real overlap, not a duplicate).
    Services within: a sensor wholly inside the duct (a clash); two duct segments joined port to port overlap 50 mm.
    """
    ox, oy, oz = offset

    def new(name):
        model = ifcopenshell.api.run("project.create_file", version="IFC4")
        project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name=name)
        ifcopenshell.api.run("unit.assign_unit", model, units=[
            ifcopenshell.api.run("unit.add_si_unit", model, unit_type="LENGTHUNIT")])
        ctx = ifcopenshell.api.run("context.add_context", model, context_type="Model")
        body = ifcopenshell.api.run("context.add_context", model, context_type="Model", context_identifier="Body",
                                    target_view="MODEL_VIEW", parent=ctx)
        storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 01")
        ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[storey])
        return model, body, storey

    def element(model, body, storey, ifc_class, name, size=None, origin=None):
        e = ifcopenshell.api.run("root.create_entity", model, ifc_class=ifc_class, name=name)
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[e])
        if size is not None:
            _box(model, body, e, size, (origin[0] + ox, origin[1] + oy, origin[2] + oz))
        return e

    def brace(model, body, storey, name, start, end):
        e = element(model, body, storey, "IfcMember", name)
        ifcopenshell.api.run("geometry.edit_object_placement", model, product=e)
        d = np.subtract(end, start)
        length = float(np.linalg.norm(d))
        profile = model.createIfcRectangleProfileDef("AREA", None, None, 0.1, 0.1)
        position = model.createIfcAxis2Placement3D(
            model.createIfcCartesianPoint((start[0] + ox, start[1] + oy, start[2] + oz)),
            model.createIfcDirection(tuple(float(x) for x in d / length)), model.createIfcDirection((0.0, 1.0, 0.0)))
        solid = model.createIfcExtrudedAreaSolid(profile, position, model.createIfcDirection((0.0, 0.0, 1.0)), length)
        e.Representation = model.createIfcProductDefinitionShape(
            None, None, [model.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])])

    s, sb, ss = new("Detection fixture structure")
    element(s, sb, ss, "IfcBeam", "Beam B1", (6.0, 0.2, 0.4), (0.0, -0.1, 2.6))
    element(s, sb, ss, "IfcMember", "Strut S1", (0.5, 0.2, 0.4), (5.97, -0.1, 2.6))
    wall = element(s, sb, ss, "IfcWall", "Wall W1", (4.0, 0.2, 3.0), (0.0, 3.0, 0.0))
    opening = element(s, sb, ss, "IfcOpeningElement", "Door opening", (1.0, 0.4, 2.1), (1.5, 2.9, 0.0))
    ifcopenshell.api.run("feature.add_feature", s, feature=opening, element=wall)
    door = element(s, sb, ss, "IfcDoor", "Door D1", (1.04, 0.2, 2.12), (1.48, 3.0, 0.0))
    ifcopenshell.api.run("feature.add_filling", s, opening=opening, element=door)
    cw = element(s, sb, ss, "IfcCurtainWall", "Curtain wall CW1")
    panels = [element(s, sb, ss, "IfcPlate", f"CW1 panel {n}", (1.55, 0.05, 3.0), (6.0 + 1.5 * n, 3.0, 0.0))
              for n in (0, 1)]
    ifcopenshell.api.run("aggregate.assign_object", s, relating_object=cw, products=panels)
    for n in (1, 2):
        element(s, sb, ss, "IfcColumn", f"Column C1 copy {n}", (0.3, 0.3, 3.0), (10.0, 0.0, 0.0))
    brace(s, sb, ss, "Brace X1", (12.0, 0.0, 0.0), (14.0, 0.0, 2.0))
    brace(s, sb, ss, "Brace X2", (12.0, 0.0, 2.0), (14.0, 0.0, 0.0))

    m, mb, ms = new("Detection fixture services")
    element(m, mb, ms, "IfcDuctSegment", "Duct D1", (0.4, 4.0, 0.3), (2.8, -2.0, 2.65))
    element(m, mb, ms, "IfcSensor", "Sensor in duct", (0.05, 0.05, 0.05), (2.9, 1.0, 2.75))
    element(m, mb, ms, "IfcPipeSegment", "Pipe P1 on beam", (0.1, 4.0, 0.1), (4.0, -2.0, 2.5))
    element(m, mb, ms, "IfcPipeSegment", "Pipe P2 half a millimetre in", (0.1, 4.0, 0.1), (4.5, -2.0, 2.5005))
    element(m, mb, ms, "IfcPipeSegment", "Pipe P3 under beam", (0.1, 4.0, 0.1), (1.0, -2.0, 2.48))
    ducts = [element(m, mb, ms, "IfcDuctSegment", f"Duct run {n}", (2.05, 0.4, 0.3), (2.0 * n, 6.0, 2.65)) for n in (0, 1)]
    ports = []
    for duct, x in zip(ducts, (2.0, 2.0)):
        port = ifcopenshell.api.run("system.add_port", m, element=duct)
        matrix = np.eye(4)
        matrix[:3, 3] = (x + ox, 6.2 + oy, 2.8 + oz)
        ifcopenshell.api.run("geometry.edit_object_placement", m, product=port, matrix=matrix, is_si=True)
        ports.append(port)
    ifcopenshell.api.run("system.connect_port", m, port1=ports[0], port2=ports[1], direction="SOURCE")

    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / "Fixture-Structure.ifc", folder / "Fixture-MEP.ifc"]
    s.write(str(paths[0]))
    m.write(str(paths[1]))
    return paths


def build_route_fixture(path: Path) -> Path:
    """Runs that only a route clears (edits.apply_route), metres, one storey. Each straight segment has ports at both
    ends; the compound duct's far port joins a 1 m end segment.

    - Compound duct (Tag RT-1, along X at y = 0, 400 wide x 300 deep, centreline z 2.8, 0-6 m): a full-height column at
      x 3.0-3.2 stands in its line. North of it a 2.9 m plinth (x 2.6-3.6, y 0.25-0.9), south of it a wall to the slab
      (x 2.0-4.0, y -0.9 to -0.3); slab soffit at 3.4. Up alone hits the column, sideways alone the plinth or the wall;
      up 300 mm, then north 550 mm over the plinth (and back) clears.
    - Two-column duct (Tag RT-2, along X at y = 5, 6 m): full-height columns south of its line at x 1.8-2.2 and 3.8-4.2
      (y 4.6-5.1), a post between them on the north side (x 2.95-3.05, y 5.3-5.4). Only one detour round each column
      (north 300 mm) clears: one long detour, or a move, hits the post.
    - Sloped duct (Tag RT-3, along X at y = -5, falling 1:100 from z 2.8, 6 m) with a full-height column at x 3.0-3.2
      in its line and room to its north.
    - Waste pipe (Tag RT-4, DN100 PVC "Waste pipe", level along X at y = -10, z 2.0, 6 m) with a column in its line.
    - Cold water pipe (Tag RT-5, DN50, level along X at y = -7.5, z 2.0, 6 m) with a column in its line: a round pipe
      may change up and sideways at once (a rolling offset).
    """
    model = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="ORCA route fixture")
    ifcopenshell.api.run("unit.assign_unit", model, units=[ifcopenshell.api.run("unit.add_si_unit", model, unit_type="LENGTHUNIT")])
    ctx = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", model, context_type="Model",
                                context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 02")
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[storey])

    def element(ifc_class, name):
        e = ifcopenshell.api.run("root.create_entity", model, ifc_class=ifc_class, name=name)
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[e])
        return e

    def block(ifc_class, name, x0, x1, y0, y1, z0, z1):
        _box(model, body, element(ifc_class, name), (x1 - x0, y1 - y0, z1 - z0), (x0, y0, z0))

    def segment(ifc_class, name, tag, start, end, profile):
        e = element(ifc_class, name)
        e.Tag = tag
        ifcopenshell.api.run("geometry.edit_object_placement", model, product=e)
        start, end = np.asarray(start, float), np.asarray(end, float)
        d = (end - start) / np.linalg.norm(end - start)
        x = np.cross(UP_, d)
        x /= np.linalg.norm(x)
        position = model.createIfcAxis2Placement3D(model.createIfcCartesianPoint(tuple(map(float, start))),
                                                   model.createIfcDirection(tuple(map(float, d))),
                                                   model.createIfcDirection(tuple(map(float, x))))
        solid = model.createIfcExtrudedAreaSolid(profile, position, model.createIfcDirection((0.0, 0.0, 1.0)),
                                                 float(np.linalg.norm(end - start)))
        e.Representation = model.createIfcProductDefinitionShape(
            None, None, [model.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])])
        ports = []
        for n, (p, flow) in enumerate(((start, "SINK"), (end, "SOURCE"))):
            port = ifcopenshell.api.run("system.add_port", model, element=e)
            port.Name, port.FlowDirection = f"Port {n}", flow
            m = np.eye(4)
            z = -d if flow == "SINK" else d
            m[:3, :3] = np.column_stack([x, np.cross(z, x), z])
            m[:3, 3] = p
            ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=m, is_si=True)
            ports.append(port)
        return e, ports

    rect = lambda: model.createIfcRectangleProfileDef("AREA", None, None, 0.4, 0.3)  # X across (level), Y up
    block("IfcSlab", "Level 03 slab", -1.0, 7.0, -12.0, 7.0, 3.4, 3.6)
    # Compound duct
    _, (_, far) = segment("IfcDuctSegment", "Supply duct 400x300", "RT-1", (0, 0, 2.8), (6, 0, 2.8), rect())
    _, (near, _) = segment("IfcDuctSegment", "Supply duct 400x300", "RT-1E", (6, 0, 2.8), (7, 0, 2.8), rect())
    ifcopenshell.api.run("system.connect_port", model, port1=far, port2=near, direction="SOURCE")
    block("IfcColumn", "Column A3", 3.0, 3.2, -0.3, 0.25, 0.0, 3.4)
    block("IfcBuildingElementProxy", "Plinth", 2.6, 3.6, 0.25, 0.9, 0.0, 2.9)
    block("IfcWall", "Wall W1", 2.0, 4.0, -0.9, -0.3, 0.0, 3.4)
    # Two-column duct
    segment("IfcDuctSegment", "Supply duct 400x300", "RT-2", (0, 5, 2.8), (6, 5, 2.8), rect())
    block("IfcColumn", "Column B2", 1.8, 2.2, 4.6, 5.1, 0.0, 3.4)
    block("IfcColumn", "Column B4", 3.8, 4.2, 4.6, 5.1, 0.0, 3.4)
    block("IfcMember", "Post P1", 2.95, 3.05, 5.3, 5.4, 0.0, 3.4)
    # Sloped duct
    segment("IfcDuctSegment", "Exhaust duct 400x300", "RT-3", (0, -5, 2.8), (6, -5, 2.74), rect())
    block("IfcColumn", "Column C3", 3.0, 3.2, -5.3, -4.9, 0.0, 3.4)
    # Waste pipe
    pipe = model.createIfcCircleProfileDef("AREA", None, None, 0.055)
    segment("IfcPipeSegment", "Waste pipe DN100", "RT-4", (0, -10, 2.0), (6, -10, 2.0), pipe)
    block("IfcColumn", "Column D3", 3.0, 3.2, -10.2, -9.9, 0.0, 3.4)
    # Cold water pipe
    segment("IfcPipeSegment", "Cold water DN50", "RT-5", (0, -7.5, 2.0), (6, -7.5, 2.0),
            model.createIfcCircleProfileDef("AREA", None, None, 0.03))
    block("IfcColumn", "Column E3", 3.0, 3.2, -7.7, -7.4, 0.0, 3.4)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return path


UP_ = np.array([0.0, 0.0, 1.0])


def build_penetration_fixture(folder: Path, version: str = "IFC4") -> list[Path]:
    """Services through walls and slabs (edits.penetration), metres, one storey, two files: structure and services.

    Structure: wall W1 (x 2.0-2.2, y -3 to 3, z 0-3.4, fire rated EI 60, not load-bearing), wall W2 (x 6.0-6.3,
    load-bearing), slab S1 (z 3.4-3.6 over x -1 to 9, y -4 to 8), beam B1 (x 3.0-3.3, y 5-7, z 2.8-3.4) and column C1
    (x 4.0-4.3, y 6.85-7.15). Services, each a straight segment with a port at both ends:
    - pipe P1 (DN100, Tag PN-1) along X at y 0, z 2.0, x 0-4: through W1;
    - duct D1 (400 x 300, PN-2) along X at y -2, z 1.5, x 0-4: through W1;
    - riser R1 (DN100, PN-3) vertical at (5, 5), z 2.5-4.5: through S1;
    - pipe P2 (DN100, PN-4) along X at y 6, z 3.1, x 2-4: through beam B1 (refused);
    - pipe P3 (DN100, PN-5) along Y at x 4.15, z 1.0, y 6-8: through column C1 (refused);
    - pipe P4 (DN100, PN-6) along X at y 2, z 3.33, x 0-4: through W1 at its top (the opening would break out).
    - pipe P5 (DN50, PN-7) along X at y 1, z 1.0, x 5-7: through load-bearing W2.
    Beyond the slab: transfer beam B2 (x 10.0-10.3, y 0-4, z 2.8-3.4) with column C2 standing on it (y 1.85-2.15,
    z 3.4-6.4), and pipe P6 (DN100, PN-8) along X at y 3, z 3.1, x 9.5-11 through it; a 3 mm gland plate GP1 (x 12-12.6,
    y 0-0.4, z 1.997-2.0) with a 32 mm conduit (PN-9) down through it at (12.3, 0.2), z 1.9-2.6; a glazing unit (x 14-14.02,
    y -1 to 1, z 0-2.5) with pipe P7 (DN50, PN-10) along X at y 0, z 1.0, x 13.5-14.5 through it.
    """
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in ("structure", "services"):
        model = ifcopenshell.api.run("project.create_file", version=version)
        if version == "IFC2X3":   # IFC2X3 requires owner history on every rooted entity
            person = model.createIfcPerson(None, "Test", None, None, None, None, None, None)
            org = model.createIfcOrganization(None, "ORCA", None, None, None)
            app = model.createIfcApplication(org, "1", "ORCA tests", "ORCA")
            history = model.createIfcOwnerHistory(model.createIfcPersonAndOrganization(person, org, None), app,
                                                  None, "ADDED", None, None, None, 0)
            ifcopenshell.api.owner.settings.get_user = lambda f, h=history: h.OwningUser
            ifcopenshell.api.owner.settings.get_application = lambda f, h=history: h.OwningApplication
        project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name=f"ORCA penetration {name}")
        ifcopenshell.api.run("unit.assign_unit", model, units=[ifcopenshell.api.run("unit.add_si_unit", model, unit_type="LENGTHUNIT")])
        ctx = ifcopenshell.api.run("context.add_context", model, context_type="Model")
        body = ifcopenshell.api.run("context.add_context", model, context_type="Model",
                                    context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
        storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 01")
        ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[storey])

        def element(ifc_class, label):
            e = ifcopenshell.api.run("root.create_entity", model, ifc_class=ifc_class, name=label)
            ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[e])
            return e

        def block(ifc_class, label, x0, x1, y0, y1, z0, z1, pset=None):
            e = element(ifc_class, label)
            _box(model, body, e, (x1 - x0, y1 - y0, z1 - z0), (x0, y0, z0))
            if pset:
                p = ifcopenshell.api.run("pset.add_pset", model, product=e, name=pset[0])
                ifcopenshell.api.run("pset.edit_pset", model, pset=p, properties=pset[1])

        def segment(ifc_class, label, tag, start, end, profile):
            e = element(ifc_class if version != "IFC2X3" else "IfcFlowSegment", label)
            e.Tag = tag
            ifcopenshell.api.run("geometry.edit_object_placement", model, product=e)
            start, end = np.asarray(start, float), np.asarray(end, float)
            d = (end - start) / np.linalg.norm(end - start)
            x = np.cross(UP_ if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0]), d)
            x /= np.linalg.norm(x)
            position = model.createIfcAxis2Placement3D(model.createIfcCartesianPoint(tuple(map(float, start))),
                                                       model.createIfcDirection(tuple(map(float, d))),
                                                       model.createIfcDirection(tuple(map(float, x))))
            solid = model.createIfcExtrudedAreaSolid(profile, position, model.createIfcDirection((0.0, 0.0, 1.0)),
                                                     float(np.linalg.norm(end - start)))
            e.Representation = model.createIfcProductDefinitionShape(
                None, None, [model.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])])
            for n, (p, flow) in enumerate(((start, "SINK"), (end, "SOURCE"))):
                port = ifcopenshell.api.run("system.add_port", model, element=e)
                port.Name, port.FlowDirection = f"Port {n}", flow
                m = np.eye(4)
                m[:3, 3] = p
                ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=m, is_si=True)

        centred = lambda: model.createIfcAxis2Placement2D(model.createIfcCartesianPoint((0.0, 0.0)), None)
        pipe = lambda r: model.createIfcCircleProfileDef("AREA", None, centred(), r)
        if name == "structure":
            block("IfcWall", "Wall W1 partition", 2.0, 2.2, -3.0, 3.0, 0.0, 3.4,
                  ("Pset_WallCommon", {"FireRating": "EI 60", "LoadBearing": False}))
            block("IfcWall", "Wall W2 core", 6.0, 6.3, -3.0, 3.0, 0.0, 3.4, ("Pset_WallCommon", {"LoadBearing": True}))
            block("IfcSlab", "Slab S1", -1.0, 9.0, -4.0, 8.0, 3.4, 3.6)
            block("IfcBeam", "Beam B1", 3.0, 3.3, 5.0, 7.0, 2.8, 3.4)
            block("IfcColumn", "Column C1", 4.0, 4.3, 6.85, 7.15, 0.0, 3.4)
            block("IfcBeam", "Transfer beam B2", 10.0, 10.3, 0.0, 4.0, 2.8, 3.4)
            block("IfcColumn", "Column C2 on B2", 10.0, 10.3, 1.85, 2.15, 3.4, 6.4)
            block("IfcPlate", "Gland plate GP1", 12.0, 12.6, 0.0, 0.4, 1.997, 2.0)
            block("IfcPlate", "Vision glazing unit G1", 14.0, 14.02, -1.0, 1.0, 0.0, 2.5)
        else:
            segment("IfcPipeSegment", "Heating flow DN100", "PN-1", (0, 0, 2.0), (4, 0, 2.0), pipe(0.055))
            segment("IfcDuctSegment", "Supply duct 400x300", "PN-2", (0, -2, 1.5), (4, -2, 1.5),
                    model.createIfcRectangleProfileDef("AREA", None, centred(), 0.4, 0.3))
            segment("IfcPipeSegment", "Riser DN100", "PN-3", (5, 5, 2.5), (5, 5, 4.5), pipe(0.055))
            segment("IfcPipeSegment", "Pipe through beam DN100", "PN-4", (2, 6, 3.1), (4, 6, 3.1), pipe(0.055))
            segment("IfcPipeSegment", "Pipe through column DN100", "PN-5", (4.15, 6, 1.0), (4.15, 8, 1.0), pipe(0.055))
            segment("IfcPipeSegment", "Pipe at wall head DN100", "PN-6", (0, 2, 3.33), (4, 2, 3.33), pipe(0.055))
            segment("IfcPipeSegment", "Cold water DN50", "PN-7", (5, 1, 1.0), (7, 1, 1.0), pipe(0.03))
            segment("IfcPipeSegment", "Pipe through transfer beam DN100", "PN-8", (9.5, 3, 3.1), (11, 3, 3.1), pipe(0.055))
            segment("IfcCableCarrierSegment", "Feed conduit 32", "PN-9", (12.3, 0.2, 2.6), (12.3, 0.2, 1.9), pipe(0.016))
            segment("IfcPipeSegment", "Pipe through glazing DN50", "PN-10", (13.5, 0, 1.0), (14.5, 0, 1.0), pipe(0.03))
        path = folder / f"pen-{name}.ifc"
        model.write(str(path))
        paths.append(path)
    if version == "IFC2X3":
        import importlib
        importlib.reload(ifcopenshell.api.owner.settings)
    return paths


def build_resize_fixture(path: Path) -> Path:
    """Runs that only a flatter section clears (edits.apply_resize), metres, one storey; straight segments with ports at
    both ends.

    - Supply duct (Tag RS-1, 500 wide x 300 deep, along X at y 0, centre z 2.6 (bottom 2.45, top 2.75), 0-6 m), joined
      at 6 m to a 1 m end segment. Beam B1 across it (x 2.8-3.2, z 2.7-3.3): 50 mm into its top. The slab above (soffit
      3.3), a ceiling 50 mm under the duct (top 2.40) and walls either side (y ±0.9) leave no offset or move: 220 mm deep,
      bottom kept, clears with 30 mm, 735 wide for the same equivalent diameter.
    - Cable tray (RS-2, 300 x 100, along X at y 5, centre z 2.6, 0-6 m) under beam B2 (bottom 2.63): 20 mm in.
    - Pipe (RS-3, DN100) and a round duct (RS-4, Ø300), both along X under beam B2's line: sizes a resize keeps.
    """
    model = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="ORCA resize fixture")
    ifcopenshell.api.run("unit.assign_unit", model, units=[ifcopenshell.api.run("unit.add_si_unit", model, unit_type="LENGTHUNIT")])
    ctx = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", model, context_type="Model",
                                context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 01")
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[storey])

    def element(ifc_class, name):
        e = ifcopenshell.api.run("root.create_entity", model, ifc_class=ifc_class, name=name)
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[e])
        return e

    def block(ifc_class, name, x0, x1, y0, y1, z0, z1):
        _box(model, body, element(ifc_class, name), (x1 - x0, y1 - y0, z1 - z0), (x0, y0, z0))

    def segment(ifc_class, name, tag, start, end, profile):
        e = element(ifc_class, name)
        e.Tag = tag
        ifcopenshell.api.run("geometry.edit_object_placement", model, product=e)
        start, end = np.asarray(start, float), np.asarray(end, float)
        d = (end - start) / np.linalg.norm(end - start)
        x = np.cross(UP_, d)
        x /= np.linalg.norm(x)
        position = model.createIfcAxis2Placement3D(model.createIfcCartesianPoint(tuple(map(float, start))),
                                                   model.createIfcDirection(tuple(map(float, d))),
                                                   model.createIfcDirection(tuple(map(float, x))))
        solid = model.createIfcExtrudedAreaSolid(profile, position, model.createIfcDirection((0.0, 0.0, 1.0)),
                                                 float(np.linalg.norm(end - start)))
        e.Representation = model.createIfcProductDefinitionShape(
            None, None, [model.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])])
        ports = []
        for n, (p, flow) in enumerate(((start, "SINK"), (end, "SOURCE"))):
            port = ifcopenshell.api.run("system.add_port", model, element=e)
            port.Name, port.FlowDirection = f"Port {n}", flow
            m = np.eye(4)
            z = -d if flow == "SINK" else d
            m[:3, :3] = np.column_stack([x, np.cross(z, x), z])
            m[:3, 3] = p
            ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=m, is_si=True)
            ports.append(port)
        return e, ports

    rect = lambda w, h: model.createIfcRectangleProfileDef("AREA", None, None, w, h)   # X across (level), Y up
    _, (_, far) = segment("IfcDuctSegment", "Supply duct 500x300", "RS-1", (0, 0, 2.6), (6, 0, 2.6), rect(0.5, 0.3))
    _, (near, _) = segment("IfcDuctSegment", "Supply duct 500x300", "RS-1E", (6, 0, 2.6), (7, 0, 2.6), rect(0.5, 0.3))
    ifcopenshell.api.run("system.connect_port", model, port1=far, port2=near, direction="SOURCE")
    block("IfcBeam", "Beam B1", 2.8, 3.2, -0.9, 0.9, 2.7, 3.3)
    block("IfcSlab", "Level 02 slab", -1.0, 8.0, -1.0, 7.0, 3.3, 3.5)
    block("IfcCovering", "Ceiling", 0.0, 6.0, -0.9, 0.9, 2.38, 2.40)
    block("IfcWall", "Wall north", 0.0, 6.0, 0.9, 1.0, 0.0, 3.3)
    block("IfcWall", "Wall south", 0.0, 6.0, -1.0, -0.9, 0.0, 3.3)
    segment("IfcCableCarrierSegment", "Cable tray 300x100", "RS-2", (0, 5, 2.6), (6, 5, 2.6), rect(0.3, 0.1))
    block("IfcBeam", "Beam B2", 2.8, 3.2, 3.5, 6.5, 2.63, 3.3)
    segment("IfcPipeSegment", "Heating pipe DN100", "RS-3", (0, 4.2, 2.6), (6, 4.2, 2.6),
            model.createIfcCircleProfileDef("AREA", None, None, 0.055))
    segment("IfcDuctSegment", "Extract duct 300", "RS-4", (0, 5.8, 2.5), (6, 5.8, 2.5),
            model.createIfcCircleProfileDef("AREA", None, None, 0.15))
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return path
