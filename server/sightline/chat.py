"""Chat with Muse Spark over the open clash report and model, through tools.

The tools are the same operations the web API and the MCP server use (`service.Workspace`), so the chat can do
what the UI can: list and read clashes, look at their Navisworks images, describe and find elements, measure, find
openings, check a move or an offset, and propose verified fixes. Two tools act on the browser instead
(`show_clash`, `set_view`, `set_filters`, `clear_filters`): they come back as "ui" events for the page to carry out.

Every step is reported through `emit` as it happens, so the UI can show the agent working:
    {"type": "thinking"}                          a model call started
    {"type": "tool", "name", "args"}              the model called a tool
    {"type": "tool_result", "name", "summary"}    what it got back, in one line
    {"type": "ui", "action", ...}                 something for the page to do (select a clash, change the view)
    {"type": "proposal", "clash_id", ...}         verified fixes from propose_fixes, for the options panel
    {"type": "message", "text"}                   the answer
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from collections import Counter, OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import checks, context_planner, domains, edits, faces, facets, journal, manual, plans, property_edits, settings
from .meta_client import ToolModel, image_part
from .service import Workspace
from .limits import env_int

MAX_STEPS = env_int("SIGHTLINE_CHAT_MAX_STEPS", 8)       # model calls per user message
MAX_SESSIONS = env_int("SIGHTLINE_CHAT_SESSIONS", 200)
MAX_HISTORY = env_int("SIGHTLINE_CHAT_HISTORY", 40)      # messages kept per session (oldest dropped first, the system prompt stays)
NOT_PHYSICAL = {"IfcSpace", "IfcDistributionPort", "IfcOpeningElement", "IfcVirtualElement", "IfcZone"}


def _fn(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or []}}}


_SIDE = {"type": "object", "description": "what one side takes: a filter the user made, by name ({\"filter\": name}), "
         "everything the user's filters show together ({\"shown\": true}: the filtered items, as on their screen), or "
         "elements described as in set_filters (classes, levels, models, where, invert); b may instead be "
         "{\"everything\": true} (the default: the models the full check covers) or {\"itself\": true}", "properties": {
    "filter": {"type": "string", "description": "one of the user's filters, by the name [context] gives"},
    "classes": {"type": "array", "items": {"type": "string"}}, "levels": {"type": "array", "items": {"type": "string"}},
    "models": {"type": "array", "items": {"type": "string"}},
    "where": {"type": "array", "items": {"type": "object", "properties": {
        "property": {"type": "string"}, "set": {"type": "string"},
        "op": {"type": "string", "enum": ["is", "is_not", "contains", "has", "missing", "less", "more", "between"]},
        "values": {"type": "array", "items": {"type": "string"}}, "min": {"type": "number"}, "max": {"type": "number"}},
        "required": ["property"]}},
    "invert": {"type": "boolean"}, "everything": {"type": "boolean"}, "itself": {"type": "boolean"},
    "shown": {"type": "boolean"}}}


TOOLS = [
    _fn('explore_wider_fix', 'Explore a complete coordinated arrangement for one clash, including surrounding '
        'elements when needed. Use when the user asks to move other objects or a single-element fix is blocked. '
        'Costs three proposal units; shows whole proposals for designer review. You cannot accept them.',
        {'clash_id': {'type': 'string'}}, ['clash_id']),
    _fn("detect_clashes", "Find the clashes in the open models with ORCA's own detection, no Navisworks report "
        "needed: every pair of models and each model against itself (hard clashes deeper than the tolerance, 1 mm by "
        "default) and duplicates. Pairs meant to meet (joined by ports, one assembly, a door in its wall) and touches "
        "are counted, not reported. Takes about 10 s. ORCA keeps the latest result of each check (the open models, and "
        "each check of some elements): running one again replaces only its clashes and says which were resolved since "
        "its last run. The user's clash list holds every kept check's clashes; a clash two checks find is one clash "
        "with one #N. Each run counts against the demo's detection runs. To check only some elements, give a (and b): "
        "one check of what A takes against what B takes (everything the full check covers, by default, or itself). "
        "To run a kept check again, give check (its name), or \"all\" for every kept check.",
        {"check": {"type": "string", "description": "a kept check's name to run it again, or \"all\""},
         "tolerance_mm": {"type": "number", "description": "hard clash tolerance in mm (default 1)"},
         "a": _SIDE, "b": _SIDE,
         "kind": {"type": "string", "enum": ["hard", "clearance", "duplicate"], "description": "with a: the kind of check"},
         "clearance_mm": {"type": "number", "description": "for a clearance check: report gaps under this"},
         "name": {"type": "string", "description": "a name for the check"}}),
    _fn("report_summary", "Counts for the open clash report: clashes per test and per element class pair, how many "
        "are found in the open model, how many are fixed. Start here for questions about the whole report."),
    _fn("list_clashes", "List clashes in the report, optionally filtered. Returns at most `limit` rows.", {
        "query": {"type": "string", "description": "words to match in names, classes, levels, test names"},
        "test": {"type": "string", "description": "exact clash test name"},
        "check": {"type": "string", "description": "only the clashes this kept check found (its name)"},
        "in_model_only": {"type": "boolean", "description": "only clashes whose two elements are in the open model"},
        "limit": {"type": "integer"}}),
    _fn("get_clash", "Everything about one clash: both elements, Navisworks distance, clash point, whether it is in "
        "the open model and fixed.", {"clash_id": {"type": "string"}}, ["clash_id"]),
    _fn("look_at_clash_images", "Attach the clash's Navisworks images (A: the pair, B: with context, C: second "
        "angle) so you can see it. Element A is red, element B green.", {"clash_id": {"type": "string"}}, ["clash_id"]),
    _fn("measure_clash", "ORCA's own geometry measure of a clash (signed distance, metres; negative = overlap).",
        {"clash_id": {"type": "string"}}, ["clash_id"]),
    _fn("describe_element", "An element of the open model: class, name, tag, level, file, what it is linked to by kind "
        "(joints, assembly, hosted, what it rests on and supports, contacts), its systems, and for a straight "
        "duct/pipe/tray segment its run (start, end, length, profile).", {"global_id": {"type": "string"}},
        ["global_id"]),
    _fn("find_elements", "Search the open model's elements by words in their name, tag or class.", {
        "query": {"type": "string"}, "ifc_class": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
    _fn("find_openings", "Openings through `obstacle` on the line of the straight segment `element`, with the "
        "offset heights (dz, metres) that pass the segment through each with the required clearance (25 mm unless the "
        "requirements ask for more).",
        {"element": {"type": "string"}, "obstacle": {"type": "string"}}, ["element", "obstacle"]),
    _fn("check_move", "Check moving elements by [dx, dy, dz] metres (Z up) against the whole model, without keeping it. "
        "The move keeps their joints (fittings beyond go along, a segment it runs along gets longer or shorter) or "
        "fails with the reason. Give `obstacle` (the element the move must clear) to check it as a proposal is: then "
        "what the moved elements stand on (a slab, a plinth) may stay as it was, and lifting them off it fails.",
        {"global_ids": {"type": "array", "items": {"type": "string"}},
         "delta_m": {"type": "array", "items": {"type": "number"}},
         "obstacle": {"type": "string"}}, ["global_ids", "delta_m"]),
    _fn("check_offset", "Check a local offset without keeping it: split the straight segment `element` at two points "
        "(metres along it from its start) around `obstacle` and raise (+) or lower (-) the middle by dz_m.",
        {"element": {"type": "string"}, "obstacle": {"type": "string"},
         "split_m": {"type": "array", "items": {"type": "number"}}, "dz_m": {"type": "number"}},
        ["element", "obstacle", "split_m", "dz_m"]),
    _fn("check_route", "Check a route without keeping it: hold stretches of the straight segment `element` at offsets "
        "(steps: from_m/to_m metres along it, up_m and side_m metres on its own axes: up, and side to the left of its "
        "direction seen from above), with 90° bends, past `obstacle`. Each change is one axis at a time.",
        {"element": {"type": "string"}, "obstacle": {"type": "string"},
         "steps": {"type": "array", "items": {"type": "object", "properties": {
             "from_m": {"type": "number"}, "to_m": {"type": "number"}, "up_m": {"type": "number"},
             "side_m": {"type": "number"}}, "required": ["from_m", "to_m"]}}}, ["element", "obstacle", "steps"]),
    _fn("check_resize", "Check a flatter section for a stretch of the straight rectangular duct or cable tray `element` "
        "past `obstacle` without keeping it: from split_m[0] to split_m[1] (metres along it) it becomes depth_m deep "
        "and as wide as keeps its equivalent diameter (a duct, at most 4:1) or its cross-section (a tray), with the "
        "`keep` face (bottom, top or centre) level and transitions either side.",
        {"element": {"type": "string"}, "obstacle": {"type": "string"},
         "split_m": {"type": "array", "items": {"type": "number"}}, "depth_m": {"type": "number"},
         "keep": {"type": "string", "enum": ["bottom", "top", "centre"]}}, ["element", "obstacle", "split_m", "depth_m"]),
    _fn("check_penetration", "Check an opening for the straight service `element` through the wall or slab `host` "
        "without keeping it: sized from the service with the clearance all round, cut in a trial, the service checked "
        "against the host and everything else. Says who must review it (structure for slabs and load-bearing walls).",
        {"element": {"type": "string"}, "host": {"type": "string"}}, ["element", "host"]),
    _fn("check_seat", "Check seating `element` on `support` without keeping it: where `element` comes down into "
        "`support` and stands above its top, it is cut where it is inside the support's footprint below that top, so "
        "what is left bears on it. Nothing moves; how it bears is reviewed (structure).",
        {"element": {"type": "string"}, "support": {"type": "string"}}, ["element", "support"]),
    _fn("propose_fixes", "Run ORCA's fix agent on a clash: it proposes moves, local offsets, routes, flatter sections, trims at joints, seats and openings, checks each "
        "against the whole model, and shows the verified ones in the options panel for the user to preview and "
        "accept. Takes about 20 s and counts against the demo's proposal allowance; use it when the user wants fixes. "
        "With escalate true it is a second, longer try on Muse Wonder that reads the first try's failures and may "
        "change several elements together (about a minute, and costs more): only after a first try found nothing, or "
        "only a resize or an opening, or when the user asks for a better fix.",
        {"clash_id": {"type": "string"}, "escalate": {"type": "boolean"}}, ["clash_id"]),
    _fn("find_root_causes", "Elements that are in several real clashes at once (the likely root causes), with clashes "
        "the geometry finds that the Navisworks report missed. Use it for 'why are there so many clashes here' or "
        "'what is the real problem'."),
    _fn("find_patterns", "Patterns: the same kind of clash many times over (every column through every slab, members "
        "all overlapping by the same 30 mm), each judged as by design, a modelling error or a real problem, with the "
        "clash rule or action to take. Use it for 'what is all this noise' or before triaging a big report. The first "
        "reading of a report's patterns costs one proposal; asking again is free."),
    _fn("plan_root_cause", "For one element from find_root_causes: work out the cause and build one coordinated plan "
        "that fixes all its clashes, checked together. Shows the plan in the user's Plan tab to preview and accept. "
        "About a minute; costs one proposal per clashing element.", {"hub": {"type": "string", "description": "GlobalId"}},
        ["hub"]),
    _fn("plan_fixes_together", "Fix several clashes in one plan: a fix for each, checked together so they do not "
        "collide. Shows the plan in the user's Plan tab. Costs one proposal per distinct pair (at most 8).",
        {"clash_ids": {"type": "array", "items": {"type": "string"}}}, ["clash_ids"]),
    _fn("show_clash", "Select a clash in the user's view and fly the camera to it.", {"clash_id": {"type": "string"}},
        ["clash_id"]),
    _fn("show_it_built", "Show how the fix chosen for a clash (or the fix kept for it) would look built: the page draws "
        "ORCA's own view of it as a clean presentation render (Muse Image), checked against the model, beside the "
        "model's view. Only when the user asks to see a fix built; it costs a few cents a picture and takes about a "
        "minute. Not for a trim.", {"clash_id": {"type": "string"}}, ["clash_id"]),
    _fn("set_view", "Change the user's 3D view.", {
        "mode": {"type": "string", "enum": ["shaded", "xray", "context", "isolate"]},
        "section_box": {"type": "boolean"}}),
    _fn("set_filters", "Find elements by what the model says about them (class, level, model, any property) and "
        "colour them, colour them by value, hide or isolate them in every view, until clear_filters. Replaces the "
        "filters you set before; the user's own are paused while yours show. Returns how many elements each finds. "
        "Fixes never see filters; detect_clashes can check what a filter finds.", {
            "filters": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"},
                "classes": {"type": "array", "items": {"type": "string"}, "description": "IFC classes"},
                "levels": {"type": "array", "items": {"type": "string"}, "description": "storey names"},
                "models": {"type": "array", "items": {"type": "string"}, "description": "model files, or part of their names"},
                "where": {"type": "array", "items": {"type": "object", "properties": {
                    "property": {"type": "string"}, "set": {"type": "string", "description": "its property set, when the name is in several"},
                    "op": {"type": "string", "enum": ["is", "is_not", "contains", "has", "missing", "less", "more", "between"]},
                    "values": {"type": "array", "items": {"type": "string"}, "description": "any of these (numbers as text)"},
                    "min": {"type": "number"}, "max": {"type": "number", "description": "lengths in metres"}},
                    "required": ["property"]}},
                "action": {"type": "string", "enum": ["colour", "colour_by_value", "hide", "isolate"]},
                "colour": {"type": "string", "description": "#rrggbb, for colour"},
                "by": {"type": "string", "description": "the property to colour by (System, class, level, model…)"},
                "invert": {"type": "boolean"}}, "required": ["action"]}},
            "grey_rest": {"type": "boolean", "description": "grey what no filter colours"},
            "hide_rest": {"type": "boolean", "description": "hide everything no filter colours or isolates"}}, ["filters"]),
    _fn("clear_filters", "Remove the filters you set; the user's own come back."),
    _fn("list_faces", "The faces of an element there are to edit by hand, named as people say them (east end, north face, "
        "top), with what each allows (push_pull, align, clip, void) and its size. `element`: a GlobalId, or \"selected\" "
        "for the element the user has selected.", {"element": {"type": "string"}}, ["element"]),
    _fn("edit_check", "Check a hand edit without keeping it; the page shows its preview and its result. `op` is one of: "
        "{op: push_pull, element, face, by_m} (a face out + or in -, metres), {op: align, element, face, to: {element, "
        "face}, gap_m, how: stretch|move}, {op: move, element, delta_m: [dx, dy, dz]}, {op: void, element, face, at: "
        "[x, y, z], shape: rect|round, width_m, height_m | diameter_m, depth_m (omit to go through)}, {op: cut_by, "
        "element, cutter, gap_m}, {op: split, element, at}, {op: remove_section, element, from, to}, {op: delete, "
        "element}, {op: clip, element, to: {element, face}, gap_m}, {op: offset, element, from, to, toward: "
        "up|down|north|south|east|west, by_m, bend_deg?: 45 for a slope with angled bends} (a section of a level duct, pipe or tray between two points along it, "
        "with bends), {op: join, element, to: {element}} (two segments' free ends: in line, or square with a 90° bend), "
        "{op: disconnect, element, from: element} (leave that joint open). `element` may be \"selected\", and `face` \"selected\" "
        "for the face the user chose in the Edit tool; other faces by name from list_faces. An edit changes only that "
        "face or element: a joint it leaves open is listed. Add carry: true to push_pull, align or move only when the "
        "user asks to take joined parts along (a joined straight follows a pushed end; a move takes its run and "
        "fittings). Add scope: \"type\" to push_pull or align only when the user asks to change the type, or every "
        "element of it: the shape, section or layer thickness its type gives changes for all of them, each checked "
        "(a length or an element without a type is refused). The result says what it clears, what it would hit (clashes), its warnings, or why it cannot be made.",
        {"op": {"type": "object"}}, ["op"]),
    _fn("edit_keep", "Keep the hand edit you checked last, only when the user's own latest message says to keep it "
        "(keep it, apply it, do it, yes). When it makes clashes, only when they said to keep it with the clashes; pass "
        "accept_clashes = that number. When its check lists joints it leaves open, only when they said to keep it with "
        "the open joint. Never on your own initiative.", {"accept_clashes": {"type": "integer"}}),
    _fn("undo_edit", "Undo the newest kept edit (a hand edit or a fix), only when the user's own latest message asks to "
        "undo it."),
    _fn("edit_property", "Change what the model says about an element, not its shape, only when the user's own latest "
        "message asks for it and says the new value (or names the type, material, storey or classification): `change` is "
        "{kind: attribute, name: Name|Description|ObjectType|Tag|PredefinedType, value} | {kind: property, pset, name, "
        "value} (a property in one of its own sets; base quantities follow its body and are refused) | {kind: type, type: "
        "GlobalId} | {kind: material, material: id} | {kind: classification, reference: id, remove? | replace?: the "
        "id of one it has, swapped in one change} | {kind: container, container: GlobalId}. Kept in the edit log at once; undo_edit takes it back.",
        {"element": {"type": "string"}, "change": {"type": "object"}}, ["change"]),
    _fn("list_edits", "Every edit kept to the model, newest last: who kept it, what it did, the clash it is for and the "
        "fix it follows.", {"limit": {"type": "integer"}}),
]

# The person's own words: what keeps or undoes an edit from chat or voice (docs/manual-edits.md). Muse never keeps.
# A bare "keep" is not consent: in this domain it mostly means maintain ("keep 25 mm clear").
_CONSENT = re.compile(r"\b(keep\s+(it|that|this|them)|apply(\s+(it|that))?|do\s+it|go\s+ahead|yes|yep|"
                      r"confirm(ed)?|accept(\s+(it|that))?|commit(\s+it)?|make\s+it\s+so|save\s+it)\b", re.I)
_REFUSE = re.compile(r"\b(don'?t|do\s+not|never|cancel|stop|wait)\b|^\s*no\b", re.I)
_UNDO = re.compile(r"\b(undo|revert|take\s+(it|that)\s+back|put\s+it\s+back)\b", re.I)
# "keep it" and little else: kept even when Muse checked it this same turn (the person said only that)
_ONLY_KEEP = re.compile(r"^\s*(ok(ay)?[, ]+|yes[, ]+|please[, ]+)*(keep|apply)\s+(it|that|this)(\s+please)?\s*[.!]?\s*$", re.I)


def consents(text: str, undo: bool = False) -> bool:
    """Whether the person's own message says to keep (or undo) an edit: plain words, no refusal anywhere in them."""
    t = text or ""
    return bool((_UNDO if undo else _CONSENT).search(t)) and not _REFUSE.search(t)


