"""Coordination requirements: the project's own rules for checking, triage and fixing, in one reusable file.

Design: docs/requirements.md. In short:
- a requirements file (`orca-requirements/1`, JSON) names a design level (L1-L5, industry-neutral), a strictness
  (lenient ... exacting), groups of elements (by team, class, system or file, never by GlobalId, so a file works on
  other projects), a matrix of checks between groups, who moves (and how far, and whether trims are allowed),
  class pairs declared by design, and guidance for Muse Spark;
- it compiles into what ORCA already runs: detection tests, triage rules and prompt lines, the fix agent's clearance,
  limits and prompt lines. Level and strictness only ever turn into numbers, through the tables below;
- Muse Spark stays in the loop: it still reads every clash no rule settles and proposes every fix, told the
  requirements; it audits the by-design rules; where editing is not allowed it recommends instead;
- no requirements (no header) is today's behaviour exactly.

A page registers its file (`register`, content-addressed) and sends the id with every request
(`X-Sightline-Requirements`); `enter` puts it in a context variable that `owner.spawn` / `owner.submit` carry into
stream workers and model-call pools.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import re
import threading
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import ifcopenshell.util.element
import ifcopenshell.util.system

FORMAT = "orca-requirements/1"
HEADER = "x-sightline-requirements"
MAX_BYTES = 64 * 1024
MAX_GUIDANCE = 1000
PROMPT = Path(__file__).parent / "domain_packs" / "requirements.md"

ROLES = ("structure", "services", "architecture", "equipment", "site", "other")
CHECKS = ("hard", "clearance", "off")
EDITS = ("any", "move", "none")          # most to least allowed
RULE_KEYS = ("same_element", "connected", "assembly", "host")
STRICTNESS_ORDER = ("lenient", "relaxed", "balanced", "strict", "exacting")
TEAM_ROLE = {"Structure": "structure", "MEP": "services", "Architecture": "architecture", "Site": "site"}

# Design levels: how mature the models are. Base numbers; strictness scales them.
LEVELS: dict[int, dict] = {
    1: {"name": "Concept", "meaning": "Massing and zones. Only gross overlaps matter; small parts are not modelled yet.",
        "hints": ["RIBA 2", "LOD 100", "Concept"], "tolerance_mm": 50, "min_size_mm": 300,
        "service_clearance_mm": 0, "edits": "move"},
    2: {"name": "Developed", "meaning": "Main systems and primary structure in place; branches and small items still move.",
        "hints": ["RIBA 3", "LOD 200", "EVT"], "tolerance_mm": 10, "min_size_mm": 100,
        "service_clearance_mm": 0, "edits": "any"},
    3: {"name": "Coordinated", "meaning": "Everything modelled to its real size and place: clashes are judged as built.",
        "hints": ["RIBA 4", "LOD 300", "DVT"], "tolerance_mm": 1, "min_size_mm": 0,
        "service_clearance_mm": 0, "edits": "any"},
    4: {"name": "Production", "meaning": "Ready to fabricate and install: the space around services (insulation, hangers, access) matters too.",
        "hints": ["RIBA 5", "LOD 400", "PVT"], "tolerance_mm": 1, "min_size_mm": 0,
        "service_clearance_mm": 25, "edits": "any"},
    5: {"name": "As-built", "meaning": "A record of what was built: check and report; ORCA recommends, it does not edit.",
        "hints": ["RIBA 6-7", "LOD 500", "In service"], "tolerance_mm": 1, "min_size_mm": 0,
        "service_clearance_mm": 25, "edits": "none"},
}

# Strictness covers flagging and fixing: strict flags more and fixes cautiously (more clearance, smaller moves, no
# trims); lenient flags less and allows bolder fixes. "balanced" at L3 is today's behaviour.
STRICTNESS: dict[str, dict] = {
    "lenient": {"name": "Lenient", "meaning": "Flag only clear problems; allow bold fixes.", "tolerance_x": 10,
                "clearance_x": 0, "min_size_x": 2, "fix_clearance_mm": 10, "max_move_mm": None, "trims": "yes",
                "lean": "by_design", "dispute_below": None},
    "relaxed": {"name": "Relaxed", "meaning": "Flag most problems; fixes may be generous.", "tolerance_x": 4,
                "clearance_x": 0.5, "min_size_x": 1.5, "fix_clearance_mm": 15, "max_move_mm": None, "trims": "yes",
                "lean": "by_design", "dispute_below": None},
    "balanced": {"name": "Balanced", "meaning": "ORCA's defaults.", "tolerance_x": 1, "clearance_x": 1,
                 "min_size_x": 1, "fix_clearance_mm": 25, "max_move_mm": None, "trims": "yes", "lean": None,
                 "dispute_below": None},
    "strict": {"name": "Strict", "meaning": "Hold to the standard: flag more, fix cautiously.", "tolerance_x": 0.5,
               "clearance_x": 1, "min_size_x": 0.5, "fix_clearance_mm": 40, "max_move_mm": 400, "trims": "cleanup",
               "lean": "real_clash", "dispute_below": 0.6},
    "exacting": {"name": "Exacting", "meaning": "Nothing slips: the tightest checks, the smallest fixes, no trims.",
                 "tolerance_x": 0.25, "clearance_x": 1.5, "min_size_x": 0, "fix_clearance_mm": 50, "max_move_mm": 300,
                 "trims": "no", "lean": "real_clash", "dispute_below": 0.8},
}
MIN_TOLERANCE_MM, MAX_TOLERANCE_MM = 1.0, 200.0
MAX_CLEARANCE_MM = 500.0

LEAN_TEXT = {"by_design": "When you are unsure whether a clash is real or by design, call it by_design.",
             "real_clash": "When you are unsure whether a clash is real or by design, call it real_clash: a person "
                           "will look."}
TRIM_TEXT = {"yes": "trims allowed", "cleanup": "trims only to tidy a joint within one model", "no": "no trims"}


# ------------------------------------------------------------------------------------------------- the document

@dataclass
class Group:
    id: str
    name: str
    role: str = "other"
    teams: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    exclude_classes: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    source: str = "user"


@dataclass
class Check:
    a: str
    b: str | None              # None: the group against itself
    check: str = "hard"
    clearance_mm: float | None = None
    tolerance_mm: float | None = None
    reason: str = ""
    source: str = "user"


@dataclass
class Mover:
    group: str
    edits: str = "any"
    max_move_mm: float | None = None
    trims: bool = True


@dataclass
class ByDesign:
    a_classes: list[str]
    b_classes: list[str]
    reason: str = ""
    source: str = "user"


PEN_RULES = ("allowed", "review", "never")
PEN_REVIEWERS = ("structure", "architecture", "fire", "safety", "services")


@dataclass
class PenRule:
    """Whether a group's elements may take an opening for a service (docs/edits.md "Which hosts"): wins over Muse's
    reading of the kind of host, never over the hard rules."""
    group: str
    rule: str = "review"            # allowed | review | never
    max_mm: float | None = None     # the largest opening, any side or diameter
    reviewer: str | None = None     # who reviews one: structure, architecture, fire, safety, services
    reason: str = ""
    source: str = "user"            # user | orca (added from Muse's reading)


@dataclass
class Doc:
    name: str = "Coordination requirements"
    version: int = 1
    level: int = 3
    strictness: str = "balanced"
    groups: list[Group] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    duplicates: bool = True
    rules: dict[str, bool] = field(default_factory=lambda: {k: True for k in RULE_KEYS})
    who_moves: list[Mover] = field(default_factory=list)
    by_design: list[ByDesign] = field(default_factory=list)
    guidance: dict[str, str] = field(default_factory=lambda: {"triage": "", "fixes": ""})
    notes: str = ""
    penetrations: list[PenRule] = field(default_factory=list)

    def group(self, gid: str) -> Group | None:
        return next((g for g in self.groups if g.id == gid), None)

    def to_dict(self) -> dict:
        d = {"format": FORMAT, **asdict(self)}
        if not self.penetrations:   # a file without the section keeps its id (content-addressed: docs/requirements.md)
            d.pop("penetrations")
        return d


_CLASS = re.compile(r"^Ifc[A-Za-z0-9]{2,60}$")
_ID = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    return _ID.sub("-", (text or "").lower()).strip("-")[:40] or "group"


def _text(v: Any, limit: int = 200) -> str:
    return str(v or "").strip()[:limit]


def _names(v: Any, limit: int = 60, pattern: re.Pattern | None = None) -> list[str]:
    out = []
    for x in (v if isinstance(v, list) else []):
        s = _text(x, 120)
        if s and (pattern is None or pattern.match(s)) and s not in out:
            out.append(s)
    return out[:limit]


def _num(v: Any, lo: float, hi: float) -> float | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return round(min(max(x, lo), hi), 3)


def parse(data: Any, classes: set[str] | None = None, teams: set[str] | None = None) -> Doc:
    """A requirements file from JSON, validated and normalised: unknown fields are dropped, numbers clamped, groups
    that a check or mover names must exist. With `classes` / `teams` (what the open models contain), names they don't
    contain are dropped too (a Muse draft must not invent classes)."""
    if not isinstance(data, dict):
        raise ValueError("requirements must be a JSON object")
    fmt = data.get("format", FORMAT)
    if fmt != FORMAT:
        raise ValueError(f"not an ORCA requirements file (format {fmt!r}, expected {FORMAT!r})")
    level = int(_num(data.get("level", 3), 1, 5) or 3)
    strictness = data.get("strictness") if data.get("strictness") in STRICTNESS else "balanced"
    cls_ok = (lambda c: c in classes) if classes is not None else (lambda c: True)
    groups: list[Group] = []
    for g in data.get("groups") or []:
        if not isinstance(g, dict):
            continue
        sel = g.get("select") if isinstance(g.get("select"), dict) else g
        gid = slug(g.get("id") or g.get("name") or "")
        while any(x.id == gid for x in groups):
            gid += "-2"
        grp = Group(id=gid, name=_text(g.get("name") or gid, 60), role=g.get("role") if g.get("role") in ROLES else "other",
                    teams=[t for t in _names(sel.get("teams")) if teams is None or t in teams],
                    classes=[c for c in _names(sel.get("classes"), 200, _CLASS) if cls_ok(c)],
                    exclude_classes=_names(sel.get("exclude_classes"), 60, _CLASS),
                    systems=_names(sel.get("systems")), files=_names(sel.get("files")),
                    source=g.get("source") if g.get("source") in ("orca", "user", "level") else "user")
        if not (grp.teams or grp.classes or grp.systems or grp.files):
            continue  # selects nothing in particular: a group of everything belongs nowhere in a matrix
        groups.append(grp)
        if len(groups) >= 24:
            break
    ids = {g.id for g in groups}
    checks: list[Check] = []
    seen: set[frozenset] = set()
    for c in data.get("checks") or []:
        if not isinstance(c, dict):
            continue
        a, b = slug(c.get("a") or ""), (slug(c["b"]) if c.get("b") else None)
        if a not in ids or (b is not None and b not in ids):
            continue
        if b == a:
            b = None
        key = frozenset((a, b or a))
        if key in seen:
            continue
        seen.add(key)
        checks.append(Check(a=a, b=b, check=c.get("check") if c.get("check") in CHECKS else "hard",
                            clearance_mm=_num(c.get("clearance_mm"), 0, MAX_CLEARANCE_MM),
                            tolerance_mm=_num(c.get("tolerance_mm"), 0.5, MAX_TOLERANCE_MM),
                            reason=_text(c.get("reason"), 240),
                            source=c.get("source") if c.get("source") in ("orca", "user", "level") else "user"))
    movers: list[Mover] = []
    for m in data.get("who_moves") or []:
        if not isinstance(m, dict):
            continue
        gid = slug(m.get("group") or "")
        if gid not in ids or any(x.group == gid for x in movers):
            continue
        movers.append(Mover(group=gid, edits=m.get("edits") if m.get("edits") in EDITS else "any",
                            max_move_mm=_num(m.get("max_move_mm"), 0, 5000) or None,
                            trims=bool(m.get("trims", True))))
    rules = {k: bool((data.get("rules") or {}).get(k, True)) for k in RULE_KEYS}
    designs: list[ByDesign] = []
    for r in data.get("by_design") or []:
        if not isinstance(r, dict):
            continue
        a = [c for c in _names(r.get("a_classes"), 20, _CLASS) if cls_ok(c)]
        b = [c for c in _names(r.get("b_classes"), 20, _CLASS) if cls_ok(c)]
        if a and b:
            designs.append(ByDesign(a, b, _text(r.get("reason"), 240),
                                    r.get("source") if r.get("source") in ("orca", "user", "triage") else "user"))
        if len(designs) >= 40:
            break
    pens: list[PenRule] = []
    for r in data.get("penetrations") or []:
        if not isinstance(r, dict):
            continue
        gid = slug(r.get("group") or "")
        if gid not in ids or any(x.group == gid for x in pens):
            continue
        pens.append(PenRule(gid, r.get("rule") if r.get("rule") in PEN_RULES else "review",
                            _num(r.get("max_mm"), 10, 5000) or None,
                            r.get("reviewer") if r.get("reviewer") in PEN_REVIEWERS else None, _text(r.get("reason"), 240),
                            r.get("source") if r.get("source") in ("orca", "user") else "user"))
    guidance = data.get("guidance") if isinstance(data.get("guidance"), dict) else {}
    return Doc(name=_text(data.get("name") or "Coordination requirements", 80),
               version=int(_num(data.get("version", 1), 1, 10_000) or 1), level=level, strictness=strictness,
               groups=groups, checks=checks, duplicates=bool(data.get("duplicates", True)), rules=rules,
               who_moves=movers, by_design=designs,
               guidance={k: _text(guidance.get(k), MAX_GUIDANCE) for k in ("triage", "fixes")},
               notes=_text(data.get("notes"), 2000), penetrations=pens)


def canonical(doc: Doc) -> str:
    return json.dumps(doc.to_dict(), sort_keys=True, separators=(",", ":"))


def doc_id(doc: Doc) -> str:
    return hashlib.sha256(canonical(doc).encode()).hexdigest()[:16]


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def model_key(doc: Doc) -> str:
    """What changes the triage model's prompt (and the strictness overlay on its answers). Rules are not in it: adding
    a by-design rule never re-asks the model."""
    return _hash({"level": doc.level, "strictness": doc.strictness, "guidance": doc.guidance.get("triage", ""),
                  "checks": prompt_text(doc, "triage", rules=False)})


def rules_key(doc: Doc) -> str:
    return _hash([asdict(r) for r in doc.by_design])


# ------------------------------------------------------------------------------------------------- numbers

@dataclass
class Params:
    level: int
    level_name: str
    strictness: str
    strictness_name: str
    tolerance_mm: float
    min_size_mm: float
    service_clearance_mm: float
    clearance_x: float
    fix_clearance_mm: float
    max_move_mm: float | None
    trims: str               # "yes" | "cleanup" | "no"
    edits: str               # the level's ceiling: "any" | "move" | "none"
    lean: str | None
    dispute_below: float | None


def resolve(doc: Doc) -> Params:
    lv, st = LEVELS[doc.level], STRICTNESS[doc.strictness]
    tol = min(max(lv["tolerance_mm"] * st["tolerance_x"], MIN_TOLERANCE_MM), MAX_TOLERANCE_MM)
    return Params(level=doc.level, level_name=lv["name"], strictness=doc.strictness, strictness_name=st["name"],
                  tolerance_mm=round(tol, 2), min_size_mm=round(lv["min_size_mm"] * st["min_size_x"], 1),
                  service_clearance_mm=round(lv["service_clearance_mm"] * st["clearance_x"], 1),
                  clearance_x=st["clearance_x"], fix_clearance_mm=st["fix_clearance_mm"],
                  max_move_mm=st["max_move_mm"], trims=st["trims"], edits=lv["edits"], lean=st["lean"],
                  dispute_below=st["dispute_below"])


def scale() -> dict:
    """The levels and strictness steps, with what each sets at L3 / balanced, for the UI."""
    return {"levels": [{"level": n, **{k: v for k, v in lv.items()}} for n, lv in LEVELS.items()],
            "strictness": [{"id": k, **v} for k, v in STRICTNESS.items()], "format": FORMAT,
            "roles": list(ROLES), "checks": list(CHECKS), "edits": list(EDITS)}


def label(doc: Doc) -> str:
    return f"L{doc.level} {LEVELS[doc.level]['name']} · {STRICTNESS[doc.strictness]['name']}"


# ------------------------------------------------------------------------------------------------- registry and context

_registry: OrderedDict[str, Doc] = OrderedDict()
_registry_lock = threading.Lock()
REGISTRY_MAX = 500
_current: contextvars.ContextVar[tuple[str, Doc] | None] = contextvars.ContextVar("requirements", default=None)


def register(doc: Doc) -> str:
    rid = doc_id(doc)
    with _registry_lock:
        _registry[rid] = doc
        _registry.move_to_end(rid)
        while len(_registry) > REGISTRY_MAX:
            _registry.popitem(last=False)
    return rid


def lookup(rid: str) -> Doc | None:
    with _registry_lock:
        doc = _registry.get(rid)
        if doc is not None:
            _registry.move_to_end(rid)
        return doc


def enter(rid: str | None) -> contextvars.Token:
    doc = lookup(rid) if rid else None
    return _current.set((rid, doc) if doc is not None else None)


def leave(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> Doc | None:
    v = _current.get()
    return v[1] if v else None


def current_id() -> str | None:
    v = _current.get()
    return v[0] if v else None


class using:
    """`with requirements.using(rid):` for code that is not behind the middleware (MCP tool calls)."""

    def __init__(self, rid: str | None):
        self.rid = rid

    def __enter__(self):
        self.token = enter(self.rid)
        return current()

    def __exit__(self, *exc):
        leave(self.token)


# ------------------------------------------------------------------------------------------------- the open models

def _file_teams(scene) -> list[str]:
    """Team per open file, guessed from its content (`document.guess_team`, as detection does); cached on the scene."""
    cached = getattr(scene, "_req_teams", None)
    if cached is not None and len(cached) == len(scene.models):
        return cached
    from .document import guess_team
    boxes = scene.bounds()
    teams = [guess_team(Counter(e.is_a() for e in m.by_type("IfcElement") if e.GlobalId in boxes), p.name)
             for m, p in zip(scene.models, scene.paths)]
    scene._req_teams = teams
    return teams


def _family(cls: str) -> str:
    """For one model alone (a machine cell, a single discipline): what kind of thing a class is."""
    from .document import _class_team
    team = _class_team(cls)
    if team == "MEP":
        return "services"
    if team == "Structure" or cls in ("IfcMember", "IfcPlate", "IfcSlab", "IfcWall", "IfcWallStandardCase", "IfcRoof"):
        return "structure"
    if team == "Site":
        return "site"
    return "equipment"


FAMILY_NAME = {"structure": "Frame and structure", "services": "Services", "equipment": "Equipment and other",
               "site": "Site"}


def inventory(scene) -> dict:
    """What the open models contain, for a draft and for the panel: files with their team and top classes, systems,
    storeys, STEP groups, and the default groups (one per team; one per kind of thing when only one team is open)."""
    boxes = scene.bounds()
    teams = _file_teams(scene)
    files, all_classes, systems, storeys, step_groups = [], Counter(), Counter(), Counter(), Counter()
    for i, (m, p) in enumerate(zip(scene.models, scene.paths)):
        classes = Counter()
        for e in m.by_type("IfcElement"):
            if e.GlobalId not in boxes:
                continue
            classes[e.is_a()] += 1
            for s in ifcopenshell.util.system.get_element_systems(e):
                if s.Name:
                    systems[s.Name] += 1
            c = ifcopenshell.util.element.get_container(e)
            if c is not None and getattr(c, "Name", None):
                storeys[c.Name] += 1
            pset = ifcopenshell.util.element.get_pset(e, "ORCA_STEP") or ifcopenshell.util.element.get_pset(e, "Sightline_STEP")
            if pset and pset.get("Group"):
                step_groups[pset["Group"]] += 1
        all_classes.update(classes)
        files.append({"file": p.name, "team": teams[i], "elements": sum(classes.values()),
                      "classes": dict(classes.most_common(30))})
    return {"files": files, "classes": dict(all_classes), "systems": dict(systems.most_common(40)),
            "storeys": dict(storeys.most_common(30)), "step_groups": dict(step_groups.most_common(40)),
            "groups": [asdict(g) for g in default_groups(scene)]}


def default_groups(scene) -> list[Group]:
    teams = _file_teams(scene)
    present = list(dict.fromkeys(teams))
    if len(present) >= 2:
        order = {"Structure": 0, "Architecture": 1, "MEP": 2, "Site": 3}
        return [Group(id=slug(t), name=t, role=TEAM_ROLE.get(t, "other"), teams=[t], source="level")
                for t in sorted(present, key=lambda t: order.get(t, 9))]
    boxes = scene.bounds()
    fams: dict[str, set[str]] = {}
    for m in scene.models:
        for e in m.by_type("IfcElement"):
            if e.GlobalId in boxes:
                fams.setdefault(_family(e.is_a()), set()).add(e.is_a())
    order = ("structure", "services", "equipment", "site")
    return [Group(id=f, name=FAMILY_NAME[f], role=f, classes=sorted(fams[f]), source="level")
            for f in order if f in fams]


def default_doc(scene, name: str = "Coordination requirements") -> Doc:
    """L3 Coordinated, balanced: hard checks between every pair of groups and within each, Site off (as
    `detect.default_tests`), structure moves last and services first. Compiles to what ORCA checks today."""
    groups = default_groups(scene)
    only_site = all(g.role == "site" for g in groups)
    checks = []
    for i, g in enumerate(groups):
        for h in groups[i:]:
            off = not only_site and "site" in (g.role, h.role)
            checks.append(Check(a=g.id, b=None if h is g else h.id, check="off" if off else "hard",
                                reason="Site is context: listed, not checked by default" if off else "",
                                source="level"))
    rank = {"structure": 0, "architecture": 1, "site": 2, "equipment": 3, "other": 4, "services": 5}
    movers = [Mover(group=g.id) for g in sorted(groups, key=lambda g: rank.get(g.role, 4))]
    return Doc(name=name, groups=groups, checks=checks, who_moves=movers)


class Matcher:
    """Which group an element belongs to (the first that selects it), off the open models; cached per scene."""

    def __init__(self, scene, doc: Doc):
        self.scene, self.doc = scene, doc
        self.teams = _file_teams(scene)
        self._cache: dict[str, Group | None] = {}

    def group_of(self, gid: str) -> Group | None:
        if gid not in self._cache:
            self._cache[gid] = self._find(gid)
        return self._cache[gid]

    def _find(self, gid: str) -> Group | None:
        try:
            i = self.scene.index_of(gid)
        except KeyError:
            return None
        e = self.scene.models[i].by_guid(gid)
        name = self.scene.paths[i].name
        for g in self.doc.groups:
            if g.files and name not in g.files:
                continue
            if g.teams and self.teams[i] not in g.teams:
                continue
            if g.classes and not any(e.is_a(c) for c in g.classes):
                continue
            if g.exclude_classes and any(e.is_a(c) for c in g.exclude_classes):
                continue
            if g.systems and not ({s.Name for s in ifcopenshell.util.system.get_element_systems(e)} & set(g.systems)):
                continue
            return g
        return None


# ------------------------------------------------------------------------------------------------- detection

def compile_tests(doc: Doc, scene=None) -> list:
    """The detection tests a requirements file asks for: one per check cell that is not off (ids `req:a|b`,
    `req:a`), with the resolved tolerance, clearance and smallest element size, plus duplicates."""
    from . import detect
    p = resolve(doc)
    tests = []
    for c in doc.checks:
        if c.check == "off":
            continue
        ga, gb = doc.group(c.a), (doc.group(c.b) if c.b else None)
        if ga is None or (c.b and gb is None):
            continue
        tol = c.tolerance_mm if c.tolerance_mm is not None else p.tolerance_mm
        clearance = _cell_clearance(c, ga, gb, p)
        kind = "clearance" if clearance > 0 else "hard"
        name = f"{ga.name} vs {gb.name}" if gb else f"{ga.name} (within)"
        if kind == "clearance":
            name += f", {clearance:.0f} mm clearance"
        tests.append(detect.Test(
            id=f"req:{c.a}|{c.b}" if c.b else f"req:{c.a}", name=name, a=_selection(ga),
            b=_selection(gb) if gb else None, kind=kind, tolerance_m=tol / 1000, clearance_m=clearance / 1000,
            rules=dict(doc.rules), min_size_m=p.min_size_mm / 1000))
    if doc.duplicates:
        on = {g for c in doc.checks if c.check != "off" for g in (c.a, c.b) if g}
        groups = [g for g in doc.groups if g.id in on]
        sel = detect.Selection()
        if groups and len(groups) < len(doc.groups):  # some groups are off (Site): duplicates in the rest only
            sel = _union(groups)
        tests.append(detect.Test(id="req:duplicates", name="Duplicates", a=sel, kind="duplicate",
                                 tolerance_m=detect.DUPLICATE_M, rules=dict(doc.rules)))
    return tests


def _cell_clearance(c: Check, ga: Group, gb: Group | None, p: Params) -> float:
    """Millimetres of clearance a check cell asks for (0: a hard check). A clearance cell's own figure (25 mm when
    unset) scaled by strictness; at L4 and L5 a hard check between services and structure gets the level's."""
    if c.check == "clearance":
        return (c.clearance_mm if c.clearance_mm is not None else 25.0) * p.clearance_x
    if c.check == "hard" and gb is not None and {ga.role, gb.role} == {"services", "structure"}:
        return p.service_clearance_mm
    return 0.0


