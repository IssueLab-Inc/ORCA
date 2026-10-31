"""An element's properties as the page's Properties panel shows them (GET /api/scenes/{id}/elements/{gid}/properties),
and the one reader the filters' index shares (facets.py), so the panel and the filters never disagree.

Everything the model says about one object, read with IfcOpenShell from the scene's current state (so a kept fix's new
pieces have theirs): every direct attribute; its type and the type's own attributes; every property set and quantity
set on it or on its type (a value its type gives is marked `from_type`; the element's own wins); every kind of
property (single, enumerated, list, bounded, table, reference, complex); the unit of each value; its materials
(layers with thicknesses, profiles, constituents, and each material's own sets); its classifications; the systems,
zones and groups it belongs to; its documents; where it sits (its storey, its direct container and the path up to the
project); and its size from the scene's cached box. Any object with a GlobalId can be read, so a breadcrumb opens a
storey's or a building's own properties.

Lengths, areas, volumes and masses come in SI (m, m², m³, kg) whatever the file's units; other measures keep their
own unit beside the value. Values are made safe for JSON; nothing is computed or guessed. One gate (`shown`) keeps
the demo models' scripting note out of everything, at every depth.
"""
from __future__ import annotations

import math

import ifcopenshell
import ifcopenshell.ifcopenshell_wrapper as wrapper
import ifcopenshell.util.classification
import ifcopenshell.util.element
import ifcopenshell.util.unit

from . import demos
from .scene import IfcScene

# The demo models carry their own notes in a property set named for the tool that generated them. The page shows the
# set as "Model data", and leaves out the scripting note on the clash host (it says the answer key was planted).
RENAMED = demos.PSET_NAMES      # the demo models' own set, by a plain name
HIDDEN = demos.HIDDEN_PROPERTIES

# Attributes that are bookkeeping or geometry, not something the model says about the object. GlobalId is shown on its
# own; a type's sets come through `sets`.
SKIPPED = {"id", "type", "GlobalId", "OwnerHistory", "ObjectPlacement", "Representation", "RepresentationMaps",
           "RepresentationContexts", "UnitsInContext", "HasPropertySets"}

# Measures shown in SI: their unit, and the power of the length unit when the file names no unit of their own.
SI = {"LENGTHUNIT": ("m", 1), "AREAUNIT": ("m²", 2), "VOLUMEUNIT": ("m³", 3), "MASSUNIT": ("kg", 0)}

# Each kind of quantity: the attribute holding its value and the kind of unit it is in.
QUANTITY = {"IfcQuantityLength": ("LengthValue", "LENGTHUNIT"), "IfcQuantityArea": ("AreaValue", "AREAUNIT"),
            "IfcQuantityVolume": ("VolumeValue", "VOLUMEUNIT"), "IfcQuantityWeight": ("WeightValue", "MASSUNIT"),
            "IfcQuantityCount": ("CountValue", None), "IfcQuantityTime": ("TimeValue", "TIMEUNIT"),
            "IfcQuantityNumber": ("NumberValue", None)}

# Symbols IfcOpenShell's own table lacks (it answers "?"), by SI unit name.
SYMBOLS = {"WATT": "W", "KELVIN": "K", "DEGREE_CELSIUS": "°C", "JOULE": "J", "HERTZ": "Hz", "VOLT": "V",
           "AMPERE": "A", "OHM": "Ω", "LUMEN": "lm", "LUX": "lx", "CANDELA": "cd", "RADIAN": "rad",
           "STERADIAN": "sr", "BECQUEREL": "Bq", "COULOMB": "C", "FARAD": "F", "HENRY": "H", "TESLA": "T",
           "WEBER": "Wb", "SIEMENS": "S", "MOLE": "mol", "GRAY": "Gy", "SIEVERT": "Sv", "SQUARE_METRE": "m²",
           "CUBIC_METRE": "m³"}

PATH_MAX = 32   # a guard against a malformed file whose decomposition loops


def shown(name) -> bool:
    """Whether a property, by name, may be shown anywhere (the one gate for the hidden demo note)."""
    return name not in HIDDEN


