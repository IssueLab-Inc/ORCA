"""Revit's faceted meshes go through the mesh kernel in every clash query (scene.faceted, scene.kernel): OpenCASCADE
sewed each into a solid first, and a check of Snowdon Towers' architecture spent 148 s of about 150 building its
triangle tree (15 s this way). Detection, the live measure and a fix's check must see the same solids, so all three
use the same rule; triangle meshes (Northbank's fittings, the cell's STEP parts) and everything else stay as they were."""
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.geom
import pytest

from sightline import detect, verify
from sightline.fixtures import _box
from sightline.scene import MESH_KERNEL, IfcScene, faceted, kernel

# A box's corners and its six faces, each wound so its normal points out.
CORNERS = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def _faces(m, lo, size):
    pts = [m.createIfcCartesianPoint(tuple(float(lo[k] + c[k] * size[k]) for k in range(3))) for c in CORNERS]
    return [m.createIfcFace([m.createIfcFaceOuterBound(m.createIfcPolyLoop([pts[i] for i in f]), True)]) for f in FACES]


def _model(tmp_path):
    m = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", m, ifc_class="IfcProject", name="Faceted")
    ifcopenshell.api.run("unit.assign_unit", m, units=[ifcopenshell.api.run("unit.add_si_unit", m, unit_type="LENGTHUNIT")])
    ctx = ifcopenshell.api.run("context.add_context", m, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", m, context_type="Model", context_identifier="Body",
                                target_view="MODEL_VIEW", parent=ctx)
    storey = ifcopenshell.api.run("root.create_entity", m, ifc_class="IfcBuildingStorey", name="Level 01")
    ifcopenshell.api.run("aggregate.assign_object", m, relating_object=project, products=[storey])

    def element(name, items, kind="Brep", ifc_class="IfcBuildingElementProxy"):
        e = ifcopenshell.api.run("root.create_entity", m, ifc_class=ifc_class, name=name)
        ifcopenshell.api.run("spatial.assign_container", m, relating_structure=storey, products=[e])
        ifcopenshell.api.run("geometry.edit_object_placement", m, product=e)
        e.Representation = m.createIfcProductDefinitionShape(None, None, [m.createIfcShapeRepresentation(body, "Body", kind, items)])
        return e

    brep = lambda lo, size=(1, 1, 1): m.createIfcFacetedBrep(m.createIfcClosedShell(_faces(m, lo, size)))
    # Two faceted boxes overlapping 0.2 m along x (a Revit family and a Revit railing, as exported); no side flush (the
    # triangle queries miss boxes with every side face flush, whatever the kernel: detect._Solids).
    element("Brep A", [brep((0, 0, 0))])
    element("Surface B", [m.createIfcFaceBasedSurfaceModel([m.createIfcConnectedFaceSet(_faces(m, (0.8, 0.3, 0.2), (1, 1, 1)))])],
            "SurfaceModel")
    # A type's faceted geometry placed through a mapped item (how Revit writes its families).
    source = m.createIfcRepresentationMap(m.createIfcAxis2Placement3D(m.createIfcCartesianPoint((0.0, 0.0, 0.0))),
                                          m.createIfcShapeRepresentation(body, "Body", "Brep", [brep((5, 0, 0))]))
    element("Mapped C", [m.createIfcMappedItem(source, m.createIfcCartesianTransformationOperator3D(
        None, None, m.createIfcCartesianPoint((0.0, 0.0, 0.0)), 1.0, None))], "MappedRepresentation")
    # What stays on OpenCASCADE: a triangle mesh, an extrusion, a faceted element with an opening, a mixed body.
    tri = m.createIfcTriangulatedFaceSet(m.createIfcCartesianPointList3D([(10.0, 0.0, 0.0), (11.0, 0.0, 0.0), (10.0, 1.0, 0.0),
                                                                          (10.0, 0.0, 1.0)]), None, True,
                                         [(1, 3, 2), (1, 2, 4), (2, 3, 4), (3, 1, 4)], None)
    element("Mesh D", [tri], "Tessellation")
    wall = ifcopenshell.api.run("root.create_entity", m, ifc_class="IfcWall", name="Wall E")
    ifcopenshell.api.run("spatial.assign_container", m, relating_structure=storey, products=[wall])
    _box(m, body, wall, (2.0, 0.2, 2.0), (20.0, 0.0, 0.0))
    holed = element("Holed F", [brep((30, 0, 0), (2, 0.2, 2))], ifc_class="IfcWall")
    opening = ifcopenshell.api.run("root.create_entity", m, ifc_class="IfcOpeningElement", name="Hole")
    _box(m, body, opening, (0.5, 0.4, 0.5), (30.5, -0.1, 0.5))
    ifcopenshell.api.run("feature.add_feature", m, feature=opening, element=holed)
    mixed = element("Mixed G", [brep((40, 0, 0))])
    _box(m, body, mixed, (1.0, 1.0, 1.0), (40.0, 2.0, 0.0))
    mixed.Representation.Representations[0].Items = [*mixed.Representation.Representations[0].Items,
                                                      *mixed.Representation.Representations[1].Items]
    path = tmp_path / "faceted.ifc"
    m.write(str(path))
    return path


@pytest.fixture
def scene(tmp_path):
    return IfcScene([_model(tmp_path)])


def gid(scene, name):
    return next(p.GlobalId for p in scene.models[0].by_type("IfcProduct") if p.Name == name)


def test_faceted_meshes_are_told_apart_from_what_stays_on_opencascade(scene):
    is_faceted = {p.Name: faceted(p) for p in scene.models[0].by_type("IfcElement") if p.Representation is not None}
    assert is_faceted == {"Brep A": True, "Surface B": True, "Mapped C": True, "Mesh D": False, "Wall E": False,
                          "Holed F": False, "Mixed G": False, "Hole": False}
    assert kernel(scene.entity(gid(scene, "Brep A"))) == {"geometry_library": MESH_KERNEL}
    assert kernel(scene.entity(gid(scene, "Wall E"))) == {}


@pytest.fixture
def kernels(monkeypatch):
    """Which kernel each element went through in the clash queries' iterators."""
    seen: dict[str, set] = {}
    real = ifcopenshell.geom.iterator

    def spy(settings, model, threads=1, include=None, **kw):
        for e in include or ():
            seen.setdefault(e.Name, set()).add(kw.get("geometry_library"))
        return real(settings, model, threads, include=include, **kw)

    monkeypatch.setattr(ifcopenshell.geom, "iterator", spy)
    return seen


def test_detection_the_live_measure_and_a_fix_check_see_the_same_faceted_solids(scene, kernels):
    a, b = gid(scene, "Brep A"), gid(scene, "Surface B")
    scene.bounds()
    kernels.clear()   # the boxes measured at open are not a clash query
    run = detect.run(scene)
    clash = next(c for c in run.report.clashes if {c.a.global_id, c.b.global_id} == {a, b})
    assert clash.distance_m == pytest.approx(-0.2, abs=2e-3)
    assert detect.measure_pair(scene, a, b) == pytest.approx(clash.distance_m, abs=1e-6), "the clash card's Now"
    verdict = verify.check(scene, [a], clearance_m=0.0)
    assert not verdict.passed and b in {h.other for h in verdict.hits}, "a fix's check sees the same overlap"
    assert kernels["Brep A"] == {MESH_KERNEL} and kernels["Surface B"] == {MESH_KERNEL}
    assert kernels.get("Wall E", {None}) == {None} and kernels.get("Mesh D", {None}) == {None}, "the rest as before"