def _selection(g: Group):
    from . import detect
    return detect.Selection(files=list(g.files), teams=list(g.teams), classes=list(g.classes),
                            exclude_classes=list(g.exclude_classes), systems=list(g.systems))


def _union(groups: list[Group]):
    """Duplicates over several groups: one selection when they select the same way (teams or classes)."""
    from . import detect
    if all(g.teams and not (g.classes or g.systems or g.files) for g in groups):
        return detect.Selection(teams=sorted({t for g in groups for t in g.teams}))
    if all(g.classes and not (g.teams or g.systems or g.files) for g in groups):
        return detect.Selection(classes=sorted({c for g in groups for c in g.classes}))
    return detect.Selection()


# ------------------------------------------------------------------------------------------------- fixes

@dataclass
class Policy:
    group: str | None
    group_name: str
    edits: str               # "any" | "move" | "none"
    max_move_m: float | None
    trims: str               # "yes" | "cleanup" | "no"


def _stricter(a: str, b: str, order: tuple) -> str:
    return a if order.index(a) >= order.index(b) else b


def policy(doc: Doc, matcher: Matcher, gid: str) -> Policy:
    """What the requirements allow on one element: the level's ceiling and strictness, and its group's mover row,
    whichever is stricter."""
    p = resolve(doc)
    g = matcher.group_of(gid)
    row = next((m for m in doc.who_moves if g and m.group == g.id), None)
    edits = p.edits if row is None else _stricter(p.edits, row.edits, EDITS)
    caps = [x for x in (p.max_move_mm, row.max_move_mm if row else None) if x]
    trims = p.trims if (row is None or row.trims) else "no"
    return Policy(g.id if g else None, g.name if g else "ungrouped elements", edits,
                  min(caps) / 1000 if caps else None, trims)


