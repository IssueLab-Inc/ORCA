"""ORCA detection: find the clashes in the open models, as a clash report the rest of ORCA already reads.

Design: docs/detection.md. In short:
- a test asks one question (hard, clearance or duplicate) of two selections, or of one selection against itself;
- the default tests are every pair of model files, each file against itself, and duplicates, hard at 1 mm;
- pairs that are meant to meet (one element, joined by ports, one assembly, a door in its wall) are never reported, but
  they are counted, as are touches no deeper than the tolerance;
- a sort and sweep over the cached element boxes finds every pair that could clash (the completeness argument), then
  one triangle tree measures them: intersection for depth, collision without touching for flush faces it misses;
- each clash keeps an id made from its test and its two GlobalIds, so running again keeps ids, and a clash that has gone
  is "resolved" only when both elements were still checked against each other.

A run returns a `reports.Report` (origin "sightline") plus per-test coverage, so the list, triage, insights, plans, chat
and the PDF work on it unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Callable

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.system
import numpy as np

from . import facets, requirements, verify
from .limits import env_int
from .reports import Report, ReportClash, ReportElement, plain_name
from .scene import IfcScene

TOLERANCE_M = 0.001        # an overlap must be deeper than this to be a hard clash; less is a touch
DUPLICATE_M = 0.001        # two copies of one thing: boxes and vertices agree within this
FAR_M = 200.0              # the triangle tree drops real overlaps this far from its origin: shift the models nearer
CAP = env_int("SIGHTLINE_DETECT_CAP", 5000)   # clashes kept per test; a test that reaches it is partial
RULES = ("same_element", "connected", "assembly", "host")
RULE_LABEL = {"same_element": "same element", "connected": "joined by ports", "assembly": "one assembly",
              "host": "door or window in its wall"}

Event = Callable[[dict], None]


@dataclass
class Selection:
    """Which elements a side of a test takes. Empty fields mean "any"."""
    files: list[str] = field(default_factory=list)        # model file names
    teams: list[str] = field(default_factory=list)        # disciplines, as guessed per file
    classes: list[str] = field(default_factory=list)      # IFC classes, subclasses included
    exclude_classes: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)      # distribution system names
    ids: list[str] = field(default_factory=list)          # particular elements, by GlobalId
    # A filter by what the model says (docs/filters.md): {when: [conditions as the page writes them], invert, by?},
    # found against the filters' index at run time, so a rerun after a kept fix selects by properties again. `by`
    # ({facet, off}) is a colour-by-value filter's: it takes only what it colours (`facets.acted`).
    filter: dict | None = None
    # What the page's filters show together ({filters, hide_rest, colours}: `facets.shown`), also found at run time.
    view: dict | None = None

    @staticmethod
    def from_dict(s: dict) -> "Selection":
        lists = {k: [str(x) for x in (v or [])] for k, v in s.items() if k in LIST_FIELDS}
        return Selection(**lists, filter=_filter(s["filter"]) if s.get("filter") is not None else None,
                         view=_view(s["view"]) if s.get("view") is not None else None)

    def on_filters(self) -> bool:
        """Whether this side comes from the page's filters (a check on filters)."""
        return self.filter is not None or self.view is not None

    def describe(self) -> str:
        """What the side takes, in words: its filter's name, else its files, classes, systems; "Everything"."""
        if self.view is not None:
            return "What the filters show"
        if self.filter is not None:
            return facets.name_for(self.filter["when"], self.filter["invert"])
        parts = [", ".join(self.files), ", ".join(c.removeprefix("Ifc") for c in self.classes), ", ".join(self.systems),
                 ", ".join(self.teams)]
        return " · ".join(p for p in parts if p) or "Everything"


LIST_FIELDS = ("files", "teams", "classes", "exclude_classes", "systems", "ids")
FILTER_CONDITIONS, FILTER_VALUES, VIEW_FILTERS = 30, 500, 100
VIEW_ACTIONS = ("colour", "byValue", "hide", "isolate")


def _filter(f) -> dict:
    """A side's filter checked and written one way only (conditions and values sorted), so the same filter always
    gives the same check id."""
    if not isinstance(f, dict):
        raise ValueError("A filter is {when, invert}")
    when = f.get("when") or []
    if not isinstance(when, list) or len(when) > FILTER_CONDITIONS:
        raise ValueError(f"A filter has at most {FILTER_CONDITIONS} conditions")
    out = []
    for c in when:
        if not isinstance(c, dict) or not isinstance(c.get("facet"), str):
            raise ValueError("Each condition names its facet")
        op = c.get("op") or "is"
        if op not in facets.OPS.values():
            raise ValueError(f"Unknown condition {op!r}")
        values = c.get("values") or []
        if not isinstance(values, list) or len(values) > FILTER_VALUES:
            raise ValueError(f"A condition has at most {FILTER_VALUES} values")
        one: dict = {"facet": c["facet"], "op": op}
        if values:
            one["values"] = sorted(values, key=lambda v: (type(v).__name__, str(v)))
        for k in ("min", "max"):
            if c.get(k) is not None:
                one[k] = float(c[k])
        out.append(one)
    out.sort(key=lambda c: json.dumps(c, sort_keys=True))
    kept = {"when": out, "invert": bool(f.get("invert"))}
    by = f.get("by")
    if by is not None:
        if not isinstance(by, dict) or not isinstance(by.get("facet"), str) or not by["facet"]:
            raise ValueError("A filter's colour by names its facet")
        off = by.get("off") or []
        if not isinstance(off, list) or len(off) > FILTER_VALUES:
            raise ValueError(f"A colour by leaves out at most {FILTER_VALUES} values")
        kept["by"] = {"facet": by["facet"], "off": sorted({str(v) for v in off})}
    return kept