def value(v):
    """A value as JSON: numbers rounded to a micro-unit (none when not finite), entities by name, wrapped values
    unwrapped, lists kept."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return round(v, 6) if math.isfinite(v) else None
    if isinstance(v, (list, tuple)):
        return [value(x) for x in v]
    if isinstance(v, ifcopenshell.entity_instance):
        if v.id() == 0 and hasattr(v, "wrappedValue"):
            return value(v.wrappedValue)
        return named(v)
    return str(v)


def named(e) -> str:
    """What to call an entity: its name, else its long name, else its class."""
    for attr in ("Name", "LongName"):
        n = getattr(e, attr, None) if e.is_entity() else None
        if isinstance(n, str) and n:
            return n
    return e.is_a()


def ref(e, file: int) -> dict:
    """An object another one points at (a breadcrumb, a container), enough to fetch its own properties."""
    return {"global_id": getattr(e, "GlobalId", None), "ifc_class": e.is_a(), "name": named(e), "file": file}


class Reader:
    """Reads objects of one file. Keeps what many objects share (units, each class's attribute types, types and
    materials already read), so reading every element for the filters' index stays cheap."""

    def __init__(self, f: ifcopenshell.file, file: int, length_scale: float):
        self.f, self.file, self.length = f, file, length_scale
        self.schema = wrapper.schema_by_name(f.schema_identifier if hasattr(f, "schema_identifier") else f.schema)
        self._units: dict[str, object] = {}
        self._attr_types: dict[str, dict[str, str | None]] = {}
        self._types: dict[int, dict] = {}
        self._materials: dict[int, list] = {}

    # ------------------------------------------------------------------ units

    def project_unit(self, unit_type: str):
        if unit_type not in self._units:
            try:
                self._units[unit_type] = ifcopenshell.util.unit.get_project_unit(self.f, unit_type)
            except Exception:
                self._units[unit_type] = None
        return self._units[unit_type]

    @staticmethod
    def symbol(unit) -> str | None:
        if unit is None:
            return None
        try:
            s = ifcopenshell.util.unit.get_unit_symbol(unit)
        except Exception:
            s = None
        if s and "?" not in s:
            return s.replace("m2", "m²").replace("m3", "m³") if s in ("m2", "m3") or s.endswith(("m2", "m3")) else s
        if unit.is_a("IfcSIUnit"):
            prefix = ifcopenshell.util.unit.prefix_symbols.get(unit.Prefix or "", "")
            base = SYMBOLS.get(unit.Name)
            return prefix + base if base else None
        n = getattr(unit, "Name", None)
        return n.lower() if isinstance(n, str) and n else None

    def measure(self, measure_class: str | None, raw, unit=None) -> tuple[object, str | None]:
        """A measured value and its unit: lengths, areas, volumes and masses in SI; others as authored, with the
        unit the value names or the project's unit for its kind of measure."""
        if measure_class is None or isinstance(raw, bool):
            return value(raw), None
        try:
            kind = ifcopenshell.util.unit.get_measure_unit_type(measure_class)
        except Exception:
            return value(raw), None
        u = unit if unit is not None else self.project_unit(kind)
        if kind in SI and isinstance(raw, (int, float)):
            symbol, power = SI[kind]
            if u is not None:
                try:
                    scale = ifcopenshell.util.unit.get_unit_scale(u)
                except Exception:
                    scale = 1.0
                if kind == "MASSUNIT":
                    scale /= 1000.0      # IfcOpenShell scales mass to grams
            else:
                scale = self.length ** power if power else 1.0
            return value(float(raw) * scale), symbol
        return value(raw), self.symbol(u)

    def wrapped(self, v, unit=None) -> tuple[object, str | None]:
        """A wrapped value (an IfcLengthMeasure(3.6), an IfcLabel('x')) and its unit."""
        if isinstance(v, ifcopenshell.entity_instance) and v.id() == 0 and hasattr(v, "wrappedValue"):
            return self.measure(v.is_a(), v.wrappedValue, unit)
        return value(v), None

    # ------------------------------------------------------------------ attributes

    def attribute_types(self, cls: str) -> dict[str, str | None]:
        """Each attribute of a class and the defined type it is declared as (IfcLengthMeasure, IfcLabel…), or None
        (an entity, a select, an enumeration, a list)."""
        if cls not in self._attr_types:
            out: dict[str, str | None] = {}
            try:
                for a in self.schema.declaration_by_name(cls).all_attributes():
                    t = a.type_of_attribute()
                    d = t.declared_type() if isinstance(t, wrapper.named_type) else None
                    out[a.name()] = d.name() if isinstance(d, wrapper.type_declaration) else None
            except Exception:
                pass
            self._attr_types[cls] = out
        return self._attr_types[cls]

    def attributes(self, e) -> list[dict]:
        """Every direct attribute that says something about the object, entity references by name."""
        types = self.attribute_types(e.is_a())
        out = []
        for name, v in e.get_info(recursive=False).items():
            if name in SKIPPED or v is None or v == "" or v == () or not shown(name):
                continue
            if isinstance(v, ifcopenshell.entity_instance) and v.id() == 0:
                val, unit = self.wrapped(v)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                val, unit = self.measure(types.get(name), v)
            else:
                val, unit = value(v), None
            row = {"name": name, "value": val}
            if unit:
                row["unit"] = unit
            out.append(row)
        return out

    # ------------------------------------------------------------------ property sets

    def prop(self, p) -> dict | None:
        """One property of any kind, as a row; a complex property nests its own rows."""
        name = getattr(p, "Name", None) or p.is_a()
        if not shown(name):
            return None
        row: dict = {"name": name}
        if p.is_a("IfcPropertySingleValue"):
            row["value"], unit = self.wrapped(p.NominalValue, getattr(p, "Unit", None))
        elif p.is_a("IfcPropertyEnumeratedValue"):
            reference = getattr(p, "EnumerationReference", None)
            u = getattr(reference, "Unit", None) if reference is not None else None
            values = [self.wrapped(x, u) for x in (p.EnumerationValues or [])]
            row["kind"], row["value"] = "enumerated", [v for v, _ in values]
            unit = next((s for _, s in values if s), None)
        elif p.is_a("IfcPropertyListValue"):
            values = [self.wrapped(x, getattr(p, "Unit", None)) for x in (p.ListValues or [])]
            row["kind"], row["value"] = "list", [v for v, _ in values]
            unit = next((s for _, s in values if s), None)
        elif p.is_a("IfcPropertyBoundedValue"):
            u = getattr(p, "Unit", None)
            bounds, unit = {}, None
            for key, attr in (("lower", "LowerBoundValue"), ("upper", "UpperBoundValue"), ("set_point", "SetPointValue")):
                v = getattr(p, attr, None)
                if v is not None:
                    bounds[key], s = self.wrapped(v, u)
                    unit = unit or s
            row["kind"], row["value"] = "bounded", bounds
        elif p.is_a("IfcPropertyTableValue"):
            defining = [self.wrapped(x, getattr(p, "DefiningUnit", None)) for x in (p.DefiningValues or [])]
            defined = [self.wrapped(x, getattr(p, "DefinedUnit", None)) for x in (p.DefinedValues or [])]
            row["kind"], row["value"], unit = "table", None, None
            row["table"] = {"defining": [v for v, _ in defining], "defined": [v for v, _ in defined],
                            "defining_unit": next((s for _, s in defining if s), None),
                            "defined_unit": next((s for _, s in defined if s), None),
                            "expression": getattr(p, "Expression", None)}
        elif p.is_a("IfcPropertyReferenceValue"):
            target = getattr(p, "PropertyReference", None)
            row["kind"], row["value"], unit = "reference", named(target) if target is not None else None, None
            if target is not None:
                row["of"] = target.is_a()
        elif p.is_a("IfcComplexProperty"):
            rows = [r for r in (self.prop(c) for c in (p.HasProperties or [])) if r is not None]
            row["kind"], row["value"], row["rows"], unit = "complex", getattr(p, "UsageName", None), rows, None
        else:
            row["kind"], row["value"], unit = p.is_a(), None, None
        if unit:
            row["unit"] = unit
        return row

    def quantity(self, q) -> dict | None:
        name = getattr(q, "Name", None) or q.is_a()
        if not shown(name):
            return None
        if q.is_a("IfcPhysicalComplexQuantity"):
            rows = [r for r in (self.quantity(c) for c in (q.HasQuantities or [])) if r is not None]
            return {"name": name, "kind": "complex", "value": getattr(q, "Usage", None), "rows": rows}
        kind = next((k for k in QUANTITY if q.is_a(k)), None)
        if kind is None:
            return {"name": name, "kind": q.is_a(), "value": None}
        attr, unit_type = QUANTITY[kind]
        raw = getattr(q, attr, None)
        row: dict = {"name": name}
        own = getattr(q, "Unit", None)
        if unit_type in SI and raw is not None:
            symbol, power = SI[unit_type]
            u = own if own is not None else self.project_unit(unit_type)
            if u is not None:
                scale = ifcopenshell.util.unit.get_unit_scale(u) / (1000.0 if unit_type == "MASSUNIT" else 1.0)
            else:
                scale = self.length ** power if power else 1.0
            row["value"], row["unit"] = value(float(raw) * scale), symbol
        else:
            row["value"] = value(raw)
            s = self.symbol(own if own is not None else (self.project_unit(unit_type) if unit_type else None))
            if s:
                row["unit"] = s
        return row

    def property_set(self, d) -> dict | None:
        """One property definition as a set of rows: a property set, a quantity set, or a predefined set (door
        lining, window panel…) read from its attributes."""
        if d.is_a("IfcElementQuantity"):
            rows = [r for r in (self.quantity(q) for q in (d.Quantities or [])) if r is not None]
            kind = "qto"
        elif d.is_a("IfcPropertySet"):
            rows = [r for r in (self.prop(p) for p in (d.HasProperties or [])) if r is not None]
            kind = "pset"
        else:
            rows = [r for r in self.attributes(d) if r["name"] not in ("Name", "Description")]
            kind = "pset"
        name = getattr(d, "Name", None) or d.is_a()
        return {"name": RENAMED.get(name, name), "kind": kind, "props": rows}

    @staticmethod
    def definitions(e) -> list:
        """The property definitions on an object (IsDefinedBy) or on a type (HasPropertySets). IFC4 may group several
        under one relationship as a set."""
        out = []
        for rel in getattr(e, "IsDefinedBy", None) or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            d = rel.RelatingPropertyDefinition
            out.extend(d if isinstance(d, (tuple, list)) else [d])
        out.extend(getattr(e, "HasPropertySets", None) or [])
        return [d for d in out if d is not None]

    def sets(self, e, kind) -> list[dict]:
        """The object's sets, then what its type adds: a set only the type has, and in a set both have, the
        properties only the type gives, each marked `from_type`."""
        own: dict[str, dict] = {}
        for d in self.definitions(e):
            s = self.property_set(d)
            if s is None:
                continue
            if s["name"] in own:      # two sets of one name: one list, the first value of a name wins
                names = {r["name"] for r in own[s["name"]]["props"]}
                own[s["name"]]["props"].extend(r for r in s["props"] if r["name"] not in names)
            else:
                own[s["name"]] = s
        if kind is not None:
            for s in self.type_sets(kind):
                mine = own.get(s["name"])
                if mine is None:
                    own[s["name"]] = {**s, "from_type": True, "props": [{**r, "from_type": True} for r in s["props"]]}
                else:
                    names = {r["name"] for r in mine["props"]}
                    mine["props"].extend({**r, "from_type": True} for r in s["props"] if r["name"] not in names)
        return [s for s in own.values() if s["props"]]

    def type_sets(self, kind) -> list[dict]:
        return self.type_of(kind)["_sets"]

    def type_of(self, kind) -> dict:
        if kind.id() not in self._types:
            self._types[kind.id()] = {"global_id": getattr(kind, "GlobalId", None), "ifc_class": kind.is_a(),
                                      "name": getattr(kind, "Name", None), "attributes": self.attributes(kind),
                                      "_sets": self.sets(kind, None)}
        return self._types[kind.id()]

    # ------------------------------------------------------------------ materials

    def material_sets(self, m) -> list[dict]:
        """A material's own property sets (IFC4 IfcMaterialProperties)."""
        out = []
        for p in getattr(m, "HasProperties", None) or []:
            rows = [r for r in (self.prop(x) for x in (getattr(p, "Properties", None) or [])) if r is not None]
            if rows:
                name = getattr(p, "Name", None) or p.is_a()
                out.append({"name": RENAMED.get(name, name), "kind": "pset", "material": named(m), "props": rows})
        return out

    def materials(self, e) -> list[dict]:
        """What the object is made of: a material, layers with thicknesses, profiles, constituents with their
        fractions, or a list; each material's own sets with it. `from_type` when only the type says."""
        try:
            m = ifcopenshell.util.element.get_material(e, should_skip_usage=True)
            own = ifcopenshell.util.element.get_material(e, should_skip_usage=True, should_inherit=False)
        except Exception:
            return []
        if m is None:
            return []
        if m.id() not in self._materials:
            self._materials[m.id()] = self._material(m)
        return [{**x, "from_type": own is None} for x in self._materials[m.id()]]

    def _material(self, m) -> list[dict]:
        mats: list = []

        def item(material, **more):
            if material is not None:
                mats.append(material)
            return {"material": named(material) if material is not None else None,
                    **{k: v for k, v in more.items() if v is not None}}

        if m.is_a("IfcMaterial"):
            entry = {"usage": "single", "name": named(m), "items": [item(m, category=getattr(m, "Category", None))]}
        elif m.is_a("IfcMaterialLayerSet"):
            items = [item(l.Material, name=getattr(l, "Name", None),
                          thickness_m=value(float(l.LayerThickness) * self.length) if l.LayerThickness is not None else None)
                     for l in (m.MaterialLayers or [])]
            total = sum(i.get("thickness_m") or 0 for i in items)
            entry = {"usage": "layers", "name": getattr(m, "LayerSetName", None) or "Layers", "items": items,
                     "total_m": value(total)}
        elif m.is_a("IfcMaterialProfileSet"):
            entry = {"usage": "profiles", "name": getattr(m, "Name", None) or "Profiles", "items": [
                item(p.Material, name=getattr(p, "Name", None),
                     profile=named(p.Profile) if getattr(p, "Profile", None) is not None else None)
                for p in (m.MaterialProfiles or [])]}
        elif m.is_a("IfcMaterialConstituentSet"):
            entry = {"usage": "constituents", "name": getattr(m, "Name", None) or "Constituents", "items": [
                item(c.Material, name=getattr(c, "Name", None), fraction=value(getattr(c, "Fraction", None)),
                     category=getattr(c, "Category", None))
                for c in (m.MaterialConstituents or [])]}
        elif m.is_a("IfcMaterialList"):
            entry = {"usage": "list", "name": "Materials", "items": [item(x) for x in (m.Materials or [])]}
        else:
            entry = {"usage": m.is_a(), "name": named(m), "items": []}
        seen, sets = set(), []
        for x in mats:
            if x.id() not in seen:
                seen.add(x.id())
                sets.extend(self.material_sets(x))
        entry["sets"] = sets
        return [entry]

    # ------------------------------------------------------------------ classification, groups, documents, place

    @staticmethod
    def classifications(e) -> list[dict]:
        out = []
        try:
            refs = ifcopenshell.util.classification.get_references(e)
        except Exception:
            refs = set()
        for r in sorted(refs, key=lambda r: r.id()):
            try:
                system = ifcopenshell.util.classification.get_classification(r)
            except Exception:
                system = None
            out.append({"system": getattr(system, "Name", None),
                        "identification": getattr(r, "Identification", None) or getattr(r, "ItemReference", None),
                        "name": getattr(r, "Name", None), "location": getattr(r, "Location", None)})
        return out

    @staticmethod
    def groups(e) -> list[dict]:
        try:
            gs = ifcopenshell.util.element.get_groups(e)
        except Exception:
            gs = []
        return sorted(({"global_id": getattr(g, "GlobalId", None), "ifc_class": g.is_a(), "name": named(g)} for g in gs),
                      key=lambda g: (g["ifc_class"], g["name"]))

    @staticmethod
    def documents(e) -> list[dict]:
        out = []
        sources = [e]
        kind = ifcopenshell.util.element.get_type(e) if e.is_a("IfcObject") else None
        if kind is not None:
            sources.append(kind)
        for src in sources:
            for rel in getattr(src, "HasAssociations", None) or []:
                if not rel.is_a("IfcRelAssociatesDocument"):
                    continue
                d = rel.RelatingDocument
                info = getattr(d, "ReferencedDocument", None) or getattr(d, "ReferenceToDocument", None)
                if isinstance(info, (tuple, list)):
                    info = info[0] if info else None
                out.append({"identification": getattr(d, "Identification", None) or getattr(d, "ItemReference", None)
                            or getattr(d, "DocumentId", None) or getattr(info, "Identification", None),
                            "name": getattr(d, "Name", None) or getattr(info, "Name", None),
                            "location": getattr(d, "Location", None) or getattr(info, "Location", None)})
        return out

    @staticmethod
    def parent(x):
        """What an object sits in: its aggregate, nest, or direct spatial container (never through an opening)."""
        return (ifcopenshell.util.element.get_aggregate(x) or ifcopenshell.util.element.get_nest(x)
                or ifcopenshell.util.element.get_container(x, should_get_direct=True))

    def path(self, e) -> list:
        """The chain from the project down to what the object sits in."""
        out, x = [], self.parent(e)
        while x is not None and len(out) < PATH_MAX:
            out.insert(0, x)
            x = self.parent(x)
        return out

    # ------------------------------------------------------------------ the object

    def read(self, e, source: str, size_m=None) -> dict:
        kind = ifcopenshell.util.element.get_type(e) if e.is_a("IfcObject") else None
        path = self.path(e)
        storey = next((x for x in reversed(path) if x.is_a("IfcBuildingStorey")), None)
        container = ifcopenshell.util.element.get_container(e, should_get_direct=True) if e.is_a("IfcProduct") else None
        t = self.type_of(kind) if kind is not None else None
        return {
            "global_id": getattr(e, "GlobalId", None),
            "ifc_class": e.is_a(),
            "name": getattr(e, "Name", None),
            "source": source,
            "file": self.file,
            "size_m": size_m,
            "attributes": self.attributes(e),
            "type": {k: v for k, v in t.items() if not k.startswith("_")} if t is not None else None,
            "storey": ref(storey, self.file) if storey is not None else None,
            "container": ref(container, self.file) if container is not None else None,
            "path": [ref(x, self.file) for x in path],
            "materials": self.materials(e) if e.is_a("IfcObjectDefinition") else [],
            "classifications": self.classifications(e),
            "groups": self.groups(e) if e.is_a("IfcObjectDefinition") else [],
            "documents": self.documents(e),
            "sets": self.sets(e, kind),
        }


