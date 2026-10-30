"""STEP models: read a STEP assembly, check it as IFC, and write the fixes back into the STEP.

Machine builders work in STEP. ORCA checks and edits IFC, so a STEP file is converted when it opens:
- every part (a leaf of the assembly tree) becomes one IFC element with a triangulated body, its STEP name and colour
  (alpha included), and a placement at its box's lower corner, so a move is one placement edit;
- the STEP groups (sub-assemblies) become IfcGroups, for organisation only. They are not IfcElementAssembly: detection
  treats an assembly's parts as meant to meet, and a machine's top groups ("Guarding") hold parts that must not clash;
- each element carries the pset `ORCA_STEP` (Group, Label, Source), which ties it back to the STEP label;
- STEP carries no IFC classes, so `classify` (one Muse call per 200 parts, from names and group paths) picks one per
  part; without it every part is an IfcBuildingElementProxy named for its group.

Fixes on these parts are moves (offsets and trims need extruded profiles). `export` writes the STEP again with each
moved part's component translated, keeping names and colours: the designer gets their own file back.

GlobalIds come from the file's hash and the part's label, so the same STEP converts to the same ids every time.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import numpy as np

from .limits import env_int
from .scene import STEP_PSET

SUFFIXES = {".step", ".stp"}
MAX_PARTS = env_int("SIGHTLINE_STEP_MAX_PARTS", 20000)
MAX_TRIANGLES = env_int("SIGHTLINE_STEP_MAX_TRIANGLES", 5000000)
PSET = STEP_PSET
NAMESPACE = uuid.UUID("3b8f2d0e-6c1a-4f5e-9a7d-2f1c5b8e4a90")

# The classes a STEP part may become (`classify`), each with its IFC4 predefined types where it has them.
CLASSES = ("IfcMember", "IfcPlate", "IfcColumn", "IfcBeam", "IfcSlab", "IfcWall", "IfcMechanicalFastener", "IfcPipeSegment",
           "IfcPipeFitting", "IfcValve", "IfcCableCarrierSegment", "IfcCableCarrierFitting", "IfcSensor", "IfcDoor",
           "IfcFurniture", "IfcTransportElement", "IfcElectricDistributionBoard", "IfcUnitaryControlElement",
           "IfcElectricMotor", "IfcFilter", "IfcSwitchingDevice", "IfcBuildingElementPart", "IfcBuildingElementProxy")


class StepError(ValueError):
    """A STEP file that cannot be converted (unreadable, empty or too big); the message is for the user."""


@dataclass
class Part:
    name: str
    group: str                   # "Guarding/Posts": the names of the assemblies above it, root excluded
    path: list[str]              # component label entries from the root down to this part (for export)
    shape: object                # TopoDS_Shape in world position (STEP units)
    colour: tuple[float, float, float] | None = None
    alpha: float = 1.0
    ifc_class: str = "IfcBuildingElementProxy"
    kind: str = ""               # predefined type, or the object type when it is not one
    gid: str = ""
    origin: list[float] = field(default_factory=list)   # placement origin, metres (box minimum)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------- reading

def _quiet() -> None:
    """OpenCASCADE's STEP reader and writer print progress to stdout; the server's log does not need it."""
    from OCP.Message import Message
    Message.DefaultMessenger_s().ChangePrinters().Clear()


def _read(path: Path):
    """The STEP as an XCAF document, with its shape and colour tools and the scale from its units to metres."""
    _quiet()
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise StepError(f"{path.name} could not be read as STEP.")
    if not reader.Transfer(doc):
        raise StepError(f"{path.name} has no shapes ORCA can read.")
    unit = (Interface_Static.CVal_s("xstep.cascade.unit") or "MM").upper()
    scale = {"MM": 0.001, "CM": 0.01, "M": 1.0, "IN": 0.0254, "INCH": 0.0254, "FT": 0.3048}.get(unit, 0.001)
    return doc, XCAFDoc_DocumentTool.ShapeTool_s(doc.Main()), XCAFDoc_DocumentTool.ColorTool_s(doc.Main()), scale


def _name(label) -> str:
    from OCP.TDataStd import TDataStd_Name
    attr = TDataStd_Name()
    return attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else ""


def _entry(label) -> str:
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TDF import TDF_Tool
    s = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, s)
    return s.ToCString()


def _colour(colours, *labels) -> tuple[tuple[float, float, float] | None, float]:
    from OCP.Quantity import Quantity_ColorRGBA
    from OCP.XCAFDoc import XCAFDoc_ColorGen, XCAFDoc_ColorSurf
    c = Quantity_ColorRGBA()
    for label in labels:
        for kind in (XCAFDoc_ColorSurf, XCAFDoc_ColorGen):
            if colours.GetColor_s(label, kind, c):
                rgb = c.GetRGB()
                return (rgb.Red(), rgb.Green(), rgb.Blue()), float(c.Alpha())
    return None, 1.0


def parts(path: Path) -> tuple[list[Part], float, str]:
    """Every leaf part of the STEP, in world position, with the scale to metres and the root's name."""
    from OCP.TDF import TDF_Label
    from OCP.TopLoc import TopLoc_Location
    from OCP.collections import Sequence_TDF_Label

    doc, shapes, colours, scale = _read(path)
    out: list[Part] = []

    def walk(label, loc, groups: list[str], trail: list[str], inherited):
        if shapes.IsAssembly_s(label):
            kids = Sequence_TDF_Label()
            shapes.GetComponents_s(label, kids)
            for i in range(1, kids.Length() + 1):
                comp = kids.Value(i)
                ref = TDF_Label()
                shapes.GetReferredShape_s(comp, ref)
                colour = _colour(colours, comp)
                sub = groups + [_name(ref)] if shapes.IsAssembly_s(ref) else groups
                walk(ref, loc.Multiplied(shapes.GetLocation_s(comp)), sub, trail + [_entry(comp)],
                     colour if colour[0] else inherited)
                if len(out) > MAX_PARTS:
                    raise StepError(f"{path.name} has more than {MAX_PARTS:,} parts: too many for the demo.")
        else:
            colour, alpha = _colour(colours, label)
            if colour is None:
                colour, alpha = inherited
            out.append(Part(name=_name(label) or f"Part {len(out) + 1}", group="/".join(groups), path=trail,
                            shape=shapes.GetShape_s(label).Moved(loc), colour=colour, alpha=alpha))

    roots = Sequence_TDF_Label()
    shapes.GetFreeShapes(roots)
    root_name = ""
    for i in range(1, roots.Length() + 1):
        root = roots.Value(i)
        root_name = root_name or _name(root)
        walk(root, TopLoc_Location(), [], [_entry(root)], (None, 1.0))
    if not out:
        raise StepError(f"{path.name} has no parts.")
    return out, scale, root_name


