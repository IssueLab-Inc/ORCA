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
import threading
import uuid
from collections import Counter, OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import context_planner, domains, edits, facets, plans, settings
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


TOOLS = [
    _fn('explore_wider_fix', 'Explore a complete coordinated arrangement for one clash, including surrounding '
        'elements when needed. Use when the user asks to move other objects or a single-element fix is blocked. '
        'Costs three proposal units; shows whole proposals for designer review. You cannot accept them.',
        {'clash_id': {'type': 'string'}}, ['clash_id']),
    _fn("detect_clashes", "Find the clashes in the open models with ORCA's own detection, no Navisworks report "
        "needed: every pair of models and each model against itself (hard clashes deeper than the tolerance, 1 mm by "
        "default) and duplicates. Pairs meant to meet (joined by ports, one assembly, a door in its wall) and touches "
        "are counted, not reported. Takes about 10 s and opens the result as the user's clash report, replacing the open "
        "one; running it again after fixes says which clashes were resolved. Each run counts against the demo's "
        "detection runs.",
        {"tolerance_mm": {"type": "number", "description": "hard clash tolerance in mm (default 1)"}}),
    _fn("report_summary", "Counts for the open clash report: clashes per test and per element class pair, how many "
        "are found in the open model, how many are fixed. Start here for questions about the whole report."),
    _fn("list_clashes", "List clashes in the report, optionally filtered. Returns at most `limit` rows.", {
        "query": {"type": "string", "description": "words to match in names, classes, levels, test names"},
        "test": {"type": "string", "description": "exact clash test name"},
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
        "Viewing only: checks and fixes never see filters.", {
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
            "grey_rest": {"type": "boolean", "description": "grey what no filter colours"}}, ["filters"]),
    _fn("clear_filters", "Remove the filters you set; the user's own come back."),
]


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

    def _context_line(self, ctx: Context) -> str:
        parts = ["[context]"]
        parts.append("a model is open" if ctx.scene_id in self.ws.scenes else "no model is open")
        if ctx.report_id in self.ws.reports:
            r = self.ws.report(ctx.report_id)
            source = "found by ORCA's own detection" if r.origin == "sightline" else "from Navisworks"
            parts.append(f"clash report '{r.title}' is open ({len(r.clashes)} clashes, {source})")
        else:
            parts.append("no clash report is open")
        if ctx.clash_id:
            parts.append(f"the user has clash {ctx.clash_id} selected")
        if ctx.fixed:
            parts.append(f"fixed so far: {', '.join(ctx.fixed[:30])}")
        return "; ".join(parts)

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

    def _report(self, ctx: Context):
        if ctx.report_id not in self.ws.reports:
            raise LookupError("no clashes are open: check the open models with detect_clashes, or ask the user to import a report "
                              "from 'Coordinate'")
        return self.ws.report(ctx.report_id)  # type: ignore[arg-type]

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
            if args.get("tolerance_mm") is not None:
                tol = max(0.0, float(args["tolerance_mm"])) / 1000
                tests = [{**t, "tolerance_m": tol if t["kind"] == "hard" else t["tolerance_m"]}
                         for t in ws.detect_tests(sid)["tests"] if t["enabled"]]
            refused = detect_ok()   # one detection run, as POST /detect/stream takes
            if refused:
                return {"error": refused}, "refused: detection runs used", []
            out = ws.detect(sid, tests, on_event=lambda e: emit({"type": "detect_event", "event": e}))
            rid = out["report"]["id"]
            ctx.report_id = rid  # the rest of this answer works on the new report
            detection = {k: out[k] for k in ("coverage", "diff", "elements", "seconds")}
            emit({"type": "ui", "action": "open_report", "report_id": rid, "detection": detection})
            n = len(out["report"]["clashes"])
            diff = out["diff"]
            summary = {"report_id": rid, "clashes": n, "seconds": out["seconds"], "elements": out["elements"],
                       "tests": [{"test": c["name"], "clashes": c["clashes"], "touching": c["touching"],
                                  "meant_to_meet": c["excluded"], "partial": c["partial"]} for c in out["coverage"]],
                       "since_last_run": None if diff.get("first") else {
                           "new": len(diff["new"]), "resolved": len(diff["resolved"]),
                           "no_longer_checked": len(diff["no_longer_checked"])},
                       "note": "The result is now the open clash report. Triage sorts real problems from noise."}
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
                   "fixed": len(ctx.fixed), "by_test": dict(tests.most_common(80)),
                   "by_class_pair": dict(sorted(pairs.items(), key=lambda kv: kv[1]["worst_mm"])),
                   "note": "non_physical_side: a space, port or opening is involved (not a physical clash); "
                           "touching: results within 1 mm (usually connections)."}
            return res, f"{len(r.clashes)} clashes in {len(tests)} tests, {in_model} in the model", []
        if name == "list_clashes":
            r, matches = self._report(ctx), self._matches(ctx)
            q = (args.get("query") or "").lower().split()
            rows = []
            for c in r.clashes:
                m = matches.get(c.id, {})
                text = " ".join(str(x) for x in [f"#{c.number}", c.title, c.name, c.test, c.a.name, c.b.name, c.a.ifc_class, c.b.ifc_class,
                                                 c.a.level, c.b.level, c.a.system, c.b.system]).lower()
                if q and not all(w in text for w in q):
                    continue
                if args.get("test") and c.test != args["test"]:
                    continue
                if args.get("in_model_only") and not (m.get("a") and m.get("b")):
                    continue
                rows.append(self._row(c, m, ctx))
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
        if name == "set_filters":
            idx = ws.facets(self._scene(ctx))
            try:
                made = [facets.resolve(idx, dict(spec), i) for i, spec in enumerate(args.get("filters") or [])]
            except facets.Unresolved as e:
                return {"error": str(e)}, "refused: not in the model", []
            emit({"type": "ui", "action": "filters", "mode": "replace", "filters": [r for r, _ in made],
                  **({"grey_rest": bool(args["grey_rest"])} if "grey_rest" in args else {})})
            found = [{"filter": r["name"] or r["action"], "elements": n} for r, n in made]
            return {"filters": found}, ", ".join(f"{n} elements" for _, n in made) or "no filters", []
        if name == "clear_filters":
            emit({"type": "ui", "action": "filters", "mode": "clear"})
            return {"done": True}, "filters cleared", []
        raise KeyError(f"unknown tool {name}")