def fix_clearance(doc: Doc, matcher: Matcher, a: str, b: str) -> float:
    """Metres a fix must clear by: strictness's fix clearance, or the pair's clearance check if larger."""
    p = resolve(doc)
    need = float(p.fix_clearance_mm)
    ga, gb = matcher.group_of(a), matcher.group_of(b)
    if ga is not None and gb is not None:
        for c in doc.checks:
            if c.check != "off" and {c.a, c.b or c.a} == {ga.id, gb.id}:
                other = doc.group(c.b) if c.b else None
                need = max(need, _cell_clearance(c, doc.group(c.a), other, p))
    return need / 1000


# Kinds whose change has a size the "largest move" limit applies to: how far any part of the element goes.
SIZED = ("move", "offset", "route", "resize")


def change_size(kind: str, delta_m: list[float]) -> float:
    """How far a fix takes the element, metres: the length of its move, or of an offset's (vertical or lateral) shift."""
    return sum(float(d) * float(d) for d in (delta_m or [])) ** 0.5


def blocked(pol_a: Policy, pol_b: Policy | None, kind: str, delta_m: list[float], same_model: bool) -> str | None:
    """Why the requirements forbid a candidate on the element with policy `pol_a`, or None. Said so Muse can avoid
    it next round."""
    kind = kind or "move"
    if pol_a.edits == "none":
        return f"blocked by requirements: {pol_a.group_name} may not be edited"
    if pol_a.edits == "move" and kind not in ("move", "penetration"):   # a penetration only asks: the service stays
        return f"blocked by requirements: {pol_a.group_name} may only be moved whole (no {kind}s)"
    if kind == "trim":
        if pol_a.trims == "no":
            return f"blocked by requirements: no trims on {pol_a.group_name}"
        if pol_a.trims == "cleanup" and not same_model:
            return "blocked by requirements: trims only tidy a joint within one model"
    if pol_a.max_move_m and kind in SIZED:
        size = change_size(kind, delta_m)
        if size > pol_a.max_move_m + 1e-6:
            return (f"blocked by requirements: {size * 1000:.0f} mm is more than the {pol_a.max_move_m * 1000:.0f} mm "
                    f"a fix may move {pol_a.group_name}")
    return None