def mesh(shape, scale: float) -> tuple[np.ndarray, np.ndarray]:
    """The shape's triangles: (vertices in metres, n x 3; faces, m x 3, 0-based), outward facing."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Tool
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)
    lo, hi = box.CornerMin(), box.CornerMax()
    size = max(hi.X() - lo.X(), hi.Y() - lo.Y(), hi.Z() - lo.Z())
    deflection = min(0.5 / (scale * 1000), 0.002 * size) or 0.1   # at most 0.5 mm, finer for small parts
    BRepMesh_IncrementalMesh(shape, deflection, False, 0.35, True)
    verts, faces, n = [], [], 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                verts.append((p.X(), p.Y(), p.Z()))
            flip = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                faces.append((n + a - 1, n + c - 1, n + b - 1) if flip else (n + a - 1, n + b - 1, n + c - 1))
            n += tri.NbNodes()
        exp.Next()
    return np.asarray(verts, dtype=float) * scale, np.asarray(faces, dtype=int).reshape(-1, 3)


def _prism(shape, scale: float) -> dict | None:
    """The part as an exact straight extrusion when it is one solid that is a cylinder rod or a box: {"profile":
    ("circle", r) | ("rect", x, y), "start", "axis", "xdir" (unit, world), "depth"} in metres; else None (a mesh).
    Rods and bars written this way can be offset and trimmed like any IFC member; everything else stays a mesh."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    solids = TopExp_Explorer(shape, TopAbs_SOLID)
    if not solids.More():
        return None
    solid = solids.Current()
    solids.Next()
    if solids.More():
        return None                        # several solids: a compound part stays a mesh
    planes, cylinders = [], []
    exp = TopExp_Explorer(solid, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face(exp.Current())
        surf = BRepAdaptor_Surface(face)
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        c = props.CentreOfMass()
        centre = np.array([c.X(), c.Y(), c.Z()])
        if surf.GetType() == GeomAbs_Plane:
            n = surf.Plane().Axis().Direction()
            normal = np.array([n.X(), n.Y(), n.Z()]) * (-1 if face.Orientation() == TopAbs_REVERSED else 1)
            planes.append((centre, normal))
        elif surf.GetType() == GeomAbs_Cylinder:
            cyl = surf.Cylinder()
            d, o = cyl.Axis().Direction(), cyl.Axis().Location()
            cylinders.append((np.array([o.X(), o.Y(), o.Z()]), np.array([d.X(), d.Y(), d.Z()]), cyl.Radius()))
        else:
            return None
        exp.Next()
    vol = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, vol)
    volume = abs(vol.Mass())
    tol = 1e-6

    if len(cylinders) == 1 and len(planes) == 2:
        origin, axis, r = cylinders[0]
        (c0, n0), (c1, n1) = planes
        if abs(abs(n0 @ axis) - 1) > tol or abs(abs(n1 @ axis) - 1) > tol:
            return None
        on_axis = lambda c: np.linalg.norm((c - origin) - axis * ((c - origin) @ axis))
        if on_axis(c0) > 1e-3 * r or on_axis(c1) > 1e-3 * r:
            return None
        depth = abs((c1 - c0) @ axis)
        if depth <= 0 or abs(volume - np.pi * r * r * depth) > 1e-3 * volume:
            return None
        axis = axis if (c1 - c0) @ axis > 0 else -axis
        xdir = np.cross(axis, [0, 0, 1] if abs(axis[2]) < 0.9 else [1, 0, 0])
        return {"profile": ("circle", r * scale), "start": (c0 * scale).tolist(), "axis": axis.tolist(),
                "xdir": (xdir / np.linalg.norm(xdir)).tolist(), "depth": depth * scale}

    if len(planes) == 6 and not cylinders:
        dirs: list[np.ndarray] = []
        for _, n in planes:
            if not any(abs(abs(n @ d) - 1) < tol for d in dirs):
                dirs.append(n)
        if len(dirs) != 3 or any(abs(dirs[i] @ dirs[j]) > tol for i in range(3) for j in range(i + 1, 3)):
            return None
        pts = []
        v = TopExp_Explorer(solid, TopAbs_VERTEX)
        while v.More():
            p = BRep_Tool.Pnt_s(TopoDS.Vertex(v.Current()))
            pts.append((p.X(), p.Y(), p.Z()))
            v.Next()
        pts = np.asarray(pts)
        lo = [float((pts @ d).min()) for d in dirs]
        hi = [float((pts @ d).max()) for d in dirs]
        size = [h - l for l, h in zip(lo, hi)]
        if abs(volume - size[0] * size[1] * size[2]) > 1e-3 * volume:
            return None
        order = sorted(range(3), key=lambda i: -size[i])      # longest is the extrusion; the next is the profile's X
        a, x, y = order
        axis, xdir = dirs[a], dirs[x]
        centre = sum(dirs[i] * (lo[i] + hi[i]) / 2 for i in range(3))
        start = centre - axis * size[a] / 2
        return {"profile": ("rect", size[x] * scale, size[y] * scale), "start": (start * scale).tolist(),
                "axis": axis.tolist(), "xdir": xdir.tolist(), "depth": size[a] * scale}
    return None