def _view(v) -> dict:
    """What the filters show, checked and written one way only: the filters that are on (sorted: what they show
    together does not depend on their order), and whether the rest is hidden and colours show."""
    if not isinstance(v, dict) or not isinstance(v.get("filters") or [], list):
        raise ValueError("A view is {filters, hide_rest, colours}")
    rules = v.get("filters") or []
    if len(rules) > VIEW_FILTERS:
        raise ValueError(f"A view has at most {VIEW_FILTERS} filters")
    out = []
    for r in rules:
        if not isinstance(r, dict) or r.get("action", "colour") not in VIEW_ACTIONS:
            raise ValueError("Each filter of a view says what it does: colour, byValue, hide or isolate")
        out.append({**_filter(r), "action": r.get("action", "colour")})
    out.sort(key=lambda r: json.dumps(r, sort_keys=True))
    return {"filters": out, "hide_rest": bool(v.get("hide_rest")), "colours": v.get("colours", True) is not False}


def check_name(a: Selection, b: Selection | None, kind: str = "hard", clearance_m: float = 0.0) -> str:
    """A check's name from its sides: "A vs B", "A (within)", "A vs Everything", and its clearance."""
    name = f"{a.describe()} (within)" if b is None else f"{a.describe()} vs {b.describe()}"
    if kind == "clearance":
        name += f", {round(clearance_m * 1000)} mm clearance"
    elif kind == "duplicate":
        name += ", duplicates"
    return name


def check_id(a: Selection, b: Selection | None, kind: str) -> str:
    """A check's id from what it compares (not its name or tolerance, as `pair:` ids), so a rerun keeps its clashes."""
    sides = {"a": asdict(a), "b": None if b is None else asdict(b), "kind": kind}
    return "filter:" + hashlib.sha1(json.dumps(sides, sort_keys=True).encode()).hexdigest()[:10]


@dataclass
class Test:
    id: str
    name: str
    a: Selection
    b: Selection | None = None   # None: A against itself
    kind: str = "hard"           # "hard" | "clearance" | "duplicate"
    tolerance_m: float = TOLERANCE_M
    clearance_m: float = 0.0
    rules: dict[str, bool] = field(default_factory=lambda: {r: True for r in RULES})
    enabled: bool = True
    min_size_m: float = 0.0      # elements whose largest box side is under this are left out (early design levels)

    @staticmethod
    def from_dict(d: dict) -> "Test":
        """A test as the page or a tool sends it. With no id (a check on filters), the id comes from what it compares
        (`check_id`) and the name from its sides (`check_name`) unless one is given."""
        kind = d.get("kind", "hard")
        if kind not in ("hard", "clearance", "duplicate"):
            raise ValueError(f"unknown test kind {kind!r}")
        a = Selection.from_dict(d.get("a") or {})
        b = None if d.get("b") is None else Selection.from_dict(d["b"])
        clearance_m = max(0.0, float(d.get("clearance_m", 0.0)))
        tid = str(d.get("id") or "") or check_id(a, b, kind)
        name = str(d.get("name") or "") or (check_name(a, b, kind, clearance_m) if not d.get("id") else tid)
        rules = {r: True for r in RULES} | {k: bool(v) for k, v in (d.get("rules") or {}).items() if k in RULES}
        return Test(id=tid, name=name, a=a, b=b,
                    kind=kind, tolerance_m=max(0.0, float(d.get("tolerance_m", TOLERANCE_M))),
                    clearance_m=clearance_m, rules=rules,
                    enabled=bool(d.get("enabled", True)), min_size_m=max(0.0, float(d.get("min_size_m", 0.0))))


@dataclass
class Coverage:
    test: str
    name: str
    kind: str
    elements_a: int
    elements_b: int
    candidate_pairs: int      # pairs whose boxes come close enough to clash: every other pair cannot
    clashes: int
    touching: int             # overlapping no deeper than the tolerance
    excluded: dict[str, int]  # overlapping pairs not reported, by rule
    partial: bool
    seconds: float


@dataclass
class Run:
    report: Report
    coverage: list[Coverage]
    diff: dict                # {"new": [ids], "resolved": [...], "no_longer_checked": [...]} against the last run
    elements: int
    seconds: float
    offset: list[float]       # what the triangle tree was shifted by (zero unless the models are far from the origin)
    state: dict               # what the next run compares against


# ------------------------------------------------------------------------------------------------- the open models