@dataclass
class PenAnswer:
    rule: str
    max_mm: float | None
    reviewer: str | None
    group_name: str


def penetration_rule(doc: Doc, matcher: Matcher, gid: str) -> PenAnswer | None:
    """The requirements' penetration rule for the group `gid` is in, or None."""
    g = matcher.group_of(gid)
    r = next((x for x in doc.penetrations if g and x.group == g.id), None)
    return PenAnswer(r.rule, r.max_mm, r.reviewer, g.name) if r else None


def can_cut(pol: Policy | None) -> bool:
    """Whether a penetration's opening may be cut in its host (else only the provision for void is written): no
    requirements, or the host's group may be edited in any way."""
    return pol is None or pol.edits == "any"


def meets(doc: Doc, pol: Policy, other: Policy, clearance_m: float, min_clearance_m: float | None,
          delta_m: list[float], kind: str) -> list[str]:
    """Which requirements a verified option meets, in plain words, from the geometry check and the policy."""
    out = []
    need = clearance_m * 1000
    if min_clearance_m is None:
        out.append(f"clear of everything by more than {need:.0f} mm ({STRICTNESS[doc.strictness]['name']})")
    else:
        out.append(f"nearest {min_clearance_m * 1000:.0f} mm ≥ {need:.0f} mm required ({STRICTNESS[doc.strictness]['name']})")
    if kind == "penetration":   # `pol` is the service's, `other` the host's
        out.append(f"opening cut in {other.group_name}, which may be edited" if other.edits == "any" else
                   f"provision for void only: {other.group_name} may not be edited, so its team cuts the opening")
    elif pol.group_name and other.group_name and pol.group != other.group:
        out.append(f"edits {pol.group_name} only; {other.group_name} untouched")
    if pol.max_move_m and (kind or "move") in SIZED:
        size = change_size(kind, delta_m)
        out.append(f"{size * 1000:.0f} mm within the {pol.max_move_m * 1000:.0f} mm limit")
    return out