def _extrusion(model, prism: dict, lo: np.ndarray):
    """An IfcExtrudedAreaSolid for a `_prism`, placed relative to the part's placement at `lo` (metres)."""
    centre = model.createIfcAxis2Placement2D(model.createIfcCartesianPoint((0.0, 0.0)), None)
    kind = prism["profile"]
    profile = (model.createIfcCircleProfileDef("AREA", None, centre, float(kind[1])) if kind[0] == "circle" else
               model.createIfcRectangleProfileDef("AREA", None, centre, float(kind[1]), float(kind[2])))
    position = model.createIfcAxis2Placement3D(
        model.createIfcCartesianPoint(tuple(float(c) for c in np.asarray(prism["start"]) - lo)),
        model.createIfcDirection(tuple(float(c) for c in prism["axis"])),
        model.createIfcDirection(tuple(float(c) for c in prism["xdir"])))
    return model.createIfcExtrudedAreaSolid(profile, position, model.createIfcDirection((0.0, 0.0, 1.0)),
                                            float(prism["depth"]))


# ------------------------------------------------------------------------------------------------- classes

def classify(found: list[Part], model, batch: int = 200) -> None:
    """Pick an IFC class (and type) per part from its name and group, with the model; parts it leaves out keep the
    proxy. Changes the parts in place."""
    prompt = (Path(__file__).parent / "domain_packs" / "step_classes.md").read_text()
    schema = {"type": "object", "properties": {"parts": {"type": "array", "items": {
        "type": "object", "properties": {"i": {"type": "integer"}, "class": {"type": "string", "enum": list(CLASSES)},
                                        "type": {"type": "string"}},
        "required": ["i", "class", "type"], "additionalProperties": False}}},
        "required": ["parts"], "additionalProperties": False}
    for start in range(0, len(found), batch):
        chunk = found[start:start + batch]
        text = "\n".join(f"{start + k}: {p.name} (in {p.group or 'the top level'})" for k, p in enumerate(chunk))
        reply = model.complete_json(prompt, text, [], schema=schema)
        for item in reply.get("parts", []):
            i = item.get("i")
            if isinstance(i, int) and start <= i < start + len(chunk) and item.get("class") in CLASSES:
                found[i].ifc_class = item["class"]
                found[i].kind = str(item.get("type") or "")[:60]