class _Index:
    """Lookups the run needs many times, built once: file of each element, physical boxes, labels, relations."""

    def __init__(self, scene: IfcScene):
        self.scene = scene
        self.boxes = scene.bounds()
        self.file: dict[str, int] = {}
        self.entity: dict[str, object] = {}
        for i, m in enumerate(scene.models):
            for p in m.by_type("IfcElement"):
                if p.GlobalId in self.boxes:
                    self.file[p.GlobalId] = i
                    self.entity[p.GlobalId] = p
        self.names = [p.name for p in scene.paths]
        # Each file's team, guessed in the scene's domain: the same names requirements groups select by.
        self.teams = list(requirements._file_teams(scene, requirements.domain_of(scene, requirements.current())))
        self._systems: dict[str, list[str]] = {}
        self._filtered: dict[str, set[str]] = {}
        self.connected = self._connected()
        self.assembly = self._assemblies()
        self.host = self._hosts()

    def systems(self, gid: str) -> list[str]:
        if gid not in self._systems:
            self._systems[gid] = [s.Name for s in ifcopenshell.util.system.get_element_systems(self.entity[gid]) if s.Name]
        return self._systems[gid]

    def _connected(self) -> set[frozenset]:
        """Element pairs joined port to port."""
        out = set()
        for m in self.scene.models:
            for rel in m.by_type("IfcRelConnectsPorts"):
                owners = [ifcopenshell.util.system.get_port_element(p) for p in (rel.RelatingPort, rel.RelatedPort)]
                if all(o is not None for o in owners) and owners[0].GlobalId != owners[1].GlobalId:
                    out.add(frozenset((owners[0].GlobalId, owners[1].GlobalId)))
        return out

    def _assemblies(self) -> dict[str, str]:
        """Element → the element-level assembly it belongs to (aggregate or nest of elements). Parts of one
        assembly, and an assembly and its parts, share a key."""
        root: dict[str, str] = {}
        for m in self.scene.models:
            for rel in list(m.by_type("IfcRelAggregates")) + list(m.by_type("IfcRelNests")):
                whole = rel.RelatingObject
                if not whole.is_a("IfcElement"):
                    continue
                for part in rel.RelatedObjects:
                    if part.is_a("IfcElement"):
                        root[part.GlobalId] = whole.GlobalId
        def top(g):
            seen = set()
            while g in root and g not in seen:
                seen.add(g)
                g = root[g]
            return g
        keys = {g: top(g) for g in root}
        for g in set(keys.values()):
            keys[g] = g
        return keys

    def _hosts(self) -> set[frozenset]:
        """A door or window and the element whose opening it fills."""
        out = set()
        for m in self.scene.models:
            for rel in m.by_type("IfcRelFillsElement"):
                for voids in rel.RelatingOpeningElement.VoidsElements or ():
                    out.add(frozenset((rel.RelatedBuildingElement.GlobalId, voids.RelatingBuildingElement.GlobalId)))
        return out

    def excluded_by(self, a: str, b: str, rules: dict[str, bool]) -> str | None:
        if rules.get("same_element", True) and a == b:
            return "same_element"
        pair = frozenset((a, b))
        if rules.get("connected", True) and pair in self.connected:
            return "connected"
        if rules.get("assembly", True) and a in self.assembly and self.assembly.get(a) == self.assembly.get(b):
            return "assembly"
        if rules.get("host", True) and pair in self.host:
            return "host"
        return None

    def filtered(self, f: dict, view: bool = False) -> set[str]:
        """The elements a side's filter acts on, or its view shows, against the filters' index as the scene is now;
        once per run."""
        key = json.dumps([view, f], sort_keys=True)
        if key not in self._filtered:
            idx = facets.index(self.scene)
            got = facets.shown(idx, f) if view else facets.acted(idx, f)
            self._filtered[key] = {idx["elements"][i] for i in got}
        return self._filtered[key]

    def select(self, sel: Selection) -> list[str]:
        out = []
        ids = set(sel.ids)
        allowed = self.filtered(sel.filter) if sel.filter is not None else None
        if sel.view is not None:
            shown = self.filtered(sel.view, view=True)
            allowed = shown if allowed is None else allowed & shown
        for g, e in self.entity.items():
            if ids and g not in ids:
                continue
            if allowed is not None and g not in allowed:
                continue
            i = self.file[g]
            if sel.files and self.names[i] not in sel.files:
                continue
            if sel.teams and self.teams[i] not in sel.teams:
                continue
            if sel.classes and not any(e.is_a(c) for c in sel.classes):
                continue
            if sel.exclude_classes and any(e.is_a(c) for c in sel.exclude_classes):
                continue
            if sel.systems and not set(self.systems(g)) & set(sel.systems):
                continue
            out.append(g)
        return sorted(out)

    def report_element(self, gid: str) -> ReportElement:
        e = self.entity[gid]
        container = ifcopenshell.util.element.get_container(e)
        systems = self.systems(gid)
        return ReportElement(global_id=gid, ifc_class=e.is_a(), name=e.Name or e.is_a(),
                             level=getattr(container, "Name", None), file=self.names[self.file[gid]],
                             system=systems[0] if systems else None, description=getattr(e, "Description", None))


# ------------------------------------------------------------------------------------------------- default tests

