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
import logging
from collections import defaultdict

from . import datums, properties
from .scene import IfcScene

Value = str | int | float | bool
log = logging.getLogger(__name__)


def _vkey(v) -> tuple:
    """A value as a dictionary key: True and 1 (and False and 0) hash alike in Python, so yes/no stays apart."""
    return (type(v) is bool, v)


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
    seen, once = set(), []
    for k, v, u in out:     # one of each (yes/no kept apart from 1/0)
        if (k, _vkey(v)) not in seen:
            seen.add((k, _vkey(v)))
            once.append((k, v, u))
    return once


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
    found: dict[str, dict[tuple, list[int]]] = defaultdict(lambda: defaultdict(list))
    units: dict[str, str] = {}
    for i, model in enumerate(scene.models):
        reader = properties.reader(scene, i)
        objects = [e for e in model.by_type("IfcElement") if e.GlobalId in wanted]
        objects += [s for s in model.by_type("IfcSpace") if s.Representation is not None and s.GlobalId not in wanted]
        for e in objects:
            if e.GlobalId in seen:      # a GlobalId two files share: the first file's
                continue
            try:
                read = reader.read(e, scene.paths[i].name)
            except Exception:       # one object IfcOpenShell cannot read leaves the rest of the index whole
                log.exception("Filters' index: skipped %s in %s", e.GlobalId, scene.paths[i].name)
                continue
            n = len(elements)
            seen.add(e.GlobalId)
            elements.append(e.GlobalId)
            files.append(i)
            storey = levels.get(e.GlobalId) or (read["storey"] or {}).get("name")
            for key, v, unit in element_facets(read, storey):
                found[key][_vkey(v)].append(n)
                if unit:
                    units.setdefault(key, unit)
    facets = []
    for key in sorted(found, key=_facet_order):
        keys = sorted(found[key], key=lambda k: _order(k[1]))
        values = [k[1] for k in keys]
        facet = {"key": key, "kind": _kind(values), "values": values, "items": [found[key][k] for k in keys]}
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


def version(scene: IfcScene) -> tuple:
    """What the index depends on: the scene's revision and its elements."""
    return (scene.revision, len(scene.bounds()))


def cached(scene: IfcScene) -> dict | None:
    """The index kept on the scene, if it is still the scene's."""
    kept = getattr(scene, "_facets", None)
    return kept[1] if kept is not None and kept[0] == version(scene) else None


def keep(scene: IfcScene, built: dict, at: tuple) -> None:
    scene._facets = (at, built)


def index(scene: IfcScene) -> dict:
    """The index, kept on the scene until its revision or its elements change."""
    found_ = cached(scene)
    if found_ is not None:
        return found_
    at = version(scene)
    built = build(scene)
    keep(scene, built, at)
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


# ---------------------------------------------------------------- resolving what chat and agents ask for

COLOURS = 20     # the page's palette (filters.ts PALETTE): past it, colour-by-value values share one colour, "Other"

OPS = {"is": "is", "is_not": "isNot", "contains": "contains", "has": "has", "missing": "missing", "less": "lt",
       "more": "gt", "between": "between"}
ACTIONS = {"colour": "colour", "colour_by_value": "byValue", "hide": "hide", "isolate": "isolate"}
BY_NAMES = {"class": "class", "classes": "class", "level": "storey", "levels": "storey", "floor": "storey",
            "floors": "storey", "storey": "storey", "model": "file", "models": "file", "file": "file", "type": "type",
            "material": "material"}


class Unresolved(ValueError):
    """What someone asked for is not in the open models; the message says what is, closest first."""


def _label(key: str) -> tuple[str, str]:
    """A facet's set and property name as people say them: ("Model data", "System"), ("", "Tag"); a complex
    property's part keeps its path: ("Pset_X", "Connection/Torque")."""
    kind, _, rest = key.partition(":")
    if not rest:
        return "", key
    if kind in ("attr", "classif", "group"):
        return {"attr": "Attributes", "classif": "Classification", "group": "Systems and groups"}[kind], rest
    set_name, _, prop = rest.partition("/")
    return set_name, prop or set_name


def _names(prop: str) -> set[str]:
    """What a property may be called: its path ("connection/torque") or its last part ("torque")."""
    low = prop.lower()
    return {low, low.rsplit("/", 1)[-1]}


def property_key(idx: dict, prop: str, set_name: str | None = None) -> str:
    """The facet key for a property named by people: "System", "Model data/System", "Tag", "FireRating", a complex
    property's part as "Torque" or "Pset_X/Connection/Torque"…"""
    want = prop.strip().lower()
    if want in BY_NAMES:
        return BY_NAMES[want]
    if "/" in want and not set_name:
        head, _, rest = prop.strip().partition("/")
        if any(_label(f["key"])[0].lower() == head.lower() for f in idx["facets"]):
            set_name, want = head, rest.lower()
    found = [f["key"] for f in idx["facets"] if want in _names(_label(f["key"])[1])
             and (not set_name or _label(f["key"])[0].lower() == set_name.strip().lower())]
    if len(found) > 1:      # the same name in several sets: a property set first, then attributes, then quantities
        found.sort(key=lambda k: {"pset": 0, "attr": 1, "group": 2, "classif": 3, "qto": 4}.get(k.split(":")[0], 5))
    if found:
        return found[0]
    names = sorted({_label(f["key"])[1].rsplit("/", 1)[-1] for f in idx["facets"] if ":" in f["key"]})
    close = difflib.get_close_matches(prop, names, n=4, cutoff=0.5)
    raise Unresolved(f"No property {prop!r}{f' in {set_name!r}' if set_name else ''} in the open models."
                     + (f" Closest: {', '.join(close)}." if close else ""))