# ------------------------------------------------------------------------------------------------- writing IFC

def _style(model, cache: dict, colour, alpha: float):
    key = (tuple(round(c, 3) for c in colour), round(alpha, 3))
    if key not in cache:
        rgb = model.createIfcColourRgb(None, *[float(c) for c in colour])
        rendering = model.createIfcSurfaceStyleRendering(rgb, round(1 - alpha, 3), None, None, None, None, None, None,
                                                         "NOTDEFINED")
        cache[key] = model.createIfcSurfaceStyle(None, "BOTH", [rendering])
    return cache[key]


def _element(model, part: Part, placement, shape):
    """The IFC element for a part: its class with a valid predefined type, else USERDEFINED and the type as text."""
    cls = part.ifc_class if part.ifc_class in CLASSES else "IfcBuildingElementProxy"
    attrs = {"GlobalId": part.gid, "Name": part.name, "ObjectPlacement": placement, "Representation": shape}
    entity = model.create_entity(cls, **attrs)
    kind = part.kind.strip()
    if hasattr(entity, "PredefinedType") and kind:
        enum = kind.upper().replace(" ", "")
        try:
            entity.PredefinedType = enum
        except Exception:
            entity.PredefinedType = "USERDEFINED"
            entity.ObjectType = kind
    elif kind:
        entity.ObjectType = kind
    elif cls == "IfcBuildingElementProxy" and part.group:
        entity.ObjectType = part.group.rsplit("/", 1)[-1]
    return entity


