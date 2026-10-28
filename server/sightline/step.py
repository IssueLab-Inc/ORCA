"""STEP models: read a STEP assembly, check it as IFC, and write the fixes back into the STEP.

Machine builders work in STEP. Sightline checks and edits IFC, so a STEP file is converted when it opens:
- every part (a leaf of the assembly tree) becomes one IFC element with a triangulated body, its STEP name and colour
  (alpha included), and a placement at its box's lower corner, so a move is one placement edit;
- the STEP groups (sub-assemblies) become IfcGroups, for organisation only. They are not IfcElementAssembly: detection
  treats an assembly's parts as meant to meet, and a machine's top groups ("Guarding") hold parts that must not clash;
- each element carries the pset `Sightline_STEP` (Group, Label, Source), which ties it back to the STEP label;
- STEP carries no IFC classes, so `classify` (one Muse call per 200 parts, from names and group paths) picks one per
  part; without it every part is an IfcBuildingElementProxy named for its group.

Fixes on these parts are moves (offsets and trims need extruded profiles). `export` writes the STEP again with each
moved part's component translated, keeping names and colours: the designer gets their own file back.

GlobalIds come from the file's hash and the part's label, so the same STEP converts to the same ids every time.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import numpy as np

SUFFIXES = {".step", ".stp"}
MAX_PARTS = int(os.environ.get("SIGHTLINE_STEP_MAX_PARTS", "20000"))
MAX_TRIANGLES = int(os.environ.get("SIGHTLINE_STEP_MAX_TRIANGLES", "5000000"))
PSET = "Sightline_STEP"
NAMESPACE = uuid.UUID("3b8f2d0e-6c1a-4f5e-9a7d-2f1c5b8e4a90")

# The classes a STEP part may become (`classify`), each with its IFC4 predefined types where it has them.
CLASSES = ("IfcMember", "IfcPlate", "IfcColumn", "IfcBeam", "IfcSlab", "IfcMechanicalFastener", "IfcPipeSegment",
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
        raise StepError(f"{path.name} has no shapes Sightline can read.")
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
        verts, faces = mesh(part.shape, scale)
        part.shape = None                 # the mesh is all that is needed from here; free the B-rep
        if not len(faces):
            continue
        triangles += len(faces)
        if triangles > MAX_TRIANGLES:
            raise StepError(f"{source} needs more than {MAX_TRIANGLES:,} triangles: too detailed for the demo.")
        lo = verts.min(axis=0)
        part.origin = [float(x) for x in lo]
        part.gid = ifcopenshell.guid.compress(uuid.uuid5(NAMESPACE, f"{digest}:{'/'.join(part.path)}").hex)
        points = model.createIfcCartesianPointList3D([tuple(map(float, v)) for v in verts - lo])
        faceset = model.createIfcTriangulatedFaceSet(points, None, True,
                                                     [tuple(int(i) + 1 for i in f) for f in faces], None)
        if part.colour:
            model.createIfcStyledItem(faceset, [_style(model, styles, part.colour, part.alpha)], None)
        shape = model.createIfcProductDefinitionShape(None, None, [
            model.createIfcShapeRepresentation(body, "Body", "Tessellation", [faceset])])
        placement = model.createIfcLocalPlacement(storey.ObjectPlacement, model.createIfcAxis2Placement3D(
            model.createIfcCartesianPoint(tuple(part.origin)), None, None))
        element = _element(model, part, placement, shape)
        pset = ifcopenshell.api.run("pset.add_pset", model, product=element, name=PSET)
        ifcopenshell.api.run("pset.edit_pset", model, pset=pset,
                             properties={"Group": part.group, "Label": part.path[-1], "Source": source})
        elements.append(element)
        groups.setdefault(part.group, []).append(element)
        manifest[part.gid] = {"name": part.name, "group": part.group, "path": part.path, "origin": part.origin}
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

def export(step_path: Path, moves: dict[str, list[float]], manifest: dict, out: Path) -> Path:
    """Write the STEP again with each moved part translated by its delta (metres, world axes): the component's
    location becomes parent⁻¹ · T · parent · old, so nested assemblies keep their own placements. Names and colours
    are kept. `manifest` is the converter's (its `parts`)."""
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TDF import TDF_Label, TDF_Tool
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_Location

    doc, shapes, _colours, scale = _read(step_path)
    data = doc.Main().Data()

    def label(entry: str):
        found = TDF_Label()
        TDF_Tool.Label_s(data, entry, found, False)
        return found

    for gid, delta in moves.items():
        info = manifest.get(gid)
        if not info or not any(abs(d) > 1e-9 for d in delta):
            continue
        path = info["path"]
        parent = TopLoc_Location()
        for entry in path[1:-1]:                       # the assemblies above the part's own component
            parent = parent.Multiplied(shapes.GetLocation_s(label(entry)))
        comp = label(path[-1])
        move = gp_Trsf()
        move.SetTranslation(gp_Vec(*(d / scale for d in delta)))
        new = parent.Inverted().Multiplied(TopLoc_Location(move)).Multiplied(parent).Multiplied(
            shapes.GetLocation_s(comp))
        XCAFDoc_Location.Set_s(comp, new)
    shapes.UpdateAssemblies()

    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    writer.SetColorMode(True)
    if not writer.Transfer(doc, STEPControl_AsIs) or writer.Write(str(out)) != IFSelect_RetDone:
        raise StepError(f"Could not write {out.name}.")
    return out