def accepts(text: str, what: str) -> bool:
    """Whether the person's message keeps the edit *with* its clashes (`what` "clash") or open joints ("joint"): said
    as such ("keep it with the clash", "apply it with 2 clashes", "keep it with the open joint"), and not ruled out
    ("keep it if it makes no clashes", "not if it clashes", "without the joint")."""
    t = text or ""
    said = re.search(rf"\b(keep|apply|accept|do)\s+(it|that|this|them)?\s*(anyway\s+)?with\s+(the|its|those|these|an?|one|"
                     rf"two|three|\d+)?\s*(open\s+)?{what}", t, re.I)
    ruled_out = re.search(rf"\b(no|not|doesn'?t|don'?t|without|unless|if|any)\b[^.?!]{{0,25}}\b{what}", t, re.I)
    return bool(said) and not ruled_out


def _said(text: str, scene, gid: str, change: dict) -> bool:
    """Whether the person's own message names the property change Muse is making: the new value (a removal: the
    property's name), or the type, material, storey or classification by its name; and refuses nothing."""
    t = (text or "").lower()
    if not t or _REFUSE.search(text or ""):
        return False
    kind = change.get("kind")
    model = scene.models[scene.index_of(gid)]
    try:
        if kind in ("attribute", "property"):
            v = change.get("value")
            if v in (None, ""):
                return str(change.get("name") or "").lower() in t
            if isinstance(v, bool):
                return bool(re.search(r"\b(yes|no|true|false)\b", t))
            if isinstance(v, (int, float)):
                return any(abs(float(x) - float(v)) < 1e-9 for x in re.findall(r"-?\d+(?:\.\d+)?", t))
            return str(v).lower() in t
        target = {"type": lambda: model.by_guid(change["type"]).Name, "container": lambda: model.by_guid(change["container"]).Name,
                  "material": lambda: model.by_id(int(change["material"])).Name,
                  "classification": lambda: property_edits.ref_code(model.by_id(int(change["reference"])))}[kind]()
    except (KeyError, RuntimeError, TypeError, ValueError):
        return False
    return bool(target) and str(target).lower() in t