def _values(idx: dict, key: str, asked: list, loose: bool = False) -> list:
    """The index's own values for what was asked (any case; a class with or without its Ifc prefix; a model by part
    of its file name)."""
    f = facet(idx, key)
    if f is None:
        raise Unresolved(f"Nothing in the open models has {key!r}.")
    out = []
    for a in asked:
        if isinstance(a, bool) or (f["kind"] == "number" and isinstance(a, (int, float))):
            out.append(a)
            continue
        text = str(a).strip().lower()
        hit = [v for v in f["values"] if str(v).lower() == text or (key == "class" and str(v).lower() == "ifc" + text)]
        if not hit and loose:
            hit = [v for v in f["values"] if text in str(v).lower()]
        if not hit and f["kind"] == "number":
            try:
                out.append(float(a))
                continue
            except ValueError:
                pass
        if not hit:
            close = difflib.get_close_matches(str(a), [str(v) for v in f["values"]], n=4, cutoff=0.4)
            raise Unresolved(f"No {_label(key)[1] or key} {a!r} in the open models."
                             + (f" Closest: {', '.join(close)}." if close else ""))
        out.extend(hit)
    return list(dict.fromkeys(out))


def complete(c: dict) -> bool:
    """Whether a condition says enough to find anything by, as the page's filters.ts `complete` reads it: a facet, and
    the values or bounds its test needs. The page leaves out one that does not, so the server must too."""
    if not c.get("facet"):
        return False
    op = c.get("op")
    if op in ("has", "missing"):
        return True
    if op == "lt":
        return c.get("max") is not None
    if op == "gt":
        return c.get("min") is not None
    if op == "between":
        return c.get("min") is not None or c.get("max") is not None
    return bool(c.get("values"))


def found(idx: dict, when: list[dict], invert: bool = False) -> set[int]:
    """The elements (by index) a filter finds, as the page's `found`: every complete condition holds (none: every
    element), then inverted if asked."""
    everyone = set(range(len(idx["elements"])))
    hit = set(everyone)
    for c in when:
        if complete(c):
            hit &= matching(idx, c["facet"], c["op"], c.get("values"), c.get("min"), c.get("max"))
            if not hit:
                break
    return everyone - hit if invert else hit


def _bound(w: dict, name: str):
    """A bound for less / more / between: `min` or `max`, else a lone number in `values` (what a model often sends)."""
    if w.get(name) is not None:
        return float(w[name])
    vals = w.get("values") or []
    if len(vals) == 1:
        try:
            return float(vals[0])
        except (TypeError, ValueError):
            return None
    return None


def resolve(idx: dict, spec: dict, at: int = 0) -> tuple[dict, set[int]]:
    """One filter as chat or an agent describes it (classes, levels, models, where, action, colour, by, invert) as the
    page's rule (filters.ts `Rule`), and the elements (by index) it acts on. Raises Unresolved, naming what is there;
    a condition the page would leave out (a test with no bound or value) is refused, so the two never disagree."""
    when = []
    for key, field in (("class", "classes"), ("storey", "levels"), ("file", "models")):
        if spec.get(field):
            when.append({"facet": key, "op": "is", "values": _values(idx, key, list(spec[field]), loose=key == "file")})
    for w in spec.get("where") or []:
        key = property_key(idx, str(w.get("property", "")), w.get("set"))
        op = OPS.get(str(w.get("op") or "is"))
        if op is None:
            raise Unresolved(f"Unknown test {w.get('op')!r}: one of {', '.join(OPS)}.")
        c: dict = {"facet": key, "op": op}
        if op in ("is", "isNot"):
            c["values"] = _values(idx, key, list(w.get("values") or []))
            if not c["values"]:
                raise Unresolved(f"Say which values of {w.get('property')!r} to match.")
        elif op == "contains":
            c["values"] = [str(v) for v in (w.get("values") or []) if str(v) != ""]
        if op == "gt" and _bound(w, "min") is not None:
            c["min"] = _bound(w, "min")
        if op == "lt" and _bound(w, "max") is not None:
            c["max"] = _bound(w, "max")
        if op == "between":
            for name in ("min", "max"):
                if w.get(name) is not None:
                    c[name] = float(w[name])
            vals = w.get("values") or []
            if "min" not in c and "max" not in c and len(vals) == 2:
                try:
                    c["min"], c["max"] = sorted(float(v) for v in vals)
                except (TypeError, ValueError):
                    pass
        if not complete(c):
            need = "values" if op == "contains" else "max" if op == "lt" else "min" if op == "gt" else "min or max"
            raise Unresolved(f"Say the {need} for {w.get('property')!r} ({w.get('op')}).")
        when.append(c)
    action = ACTIONS.get(str(spec.get("action") or "colour"))
    if action is None:
        raise Unresolved(f"Unknown action {spec.get('action')!r}: one of {', '.join(ACTIONS)}.")
    rule: dict = {"id": f"chat{at}", "name": str(spec.get("name") or ""), "on": True, "when": when, "action": action,
                  "origin": "chat"}
    if spec.get("invert"):
        rule["invert"] = True
    if action == "colour" and spec.get("colour"):
        colour = str(spec["colour"])
        if not (len(colour) == 7 and colour.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in colour[1:])):
            raise Unresolved(f"A colour is #rrggbb, not {colour!r}.")
        rule["colour"] = colour.lower()
    if action == "byValue":
        if not spec.get("by"):
            raise Unresolved("Say which property to colour by (by), e.g. System, class or level.")
        rule["by"] = {"facet": property_key(idx, str(spec["by"]))}
    hit = found(idx, when, bool(spec.get("invert")))
    if action == "byValue":
        f = facet(idx, rule["by"]["facet"])
        hit &= set().union(*map(set, f["items"])) if f and f["items"] else set()
    return rule, hit