# ------------------------------------------------------------------------------------------------- triage

def settle(doc: Doc, clash) -> dict | None:
    """A clash a by-design rule covers: the settled verdict, saying which rule and why. No model call."""
    from .triage import not_a_clash
    a, b = clash.a.ifc_class or "", clash.b.ifc_class or ""
    for i, r in enumerate(doc.by_design):
        if (a in r.a_classes and b in r.b_classes) or (b in r.a_classes and a in r.b_classes):
            why = f" ({r.reason})" if r.reason else ""
            v = not_a_clash("requirement",
                            f"Not a clash under the project requirements: {clash.a.name or a} with {clash.b.name or b} "
                            f"is declared by design{why}.",
                            f"Requirements rule: {_pair_text(r)} is by design. Remove the rule to have it read again.")
            return {**v, "rule": i}
    return None


def _pair_text(r: ByDesign) -> str:
    def side(cs):
        return " / ".join(c.removeprefix("Ifc") for c in cs)
    return f"{side(r.a_classes)} with {side(r.b_classes)}"


def overlay(doc: Doc, verdict: dict) -> dict:
    """Strict and exacting: a model's low-confidence "by design" is not trusted to set a clash aside; it becomes a
    real clash for a person to look at, with the model's reading kept. Deterministic given the model's answer."""
    p = resolve(doc)
    if (p.dispute_below is None or verdict.get("source") != "model" or verdict.get("verdict") != "by_design"
            or float(verdict.get("confidence") or 0) >= p.dispute_below):
        return verdict
    return {**verdict, "verdict": "real_clash", "severity": verdict.get("severity") if verdict.get("severity") not in (None, "none") else "low",
            "basis": "strictness", "model_verdict": "by_design",
            "understanding": f"{verdict.get('understanding', '')} (Read as by design with confidence "
                             f"{float(verdict.get('confidence') or 0):.2f}, under {STRICTNESS[doc.strictness]['name']}'s "
                             f"{p.dispute_below:.1f}: kept for a person to check.)".strip()}