def default_tests(scene: IfcScene, index: _Index | None = None) -> list[Test]:
    """Every pair of model files, each file against itself, and duplicates across everything: hard, 1 mm. A site model
    (terrain, paving, planting) is context for the building, so its tests are listed but off, unless it is all there is."""
    ix = index or _Index(scene)
    files = _files(scene, ix)
    counts = Counter(ix.teams[i] for i in files)
    # A discipline names a model only among several; one model on its own (a machine cell) keeps its file name.
    label = {i: ix.teams[i] if len(files) > 1 and counts[ix.teams[i]] == 1 else Path(ix.names[i]).stem for i in files}
    order = sorted(files, key=lambda i: label[i])
    site = _site(ix, files)
    tests = []
    for i, j in combinations(order, 2):
        tests.append(Test(id=f"pair:{ix.names[i]}|{ix.names[j]}", name=f"{label[i]} vs {label[j]}",
                          a=Selection(files=[ix.names[i]]), b=Selection(files=[ix.names[j]]),
                          enabled=not ({i, j} & site)))
    for i in order:
        tests.append(Test(id=f"self:{ix.names[i]}", name=f"{label[i]} (within)", a=Selection(files=[ix.names[i]]),
                          enabled=i not in site))
    tests.append(Test(id="duplicates", name="Duplicates (all models)" if not site else "Duplicates (building models)",
                      a=Selection(files=[ix.names[i] for i in order if i not in site]) if site else Selection(),
                      kind="duplicate", tolerance_m=DUPLICATE_M))
    return tests


def _files(scene: IfcScene, ix: _Index) -> list[int]:
    return [i for i in range(len(scene.models)) if any(f == i for f in ix.file.values())]


def _site(ix: _Index, files: list[int]) -> set[int]:
    """The site models among the files (terrain, paving, planting): context for the building, unless all there is."""
    site = {i for i in files if ix.teams[i] == "Site"}
    return set() if site == set(files) else site


def everything(scene: IfcScene, index: _Index | None = None) -> Selection:
    """"Everything" as a check on filters takes it: what the full check covers, so a site model is left out as
    context (`default_tests`), unless it is all there is (docs/filters.md, "Checks")."""
    ix = index or _Index(scene)
    files = _files(scene, ix)
    site = _site(ix, files)
    return Selection(files=sorted(ix.names[i] for i in files if i not in site)) if site else Selection()


def presets(scene: IfcScene, index: _Index | None = None) -> list[Test]:
    """Tests offered but not run by default: a building's services clear of its structure, by the default clearance
    (a machine's files are teams of their own names, so it gets none)."""
    ix = index or _Index(scene)
    teams = set(ix.teams)
    if {"MEP", "Structure"} <= teams:
        mm = requirements.DEFAULT_CLEARANCE_MM
        return [Test(id="clearance:MEP|Structure", name=f"MEP vs Structure, {mm} mm clearance", kind="clearance",
                     a=Selection(teams=["MEP"]), b=Selection(teams=["Structure"]),
                     clearance_m=requirements.DEFAULT_CLEARANCE_M, enabled=False)]
    return []


# ------------------------------------------------------------------------------------------------- broad phase

def _candidates(ix: _Index, a: list[str], b: list[str] | None, margin: float) -> list[tuple[str, str]]:
    """Every pair whose boxes come within `margin` of each other: a sort and sweep on x, then y and z. A pair it does
    not return cannot overlap or come that close, so it needs no further check. `b` None pairs A with itself, once."""
    if not a or (b is not None and not b):
        return []
    A = np.array([ix.boxes[g] for g in a])            # (n, 2, 3)
    B = A if b is None else np.array([ix.boxes[g] for g in b])
    ids_b = a if b is None else b
    # A check on filters can take an element on both sides (a filter against Everything): never pair an element with
    # itself, and each pair once.
    both = b is not None and not set(a).isdisjoint(b)
    once: set[tuple[str, str]] = set()
    order = np.argsort(B[:, 0, 0])
    rank = np.empty(len(order), dtype=np.int64)
    rank[order] = np.arange(len(order))
    # A box that starts more than the widest box's width before this one's start cannot reach it: the window on x is
    # [lo - widest, hi]. The few very long boxes (a slab, a long wall: wider than all but 1 in 100) would widen it for
    # everyone, so they are checked with every box instead. Without the lower bound the sweep was quadratic (a 500 MB
    # model: 8 minutes with nothing to find).
    widths = B[:, 1, 0] - B[:, 0, 0]
    cut = float(np.percentile(widths, 99)) if len(widths) > 100 else float(widths.max())
    long_ = np.nonzero(widths > cut)[0]
    short = order[widths[order] <= cut]
    short_min = B[short, 0, 0]
    widest = float(widths[short].max()) if len(short) else 0.0
    out = []
    for i, g in enumerate(a):
        lo, hi = A[i, 0] - margin, A[i, 1] + margin
        start = np.searchsorted(short_min, lo[0] - widest, side="left")
        end = np.searchsorted(short_min, hi[0], side="right")
        js = np.concatenate([short[start:end], long_])
        js = js[np.argsort(rank[js], kind="stable")]   # in sweep order, as always
        js = js[(B[js, 0, 0] <= hi[0]) & (B[js, 1, 0] >= lo[0]) & (B[js, 0, 1] <= hi[1]) & (B[js, 1, 1] >= lo[1])
                & (B[js, 0, 2] <= hi[2]) & (B[js, 1, 2] >= lo[2])]
        for j in js:
            h = ids_b[j]
            if b is None and h <= g:      # self test: each unordered pair once, never an element with itself
                continue
            if both:
                if h == g or (min(g, h), max(g, h)) in once:
                    continue
                once.add((min(g, h), max(g, h)))
            out.append((g, h))
    return out