def _coloured(idx: dict, rule: dict, hit: set[int]) -> dict:
    """For a colour-by-value filter, the values it colours (from what `facets.resolve` found) with how many elements
    each, as the model may name them; past the palette's colours the rest share one, as the page draws them."""
    if rule["action"] != "byValue":
        return {}
    f = facets.facet(idx, rule["by"]["facet"])
    rows = [{"value": v, "elements": len(hit & set(items))} for v, items in zip(f["values"], f["items"])] if f else []
    rows = [r for r in rows if r["elements"]]
    if len(rows) <= facets.COLOURS:
        return {"values": rows}
    rest = rows[facets.COLOURS:]
    return {"values": rows[:facets.COLOURS], "other": {"values": len(rest), "elements": sum(r["elements"] for r in rest)}}


@dataclass
class Session:
    id: str
    messages: list[dict] = field(default_factory=list)
    _history_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)
    _next_turn: int = field(default=0, init=False, repr=False)
    _published_turn: int = field(default=0, init=False, repr=False)


@dataclass
class Context:
    """What the page knows that the server does not: what is open and selected, and what was fixed."""
    scene_id: str | None = None
    report_id: str | None = None
    clash_id: str | None = None
    fixed: list[str] = field(default_factory=list)
    # The user's own filters on the page (docs/filters.md): [{id, name, when, invert, on, action, by}], for
    # detect_clashes by name, and how they show together ({hide_rest, colours}) for its {"shown": true} side.
    filters: list[dict] = field(default_factory=list)
    filter_view: dict = field(default_factory=dict)
    check: str | None = None   # the kept check the user's list shows (its key; None: every kept check)
    # What the user has selected on the page: {element, face?, pick?} (the Edit tool's face, when one is chosen, and the
    # point and normal picked on it).
    selected: dict | None = None


def page_view(ctx: Context) -> dict:
    """What the page's filters show together, as a check's side takes it (detect.Selection.view): the filters that
    are on, and whether the rest is hidden and colours show."""
    return {"filters": [_page_filter(f) | {"action": f.get("action") or "colour"} for f in ctx.filters if f.get("on", True)],
            "hide_rest": bool(ctx.filter_view.get("hide_rest")), "colours": ctx.filter_view.get("colours", True) is not False}


def side_count(idx: dict, drawn: set[str], side: dict | None) -> dict | None:
    """What a check's side takes, counted as the page's Filters panel counts it (rooms included, docs/filters.md,
    "Checks"): `elements`, the `rooms` among them (spaces: no solid body, so never checked) and what is `checked`.
    Everything counts the models the full check covers the same way. None for itself."""
    if side is None:
        return None
    if side.get("view") or side.get("filter"):
        got = facets.shown(idx, side["view"]) if side.get("view") else facets.acted(idx, side["filter"])
    else:   # everything: the models the full check covers
        files = set(side.get("files") or [])
        got = {i for i in range(len(idx["elements"])) if not files or idx["files"][idx["file"][i]] in files}
    cls = facets.facet(idx, "class")
    rooms = set(cls["items"][cls["values"].index("IfcSpace")]) if cls and "IfcSpace" in cls["values"] else set()
    checked = len({idx["elements"][i] for i in got} & drawn)
    return {"elements": len(got), "rooms": len(got & rooms), "checked": checked}


def _page_filter(f: dict) -> dict:
    """One of the page's filters as a check's side takes it: what it finds, and for one colouring by value, only what
    it colours (detect.Selection.filter)."""
    side = {"when": list(f.get("when") or []), "invert": bool(f.get("invert"))}
    if f.get("action") == "byValue" and isinstance(f.get("by"), dict) and f["by"].get("facet"):
        side["by"] = {"facet": f["by"]["facet"], "off": list(f["by"].get("off") or [])}
    return side