# ------------------------------------------------------------------------------------------------- prompts

def prompt_text(doc: Doc, role: str, rules: bool = True) -> str:
    """Lines added to Muse Spark's system prompt: "triage" or "fixes". Only what differs from ORCA's defaults is said
    (L3 balanced with no rules or guidance says nothing to triage): a requirement that only restates the defaults
    must not move the model's verdicts (measured: "every hard clash matters" turned 12 model errors into 80)."""
    p = resolve(doc)
    lv = LEVELS[doc.level]
    lines: list[str] = []
    if doc.level != 3:
        lines.append(f"- Design level L{doc.level} {lv['name']}: {lv['meaning']}")
    if p.lean:
        lines.append(f"- Strictness {p.strictness_name}: {LEAN_TEXT[p.lean]}")
    cells = [t.name for t in compile_tests(doc) if t.kind == "clearance"]
    names = {g.id: g.name for g in doc.groups}
    if role == "triage":
        if p.tolerance_mm != 1 or p.min_size_mm:
            lines.append(f"- Hard clashes count from {p.tolerance_mm:g} mm of overlap"
                         + (f"; elements smaller than {p.min_size_mm:.0f} mm are not checked" if p.min_size_mm else "") + ".")
        if cells:
            lines.append("- Clearance checks (a gap that must stay): " + "; ".join(cells) + ".")
        if rules and doc.by_design:
            lines.append("- Declared by design: " + "; ".join(_pair_text(r) + (f" ({r.reason})" if r.reason else "")
                                                             for r in doc.by_design) + ".")
    else:
        if doc.strictness != "balanced":
            lines.append(f"- A fix must clear everything by at least {p.fix_clearance_mm:.0f} mm"
                         + (f" and move nothing more than {p.max_move_mm:.0f} mm" if p.max_move_mm else "")
                         + f"; {TRIM_TEXT[p.trims]}.")
        if cells:
            lines.append("- Clearance checks (a gap that must stay): " + "; ".join(cells) + ".")
        if doc.who_moves:
            order = [names.get(m.group, m.group) for m in doc.who_moves]
            if len(order) > 1:
                lines.append(f"- Who moves: {order[0]} stays put the most"
                             + (f", then {', '.join(order[1:-1])}" if len(order) > 2 else "") + f"; {order[-1]} moves first.")
        limits = []
        for m in doc.who_moves:
            n = names.get(m.group, m.group)
            if m.edits == "none":
                limits.append(f"{n} may not be edited")
            elif m.edits == "move":
                limits.append(f"{n} may only be moved whole")
            if m.max_move_mm:
                limits.append(f"{n} moves at most {m.max_move_mm:.0f} mm")
            if not m.trims:
                limits.append(f"no trims on {n}")
        if p.edits == "move":
            limits.append("at this level fixes are whole moves only")
        if limits:
            lines.append("- Limits: " + "; ".join(limits) + ".")
        if doc.penetrations:
            lines.append("- Openings for services: " + "; ".join(
                f"{names.get(r.group, r.group)} " + {"allowed": "may take them", "review": "may take them, reviewed",
                                                     "never": "never takes one"}[r.rule]
                + (f" up to {r.max_mm:.0f} mm" if r.max_mm and r.rule != "never" else "")
                + (f" by {r.reviewer}" if r.reviewer and r.rule != "never" else "") for r in doc.penetrations) + ".")
    text = doc.guidance.get(role, "").strip()
    if text:
        lines.append(f"- The team's guidance: {text}")
    if not lines:
        return ""
    return "\n".join(["", "Project coordination requirements (the team's settings; apply them where they bear on a clash):",
                      *lines])


