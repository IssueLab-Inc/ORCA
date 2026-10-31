"""The filters' index (GET /api/scenes/{id}/facets, docs/filters.md): every value the Properties panel shows an element
with that a filter can match, turned round so each value lists the elements that have it.

The elements are the ones the page draws and the checks see (the scene's boxes), plus spaces with a body. Each is read
once with `properties.Reader`, the panel's own reader, so a filter and the panel can never disagree, and the hidden
demo note can never reach a filter. Facets, by key:

- `file`, `class`, `storey` (the nearest building storey, as the level checkboxes and the drawing views read it:
  `datums.storeys`), `type` (the type's name) and `material` (each material it is made of);
- `attr:<Name>`: each direct attribute with one value (tag, predefined type, object type…);
- `pset:<Set>/<Prop>` and `qto:<Set>/<Name>`: each property and quantity, its type's included (a complex property's
  parts as `pset:<Set>/<Complex>/<Prop>`); an enumerated or list value counts each of its values;
- `classif:<System>`: each classification reference's identification (or its name);
- `group:<IfcClass>`: each system, zone or group by name.

Numbers stay numbers, in SI (lengths in metres) as the panel's rows carry them; ranges and tables are not indexed. The
index is kept on the scene until a kept edit changes its revision or its elements.
"""
from __future__ import annotations

import difflib
from collections import defaultdict

from . import datums, properties
from .scene import IfcScene

Value = str | int | float | bool


def _scalar(v) -> bool:
    return isinstance(v, (bool, int, float)) or (isinstance(v, str) and v != "")


def _rows(acc, key: str, rows: list[dict]):
    for r in rows:
        if r.get("kind") == "complex":
            _rows(acc, f"{key}/{r['name']}", r.get("rows") or [])
            continue
        if r.get("kind") in ("table", "bounded"):     # a range or a table is not one value to match
            continue
        v = r.get("value")
        values = v if isinstance(v, list) else [v]
        for x in values:
            if _scalar(x):
                acc.append((f"{key}/{r['name']}", x, r.get("unit")))


def element_facets(read: dict, storey: str | None) -> list[tuple[str, Value, str | None]]:
    """(facet key, value, unit) for one read object: what a filter may match it by."""
    out: list[tuple[str, Value, str | None]] = [("file", read["source"], None), ("class", read["ifc_class"], None)]
    if storey:
        out.append(("storey", storey, None))
    if read["type"] and read["type"].get("name"):
        out.append(("type", read["type"]["name"], None))
    for m in read["materials"]:
        for item in m["items"]:
            if item.get("material"):
                out.append(("material", item["material"], None))
    for a in read["attributes"]:
        if _scalar(a["value"]):
            out.append((f"attr:{a['name']}", a["value"], a.get("unit")))
    for c in read["classifications"]:
        v = c.get("identification") or c.get("name")
        if v:
            out.append((f"classif:{c.get('system') or ''}", v, None))
    for g in read["groups"]:
        out.append((f"group:{g['ifc_class']}", g["name"], None))
    for s in read["sets"]:
        _rows(out, f"{s['kind']}:{s['name']}", s["props"])
    return list(dict.fromkeys(out))      # one of each


def _kind(values) -> str:
    if all(isinstance(v, bool) for v in values):
        return "bool"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return "number"
    return "text"


def _order(v):
    return (0, v, "") if isinstance(v, (int, float)) and not isinstance(v, bool) else (1, 0, str(v).lower())