# ------------------------------------------------------------------------------------------------- narrow phase

def _offset(ix: _Index) -> np.ndarray:
    """Shift for the triangle tree: zero near the origin; the federation's middle, in whole metres, when far."""
    if not ix.boxes:
        return np.zeros(3)
    lo = np.min([b[0] for b in ix.boxes.values()], axis=0)
    hi = np.max([b[1] for b in ix.boxes.values()], axis=0)
    if max(np.abs(lo).max(), np.abs(hi).max()) <= FAR_M:
        return np.zeros(3)
    return -np.round((lo + hi) / 2)


def _tree(ix: _Index, gids: set[str], offset: np.ndarray):
    tree = ifcopenshell.geom.tree(backend="opencascade.trianglebvh")
    by_file: dict[int, list] = {}
    for g in gids:
        by_file.setdefault(ix.file[g], []).append(ix.entity[g])
    for i, include in by_file.items():
        s = verify._settings()
        if offset.any():
            s.set("model-offset", tuple(float(x) for x in offset))
        tree.add_iterator(ifcopenshell.geom.iterator(s, ix.scene.models[i], os.cpu_count() or 1, include=include))
    return tree


def _box_point(ix: _Index, a: str, b: str) -> list[float]:
    (amin, amax), (bmin, bmax) = ix.boxes[a], ix.boxes[b]
    return [float(x) for x in (np.maximum(amin, bmin) + np.minimum(amax, bmax)) / 2]


def _box_depth(ix: _Index, a: str, b: str) -> float:
    """How far one box must move to clear the other (0 when apart or touching). It bounds the elements' own depth
    from above: moving the boxes apart moves what is inside them apart too."""
    (amin, amax), (bmin, bmax) = ix.boxes[a], ix.boxes[b]
    return float(max(0.0, np.minimum(amax - bmin, bmax - amin).min()))


class _Solids:
    """Oriented boxes of rectangular extrusions, for the exact separating-axis depth. The triangle queries miss two
    such solids that overlap with every side face flush (a strut run 30 mm into a beam's end, two panels of one wall
    lapping), so pairs whose boxes overlap get this check too when both are rectangular."""

    def __init__(self, ix: _Index):
        self.ix = ix
        self._cache: dict[str, tuple | None] = {}

    def box(self, gid: str):
        if gid not in self._cache:
            self._cache[gid] = self._make(gid)
        return self._cache[gid]

    def _make(self, gid: str):
        from . import edits
        entity = self.ix.entity[gid]
        if getattr(entity, "HasOpenings", ()):
            return None
        try:
            _, _, solid, _, direction, px, py = edits._frames(self.ix.scene, entity)
        except Exception:
            return None
        if solid.SweptArea.is_a() != "IfcRectangleProfileDef":
            return None
        position = solid.SweptArea.Position
        if position is not None and position.RefDirection is not None:
            x, y = position.RefDirection.DirectionRatios
            norm = float(np.hypot(x, y))
            px, py = (px * x + py * y) / norm, (-px * y + py * x) / norm
        verts = _verts(self.ix, gid)
        axes = np.array([px, py, direction], dtype=float)
        axes /= np.linalg.norm(axes, axis=1)[:, None]
        local = verts @ axes.T
        return ((local.max(axis=0) + local.min(axis=0)) / 2) @ axes, (local.max(axis=0) - local.min(axis=0)) / 2, axes

    def depth(self, a: str, b: str) -> float | None:
        """Exact minimum translation to separate two rectangular solids; None when either is not one."""
        A, B = self.box(a), self.box(b)
        if A is None or B is None:
            return None
        (ca, ha, aa), (cb, hb, ab) = A, B
        best = float("inf")
        for axis in list(aa) + list(ab) + [np.cross(x, y) for x in aa for y in ab]:
            n = np.linalg.norm(axis)
            if n < 1e-8:
                continue
            axis = axis / n
            overlap = float(ha @ np.abs(aa @ axis) + hb @ np.abs(ab @ axis) - abs((cb - ca) @ axis))
            if overlap <= 0:
                return 0.0
            best = min(best, overlap)
        return best


def _verts(ix: _Index, gid: str) -> np.ndarray:
    shape = ifcopenshell.geom.create_shape(verify._settings(), ix.entity[gid])
    return np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)