def write_ifc(found: list[Part], scale: float, out: Path, title: str, source: str, digest: str) -> dict:
    """Write the parts as IFC4 (metres) at `out`. Returns the manifest: per GlobalId, its STEP label path and origin."""
    model = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name=title)
    ifcopenshell.api.run("unit.assign_unit", model, length={"is_metric": True, "raw": "METRES"})
    context = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", model, context_type="Model", context_identifier="Body",
                                target_view="MODEL_VIEW", parent=context)
    site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name=f"{title} site")
    building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding", name=title)
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name=title)
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[site])
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=site, products=[building])
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=building, products=[storey])
    origin = model.createIfcAxis2Placement3D(model.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None)
    storey.ObjectPlacement = model.createIfcLocalPlacement(None, origin)

    styles: dict = {}
    elements, groups, manifest, triangles = [], {}, {}, 0
    for k, part in enumerate(found):
        prism = _prism(part.shape, scale)
        verts, faces = mesh(part.shape, scale)
        part.shape = None                 # the mesh (or the prism) is all that is needed from here; free the B-rep
        if not len(faces):
            continue
        triangles += len(faces)
        if triangles > MAX_TRIANGLES:
            raise StepError(f"{source} needs more than {MAX_TRIANGLES:,} triangles: too detailed for the demo.")
        lo = verts.min(axis=0)
        part.origin = [float(x) for x in lo]
        part.gid = ifcopenshell.guid.compress(uuid.uuid5(NAMESPACE, f"{digest}:{'/'.join(part.path)}").hex)
        if prism:
            item, kind = _extrusion(model, prism, lo), "SweptSolid"
        else:
            points = model.createIfcCartesianPointList3D([tuple(map(float, v)) for v in verts - lo])
            item = model.createIfcTriangulatedFaceSet(points, None, True,
                                                      [tuple(int(i) + 1 for i in f) for f in faces], None)
            kind = "Tessellation"
        if part.colour:
            model.createIfcStyledItem(item, [_style(model, styles, part.colour, part.alpha)], None)
        representation = model.createIfcShapeRepresentation(body, "Body", kind, [item])
        shape = model.createIfcProductDefinitionShape(None, None, [representation])
        placement = model.createIfcLocalPlacement(storey.ObjectPlacement, model.createIfcAxis2Placement3D(
            model.createIfcCartesianPoint(tuple(part.origin)), None, None))
        element = _element(model, part, placement, shape)
        pset = ifcopenshell.api.run("pset.add_pset", model, product=element, name=PSET)
        ifcopenshell.api.run("pset.edit_pset", model, pset=pset,
                             properties={"Group": part.group, "Label": part.path[-1], "Source": source})
        elements.append(element)
        groups.setdefault(part.group, []).append(element)
        manifest[part.gid] = {"name": part.name, "group": part.group, "path": part.path, "origin": part.origin,
                              "prism": prism, "colour": list(part.colour) if part.colour else None,
                              "alpha": part.alpha}
    if not elements:
        raise StepError(f"{source} has no solid geometry.")
    model.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), None, None, None, elements, storey)
    for path, members in groups.items():
        if path:
            group = model.createIfcGroup(ifcopenshell.guid.new(), None, path, None, "STEP assembly")
            model.createIfcRelAssignsToGroup(ifcopenshell.guid.new(), None, None, None, members, None, group)
    model.write(str(out))
    return manifest