def build(scene: IfcScene) -> dict:
    """The index for the scene as it is now."""
    wanted = set(scene.bounds())
    levels = datums.storeys(scene)
    elements: list[str] = []
    seen: set[str] = set()
    files: list[int] = []
    found: dict[str, dict[Value, list[int]]] = defaultdict(lambda: defaultdict(list))
    units: dict[str, str] = {}
    for i, model in enumerate(scene.models):
        reader = properties.reader(scene, i)
        objects = [e for e in model.by_type("IfcElement") if e.GlobalId in wanted]
        objects += [s for s in model.by_type("IfcSpace") if s.Representation is not None and s.GlobalId not in wanted]
        for e in objects:
            if e.GlobalId in seen:      # a GlobalId two files share: the first file's
                continue
            n = len(elements)
            seen.add(e.GlobalId)
            elements.append(e.GlobalId)
            files.append(i)
            read = reader.read(e, scene.paths[i].name)
            storey = levels.get(e.GlobalId) or (read["storey"] or {}).get("name")
            for key, v, unit in element_facets(read, storey):
                found[key][v].append(n)
                if unit:
                    units.setdefault(key, unit)
    facets = []
    for key in sorted(found, key=_facet_order):
        values = sorted(found[key], key=_order)
        facet = {"key": key, "kind": _kind(values), "values": values, "items": [found[key][v] for v in values]}
        if key in units:
            facet["unit"] = units[key]
        facets.append(facet)
    return {"revision": scene.revision, "files": [p.name for p in scene.paths], "elements": elements, "file": files,
            "facets": facets}


BUILT_IN = ("file", "class", "storey", "type", "material")


def _facet_order(key: str):
    if key in BUILT_IN:
        return (0, BUILT_IN.index(key), key)
    return ({"attr": 1, "pset": 2, "qto": 3, "classif": 4, "group": 5}.get(key.split(":", 1)[0], 6), 0, key.lower())


def index(scene: IfcScene) -> dict:
    """The index, kept on the scene until its revision or its elements change."""
    key = (scene.revision, len(scene.bounds()))
    cached = getattr(scene, "_facets", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    built = build(scene)
    scene._facets = (key, built)
    return built


# ---------------------------------------------------------------- matching (chat and MCP: set_filters)

def facet(idx: dict, key: str) -> dict | None:
    return next((f for f in idx["facets"] if f["key"] == key), None)


def matching(idx: dict, key: str, op: str = "is", values: list | None = None, lo: float | None = None,
             hi: float | None = None) -> set[int]:
    """The elements (by index) one condition takes, as the page's filters.ts reads it: `is`, `isNot`, `contains`
    (text, any case), `has`, `missing`, `lt`, `gt`, `between` (numbers in SI)."""
    f = facet(idx, key)
    everyone = set(range(len(idx["elements"])))
    if f is None:
        return everyone if op in ("missing", "isNot") else set()
    having = set().union(*map(set, f["items"])) if f["items"] else set()
    if op == "has":
        return having
    if op == "missing":
        return everyone - having
    wanted = [str(v).lower() for v in (values or [])]
    take: set[int] = set()
    for v, items in zip(f["values"], f["items"]):
        numeric = isinstance(v, (int, float)) and not isinstance(v, bool)
        if op in ("is", "isNot"):
            hit = any(str(v).lower() == w or (numeric and _same(v, w)) for w in wanted)
        elif op == "contains":
            hit = any(w in str(v).lower() for w in wanted)
        elif op == "lt":
            hit = numeric and hi is not None and v < hi
        elif op == "gt":
            hit = numeric and lo is not None and v > lo
        elif op == "between":
            hit = numeric and (lo is None or v >= lo) and (hi is None or v <= hi)
        else:
            raise ValueError(f"Unknown condition {op!r}")
        if hit:
            take.update(items)
    return everyone - take if op == "isNot" else take


def _same(v: float, w: str) -> bool:
    try:
        return abs(float(w) - v) <= 1e-6 * max(1.0, abs(v))
    except ValueError:
        return False


def suggest(idx: dict, words: str, among: list[str] | None = None, n: int = 3) -> list[str]:
    """The closest facet keys (or values among `among`) to what someone typed."""
    pool = among if among is not None else [f["key"] for f in idx["facets"]]
    low = {p.lower(): p for p in pool}
    return [low[m] for m in difflib.get_close_matches(words.lower(), list(low), n=n, cutoff=0.5)]
