"""Does the Properties panel show everything the model says? (properties.py, docs/panels.md "Properties")

For every object with a GlobalId in the given IFC files (elements, spaces, storeys, buildings, sites, the project),
an independent count of the property values the file gives it, walked from the raw relationships, must equal what
`properties.read` returns:

- each property set, quantity set and predefined set on the object (IsDefinedBy, IFC4 sets of sets too) and on its
  type (HasPropertySets);
- a property or quantity counts once per set name and property name (the object's own value wins over its type's);
- a complex property counts its parts; a predefined set counts its filled attributes;
- the demo models' hidden note (demos.HIDDEN_PROPERTIES) is never counted, and must never be shown.

    cd server
    uv run python ../evals/properties_complete.py                       # Northbank from $DEMO_MODELS or samples/
    uv run python ../evals/properties_complete.py path/to/a.ifc ...     # any models

Prints one line per file (objects, values, seconds) and every object that differs; exits 1 when any does.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A clone of IssueLab's demo-models repo (CLAUDE.md, "Demo data"): $DEMO_MODELS, else ../demo-models.
DEMO = Path(os.environ.get("DEMO_MODELS", ROOT.parent / "demo-models"))
sys.path.insert(0, str(ROOT / "server"))

import ifcopenshell  # noqa: E402
import ifcopenshell.util.element  # noqa: E402

from sightline import demos, properties  # noqa: E402

NORTHBANK = ("Northbank-Structure.ifc", "Northbank-MEP.ifc", "Northbank-Architecture.ifc", "Northbank-Site.ifc",
             "Northbank-Grids.ifc", "Northbank-MEP-Rev04.ifc")
NOT_A_VALUE = {"id", "type", "GlobalId", "OwnerHistory", "Name", "Description"}


def northbank() -> list[Path]:
    """Northbank's files from the demo-models clone, else from samples/; [] when neither has them."""
    for folder in (DEMO / "northbank" / "IFC", ROOT / "samples"):
        found = [folder / n for n in NORTHBANK if (folder / n).exists()]
        if found:
            return found
    return []


def _count(p) -> int:
    """One property's values: a complex property counts its parts, a hidden one nothing."""
    if (getattr(p, "Name", None) or "") in demos.HIDDEN_PROPERTIES:
        return 0
    if p.is_a("IfcComplexProperty"):
        return sum(_count(c) for c in p.HasProperties or [])
    if p.is_a("IfcPhysicalComplexQuantity"):
        return sum(_count(c) for c in p.HasQuantities or [])
    return 1


def _members(d) -> dict[str, int]:
    """A set's values by property name."""
    if d.is_a("IfcPropertySet"):
        items = d.HasProperties or []
    elif d.is_a("IfcElementQuantity"):
        items = d.Quantities or []
    else:   # a predefined set (door lining, window panel…): its filled attributes
        return {k: 1 for k, v in d.get_info(recursive=False).items()
                if k not in NOT_A_VALUE and v not in (None, "", ()) and k not in demos.HIDDEN_PROPERTIES}
    out: dict[str, int] = {}
    for p in items:
        out.setdefault(p.Name, _count(p))
    return {k: v for k, v in out.items() if v}


def _definitions(o) -> list:
    out = []
    for rel in getattr(o, "IsDefinedBy", None) or []:
        if rel.is_a("IfcRelDefinesByProperties"):
            d = rel.RelatingPropertyDefinition
            out.extend(d if isinstance(d, (tuple, list)) else [d])
    out.extend(getattr(o, "HasPropertySets", None) or [])
    return out


def raw_values(e) -> int:
    """How many property values the file gives an object, its type's included, counted from the relationships."""
    sets: dict[str, dict[str, int]] = {}
    sources = [e]
    kind = ifcopenshell.util.element.get_type(e) if e.is_a("IfcObject") else None
    if kind is not None:
        sources.append(kind)
    for src in sources:       # the object first: its value of a name wins over its type's
        for d in _definitions(src):
            name = demos.PSET_NAMES.get(d.Name, d.Name) if getattr(d, "Name", None) else d.is_a()
            mine = sets.setdefault(name, {})
            for k, v in _members(d).items():
                mine.setdefault(k, v)
    return sum(sum(m.values()) for m in sets.values())


def check(paths: list[Path]) -> tuple[list[dict], list[str]]:
    """Per file: objects, values and seconds; and every object whose values differ (or that shows a hidden one)."""
    rows, wrong = [], []
    for path in paths:
        f = ifcopenshell.open(str(path))
        reader = properties.Reader(f, 0, 1.0 if not f.by_type("IfcProject") else _scale(f))
        objects = [o for o in f.by_type("IfcRoot") if o.is_a("IfcObjectDefinition") and not o.is_a("IfcTypeObject")]
        t0, values = time.perf_counter(), 0
        for o in objects:
            got = reader.read(o, path.name)
            n, want = properties.leaves(got), raw_values(o)
            values += n
            if n != want:
                wrong.append(f"{path.name} {o.GlobalId} {o.is_a()} {o.Name!r}: shows {n}, the file gives {want}")
            text = json.dumps(got)
            if any(h in text for h in demos.HIDDEN_PROPERTIES):
                wrong.append(f"{path.name} {o.GlobalId}: a hidden property is shown")
        rows.append({"file": path.name, "objects": len(objects), "values": values,
                     "seconds": round(time.perf_counter() - t0, 2)})
    return rows, wrong


def _scale(f) -> float:
    import ifcopenshell.util.unit
    return ifcopenshell.util.unit.calculate_unit_scale(f)


def main() -> int:
    paths = [Path(a) for a in sys.argv[1:]] or northbank()
    if not paths:
        print("No models: pass IFC paths, set DEMO_MODELS, or copy Northbank into samples/.")
        return 2
    rows, wrong = check(paths)
    for r in rows:
        print(f"{r['file']:32} {r['objects']:6} objects {r['values']:7} values {r['seconds']:6} s")
    for w in wrong:
        print("DIFFERS", w)
    print("complete" if not wrong else f"{len(wrong)} objects differ")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