def convert(path: Path, out_dir: Path, classify_with=None, cache: Path | None = None,
            on_event: Callable[[dict], None] = lambda e: None) -> tuple[Path, Path]:
    """STEP → IFC: returns (ifc path, manifest path). With `cache`, a file converted before (same bytes) is reused.
    `classify_with` is a chat model for the part classes, or None for proxies."""
    t0 = time.perf_counter()
    path = Path(path)
    digest = file_hash(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    ifc, manifest_path = out_dir / f"{path.stem}.ifc", out_dir / f"{path.stem}.step.json"
    if cache is not None:
        hit_ifc, hit_manifest = cache / f"{digest}.ifc", cache / f"{digest}.json"
        if hit_ifc.exists() and hit_manifest.exists():
            ifc.write_bytes(hit_ifc.read_bytes())
            manifest_path.write_text(hit_manifest.read_text().replace('"__SOURCE__"', json.dumps(str(path))))
            on_event({"type": "converted", "file": path.name, "cached": True})
            return ifc, manifest_path
    on_event({"type": "reading", "file": path.name})
    found, scale, root = parts(path)
    classified = False
    if classify_with is not None:
        on_event({"type": "classifying", "file": path.name, "parts": len(found)})
        try:
            classify(found, classify_with)
            classified = True
        except Exception as e:  # proxies still convert and check; the names say what each part is
            on_event({"type": "classify_failed", "detail": f"{type(e).__name__}: {e}"})
    on_event({"type": "meshing", "file": path.name, "parts": len(found)})
    manifest = write_ifc(found, scale, ifc, root or path.stem, path.name, digest)
    doc = {"source": str(path), "digest": digest, "classified": classified, "parts": manifest,
           "seconds": round(time.perf_counter() - t0, 2)}
    manifest_path.write_text(json.dumps(doc))
    if cache is not None and classified:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / f"{digest}.ifc").write_bytes(ifc.read_bytes())
        (cache / f"{digest}.json").write_text(json.dumps({**doc, "source": "__SOURCE__"}))
    on_event({"type": "converted", "file": path.name, "parts": len(manifest), "seconds": doc["seconds"]})
    return ifc, manifest_path


# ------------------------------------------------------------------------------------------------- export