def _same_shape(ix: _Index, a: str, b: str, tol: float) -> bool:
    """Every vertex of each lies within `tol` of a vertex of the other (symmetric Hausdorff over vertices)."""
    va, vb = _verts(ix, a), _verts(ix, b)
    if not len(va) or not len(vb) or max(len(va), len(vb)) > 4000:
        return False
    d = np.linalg.norm(va[:, None, :] - vb[None, :, :], axis=2)
    return bool(d.min(axis=1).max() <= tol and d.min(axis=0).max() <= tol)


@dataclass
class _Hit:
    a: str
    b: str
    distance_m: float
    point: list[float]


def _measure(ix: _Index, solids: _Solids, test: Test, pairs: list[tuple[str, str]], tree, offset: np.ndarray,
             ) -> tuple[dict[frozenset, _Hit], list[tuple[str, str]]]:
    """Measure candidate pairs. Returns the overlapping (or too close) pairs and the pairs that only touch.

    Depth is how far one must move to clear the other. For two rectangular solids it is exact (separating axes).
    Otherwise it is an estimate: the lesser of the intersection query's figure and how far the boxes must move apart.
    The query's figure alone can be far off either way: a pipe half a millimetre into a beam's underside reads 200 mm
    (the beam's width), and a top rail 40 mm into a post reads 20."""
    if not pairs:
        return {}, []
    allowed = {frozenset(p): p for p in pairs}
    left = sorted({a for a, _ in pairs})
    right = sorted({b for _, b in pairs})
    ea = [ix.entity[g] for g in left]
    eb = [ix.entity[g] for g in right]
    back = lambda p: [float(x) - float(o) for x, o in zip(p, offset)]
    hits: dict[frozenset, _Hit] = {}
    touching: list[tuple[str, str]] = []

    def keep(a, b, distance, point):
        key = frozenset((a, b))
        old = hits.get(key)
        if old is None or distance < old.distance_m:
            oa, ob = allowed[key]
            hits[key] = _Hit(oa, ob, distance, point)

    if test.kind == "duplicate":
        for a, b in pairs:
            if ix.entity[a].is_a() != ix.entity[b].is_a():
                continue
            if np.abs(ix.boxes[a] - ix.boxes[b]).max() > test.tolerance_m:
                continue
            if _same_shape(ix, a, b, test.tolerance_m):
                keep(a, b, -_box_depth(ix, a, b), _box_point(ix, a, b))
        return hits, []

    tol = test.tolerance_m if test.kind == "hard" else 0.0
    seen: set[frozenset] = set()

    def judge(a, b, depth, point):
        key = frozenset((a, b))
        seen.add(key)
        exact = solids.depth(a, b)
        depth = exact if exact is not None else min(depth, _box_depth(ix, a, b))
        if depth <= tol:
            if depth > 0:
                touching.append((a, b))
            return
        keep(a, b, -depth, point)

    # Intersection finds overlaps, also one element wholly inside another.
    for c in tree.clash_intersection_many(ea, eb, tolerance=0.0, check_all=True):
        a, b = c.a.GlobalId, c.b.GlobalId
        if a != b and frozenset((a, b)) in allowed and frozenset((a, b)) not in seen:
            judge(a, b, abs(float(c.distance)), [(x + y) / 2 for x, y in zip(back(c.p1), back(c.p2))])
    # Collision without touching sees some flush-face overlaps intersection misses.
    for c in tree.clash_collision_many(ea, eb, allow_touching=False):
        a, b = c.a.GlobalId, c.b.GlobalId
        if a != b and frozenset((a, b)) in allowed and frozenset((a, b)) not in seen:
            judge(a, b, float("inf"), _box_point(ix, a, b))
    # Neither sees two rectangular solids overlapping with every side flush: the separating-axis check does.
    for a, b in pairs:
        key = frozenset((a, b))
        if a == b or key in seen or _box_depth(ix, a, b) <= tol:
            continue
        exact = solids.depth(a, b)
        if exact is not None and exact > 0:
            judge(a, b, exact, _box_point(ix, a, b))
    if test.kind == "clearance":
        # The clearance query's gap for pairs that overlap is unreliable, so overlaps keep the measures above.
        for c in tree.clash_clearance_many(ea, eb, clearance=test.clearance_m, check_all=True):
            a, b = c.a.GlobalId, c.b.GlobalId
            key = frozenset((a, b))
            if a == b or key not in allowed or key in seen:
                continue
            gap = float(c.distance)
            if gap < test.clearance_m:
                keep(a, b, gap, [(x + y) / 2 for x, y in zip(back(c.p1), back(c.p2))])
    return hits, touching


# ------------------------------------------------------------------------------------------------- a run

def measure_pair(scene: IfcScene, a: str, b: str) -> float | None:
    """How deep two elements overlap now, the way a run measures it (negative metres), or None when they don't."""
    ix = _Index(scene)
    if a not in ix.entity or b not in ix.entity or a == b:
        return None
    test = Test(id="pair", name="pair", a=Selection(ids=[a]), b=Selection(ids=[b]), tolerance_m=0.0)
    pairs = _candidates(ix, [a], [b], 0.0)
    if not pairs:
        return None
    hits, _ = _measure(ix, _Solids(ix), test, pairs, _tree(ix, {a, b}, _offset(ix)), _offset(ix))
    hit = hits.get(frozenset((a, b)))
    return None if hit is None else round(hit.distance_m, 6)


