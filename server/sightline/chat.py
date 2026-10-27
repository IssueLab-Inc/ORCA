"""Chat with Muse Spark over the open clash report and model, through tools.

The tools are the same operations the web API and the MCP server use (`service.Workspace`), so the chat can do
what the UI can: list and read clashes, look at their Navisworks images, describe and find elements, measure, find
openings, check a move or an offset, and propose verified fixes. Two tools act on the browser instead
(`show_clash`, `set_view`): they come back as "ui" events for the page to carry out.

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
import uuid
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import edits, plans
from .meta_client import ToolModel, image_part
from .service import Workspace

PROMPT = Path(__file__).parent / "domain_packs" / "chat.md"
MAX_STEPS = 8          # model calls per user message
MAX_SESSIONS = 200
MAX_HISTORY = 40       # messages kept per session (oldest dropped first, the system prompt stays)
NOT_PHYSICAL = {"IfcSpace", "IfcDistributionPort", "IfcOpeningElement", "IfcVirtualElement", "IfcZone"}


def _fn(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or []}}}


TOOLS = [
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
    _fn("measure_clash", "Sightline's own geometry measure of a clash (signed distance, metres; negative = overlap).",
        {"clash_id": {"type": "string"}}, ["clash_id"]),
    _fn("describe_element", "An element of the open model: class, name, tag, level, file, connected elements, and for "
        "a straight duct/pipe/tray segment its run (start, end, length, profile).", {"global_id": {"type": "string"}},
        ["global_id"]),
    _fn("find_elements", "Search the open model's elements by words in their name, tag or class.", {
        "query": {"type": "string"}, "ifc_class": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
    _fn("find_openings", "Openings through `obstacle` on the line of the straight segment `element`, with the "
        "offset heights (dz, metres) that pass the segment through each with 25 mm clearance.",
        {"element": {"type": "string"}, "obstacle": {"type": "string"}}, ["element", "obstacle"]),
    _fn("check_move", "Check moving elements by [dx, dy, dz] metres (Z up) against the whole model, without keeping it.",
        {"global_ids": {"type": "array", "items": {"type": "string"}},
         "delta_m": {"type": "array", "items": {"type": "number"}}}, ["global_ids", "delta_m"]),
    _fn("check_offset", "Check a local offset without keeping it: split the straight segment `element` at two points "
        "(metres along it from its start) around `obstacle` and raise (+) or lower (-) the middle by dz_m.",
        {"element": {"type": "string"}, "obstacle": {"type": "string"},
         "split_m": {"type": "array", "items": {"type": "number"}}, "dz_m": {"type": "number"}},
        ["element", "obstacle", "split_m", "dz_m"]),
    _fn("propose_fixes", "Run Sightline's fix agent on a clash: it proposes moves, local offsets and trims at joints, checks each "
        "against the whole model, and shows the verified ones in the options panel for the user to preview and "
        "accept. Takes about 20 s and counts against the demo's proposal allowance; use it when the user wants fixes.",
        {"clash_id": {"type": "string"}}, ["clash_id"]),
    _fn("find_root_causes", "Elements that are in several real clashes at once (the likely root causes), with clashes "
        "the geometry finds that the Navisworks report missed. Use it for 'why are there so many clashes here' or "
        "'what is the real problem'."),
    _fn("find_patterns", "Patterns: the same kind of clash many times over (every column through every slab, members "
        "all overlapping by the same 30 mm), each judged as by design, a modelling error or a real problem, with the "
        "clash rule or action to take. Use it for 'what is all this noise' or before triaging a big report."),
    _fn("plan_root_cause", "For one element from find_root_causes: work out the cause and build one coordinated plan "
        "that fixes all its clashes, checked together. Shows the plan in the user's Plan tab to preview and accept. "
        "About a minute; costs one proposal per clashing element.", {"hub": {"type": "string", "description": "GlobalId"}},
        ["hub"]),
    _fn("plan_fixes_together", "Fix several clashes in one plan: a fix for each, checked together so they do not "
        "collide. Shows the plan in the user's Plan tab. Costs one proposal per distinct pair (at most 8).",
        {"clash_ids": {"type": "array", "items": {"type": "string"}}}, ["clash_ids"]),
    _fn("show_clash", "Select a clash in the user's view and fly the camera to it.", {"clash_id": {"type": "string"}},
        ["clash_id"]),
    _fn("set_view", "Change the user's 3D view.", {
        "mode": {"type": "string", "enum": ["shaded", "xray", "context", "isolate"]},
        "section_box": {"type": "boolean"}}),
]


@dataclass
class Session:
    id: str
    messages: list[dict] = field(default_factory=list)


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

    @property
    def model(self) -> ToolModel:
        if self._model is None:
            self._model = self.ws.model  # the same Meta client; it also does tool calls
        return self._model  # type: ignore[return-value]

    def session(self, session_id: str | None) -> Session:
        if session_id and session_id in self.sessions:
            self.sessions.move_to_end(session_id)
            return self.sessions[session_id]
        s = Session(uuid.uuid4().hex[:12], [{"role": "system", "content": PROMPT.read_text()}])
        self.sessions[s.id] = s
        while len(self.sessions) > MAX_SESSIONS:
            self.sessions.popitem(last=False)
        return s

    def turn(self, session: Session, text: str, ctx: Context, emit: Callable[[dict], None]) -> str:
        session.messages.append({"role": "user", "content": f"{self._context_line(ctx)}\n\n{text}"})
        answer = ""
        for _ in range(MAX_STEPS):
            emit({"type": "thinking"})
            reply = self.model.chat(session.messages, TOOLS)
            calls = reply.get("tool_calls") or []
            session.messages.append({k: v for k, v in reply.items() if k in ("role", "content", "tool_calls") and v}
                                    | {"role": "assistant"})
            if not calls:
                answer = reply.get("content") or ""
                break
            images: list[Path] = []
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                emit({"type": "tool", "name": name, "args": args})
                try:
                    result, summary, pics = self._run(name, args, ctx, emit)
                except Exception as e:  # a bad id, a shape that cannot be edited: tell the model, keep going
                    result, summary, pics = {"error": f"{type(e).__name__}: {e}"}, f"failed: {e}", []
                images += pics
                emit({"type": "tool_result", "name": name, "summary": summary})
                session.messages.append({"role": "tool", "tool_call_id": call["id"],
                                         "content": json.dumps(result, default=str)[:12000]})
            if images:  # tool results are text only; images go to the model as the next user message
                session.messages.append({"role": "user", "content": [
                    {"type": "text", "text": "The clash images you asked for (A, B, C):"}] + [image_part(p) for p in images]})
        else:
            answer = "I ran out of steps on that one. Ask me to carry on, or narrow the question."
        self._trim(session)
        emit({"type": "message", "text": answer})
        return answer

    def _context_line(self, ctx: Context) -> str:
        parts = ["[context]"]
        parts.append("a model is open" if ctx.scene_id in self.ws.scenes else "no model is open")
        if ctx.report_id in self.ws.reports:
            r = self.ws.report(ctx.report_id)
            parts.append(f"clash report '{r.title}' is open ({len(r.clashes)} clashes)")
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
            raise LookupError("no clash report is open: ask the user to open one from 'Clash report'")
        return self.ws.report(ctx.report_id)  # type: ignore[arg-type]

    def _matches(self, ctx: Context) -> dict:
        return self.ws.match(ctx.report_id, ctx.scene_id) if ctx.scene_id in self.ws.scenes else {}  # type: ignore

    def _row(self, c, m: dict, ctx: Context) -> dict:
        return {"clash_id": c.id, "name": c.name, "test": c.test,
                "a": f"{c.a.ifc_class} '{c.a.name}'", "b": f"{c.b.ifc_class} '{c.b.name}'",
                "level": c.a.level or c.b.level, "distance_mm": round(c.distance_m * 1000) if c.distance_m is not None else None,
                "in_model": bool(m.get("a") and m.get("b")), "fixed": c.id in ctx.fixed}

    def _run(self, name: str, args: dict, ctx: Context, emit) -> tuple[dict, str, list[Path]]:
        ws = self.ws
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
                text = " ".join(str(x) for x in [c.name, c.test, c.a.name, c.b.name, c.a.ifc_class, c.b.ifc_class,
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
            return res, f"{c.name}: {res['a']} vs {res['b']}", []
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
            holes = edits.passages(ws.scene(self._scene(ctx)), args["element"], args["obstacle"])
            return {"openings": holes}, f"{len(holes)} opening(s)", []
        if name == "check_move":
            v = ws.verify_move(self._scene(ctx), list(args["global_ids"]), [float(x) for x in args["delta_m"]])
            v.pop("placements", None)
            return v, "passes" if v["passed"] else f"fails: {len(v['hits'])} hit(s)", []
        if name == "check_offset":
            v = ws.check_offset(self._scene(ctx), args["element"], args["obstacle"],
                                [float(x) for x in args["split_m"]], float(args["dz_m"]))
            v.pop("preview", None)
            return v, "passes" if v["passed"] else f"fails: {v['reason']}", []
        if name == "propose_fixes":
            refused = self.propose_allowed()
            if refused:
                return {"error": refused}, "refused: allowance used", []
            r, sid = self._report(ctx), self._scene(ctx)
            c = r.clash(args["clash_id"])
            m = self._matches(ctx).get(c.id, {})
            if not (m.get("a") and m.get("b")):
                return {"error": "both elements must be in the open model"}, "not in the model", []
            emit({"type": "ui", "action": "select_clash", "clash_id": c.id})
            result = ws.propose(sid, m["a"], m["b"], report_id=r.id, clash_id=c.id,
                                on_event=lambda e: emit({"type": "agent", "event": e}))
            emit({"type": "proposal", "clash_id": c.id, "element_a": m["a"], "element_b": m["b"], **result})
            summary = [{"title": o["title"], "kind": o["kind"], "delta_m": o["delta_m"], "split_m": o["split_m"],
                        "clearance_mm": None if o["min_clearance_m"] is None else round(o["min_clearance_m"] * 1000)}
                       for o in result["options"]]
            failed = [{"title": a["title"], "reason": a["reason"]} for a in result["attempts"] if not a["passed"]]
            return ({"understanding": result["understanding"], "verified_options": summary, "failed": failed[:8],
                     "note": "The verified options are now in the user's options panel to preview and accept."},
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
            verdicts = plans.triage_patterns(ws, pats) if pats else {}
            rows = [{"pattern": f"{p['clashes']} x {p['classes'][0]} vs {p['classes'][1]}", "files": p["files"],
                     "levels": p["levels"], "overlap_mm": [p["min_mm"], p["max_mm"]], "clash_ids": p["clash_ids"][:12],
                     **verdicts.get(p["id"], {})} for p in pats]
            return {"patterns": rows}, f"{len(rows)} pattern(s)", []
        if name in ("plan_root_cause", "plan_fixes_together"):
            n = (1 if name == "plan_root_cause"  # the fixes are charged later, only if the cause needs edits
                 else len(plans.pairs_for(ws, self._scene(ctx), self._report(ctx).id, list(args["clash_ids"]))[0]))
            refused = self.propose_allowed_many(max(n, 1))
            if refused:
                return {"error": refused}, "refused: allowance used", []
            emit({"type": "plan_started", "kind": "root_cause" if name == "plan_root_cause" else "batch"})
            forward = lambda e: emit({"type": "plan_event", "event": e})
            plan = (plans.build_root_cause(ws, self._scene(ctx), self._report(ctx).id, args["hub"], ctx.fixed, forward,
                                           charge=self.propose_allowed_many)
                    if name == "plan_root_cause"
                    else plans.build_batch(ws, self._scene(ctx), self._report(ctx).id, list(args["clash_ids"]), forward))
            data = json.loads(plans.to_json(plan))
            emit({"type": "plan", **data})
            summary = {"root_cause": plan.root_cause, "strategy": plan.strategy, "verified_together": plan.check.get("passed"),
                       "fixes": [{"pair": it.label, "fix": it.option["title"] if it.option else None, "error": it.error,
                                  "in_report": it.in_report} for it in plan.items],
                       "note": "The plan is in the user's Plan tab to preview and accept; you cannot accept it."}
            return summary, f"{sum(1 for it in plan.items if it.option)} of {len(plan.items)} fixed, "                             f"{'verified together' if plan.check.get('passed') else 'not all verified'}", []
        if name == "show_clash":
            c = self._report(ctx).clash(args["clash_id"])
            emit({"type": "ui", "action": "select_clash", "clash_id": c.id})
            return {"shown": c.id}, f"showing {c.name}", []
        if name == "set_view":
            emit({"type": "ui", "action": "set_view", **{k: args[k] for k in ("mode", "section_box") if k in args}})
            return {"done": True}, "view changed", []
        raise KeyError(f"unknown tool {name}")