def reader(scene: IfcScene, i: int) -> Reader:
    return Reader(scene.models[i], i, scene.unit_scales[i])


def size_of(scene: IfcScene, global_id: str):
    box = scene.bounds().get(global_id)
    return [round(float(hi - lo), 4) for lo, hi in zip(box[0], box[1])] if box is not None else None


def properties(scene: IfcScene, global_id: str, file: int | None = None) -> dict:
    """Everything the model says about one object (an element, or a storey, building or site from a breadcrumb).
    `file` picks the model when federated files repeat a GlobalId. Raises KeyError for one the scene doesn't have."""
    if file is not None and not 0 <= file < len(scene.models):
        raise KeyError(f"No file {file} in this model set")
    files = [file] if file is not None else range(len(scene.models))
    for i in files:
        try:
            e = scene.models[i].by_guid(global_id)
        except RuntimeError:
            continue
        return reader(scene, i).read(e, scene.paths[i].name, size_of(scene, global_id))
    raise KeyError(f"No object with GlobalId {global_id} in {[p.name for p in scene.paths]}")


def leaves(p: dict) -> int:
    """How many values a read object's sets hold (a complex property counts its parts): the completeness check's
    measure."""
    def count(rows):
        return sum(count(r["rows"]) if r.get("kind") == "complex" else 1 for r in rows)
    return sum(count(s["props"]) for s in p["sets"])