def _sized(ix: _Index, ids: list[str], min_size_m: float) -> list[str]:
    """Only elements at least `min_size_m` across in their largest direction (all when it is 0)."""
    if min_size_m <= 0:
        return ids
    return [g for g in ids if float(np.max(ix.boxes[g][1] - ix.boxes[g][0])) >= min_size_m]


def clash_id(test_id: str, a: str, b: str) -> str:
    x, y = sorted((a, b))
    return "s" + hashlib.sha1(f"{test_id}|{x}|{y}".encode()).hexdigest()[:9]


def run(scene: IfcScene, tests: list[Test] | None = None, on_event: Event | None = None, previous: dict | None = None,
        cap: int = CAP, title: str | None = None, known: dict | None = None, root: Path | None = None) -> Run:
    """Run the tests (default: `default_tests`) over the open models and return them as a clash report.

    `previous`: the state this run compares with (what it calls new, resolved or no longer checked): the same check's
    last run. `known`: every clash the scene has given an id and a number ({"clashes": id → {kind, a, b}, "numbers",
    "open": ids in the open list}, `checks.Register.known`); without it, `previous` is all the run knows. `root`: the
    folder the report keeps its files in (a new temporary one, deleted with the report, by default)."""
    emit = on_event or (lambda e: None)
    if known is None:
        was = (previous or {}).get("clashes", {})
        known = {"clashes": was, "numbers": (previous or {}).get("numbers", {}), "open": set(was)}
    t0 = time.perf_counter()
    emit({"type": "phase", "text": "Reading the models"})
    ix = _Index(scene)
    tests = [t for t in (tests if tests is not None else default_tests(scene, ix)) if t.enabled]
    if len({t.id for t in tests}) != len(tests):
        raise ValueError("Two tests share an id")
    emit({"type": "start", "elements": len(ix.entity), "tests": [{"id": t.id, "name": t.name, "kind": t.kind}
                                                                   for t in tests]})
    # Broad phase for every test first, so the triangle tree is built once over just what can clash.
    plans = []
    for t in tests:
        a = _sized(ix, ix.select(t.a), t.min_size_m)
        b = None if t.b is None else _sized(ix, ix.select(t.b), t.min_size_m)
        margin = t.clearance_m if t.kind == "clearance" else t.tolerance_m
        plans.append((t, a, b, _candidates(ix, a, b, margin)))
    needed = {g for _, _, _, pairs in plans for p in pairs for g in p}
    offset = _offset(ix)
    emit({"type": "phase", "text": f"Building geometry for {len(needed)} elements"})
    tree = _tree(ix, needed, offset) if needed else None
    solids = _Solids(ix)

    hits_found: list[tuple[Test, object]] = []
    contacts: set[frozenset] = set()   # pairs that only touch: what rests on or meets what (connections.graph)
    coverage: list[Coverage] = []
    selections: dict[str, dict] = {}
    for n, (t, a, b, pairs) in enumerate(plans):
        t1 = time.perf_counter()
        emit({"type": "test", "index": n, "id": t.id, "name": t.name, "candidates": len(pairs)})
        hits, touches = _measure(ix, solids, t, pairs, tree, offset) if tree is not None else ({}, [])
        contacts.update(frozenset(p) for p in touches)
        touching = len(touches)
        excluded: Counter = Counter()
        found = []
        for h in hits.values():
            rule = ix.excluded_by(h.a, h.b, t.rules)
            if rule:
                excluded[rule] += 1
            else:
                found.append(h)
        found.sort(key=lambda h: (h.distance_m, h.a, h.b))
        partial = len(found) > cap
        found = found[:cap]
        hits_found.extend((t, h) for h in found)
        cov = Coverage(test=t.id, name=t.name, kind=t.kind, elements_a=len(a), elements_b=len(a if b is None else b),
                       candidate_pairs=len(pairs), clashes=len(found), touching=touching, excluded=dict(excluded),
                       partial=partial, seconds=round(time.perf_counter() - t1, 3))
        coverage.append(cov)
        selections[t.id] = {"a": set(a), "b": None if b is None else set(b), "complete": not partial}
        emit({"type": "test_done", "index": n, "coverage": asdict(cov)})

    ids = _assign_ids(hits_found, known["clashes"])
    clashes: list[ReportClash] = []
    tested: dict[str, Test] = {}
    for (t, h), cid in zip(hits_found, ids):
        tested[cid] = t
        ea, eb = ix.report_element(h.a), ix.report_element(h.b)
        clashes.append(ReportClash(
            id=cid, name=plain_name(ea, eb), guid=cid, test=t.name, test_type=t.kind,
            tolerance_m=t.clearance_m if t.kind == "clearance" else t.tolerance_m, status="new",
            distance_m=round(h.distance_m, 6), point=[round(x, 4) for x in h.point], grid=None,
            a=ea, b=eb, source="sightline"))

    # #N across the whole set and across runs: a clash keeps its number, a new one takes the next, none is reused.
    numbers = dict(known["numbers"])
    following = max([0, *numbers.values()]) + 1
    for c in clashes:
        if c.id not in numbers:
            numbers[c.id], following = following, following + 1
        c.number = numbers[c.id]
    # Only like with like: a run whose tests share none with the last run's (the full check after a check on filters,
    # or the other way round) says nothing about what was resolved or no longer checked, and calls new only a clash
    # these models never had a number for (the full check's clashes come back from a check on filters, not anew).
    # A check's first run calls new only what the open list does not already hold (another check found the rest).
    diff = _diff(previous, clashes, selections)
    if previous and not set(selections) & set(previous.get("selections", {})):
        fresh = sorted({c.id for c in clashes} - set(known["numbers"]))
        diff = {**diff, "new": fresh, "new_ids": set(fresh), "resolved": [], "no_longer_checked": []}
    elif not previous and known["open"]:
        fresh = sorted({c.id for c in clashes} - set(known["open"]))
        diff = {**diff, "new": fresh, "new_ids": set(fresh)}
    for c in clashes:
        if c.id not in diff["new_ids"]:
            c.status = "active"
    temporary = root is None
    root = root if root is not None else Path(tempfile.mkdtemp(prefix="sightline-run-"))
    # The title and the element count say what the tests checked (a site model open for context is not, by default).
    checked_ids = {g for sel in selections.values() for side in (sel["a"], sel["b"] or ()) for g in side}
    checked = len({ix.file[g] for g in checked_ids})
    if title is None and len(tests) == 1 and (tests[0].a.on_filters() or (tests[0].b and tests[0].b.on_filters())):
        title = f"Coordination · {tests[0].name}"
    report = Report(id=uuid.uuid4().hex[:12], title=title or f"Coordination · {checked} model"
                    f"{'' if checked == 1 else 's'}", root=root, sources=list(ix.names), clashes=clashes,
                    temporary=temporary, origin="sightline")
    state = {"clashes": {c.id: {"test": tested[c.id].id, "name": tested[c.id].name, "kind": tested[c.id].kind,
                                "a": c.a.global_id, "b": c.b.global_id} for c in clashes},
             "selections": selections, "numbers": numbers, "contacts": [sorted(p) for p in contacts]}
    seconds = round(time.perf_counter() - t0, 2)
    return Run(report, coverage, {k: v for k, v in diff.items() if k != "new_ids"}, len(checked_ids), seconds,
               [float(x) for x in offset], state)