class Chat:
    def __init__(self, ws: Workspace, model: ToolModel | None = None,
                 propose_allowed: Callable[[], str | None] | None = None):
        self.ws = ws
        self._model = model
        self.sessions: OrderedDict[str, Session] = OrderedDict()
        self.propose_allowed = propose_allowed or (lambda: None)
        self.propose_allowed_many: Callable[[int], str | None] = lambda n: None
        self.escalate_allowed: Callable[[], str | None] = lambda: None
        self.detect_allowed: Callable[[], str | None] = lambda: None
        # Per session, the hand edit Muse checked last (edit_keep keeps only that one, on the person's own words).
        self.pending: dict[str, dict] = {}
        self._turn = threading.local()

    @property
    def model(self) -> ToolModel:
        if self._model is None:
            self._model = self.ws.model  # the same Meta client; it also does tool calls
        return self._model  # type: ignore[return-value]

    def session(self, session_id: str | None) -> Session:
        if session_id and session_id in self.sessions:
            self.sessions.move_to_end(session_id)
            return self.sessions[session_id]
        s = Session(uuid.uuid4().hex[:12], [{"role": "system", "content": domains.prompt("chat")}])
        self.sessions[s.id] = s
        while len(self.sessions) > MAX_SESSIONS:
            self.sessions.popitem(last=False)
        return s

    def turn(self, session: Session, text: str, ctx: Context, emit: Callable[[dict], None], *,
             cancel: threading.Event | None = None,
             propose_allowed: Callable[[], str | None] | None = None,
             propose_allowed_many: Callable[[int], str | None] | None = None,
             escalate_allowed: Callable[[], str | None] | None = None,
             detect_allowed: Callable[[], str | None] | None = None,
             before_publish: Callable[[], None] | None = None) -> str:
        cancel = cancel or threading.Event()
        # Defaults preserve constructor/direct-tool callers; each turn captures its
        # callbacks before a model wait can interleave with another visitor's turn.
        allowed = self.propose_allowed if propose_allowed is None else propose_allowed
        allowed_many = self.propose_allowed_many if propose_allowed_many is None else propose_allowed_many
        escalate_ok = self.escalate_allowed if escalate_allowed is None else escalate_allowed
        detect_ok = self.detect_allowed if detect_allowed is None else detect_allowed
        target = session
        with target._history_lock:
            target._next_turn += 1
            turn_number = target._next_turn
            # Active requests own their tool history; only completed turns become shared context.
            session = Session(target.id, deepcopy(target.messages))
        if session.messages and session.messages[0].get("role") == "system":   # in the open scene's voice
            voice = domains.prompt("chat", domains.of(self.ws, ctx.scene_id))
            session.messages[0] = {"role": "system", "content": voice}
        session.messages.append({"role": "user", "content": f"{self._context_line(ctx)}\n\n{text}"})
        self._turn.state = {"session": target.id, "turn": turn_number, "text": text}
        answer = ""
        for _ in range(MAX_STEPS):
            if cancel.is_set():
                break
            emit({"type": "thinking"})
            if cancel.is_set():
                break
            try:
                reply = self.model.chat(session.messages, TOOLS)
            except Exception:
                if cancel.is_set():
                    break
                raise
            if cancel.is_set():
                break
            calls = reply.get("tool_calls") or []
            session.messages.append({k: v for k, v in reply.items() if k in ("role", "content", "tool_calls") and v}
                                    | {"role": "assistant"})
            if not calls:
                answer = reply.get("content") or ""
                break
            images: list[Path] = []
            for call in calls:
                if cancel.is_set():
                    break
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                emit({"type": "tool", "name": name, "args": args})
                if cancel.is_set():
                    break
                try:
                    result, summary, pics = self._run(name, args, ctx, emit, cancel=cancel,
                                                     propose_allowed=allowed, propose_allowed_many=allowed_many,
                                                     escalate_allowed=escalate_ok, detect_allowed=detect_ok)
                except Exception as e:  # a bad id, a shape that cannot be edited: tell the model, keep going
                    result, summary, pics = {"error": f"{type(e).__name__}: {e}"}, f"failed: {e}", []
                if cancel.is_set():
                    break
                images += pics
                emit({"type": "tool_result", "name": name, "summary": summary})
                session.messages.append({"role": "tool", "tool_call_id": call["id"],
                                         "content": json.dumps(result, default=str)[:12000]})
            if images:  # tool results are text only; images go to the model as the next user message
                session.messages.append({"role": "user", "content": [
                    {"type": "text", "text": "The clash images you asked for (A, B, C):"}] + [image_part(p) for p in images]})
        else:
            answer = "I ran out of steps on that one. Ask me to carry on, or narrow the question."
        if cancel.is_set():
            return ''
        self._trim(session)
        with target._history_lock:
            if cancel.is_set():
                return ''
            # Final callbacks only enqueue bounded, nonblocking events. Hold the
            # session snapshot lock across completion AND its guarded history commit:
            # a follow-up after done must see this exchange in its initial snapshot.
            emit({"type": "message", "text": answer})
            if before_publish is not None:
                before_publish()
            # Message/done/end may themselves overflow the bounded queue.
            if cancel.is_set():
                return ''
            # An older in-flight request cannot replace a newer completed conversation.
            if turn_number > target._published_turn:
                target.messages = session.messages
                target._published_turn = turn_number
        return answer

    def _side(self, idx: dict, ctx: Context, spec: dict | None, b: bool, every: dict) -> tuple[dict | None, str]:
        """One side of a check as the detection test takes it (`every` for everything, None itself, else a filter or
        what the filters show), and what it is called. Raises facets.Unresolved, naming what there is."""
        spec = spec or {"everything": True}
        if spec.get("itself"):
            if not b:
                raise facets.Unresolved("Side A cannot be itself: give A a filter or describe its elements.")
            return None, "itself"
        if spec.get("shown"):
            if not any(f.get("on", True) for f in ctx.filters):
                raise facets.Unresolved("The user has no filters on: describe the elements instead.")
            return {"view": page_view(ctx)}, "what the filters show"
        if spec.get("filter"):
            want = str(spec["filter"]).strip().lower()
            mine = {str(f.get("name") or "").lower(): f for f in ctx.filters}
            f = mine.get(want)
            if f is None:
                if not ctx.filters:
                    raise facets.Unresolved("The user has no filters on the page: describe the elements instead.")
                close = facets.suggest(idx, spec["filter"], among=[str(x.get("name")) for x in ctx.filters], n=4)
                raise facets.Unresolved(f"No filter {spec['filter']!r} on the page. Its filters: "
                                        + ", ".join(close or [str(x.get("name")) for x in ctx.filters][:12]) + ".")
            return {"filter": _page_filter(f)}, str(f.get("name"))
        described = {k: v for k, v in spec.items() if k in ("classes", "levels", "models", "where", "invert")}
        if spec.get("everything") or not described:
            return dict(every), "everything"
        rule, _ = facets.resolve(idx, {**described, "action": "isolate"})
        return {"filter": {"when": rule["when"], "invert": bool(rule.get("invert"))}}, facets.name_for(rule["when"], bool(rule.get("invert")))

    def _check(self, sid: str, ctx: Context, args: dict) -> tuple[dict, dict]:
        """detect_clashes with sides: the one test it runs, and what each side takes."""
        ws = self.ws
        idx = ws.facets(sid)
        d = ws.check_defaults(sid)
        a, a_name = self._side(idx, ctx, args.get("a"), False, d["everything"])
        b, b_name = self._side(idx, ctx, args.get("b"), True, d["everything"])
        drawn = set(ws.scene(sid).bounds())
        c_a, c_b = side_count(idx, drawn, a), side_count(idx, drawn, b)
        for side, c, side_name in (("A", c_a, a_name), ("B", c_b, b_name)):
            if c is not None and not c["checked"]:
                raise facets.Unresolved(f"Side {side} ({side_name}) finds no element the check can test"
                                        + (": only rooms, which have no solid body to clash." if c["elements"] else "."))
        kind = str(args.get("kind") or "hard")
        if kind not in ("hard", "clearance", "duplicate"):
            raise facets.Unresolved(f"Unknown kind {kind!r}: hard, clearance or duplicate.")
        # Named as the user knows its sides (their filter's own name), as detect.check_name does otherwise.
        shown_name = lambda n: "What the filters show" if n == "what the filters show" else n
        name = str(args.get("name") or "") or (f"{shown_name(a_name)} (within)" if b is None else f"{shown_name(a_name)} vs "
                                              f"{'Everything' if b_name == 'everything' else shown_name(b_name)}")
        if kind == "clearance" and not args.get("name"):
            mm = d["clearance_m"] if args.get("clearance_mm") is None else float(args["clearance_mm"]) / 1000
            name += f", {round(mm * 1000)} mm clearance"
        test = {"id": "", "name": name, "a": a, "b": b, "kind": kind, "rules": d["rules"],
                "min_size_m": d["min_size_m"],
                "tolerance_m": d["tolerance_m"] if args.get("tolerance_mm") is None else max(0.0, float(args["tolerance_mm"])) / 1000,
                "clearance_m": d["clearance_m"] if args.get("clearance_mm") is None else max(0.0, float(args["clearance_mm"])) / 1000}
        told = lambda name, c: None if c is None else {"name": name, "elements": c["elements"],
                                                       **({"rooms_not_checked": c["rooms"]} if c["rooms"] else {})}
        return test, {"a": told(a_name, c_a), "b": {"name": b_name, "elements": None} if c_b is None else told(b_name, c_b)}

    def _selected(self, ctx: Context, gid):
        if gid in (None, "", "selected", "this", "it"):
            sel = (ctx.selected or {}).get("element")
            if not sel:
                raise ValueError("nothing is selected: ask the user to click the element, or name it")
            return sel
        return gid

    @staticmethod
    def _chosen_face(ctx: Context, gid, face):
        """The face the user chose in the Edit tool, as its pick, when Muse means it ("selected", or its name on the
        element selected): a face only a pick places (an I-section's side, a fitting's face) works from chat too."""
        sel = ctx.selected or {}
        pick = sel.get("pick")
        if not isinstance(face, str) or not isinstance(pick, dict) or sel.get("element") != gid:
            return face
        if face.strip().lower() in ("selected", "this", "this face", "it", "chosen") or face == sel.get("face"):
            return {"point": pick.get("point"), "normal": pick.get("normal")}
        return face

    def _edit_tool(self, name: str, args: dict, ctx: Context, emit) -> tuple[dict, str, list[Path]]:
        """The hand-edit tools (docs/manual-edits.md): Muse checks, the person keeps."""
        ws, sid = self.ws, self._scene(ctx)
        state = getattr(self._turn, "state", None) or {}
        session = state.get("session") or "direct"
        if name == "list_faces":
            gid = self._selected(ctx, args.get("element"))
            listed = [{k: v for k, v in f.to_dict().items() if k in ("id", "name", "kind", "size_m", "allows", "why_not")}
                      for f in faces.faces(ws.scene(sid), gid)]
            return {"element": gid, "label": manual.label(ws.scene(sid), gid), "faces": listed}, f"{len(listed)} faces", []
        if name == "list_edits":
            j = ws.journal(sid)
            limit = max(1, min(int(args.get("limit") or 10), 30))
            rows = [{k: e.to_dict()[k] for k in ("id", "when", "source", "kind", "summary", "clashes", "follows", "state", "warnings")}
                    for e in j.entries[-limit:]]
            return {"edits": rows, "can_undo": j.summary()["can_undo"]}, f"{len(rows)} edits", []
        if name == "edit_check":
            op = dict(args.get("op") or {})
            op["element"] = self._selected(ctx, op.get("element"))
            op["face"] = self._chosen_face(ctx, op["element"], op.get("face"))
            r = manual.check(ws, sid, op)
            # What keeping needs (not the preview's meshes, which can be large)
            self.pending[session] = {"check": {k: v for k, v in r.items() if k not in ("preview", "before")},
                                     "turn": state.get("turn"), "scene": sid}
            emit({"type": "ui", "action": "edit_preview", "check": r})
            told = {k: v for k, v in r.items() if k not in ("preview", "before", "targets")}
            return told, ("cannot: " + r["blocked"]) if r.get("blocked") else (
                f"makes {r['clashes']} clash(es)" if r["clashes"] else "clear"), []
        if name == "edit_keep":
            pend = self.pending.get(session)
            text = state.get("text") or ""
            if not pend or pend.get("scene") != sid:
                return {"error": "there is no checked edit to keep: check one first"}, "nothing to keep", []
            r = pend["check"]
            if r.get("blocked"):
                return {"error": f"that edit cannot be made: {r['blocked']}"}, "refused", []
            if not consents(text):
                return {"error": "only the user can keep an edit: ask them to say keep it"}, "waiting for the user", []
            if pend.get("turn") == state.get("turn") and not _ONLY_KEEP.match(text):
                # Checked this turn: the person has not seen its preview yet ("push it up 100 mm and keep 50 mm clear")
                return {"error": "show the user the check first: keep it only when they say so after seeing it"}, \
                    "waiting for the user", []
            n = int(args.get("accept_clashes") or 0)
            if r["clashes"] and (n < r["clashes"] or not accepts(text, "clash")):
                return {"error": f"it makes {r['clashes']} clash(es): keep it only if the user says to keep it with the clashes"}, \
                    "waiting for the user", []
            joints = len(r.get("joints") or [])
            if joints and not accepts(text, "joint"):
                return {"error": f"it leaves {joints} joint(s) open: keep it only if the user says to keep it with the open "
                                 "joint"}, "waiting for the user", []
            scene = ws.scene(sid)
            with ws.lock:
                before = scene.revision
                kept = manual.apply(ws, sid, r["op"], key=r.get("key"), accept_clashes=n, accept_joints=joints, source="muse",
                                    clash_id=ctx.clash_id, pair=self._pair(ctx))
                patch = ws.patch(sid, kept["changed"], before, removed=kept["removed"])
            self.pending.pop(session, None)
            emit({"type": "ui", "action": "edit_kept", "kept": {**kept, **patch}})
            return {"kept": kept["entry"]["id"] if kept["entry"] else None, "summary": kept["entry"]["summary"] if kept["entry"] else ""}, "kept", []
        if name == "edit_property":
            gid = self._selected(ctx, args.get("element"))
            change = dict(args.get("change") or {})
            if not _said(state.get("text") or "", ws.scene(sid), gid, change):
                return {"error": "only change a property the user asked for, with its new value in their own words"}, \
                    "waiting for the user", []
            scene = ws.scene(sid)
            try:
                with ws.lock:
                    before = scene.revision
                    r = property_edits.edit(ws, sid, gid, change, source="muse")
                    patch = ws.patch(sid, [gid], before)
            except (edits.Unsupported, ValueError, TypeError) as e:
                return {"error": f"that change cannot be made: {e}"}, "refused", []
            entry = r["entry"] or {}
            emit({"type": "ui", "action": "edit_kept", "kept": {"entry": entry, "files": entry.get("files", []), "changed": [gid],
                                                               "created": [], "removed": [], "pieces": [], "check": {}, **patch}})
            return {"kept": entry.get("id"), "summary": entry.get("summary")}, "kept", []
        if name == "undo_edit":
            if not consents(state.get("text") or "", undo=True):
                return {"error": "only the user can undo an edit: ask them to say undo"}, "waiting for the user", []
            scene = ws.scene(sid)
            with ws.lock:
                before = scene.revision
                r = ws.undo_edit(sid)
                patch = ws.patch(sid, r["changed"], before, removed=r["removed"])
            emit({"type": "ui", "action": "edit_stepped", "step": {**r, **patch}})
            return {"undone": r["entry"]["id"], "summary": r["entry"]["summary"]}, "undone", []
        raise ValueError(name)

    def _pair(self, ctx: Context) -> list[str] | None:
        if not ctx.clash_id or not ctx.report_id:
            return None
        m = self._matches(ctx).get(ctx.clash_id, {})
        return [m["a"], m["b"]] if m.get("a") and m.get("b") else None

    def _context_line(self, ctx: Context) -> str:
        parts = ["[context]"]
        parts.append("a model is open" if ctx.scene_id in self.ws.scenes else "no model is open")
        r = self._open_report(ctx)
        if r is not None:
            source = "found by ORCA's own detection" if r.origin == "sightline" else "from Navisworks"
            parts.append(f"clash report '{r.title}' is open ({len(r.clashes)} clashes, {source})")
            if r.origin == "sightline" and r.checks:
                kept = [f"'{c['name']}' ({c['clashes']})" for c in r.checks]
                parts.append(f"it lists {len(kept)} kept check{'s' if len(kept) != 1 else ''}: {', '.join(kept)}")
                viewing = next((c["name"] for c in r.checks if c["key"] == ctx.check), None)
                if viewing:
                    parts.append(f"the user's list shows only '{viewing}'")
        else:
            parts.append("no clash report is open")
        if ctx.clash_id:
            parts.append(f"the user has clash {ctx.clash_id} selected")
        sel = (ctx.selected or {}).get("element")
        if sel and ctx.scene_id in self.ws.scenes:
            try:
                scene = self.ws.scene(ctx.scene_id)
                face = (ctx.selected or {}).get("face")
                parts.append(f"the user has element {manual.label(scene, sel)} selected ({sel})"
                             + (f", its {face} chosen in the Edit tool" if face else ""))
            except KeyError:
                pass
        if ctx.scene_id in self.ws.journals and self.ws.journals[ctx.scene_id].entries:
            lines = journal.entry_lines(self.ws.journals[ctx.scene_id].entries, 3)
            parts.append("edits kept so far (newest last): " + " | ".join(lines))
        if ctx.fixed:
            parts.append(f"fixed so far: {', '.join(ctx.fixed[:30])}")
        if ctx.filters:
            names = [f'"{f.get("name")}"' for f in ctx.filters if f.get("name")]
            more = f" (+{len(names) - 12} more)" if len(names) > 12 else ""
            parts.append(f"the user's filters: {', '.join(names[:12])}{more}")
            shown = self._shown_count(ctx)
            if shown is not None:
                parts.append(f"together they show {shown[0]} of {shown[1]} elements")
        return "; ".join(parts)

    def _shown_count(self, ctx: Context) -> tuple[int, int] | None:
        """How many elements the user's filters show together, of all there are, rooms included as the page counts
        them, or None without models or filters on."""
        if ctx.scene_id not in self.ws.scenes or not any(f.get("on", True) for f in ctx.filters):
            return None
        idx = self.ws.facets(ctx.scene_id)
        return len(facets.shown(idx, page_view(ctx))), len(idx["elements"])

    def _trim(self, session: Session) -> None:
        # Keep the system prompt; drop the oldest turns, never splitting a tool call from its results.
        while len(session.messages) > MAX_HISTORY:
            del session.messages[1]
            while len(session.messages) > 1 and session.messages[1]["role"] == "tool":
                del session.messages[1]

    # ------------------------------------------------------------------ tools

    def _scene(self, ctx: Context) -> str:
        if ctx.scene_id not in self.ws.scenes:
            raise LookupError("no model is open: ask the user to open the models first")
        return ctx.scene_id  # type: ignore[return-value]

    def _open_report(self, ctx: Context):
        """The open report, or None. ORCA's list of checks the server let go is made again (clash ids are the same)."""
        if ctx.report_id in self.ws.reports:
            return self.ws.report(ctx.report_id)  # type: ignore[arg-type]
        if ctx.report_id and ctx.scene_id in self.ws.scenes:
            register = self.ws.checks.get(ctx.scene_id)  # type: ignore[arg-type]
            if register is not None and ctx.report_id in register.unions:
                report = self.ws.union_report(ctx.scene_id)  # type: ignore[arg-type]
                if report is not None:
                    ctx.report_id = report.id
                    return report
        return None

    def _report(self, ctx: Context):
        report = self._open_report(ctx)
        if report is None:
            raise LookupError("no clashes are open: check the open models with detect_clashes, or ask the user to import a report "
                              "from 'Coordinate'")
        return report

    def _matches(self, ctx: Context) -> dict:
        return self.ws.match(ctx.report_id, ctx.scene_id) if ctx.scene_id in self.ws.scenes else {}  # type: ignore

    def _row(self, c, m: dict, ctx: Context) -> dict:
        return {"clash_id": c.id, "number": f"#{c.number}", "title": c.title or c.name, "test": c.test,
                "a": f"{c.a.ifc_class} '{c.a.name}'", "b": f"{c.b.ifc_class} '{c.b.name}'",
                "level": c.a.level or c.b.level, "distance_mm": round(c.distance_m * 1000) if c.distance_m is not None else None,
                "in_model": bool(m.get("a") and m.get("b")), "fixed": c.id in ctx.fixed}

    def _run(self, name: str, args: dict, ctx: Context, emit, *, cancel=None, propose_allowed=None,
             propose_allowed_many=None, escalate_allowed=None, detect_allowed=None) -> tuple[dict, str, list[Path]]:
        ws = self.ws
        allowed = self.propose_allowed if propose_allowed is None else propose_allowed
        allowed_many = self.propose_allowed_many if propose_allowed_many is None else propose_allowed_many
        escalate_ok = self.escalate_allowed if escalate_allowed is None else escalate_allowed
        detect_ok = self.detect_allowed if detect_allowed is None else detect_allowed
        if name == 'explore_wider_fix':
            report, sid = self._report(ctx), self._scene(ctx)
            c = report.clash(args['clash_id'])
            matched = self._matches(ctx).get(c.id, {})
            objective = context_planner.validate_objective(ws, sid, dict(element_a=matched.get('a'),
                element_b=matched.get('b'), report_id=report.id, clash_id=c.id))
            refused = allowed_many(3)
            if refused:
                return {'error': refused}, 'refused: allowance used', []
            forward = lambda event: emit(dict(type='context_event', event=event))
            result = context_planner.build(ws, sid, objective, forward, cancel=cancel)
            if cancel is None or not cancel.is_set():
                forward(result)
            summary = dict(proposals=[dict(id=p['id'], title=p['title'], review_conditions=p['review_conditions'])
                                     for p in result['proposals']], message=result['message'],
                           note='Whole proposals are available for preview and designer review. You cannot accept them.')
            return summary, f'{len(result["proposals"])} passing context arrangements for review', []
        if name == "detect_clashes":
            sid = self._scene(ctx)
            tests = None
            check = None
            # A kept check again, by its name, or every kept check (docs/detection.md, "Kept checks").
            again = str(args.get("check") or "").strip()
            register = ws.checks.get(sid)
            kept = None
            if again:
                if again.lower() != "all":
                    kept = register.find(again) if register is not None else None
                    if kept is None:
                        names = [c.name for c in register.checks.values()] if register is not None else []
                        return ({"error": f"No kept check {again!r}." + (f" Kept: {', '.join(names)}." if names else
                                                                        " None is kept yet: run one first.")},
                                "refused: no such check", [])
            elif args.get("a") or args.get("b"):
                # One check of what A takes against what B takes (docs/filters.md, "Checks"), resolved and counted
                # before a detection run is spent: a name the models lack, or an A that finds nothing, costs none.
                try:
                    test, check = self._check(sid, ctx, args)
                except facets.Unresolved as e:
                    return {"error": str(e)}, "refused: not in the model", []
                tests = [test]
            elif args.get("tolerance_mm") is not None:
                tol = max(0.0, float(args["tolerance_mm"])) / 1000
                tests = [{**t, "tolerance_m": tol if t["kind"] == "hard" else t["tolerance_m"]}
                         for t in ws.detect_tests(sid)["tests"] if t["enabled"]]
            refused = detect_ok()   # one detection run, as POST /detect/stream takes
            if refused:
                return {"error": refused}, "refused: detection runs used", []
            forward = lambda e: emit({"type": "detect_event", "event": e})
            if again.lower() == "all":
                out = ws.detect_all(sid, on_event=forward)
            else:
                out = ws.detect(sid, tests, on_event=forward, check=kept.key if kept is not None else None)
            rid = out["report"]["id"]
            ctx.report_id = rid  # the rest of this answer works on the new report
            ctx.check = out["check"]
            detection = {k: out[k] for k in ("coverage", "diff", "elements", "seconds", "tests")}
            emit({"type": "ui", "action": "open_report", "report_id": rid, "detection": detection,
                  "check": out["check"], "checks": out["checks"]})
            n = len(out["report"]["clashes"])
            ran = [c for c in out["checks"] if c["key"] in out["ran"]]
            kept_checks = [{"name": c["name"], "clashes": c["clashes"], "stale": c["stale"]} for c in out["checks"]]
            if out["check"] is None:   # every kept check again
                summary = {"report_id": rid, "clashes": n, "seconds": out["seconds"],
                           "checks_run": [{"name": c["name"], "clashes": c["clashes"], "since_last_run": None
                                           if c["diff"].get("first") else {"new": len(c["diff"]["new"]),
                                                                           "resolved": len(c["diff"]["resolved"])}}
                                          for c in ran],
                           "note": "Every kept check ran again; the open list holds all their clashes."}
                return summary, f"{len(ran)} checks run again, {n} clashes in the list", []
            this = ran[0]
            diff = out["diff"]
            summary = {"report_id": rid, "check": {"name": this["name"]}, "clashes": this["clashes"],
                       "open_list": n, "kept_checks": kept_checks,
                       "seconds": out["seconds"], "elements": out["elements"],
                       "tests": [{"test": c["name"], "clashes": c["clashes"], "touching": c["touching"],
                                  "meant_to_meet": c["excluded"], "partial": c["partial"]} for c in out["coverage"]],
                       "since_last_run": None if diff.get("first") else {
                           "new": len(diff["new"]), "resolved": len(diff["resolved"]),
                           "no_longer_checked": len(diff["no_longer_checked"])},
                       "note": "The check is kept with the others; the open list holds every kept check's clashes, "
                               "and the user's list now shows this check. Triage sorts real problems from noise."}
            if check is not None:
                summary["check"] = {**check, "name": out["tests"][0]["name"]}
                rooms = [f"{c['rooms_not_checked']} in {c['name']}" for c in (check["a"], check["b"])
                         if c and c.get("rooms_not_checked")]
                if rooms:   # counted as the user's Filters panel counts them, but never part of a clash check
                    summary["note"] += (f" Rooms are counted in elements, as the user's Filters panel counts them, but are "
                                        f"never checked (no solid body to clash): {' and '.join(rooms)}. Say so with the counts.")
            return summary, f"{n} clashes found by ORCA in {out['seconds']} s", []
        if name == "report_summary":
            r, matches = self._report(ctx), self._matches(ctx)
            tests = Counter(c.test for c in r.clashes)
            in_model = sum(1 for c in r.clashes if matches.get(c.id, {}).get("a") and matches.get(c.id, {}).get("b"))
            # Per element class pair: how many, the deepest overlap, and hints for spotting noise quickly.
            pairs: dict[str, dict] = {}
            for c in r.clashes:
                key = " vs ".join(sorted([c.a.ifc_class or "?", c.b.ifc_class or "?"]))
                p = pairs.setdefault(key, {"count": 0, "worst_mm": 0, "touching": 0, "example": c.id,
                                           "non_physical_side": bool({c.a.ifc_class, c.b.ifc_class} & NOT_PHYSICAL)})
                p["count"] += 1
                d = round((c.distance_m or 0) * 1000)
                if d < p["worst_mm"]:
                    p["worst_mm"], p["example"] = d, c.id
                p["touching"] += abs(d) <= 1
            res = {"title": r.title, "clashes": len(r.clashes), "tests": len(tests), "in_open_model": in_model,
                   **({"checks": [{"name": c["name"], "clashes": c["clashes"], "stale": c["stale"]} for c in
                                  self.ws.report_summary(r.id).get("checks", [])]} if r.checks else {}),
                   "fixed": len(ctx.fixed), "by_test": dict(tests.most_common(80)),
                   "by_class_pair": dict(sorted(pairs.items(), key=lambda kv: kv[1]["worst_mm"])),
                   "note": "non_physical_side: a space, port or opening is involved (not a physical clash); "
                           "touching: results within 1 mm (usually connections)."}
            return res, f"{len(r.clashes)} clashes in {len(tests)} tests, {in_model} in the model", []
        if name == "list_clashes":
            r, matches = self._report(ctx), self._matches(ctx)
            q = (args.get("query") or "").lower().split()
            rows = []
            only = None
            if args.get("check"):
                kept = checks.pick(r.checks, args["check"])
                only = kept["key"] if kept else None
                if only is None:
                    return ({"error": f"No kept check {args['check']!r}. Kept: "
                                      + (", ".join(c["name"] for c in r.checks) or "none") + "."}, "no such check", [])
            for c in r.clashes:
                if only is not None and only not in c.checks:
                    continue
                m = matches.get(c.id, {})
                text = " ".join(str(x) for x in [f"#{c.number}", c.title, c.name, c.test, c.a.name, c.b.name, c.a.ifc_class, c.b.ifc_class,
                                                 c.a.level, c.b.level, c.a.system, c.b.system]).lower()
                if q and not all(w in text for w in q):
                    continue
                if args.get("test") and c.test != args["test"]:
                    continue
                if args.get("in_model_only") and not (m.get("a") and m.get("b")):
                    continue
                row = self._row(c, m, ctx)
                if c.checks:   # which kept checks found it, by their names
                    names = {k["key"]: k["name"] for k in r.checks}
                    row["checks"] = [names.get(k, k) for k in c.checks]
                rows.append(row)
            limit = max(1, min(int(args.get("limit") or 30), 60))
            return {"total": len(rows), "clashes": rows[:limit]}, f"{len(rows)} clashes match", []
        if name == "get_clash":
            r = self._report(ctx)
            c = r.clash(args["clash_id"])
            m = self._matches(ctx).get(c.id, {})
            res = {**self._row(c, m, ctx), "point_m": c.point, "status": c.status, "tolerance_m": c.tolerance_m,
                   "element_a": asdict(c.a), "element_b": asdict(c.b), "model_ids": {"a": m.get("a"), "b": m.get("b")},
                   "images": [label for label, _ in c.images]}
            return res, f"{c.label}: {res['a']} vs {res['b']}", []
        if name == "look_at_clash_images":
            c = self._report(ctx).clash(args["clash_id"])
            pics = [p for _, p in c.images]
            return {"attached": [label for label, _ in c.images]}, f"{len(pics)} images", pics
        if name == "measure_clash":
            res = ws.measure(self._report(ctx).id, args["clash_id"], self._scene(ctx))
            d = res.get("distance_m")
            return res, "no overlap here" if d is None else f"{d * 1000:+.0f} mm", []
        if name == "describe_element":
            sid = self._scene(ctx)
            res = ws.describe(sid, args["global_id"])
            try:
                res["run"] = asdict(edits.run_of(ws.scene(sid), args["global_id"]))
            except (edits.Unsupported, KeyError, RuntimeError):
                pass
            return res, f"{res['ifc_class']} '{res['name']}'", []
        if name == "find_elements":
            scene = ws.scene(self._scene(ctx))
            words = (args.get("query") or "").lower().split()
            out = []
            for model in scene.models:
                for p in model.by_type(args.get("ifc_class") or "IfcProduct"):
                    text = f"{p.Name or ''} {getattr(p, 'Tag', '') or ''} {p.is_a()}".lower()
                    if all(w in text for w in words):
                        out.append({"global_id": p.GlobalId, "class": p.is_a(), "name": p.Name, "tag": getattr(p, "Tag", None)})
            limit = max(1, min(int(args.get("limit") or 20), 50))
            return {"total": len(out), "elements": out[:limit]}, f"{len(out)} elements", []
        if name == "find_openings":
            sid = self._scene(ctx)
            holes = edits.passages(ws.scene(sid), args["element"], args["obstacle"],
                                   ws.clearance(sid, args["element"], args["obstacle"]))
            return {"openings": holes}, f"{len(holes)} opening(s)", []
        if name == "check_move":
            v = ws.verify_move(self._scene(ctx), list(args["global_ids"]), [float(x) for x in args["delta_m"]],
                               obstacles=[args["obstacle"]] if args.get("obstacle") else [])
            v.pop("placements", None)
            why = v.get("reason") or f"{len(v['hits'])} hit(s)"
            return v, "passes" if v["passed"] else f"fails: {why}", []
        if name == "check_offset":
            v = ws.check_offset(self._scene(ctx), args["element"], args["obstacle"],
                                [float(x) for x in args["split_m"]], float(args["dz_m"]))
            v.pop("preview", None)
            return v, "passes" if v["passed"] else f"fails: {v['reason']}", []
        if name == "check_route":
            v = ws.check_route(self._scene(ctx), args["element"], args["obstacle"], list(args["steps"]))
            v.pop("preview", None)
            return v, "passes" if v["passed"] else f"fails: {v['reason']}", []
        if name == "check_resize":
            v = ws.check_resize(self._scene(ctx), args["element"], args["obstacle"], [float(x) for x in args["split_m"]],
                                float(args["depth_m"]), args.get("keep") or "bottom")
            v.pop("preview", None)
            return v, "passes" if v["passed"] else f"fails: {v['reason']}", []
        if name == "check_penetration":
            v = ws.check_penetration(self._scene(ctx), args["element"], args["host"])
            v.pop("preview", None)
            return v, "passes" if v["passed"] else f"fails: {v['reason']}", []
        if name == "check_seat":
            v = ws.check_seat(self._scene(ctx), args["element"], args["support"])
            v.pop("preview", None)
            return v, "passes" if v["passed"] else f"fails: {v['reason']}", []
        if name == "propose_fixes":
            second = bool(args.get("escalate"))
            r, sid = self._report(ctx), self._scene(ctx)
            c = r.clash(args["clash_id"])
            m = self._matches(ctx).get(c.id, {})
            if not (m.get("a") and m.get("b")):
                return {"error": "both elements must be in the open model"}, "not in the model", []
            recommend = second and ws.fix_settings(sid, m["a"], m["b"]).get("recommend")
            if recommend:   # nothing may be edited: no second try to make, and nothing charged for one
                return ({"error": f"Nothing may be edited here ({recommend}); a first try gives the recommendation."},
                        "no second try: recommendation only", [])
            refused = escalate_ok() if second else allowed()
            if refused:
                return {"error": refused}, "refused: " + ("no second try" if second else "allowance used"), []
            emit({"type": "ui", "action": "select_clash", "clash_id": c.id})
            on_event = lambda e: emit({"type": "agent", "event": e})   # noqa: E731
            if second:
                result = ws.escalate(sid, m["a"], m["b"], report_id=r.id, clash_id=c.id, on_event=on_event)
            else:
                result = ws.propose(sid, m["a"], m["b"], report_id=r.id, clash_id=c.id, on_event=on_event,
                                    escalate_check=escalate_ok)
            emit({"type": "proposal", "clash_id": c.id, "element_a": m["a"], "element_b": m["b"], **result})
            summary = [{"title": o["title"], "kind": o["kind"], "delta_m": o["delta_m"], "split_m": o["split_m"],
                        "edit": (o.get("edit") or {}).get("summary"), "review": o.get("review"),
                        "found_by": o.get("model") or None,
                        "clearance_mm": None if o["min_clearance_m"] is None else round(o["min_clearance_m"] * 1000)}
                       for o in result["options"]]
            failed = [{"title": a["title"], "reason": a["reason"]} for a in result["attempts"] if not a["passed"]]
            note = "The verified options are now in the user's options panel to preview and accept."
            if result.get("escalated"):
                note += " This was a second try on Muse Wonder: the first try's fixes are included."
            elif (not summary or all(o["kind"] in ("resize", "penetration") for o in summary)) and \
                    not result.get("recommendation") and settings.escalation() != "off":
                note += (" A second, longer try on Muse Wonder is possible (propose_fixes with escalate true) if the "
                         "user wants one.")
            return ({"understanding": result["understanding"], "verified_options": summary, "failed": failed[:8],
                     "advice": result.get("advice") or None, "note": note},
                    f"{len(summary)} verified of {len(result['attempts'])} tried", [])
        if name == "find_root_causes":
            r, sid = self._report(ctx), self._scene(ctx)
            causes = plans.root_causes(ws, sid, r.id, ctx.fixed)
            rows = [{"hub": c["hub"]["global_id"], "element": f"{c['hub']['ifc_class']} '{c['hub']['name']}'",
                     "level": c["hub"]["storey"], "file": c["hub"]["source"],
                     "clashes_with": [f"{p['ifc_class']} '{p['name']}' {p['distance_m'] * 1000:+.0f} mm"
                                      + ("" if p["in_report"] else " (NOT in the report)") for p in c["partners"]],
                     "cross_discipline": c["cross_discipline"] > 0} for c in causes]
            return {"root_causes": rows}, f"{len(rows)} candidate root cause(s)", []
        if name == "find_patterns":
            r, sid = self._report(ctx), self._scene(ctx)
            pats = plans.patterns(ws, sid, r.id, ctx.fixed)
            # The route's reading: one proposal the first time, then shared (a reading the page made is free here).
            verdicts, refused = plans.read_patterns(ws, sid, r.id, pats, allowed)
            if refused:
                return {"error": refused}, "refused: allowance used", []
            rows = [{"pattern": f"{p['clashes']} x {p['classes'][0]} vs {p['classes'][1]}", "files": p["files"],
                     "levels": p["levels"], "overlap_mm": [p["min_mm"], p["max_mm"]], "clash_ids": p["clash_ids"][:12],
                     **verdicts.get(p["id"], {})} for p in pats]
            return {"patterns": rows}, f"{len(rows)} pattern(s)", []
        if name in ("plan_root_cause", "plan_fixes_together"):
            n = (1 if name == "plan_root_cause"  # the fixes are charged later, only if the cause needs edits
                 else len(plans.pairs_for(ws, self._scene(ctx), self._report(ctx).id, list(args["clash_ids"]))[0]))
            refused = allowed_many(max(n, 1))
            if refused:
                return {"error": refused}, "refused: allowance used", []
            emit({"type": "plan_started", "kind": "root_cause" if name == "plan_root_cause" else "batch"})
            forward = lambda e: emit({"type": "plan_event", "event": e})
            plan = (plans.build_root_cause(ws, self._scene(ctx), self._report(ctx).id, args["hub"], ctx.fixed, forward,
                                           charge=allowed_many)
                    if name == "plan_root_cause"
                    else plans.build_batch(ws, self._scene(ctx), self._report(ctx).id, list(args["clash_ids"]), forward))
            data = json.loads(plans.to_json(plan))
            emit({"type": "plan", **data})
            summary = {"title": plan.title, "root_cause": plan.root_cause, "strategy": plan.strategy,
                       "verified_together": plan.check.get("passed"),
                       "fixes": [{"pair": it.label, "fix": it.option["title"] if it.option else None, "error": it.error,
                                  "in_report": it.in_report} for it in plan.items],
                       "note": "The plan is in the user's Plan tab to preview and accept; you cannot accept it."}
            # Counted in clashes, as the plan's title is: one fix can clear several (plans.merge_shared).
            n = plans.clashes_covered(plan.items)
            return summary, (f"{plans.clashes_covered([it for it in plan.items if it.option])} of {n} "
                             f"clash{'es' if n != 1 else ''} fixed, "
                             f"{'verified together' if plan.check.get('passed') else 'not all verified'}"), []
        if name == "show_clash":
            c = self._report(ctx).clash(args["clash_id"])
            emit({"type": "ui", "action": "select_clash", "clash_id": c.id})
            return {"shown": c.id}, f"showing {c.label}", []
        if name == "show_it_built":
            if not settings.built_views():
                return {"error": "Show it built is switched off here."}, "switched off", []
            c = self._report(ctx).clash(args["clash_id"])
            emit({"type": "ui", "action": "select_clash", "clash_id": c.id})
            emit({"type": "ui", "action": "show_it_built", "clash_id": c.id})
            return ({"note": "The page draws the chosen or kept fix of this clash and shows it beside ORCA's view when "
                             "it passes the check (about a minute). If no fix is chosen or kept, there is nothing to "
                             "draw: propose fixes first."}, f"drawing {c.label}", [])
        if name == "set_view":
            emit({"type": "ui", "action": "set_view", **{k: args[k] for k in ("mode", "section_box") if k in args}})
            return {"done": True}, "view changed", []
        if name in ("list_faces", "edit_check", "edit_keep", "undo_edit", "list_edits", "edit_property"):
            return self._edit_tool(name, args, ctx, emit)
        if name == "set_filters":
            idx = ws.facets(self._scene(ctx))
            try:
                made = [facets.resolve(idx, dict(spec), i) for i, spec in enumerate(args.get("filters") or [])]
            except facets.Unresolved as e:
                return {"error": str(e)}, "refused: not in the model", []
            emit({"type": "ui", "action": "filters", "mode": "replace", "filters": [r for r, _ in made],
                  **{k: bool(args[k]) for k in ("grey_rest", "hide_rest") if k in args}})
            found = [{"filter": r["name"] or r["action"], "elements": len(hit), **_coloured(idx, r, hit)} for r, hit in made]
            return {"filters": found}, ", ".join(f"{len(hit)} elements" for _, hit in made) or "no filters", []
        if name == "clear_filters":
            emit({"type": "ui", "action": "filters", "mode": "clear"})
            return {"done": True}, "filters cleared", []
        raise KeyError(f"unknown tool {name}")