def _shape(spec: dict, scale: float):
    """A B-rep in STEP units from a spec in metres: an exact cylinder or box for a "prism", a "cut" (a base spec less
    its "tools": a host's openings), else a sewn faceted solid from a "mesh" (verts, faces)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeSolid, \
        BRepBuilderAPI_Sewing
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    k = 1 / scale
    if spec["kind"] == "cut":   # a host with openings cut for services: its body less each void
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        shape = _shape(spec["base"], scale)
        for tool in spec["tools"]:
            cut = BRepAlgoAPI_Cut(shape, _shape(tool, scale))
            if cut.IsDone() and not cut.Shape().IsNull():
                shape = cut.Shape()   # a boolean OCP cannot do leaves the host whole: the IFC still has the opening
        return shape
    if spec["kind"] == "prism":
        axis, xdir = np.asarray(spec["axis"], float), np.asarray(spec["xdir"], float)
        start = np.asarray(spec["start"], float) * k
        profile = spec["profile"]
        if profile[0] == "circle":
            frame = gp_Ax2(gp_Pnt(*start), gp_Dir(*axis), gp_Dir(*xdir))
            return BRepPrimAPI_MakeCylinder(frame, profile[1] * k, spec["depth"] * k).Shape()
        ydir = np.cross(axis, xdir)
        corner = start - xdir * profile[1] * k / 2 - ydir * profile[2] * k / 2
        frame = gp_Ax2(gp_Pnt(*corner), gp_Dir(*axis), gp_Dir(*xdir))
        return BRepPrimAPI_MakeBox(frame, profile[1] * k, profile[2] * k, spec["depth"] * k).Shape()
    verts = np.asarray(spec["verts"], float) * k
    sewing = BRepBuilderAPI_Sewing(1e-3)
    for a, b, c in spec["faces"]:
        poly = BRepBuilderAPI_MakePolygon(gp_Pnt(*verts[a]), gp_Pnt(*verts[b]), gp_Pnt(*verts[c]), True)
        face = BRepBuilderAPI_MakeFace(poly.Wire(), True)
        if face.IsDone():
            sewing.Add(face.Face())
    sewing.Perform()
    sewn = sewing.SewedShape()
    shells = TopExp_Explorer(sewn, TopAbs_SHELL)
    if shells.More():
        solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell(shells.Current()))
        if solid.IsDone():
            return solid.Solid()
    return sewn


def _placed(shape, loc):
    """`shape` with `loc` baked into its geometry. A located shape (`Moved`) loses its name and colour on the way out:
    the STEP writer cannot match it to its label."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Identity
    trsf = loc.Transformation()
    if trsf.Form() == gp_Identity:
        return shape
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def export(step_path: Path, manifest: dict, out: Path, moves: dict[str, list[float]] | None = None,
           replace: dict[str, dict] | None = None, add: list[dict] | None = None) -> Path:
    """Write the STEP again with ORCA's edits, keeping every name and colour. `manifest` is the converter's
    `parts`; all geometry is in metres, world axes.
    - `moves` {gid: delta}: the part's component location becomes parent⁻¹ · T · parent · old, so nested assemblies
      keep their own placements;
    - `replace` {gid: spec}: the part's shape changed (an offset's first piece, a trimmed member, a wall cut for a
      service); its prototype gets the new shape, brought into the component's frame;
    - `add` [{name, label (the original part's component entry), spec, colour, alpha}]: new parts (an offset's middle,
      risers and bends, a provision for void), placed in the original part's group."""
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Quantity import Quantity_Color, Quantity_ColorRGBA, Quantity_TOC_RGB
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_Label, TDF_Tool
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_Location

    doc, shapes, colours, scale = _read(step_path)
    data = doc.Main().Data()

    def label(entry: str):
        found = TDF_Label()
        TDF_Tool.Label_s(data, entry, found, False)
        return found

    def parent_of(path: list[str]) -> TopLoc_Location:
        loc = TopLoc_Location()
        for entry in path[1:-1]:                       # the assemblies above the part's own component
            loc = loc.Multiplied(shapes.GetLocation_s(label(entry)))
        return loc

    for gid, delta in (moves or {}).items():
        info = manifest.get(gid)
        if not info or gid in (replace or {}) or not any(abs(d) > 1e-9 for d in delta):
            continue
        parent, comp = parent_of(info["path"]), label(info["path"][-1])
        move = gp_Trsf()
        move.SetTranslation(gp_Vec(*(d / scale for d in delta)))
        XCAFDoc_Location.Set_s(comp, parent.Inverted().Multiplied(TopLoc_Location(move)).Multiplied(parent).Multiplied(
            shapes.GetLocation_s(comp)))

    for gid, spec in (replace or {}).items():
        info = manifest.get(gid)
        if not info:
            continue
        comp = label(info["path"][-1])
        proto = TDF_Label()
        shapes.GetReferredShape_s(comp, proto)
        whole = parent_of(info["path"]).Multiplied(shapes.GetLocation_s(comp))
        shapes.SetShape(proto, _placed(_shape(spec, scale), whole.Inverted()))

    by_label = {info["path"][-1]: info for info in manifest.values()}
    for new in add or []:
        info = by_label.get(new.get("label", ""))
        if not info:
            continue
        path = info["path"]
        group = label(path[0])
        if len(path) >= 3:
            group = TDF_Label()
            shapes.GetReferredShape_s(label(path[-2]), group)
        local = _placed(_shape(new["spec"], scale), parent_of(path).Inverted())
        part = shapes.AddShape(local, False)
        TDataStd_Name.Set_s(part, TCollection_ExtendedString(new["name"]))
        rgb, alpha = new.get("colour") or info.get("colour"), new.get("alpha", info.get("alpha", 1.0))
        if rgb:
            colours.SetColor(part, Quantity_ColorRGBA(*rgb, alpha) if alpha < 1 else
                             Quantity_Color(*rgb, Quantity_TOC_RGB), XCAFDoc_ColorSurf)
        shapes.AddComponent(group, part, TopLoc_Location())
    shapes.UpdateAssemblies()

    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    writer.SetColorMode(True)
    if not writer.Transfer(doc, STEPControl_AsIs) or writer.Write(str(out)) != IFSelect_RetDone:
        raise StepError(f"Could not write {out.name}.")
    return out