RECOMMEND = ("\n\nThe project requirements do not allow ORCA to edit the model for this clash ({why}). Nothing you "
             "propose will be applied or tried: give your best fixes as recommendations for the designer, best "
             "first, with the numbers they would need, and say in advice who should make the change.")


# ------------------------------------------------------------------------------------------------- the Muse draft

SUGGEST_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "groups", "checks", "who_moves", "by_design", "guidance"],
    "properties": {
        "summary": {"type": "string"},
        "groups": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "name", "role", "teams", "classes", "reason"],
            "properties": {"id": {"type": "string"}, "name": {"type": "string"},
                           "role": {"type": "string", "enum": list(ROLES)},
                           "teams": {"type": "array", "items": {"type": "string"}},
                           "classes": {"type": "array", "items": {"type": "string"}},
                           "reason": {"type": "string"}}}},
        "checks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["a", "b", "check", "clearance_mm", "reason"],
            "properties": {"a": {"type": "string"}, "b": {"type": "string"},
                           "check": {"type": "string", "enum": list(CHECKS)},
                           "clearance_mm": {"type": "number"}, "reason": {"type": "string"}}}},
        "who_moves": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["group", "edits", "max_move_mm", "trims"],
            "properties": {"group": {"type": "string"}, "edits": {"type": "string", "enum": list(EDITS)},
                           "max_move_mm": {"type": "number"}, "trims": {"type": "boolean"}}}},
        "by_design": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["a_classes", "b_classes", "reason"],
            "properties": {"a_classes": {"type": "array", "items": {"type": "string"}},
                           "b_classes": {"type": "array", "items": {"type": "string"}},
                           "reason": {"type": "string"}}}},
        "guidance": {"type": "object", "additionalProperties": False, "required": ["triage", "fixes"],
                     "properties": {"triage": {"type": "string"}, "fixes": {"type": "string"}}},
    },
}