def _assign_ids(hits: list[tuple[Test, object]], known: dict[str, dict]) -> list[str]:
    """Each hit's clash id. A clash keeps its id, and so its #N, title, views, sign-offs and marks, wherever it is found
    again: first, every hit whose own id (`clash_id` of its test and pair) was issued before keeps it; then any other
    hit takes the id first issued for its pair and kind (a check on filters finding a pair the full check found takes
    the full check's id), else its own. No id is taken twice in one run (two tests finding one pair stay two clashes),
    whatever order the tests ran in."""
    by_pair: dict[tuple, list[str]] = {}
    for cid, was in known.items():
        by_pair.setdefault((was.get("kind") or "hard", frozenset((was["a"], was["b"]))), []).append(cid)
    out: list[str | None] = [None] * len(hits)
    taken: set[str] = set()
    for i, (t, h) in enumerate(hits):
        own = clash_id(t.id, h.a, h.b)
        if own in known and (known[own].get("kind") or "hard") == t.kind and own not in taken:
            out[i] = own
            taken.add(own)
    for i, (t, h) in enumerate(hits):
        if out[i] is not None:
            continue
        same = next((cid for cid in by_pair.get((t.kind, frozenset((h.a, h.b))), []) if cid not in taken), None)
        own = clash_id(t.id, h.a, h.b)
        if same is None:
            # Its own id, unless that was issued for another kind of clash on this pair (a test id reused for another
            # kind under other requirements): then one of its own kind.
            same = own if own not in known and own not in taken else clash_id(f"{t.id}|{t.kind}", h.a, h.b)
        out[i] = same
        taken.add(same)
    return out  # type: ignore[return-value]


def _diff(previous: dict | None, clashes: list[ReportClash], selections: dict[str, dict]) -> dict:
    """Against the last run: which clashes are new, which have gone because they were fixed (both elements still
    checked against each other in a complete test), and which have gone only because they were no longer checked."""
    now = {c.id for c in clashes}
    if not previous:
        return {"new": sorted(now), "new_ids": now, "resolved": [], "no_longer_checked": [], "first": True}
    before = previous.get("clashes", {})
    new = sorted(now - set(before))
    resolved, unchecked = [], []
    for cid, was in before.items():
        if cid in now:
            continue
        sel = selections.get(was["test"])
        item = {"id": cid, "test": was["name"], "a": was["a"], "b": was["b"]}
        if sel is None or not sel["complete"]:
            unchecked.append(item)
            continue
        side_b = sel["a"] if sel["b"] is None else sel["b"]
        still = (was["a"] in sel["a"] and was["b"] in side_b) or (was["b"] in sel["a"] and was["a"] in side_b)
        (resolved if still else unchecked).append(item)
    return {"new": new, "new_ids": set(new), "resolved": resolved, "no_longer_checked": unchecked, "first": False}