def suggest(model, inv: dict, level: int, strictness: str, name: str = "Coordination requirements") -> tuple[Doc, str]:
    """One Muse Spark call: a draft from what the models contain, at the chosen level and strictness. Everything it
    returns is marked "orca" and validated against the inventory (no invented classes or teams)."""
    level = level if level in LEVELS else 3
    strictness = strictness if strictness in STRICTNESS else "balanced"
    facts = {"level": {"level": level, **{k: LEVELS[level][k] for k in ("name", "meaning")}},
             "strictness": {"id": strictness, **{k: STRICTNESS[strictness][k] for k in ("name", "meaning")}},
             "files": inv.get("files", []), "systems": inv.get("systems", {}), "storeys": inv.get("storeys", {}),
             "step_groups": inv.get("step_groups", {}), "default_groups": inv.get("groups", [])}
    reply = model.complete_json(PROMPT.read_text(), json.dumps(facts, indent=1), [], schema=SUGGEST_SCHEMA)
    for g in reply.get("groups", []):
        g["source"] = "orca"
    checks = []
    for c in reply.get("checks", []):
        checks.append({**c, "b": c.get("b") or None, "source": "orca",
                       "clearance_mm": c.get("clearance_mm") if c.get("check") == "clearance" else None})
    movers = [{**m, "max_move_mm": m.get("max_move_mm") or None} for m in reply.get("who_moves", [])]
    data = {"format": FORMAT, "name": name, "level": level, "strictness": strictness, "groups": reply.get("groups", []),
            "checks": checks, "who_moves": movers,
            "by_design": [{**r, "source": "orca"} for r in reply.get("by_design", [])],
            "guidance": reply.get("guidance", {})}
    teams = {f["team"] for f in inv.get("files", [])}
    doc = parse(data, classes=set(inv.get("classes", {})), teams=teams)
    if not doc.groups:  # a reply with nothing usable: keep the default groups, so the draft is never empty
        doc.groups = [Group(**{**g, "source": "level"}) for g in inv.get("groups", [])]
    return doc, str(reply.get("summary", ""))[:600]
