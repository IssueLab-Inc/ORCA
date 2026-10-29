"""ORCA as an MCP server, for agents (Muse Code, Claude, an IDE): the coordination run you have open, its
clashes, the model, verified fixes, pictures, the report.

Two ways in:
- **Remote**, mounted at `/mcp` on the web server (`app.py`, streamable HTTP). The agent presents a link token
  (`Authorization: Bearer <token>`, or `?key=<token>`), made in the app with "Connect an agent". It then works on that
  visitor's session: what they have open, and their open browser, which follows what the agent does.
- **Local**, over stdio: `uv run python -m sightline.mcp_server`. Its own session, no browser: open models with
  `open_models`, check them with `detect_clashes`, and so on.

The tools are the chat's (`chat.Chat._run`: the same operations as the web API, over `service.Workspace`) plus what
only an outside agent needs: what is open, pictures, jobs for long work, applying a fix, triage, the report, export.
Fixes cost proposals from the demo's allowance, charged to whoever made the link.
"""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image
from mcp_types import ToolAnnotations

from . import agents, chat, edits, plans, requirements
from .service import Workspace

INSTRUCTIONS = """ORCA is an AI design coordinator for 3D models (buildings from IFC, machines from STEP). It finds
clashes between models, proposes fixes that edit real model elements, and checks every fix with geometry before
anyone sees it. Start with get_session to see what is open. Then report_summary or list_clashes, get_clash and
get_clash_images to understand a clash, and check_move / check_offset / check_route to test your own idea, or propose_fixes to run
ORCA's fix agent. Nothing changes the model until apply_fix or apply_plan. Distances are metres, Z up; a negative
distance is an overlap. When a person has ORCA open with this link, show_clash and set_view move their view and
capture_view shows you what they see."""


@dataclass
class Hooks:
    """What the hosting web server lends the tools (`app.py`); `None` parts are not available there."""
    links: agents.Links | None = None                                # remote: links by token
    charge: Callable[[agents.Link, int], str | None] = lambda link, n: None   # proposals; why not, or None
    allow_call: Callable[[agents.Link], str | None] = lambda link: None     # per-link call cap
    start_triage: Callable[[str, str | None, agents.Link], Any] | None = None
    triage_state: Callable[[str, str | None], dict] | None = None
    build_document: Callable[[str, str | None, str], dict] | None = None
    spawn: Callable[[Callable[[], None]], Any] | None = None


def build(ws: Workspace | Callable[[], Workspace], hooks: Hooks | None = None,
          local: agents.Link | None = None) -> MCPServer:
    """The MCP server over `ws` (or a function returning the current one: tests swap the web server's). With
    `hooks.links` it serves remote agents by token; else every call works on `local` (stdio)."""
    hooks = hooks or Hooks()
    W: Callable[[], Workspace] = ws if callable(ws) and not isinstance(ws, Workspace) else (lambda: ws)  # type: ignore
    chats: dict[int, chat.Chat] = {}

    def T() -> chat.Chat:
        w = W()
        if id(w) not in chats:
            chats.clear()
            chats[id(w)] = chat.Chat(w)
        return chats[id(w)]
    mcp = MCPServer("orca", title="ORCA", instructions=INSTRUCTIONS,
                    website_url="https://dodzikojo--orca-web.us-east.modal.run")

    # ------------------------------------------------------------------ plumbing

    def tool(read_only: bool = False, **kw):
        """Register a tool whose expected failures (a bad id, nothing open, a refused allowance, an expired link)
        reach the agent as their own words; anything else stays a crash, logged here. `read_only`: it changes neither
        the model, the open report nor the allowance (clients such as Muse Code run those without asking)."""
        kw.setdefault("annotations", ToolAnnotations(read_only_hint=read_only, destructive_hint=False if read_only else None,
                                                     open_world_hint=False))
        def register(fn):
            @functools.wraps(fn)
            def guarded(*args, **kwargs):
                try:
                    with requirements.using(_link_requirements([*args, *kwargs.values()])):
                        return fn(*args, **kwargs)
                except ToolError:
                    raise
                except KeyError as e:
                    raise ToolError(str(e.args[0]) if e.args else "not found") from e
                except (PermissionError, LookupError, FileNotFoundError, ValueError, RuntimeError,
                        edits.Unsupported) as e:
                    raise ToolError(str(e)) from e
            return mcp.tool(**kw)(guarded)
        return register

    def _link_requirements(values: list) -> str | None:
        """The coordination requirements of the link a tool call came on (what its page set), else none."""
        ctx = next((v for v in values if isinstance(v, Context)), None)
        try:
            return link_of(ctx).requirements
        except PermissionError:
            return None

    def link_of(ctx: Context | None) -> agents.Link:
        if hooks.links is None:
            assert local is not None
            return local
        headers = ctx.headers if ctx is not None else None
        link = hooks.links.get(agents.token_from(headers or {}))
        if link is None:
            raise PermissionError("This agent link has expired or was revoked. Make a new one in ORCA: "
                                  "Connect an agent.")
        return link

    def base_url(ctx: Context | None) -> str:
        headers = (ctx.headers if ctx is not None else None) or {}
        host = headers.get("x-forwarded-host") or headers.get("host") or "localhost"
        proto = headers.get("x-forwarded-proto") or ("http" if host.startswith(("localhost", "127.")) else "https")
        return f"{proto}://{host}"

    def call(ctx: Context | None, tool: str, args: dict | None = None) -> agents.Link:
        link = link_of(ctx)
        refused = hooks.allow_call(link)
        if refused:
            raise PermissionError(refused)
        link.calls += 1
        link.last_call = {"tool": tool, "at": time.time()}
        link.publish({"type": "agent_call", "tool": tool, "args": _short(args or {}), "expires_at": link.expires})
        return link

    def done(link: agents.Link, tool: str, summary: str) -> None:
        link.publish({"type": "agent_result", "tool": tool, "summary": summary})

    def emit_for(link: agents.Link) -> Callable[[dict], None]:
        """Events the chat's tools send the page; proposals and plans are also kept for apply_fix / apply_plan."""
        def emit(e: dict) -> None:
            if e.get("type") == "proposal":
                link.proposals[e["clash_id"]] = e
            if e.get("type") == "plan":
                link.plans[_plan_id(e)] = e
            link.publish(e)
        return emit

    def run(ctx: Context | None, name: str, args: dict | None = None) -> dict:
        """One of the chat's tools, on this link's session."""
        args = args or {}
        link = call(ctx, name, args)
        result, summary, _ = T()._run(name, args, link.ctx, emit_for(link),
                                       propose_allowed=lambda: hooks.charge(link, 1),
                                       propose_allowed_many=lambda n: hooks.charge(link, n))
        done(link, name, summary)
        return result

    def job(ctx: Context | None, name: str, args: dict, wait_s: float, after: Callable[[dict], dict] | None = None) -> dict:
        """A chat tool that can take longer than a client waits: started as a job, waited on up to `wait_s`."""
        link = call(ctx, name, args)

        def work():
            result, summary, _ = T()._run(name, args, link.ctx, emit_for(link),
                                           propose_allowed=lambda: hooks.charge(link, 1),
                                           propose_allowed_many=lambda n: hooks.charge(link, n))
            done(link, name, summary)
            return after(result) if after else result
        return link.wait(link.start(name, work, hooks.spawn), wait_s)

    def need_report(link: agents.Link):
        if link.ctx.report_id not in W().reports:
            raise LookupError("No clashes are open. Call detect_clashes to check the open models.")
        return W().report(link.ctx.report_id)

    # ------------------------------------------------------------------ the session

    @tool(read_only=True)
    def get_session(ctx: Context) -> dict:
        """What is open in this ORCA session: the models, the clash report (how many clashes, how found), the clash
        the person has selected, what is fixed, whether triage has run, and whether their browser is connected."""
        link = call(ctx, "get_session")
        c = link.ctx
        out: dict[str, Any] = {"browser_connected": link.browser, "models": None, "report": None,
                               "selected_clash": c.clash_id, "fixed": list(c.fixed)}
        if c.scene_id in W().scenes:
            scene = W().scene(c.scene_id)
            out["models"] = {"files": [p.name for p in scene.paths], "elements": len(scene.bounds())}
        if c.report_id in W().reports:
            r = W().report(c.report_id)
            out["report"] = {"title": r.title, "clashes": len(r.clashes),
                             "found_by": "ORCA's own check" if r.origin == "sightline" else "a Navisworks report"}
            if hooks.triage_state is not None:
                t = hooks.triage_state(r.id, c.scene_id)
                out["triage"] = {"started": t.get("started", bool(t.get("results"))), "done": t.get("done", False),
                                 "verdicts": len(t.get("results") or {})}
        if out["models"] is None:
            out["next"] = ("Ask the person to open models in ORCA, or call open_models." if link.browser
                           else "Call list_models, then open_models.")
        elif not link.browser and hooks.links is not None:
            out["note"] = ("The person's ORCA page is closed: capture_view, pictures of clashes ORCA found, show_clash "
                           "and set_view need it open (they can resume the session in ORCA); everything else works.")
        done(link, "get_session", "session read")
        return out

    @tool(read_only=True)
    def list_models(ctx: Context) -> list[str]:
        """The models ORCA can open: IFC files, and STEP files (converted to IFC when they open)."""
        call(ctx, "list_models")
        return W().list_samples()

    @tool()
    def open_models(names: list[str], ctx: Context) -> dict:
        """Open models that share coordinates (e.g. the structure, MEP and architecture of one building) and check
        them for clashes. With a browser connected, the person's page opens them; else they open here."""
        link = call(ctx, "open_models", {"names": names})
        known = set(W().list_samples())
        missing = [n for n in names if n not in known]
        if missing:
            raise FileNotFoundError(f"not available: {', '.join(missing)}; see list_models")
        if link.browser:
            before = link.ctx.report_id
            link.publish({"type": "ui", "action": "open_models", "names": names})
            for _ in range(240):  # the page opens them, checks them and tells us (up to a minute)
                if link.ctx.report_id and link.ctx.report_id != before and link.ctx.scene_id in W().scenes:
                    break
                time.sleep(0.25)
            else:
                return {"status": "opening", "note": "The page is still opening them. Call get_session shortly."}
        else:
            link.ctx.scene_id = W().open(names)
            link.ctx.report_id, link.ctx.clash_id, link.ctx.fixed = None, None, []
            T()._run("detect_clashes", {}, link.ctx, lambda e: None)
        done(link, "open_models", f"opened {len(names)} model(s)")
        r = W().report(link.ctx.report_id) if link.ctx.report_id in W().reports else None
        return {"status": "open", "files": names, "clashes": len(r.clashes) if r else None}

    # ------------------------------------------------------------------ clashes

    @tool()
    def detect_clashes(ctx: Context, tolerance_mm: float | None = None) -> dict:
        """Check the open models for clashes with ORCA's own detection: every pair of models and each model against
        itself. Opens the result as the clash report (in the person's page too). Running it again after fixes says
        which clashes were resolved."""
        return run(ctx, "detect_clashes", {} if tolerance_mm is None else {"tolerance_mm": tolerance_mm})

    @tool(read_only=True)
    def report_summary(ctx: Context) -> dict:
        """Counts for the open clash report: per test and per element class pair (deepest overlap, how many only
        touch, whether a non-physical element is involved), how many are fixed."""
        return run(ctx, "report_summary")

    @tool(read_only=True)
    def list_clashes(ctx: Context, query: str = "", test: str = "", in_model_only: bool = False, limit: int = 30) -> dict:
        """Clashes in the open report, filtered by words (names, classes, levels, #numbers), test name or whether
        both elements are in the open model. Each row has its id, number, title, the two elements and the depth."""
        return run(ctx, "list_clashes", {"query": query, "test": test or None, "in_model_only": in_model_only,
                                         "limit": limit})

    @tool(read_only=True)
    def get_clash(clash_id: str, ctx: Context) -> dict:
        """Everything about one clash (id or #number): both elements, depth, clash point, the elements' ids in the
        model, whether it is fixed, and which pictures it has."""
        return run(ctx, "get_clash", {"clash_id": clash_id})

    @tool(read_only=True, structured_output=False)
    def get_clash_images(clash_id: str, ctx: Context) -> list:
        """The clash's pictures: A the pair, B with what is around it, C a second angle. Element A is red, B green.
        For a clash ORCA found, the person's page takes them if they do not exist yet (it needs the browser)."""
        link = call(ctx, "get_clash_images", {"clash_id": clash_id})
        c = need_report(link).clash(clash_id)
        if not c.images and link.browser:
            m = W().match(link.ctx.report_id, link.ctx.scene_id).get(c.id, {}) if link.ctx.scene_id in W().scenes else {}
            if m.get("a") and m.get("b"):
                link.capture("clash", wait_s=20, report_id=link.ctx.report_id, clash_id=c.id, a=m["a"], b=m["b"])
                c = W().report(link.ctx.report_id).clash(c.id)
        if not c.images:
            done(link, "get_clash_images", "no pictures")
            return ["No pictures for this clash yet: open ORCA with this link (the page takes them), or use get_clash."]
        done(link, "get_clash_images", f"{len(c.images)} pictures")
        out: list = [f"{c.label}: A (red) {c.a.ifc_class} '{c.a.name}', B (green) {c.b.ifc_class} '{c.b.name}'."]
        for label, path in c.images:
            out += [f"View {label}:", Image(path=Path(path))]
        return out

    @tool(read_only=True)
    def measure_clash(clash_id: str, ctx: Context) -> dict:
        """ORCA's own measure of a clash in the open model: signed distance in metres (negative = overlap)."""
        return run(ctx, "measure_clash", {"clash_id": clash_id})

    @tool(read_only=True)
    def show_clash(clash_id: str, ctx: Context) -> dict:
        """Select a clash in the person's page and fly their camera to it."""
        return run(ctx, "show_clash", {"clash_id": clash_id})

    @tool(read_only=True)
    def set_view(ctx: Context, mode: Literal["shaded", "xray", "context", "isolate"] | None = None,
                 section_box: bool | None = None) -> dict:
        """Change the person's 3D view: shaded, x-ray, context (what is near the clash) or isolate, and the section
        box around the clash."""
        args = {k: v for k, v in (("mode", mode), ("section_box", section_box)) if v is not None}
        return run(ctx, "set_view", args)

    @tool(read_only=True, structured_output=False)
    def capture_view(ctx: Context) -> list:
        """A picture of what the person's 3D view shows right now (needs their browser)."""
        link = call(ctx, "capture_view")
        got = link.capture("view")
        if not got:
            done(link, "capture_view", "no browser")
            return ["No browser answered: " + ("the person needs ORCA open with this link." if hooks.links is not None
                                                else "a local session has no browser to look at.")]
        done(link, "capture_view", "view captured")
        return ["The person's view now:", Image(data=got[0], format="png")]

    # ------------------------------------------------------------------ the model

    @tool(read_only=True)
    def describe_element(global_id: str, ctx: Context) -> dict:
        """An element of the open model: class, name, tag, level, file, what it connects to, and for a straight
        duct, pipe or tray segment its run (start, end, length, profile)."""
        return run(ctx, "describe_element", {"global_id": global_id})

    @tool(read_only=True)
    def find_elements(query: str, ctx: Context, ifc_class: str = "", limit: int = 20) -> dict:
        """Search the open model's elements by words in their name, tag or class."""
        return run(ctx, "find_elements", {"query": query, "ifc_class": ifc_class or None, "limit": limit})

    @tool(read_only=True)
    def find_openings(element: str, obstacle: str, ctx: Context) -> dict:
        """Openings through `obstacle` in line with the straight segment `element`, with the offset heights (dz,
        metres) that pass the segment through each with 25 mm clearance."""
        return run(ctx, "find_openings", {"element": element, "obstacle": obstacle})

    # ------------------------------------------------------------------ fixes

    @tool(read_only=True)
    def check_move(global_ids: list[str], delta_m: list[float], ctx: Context) -> dict:
        """Check moving elements by [dx, dy, dz] metres (Z up) against the whole model, without keeping it: passes,
        or what it would hit and how deep."""
        return run(ctx, "check_move", {"global_ids": global_ids, "delta_m": delta_m})

    @tool(read_only=True)
    def check_offset(element: str, obstacle: str, split_m: list[float], dz_m: float, ctx: Context) -> dict:
        """Check a local offset without keeping it: split the straight segment `element` at two points (metres along
        it from its start) around `obstacle`, and raise (+) or lower (-) the middle piece by dz_m with bends."""
        return run(ctx, "check_offset", {"element": element, "obstacle": obstacle, "split_m": split_m, "dz_m": dz_m})

    @tool(read_only=True)
    def check_route(element: str, obstacle: str, steps: list[dict], ctx: Context) -> dict:
        """Check a route without keeping it: hold stretches of the straight segment `element` at offsets past
        `obstacle`. Each step is {from_m, to_m, up_m, side_m}: metres along it from its start, and metres on its own
        axes (up; side = to the left of its direction seen from above). Steps that share a boundary change straight
        from one offset to the next; each change is one axis at a time. 90° bends join them."""
        return run(ctx, "check_route", {"element": element, "obstacle": obstacle, "steps": steps})

    @tool()
    def propose_fixes(clash_id: str, ctx: Context, wait_s: float = 40) -> dict:
        """Run ORCA's fix agent on a clash: it proposes moves, local offsets and trims, checks each against the whole
        model, and returns the verified ones (numbered options). The person's page shows it working. Takes 20-60 s;
        if it is not done within wait_s, you get a job_id for get_job. Costs one proposal from the allowance."""
        def numbered(result: dict) -> dict:
            for i, o in enumerate(result.get("verified_options") or [], 1):
                o["option"] = i
            if result.get("verified_options"):
                result["note"] = "Apply one with apply_fix(clash_id, option). The person can also accept it in ORCA."
            return result
        return job(ctx, "propose_fixes", {"clash_id": clash_id}, wait_s, numbered)

    @tool()
    def plan_fixes_together(clash_ids: list[str], ctx: Context, wait_s: float = 40) -> dict:
        """Fix several clashes in one plan, checked together so the fixes do not collide; clashes that share a
        movable element become one job. Returns a plan_id for apply_plan. Costs one proposal per distinct pair."""
        return job(ctx, "plan_fixes_together", {"clash_ids": clash_ids}, wait_s, lambda r: _with_plan_id(r, link_of(ctx)))

    @tool(read_only=True)
    def find_root_causes(ctx: Context) -> dict:
        """Elements in several real clashes at once (likely root causes), with clashes the geometry finds that the
        report missed."""
        return run(ctx, "find_root_causes")

    @tool()
    def plan_root_cause(hub: str, ctx: Context, wait_s: float = 40) -> dict:
        """For one element from find_root_causes: the cause, and one coordinated plan for all its clashes, checked
        together. Returns a plan_id for apply_plan. About a minute."""
        return job(ctx, "plan_root_cause", {"hub": hub}, wait_s, lambda r: _with_plan_id(r, link_of(ctx)))

    @tool()
    def find_patterns(ctx: Context) -> dict:
        """The same kind of clash many times over, each judged as by design, a modelling error or a real problem,
        with the clash rule or action to take."""
        return run(ctx, "find_patterns")

    @tool(read_only=True)
    def get_job(job_id: str, ctx: Context, wait_s: float = 30) -> dict:
        """The result of a long tool call (propose_fixes, a plan, triage, the report), waiting up to wait_s."""
        link = call(ctx, "get_job", {"job_id": job_id})
        j = link.jobs.get(job_id)
        if j is None:
            raise KeyError(f"no job {job_id} on this link")
        return link.wait(j, wait_s)

    @tool()
    def apply_fix(clash_id: str, ctx: Context, option: int = 1) -> dict:
        """Keep a verified option from propose_fixes in the model (option numbers start at 1). The person's page
        reloads the changed file and marks the clash fixed. Export with export_models."""
        link = call(ctx, "apply_fix", {"clash_id": clash_id, "option": option})
        c = need_report(link).clash(clash_id)
        proposal = link.proposals.get(c.id)
        options = (proposal or {}).get("options") or []
        if not 1 <= option <= len(options):
            raise LookupError(f"no verified option {option} for {c.label}: run propose_fixes first")
        o = options[option - 1]
        before = W().scene(link.ctx.scene_id).revision
        out = plans.apply(W(), link.ctx.scene_id, [o])
        out = {**out, **W().patch(link.ctx.scene_id, out["changed"], before)}
        pairs = [[proposal["element_a"], proposal["element_b"]]]
        _applied(link, out, pairs, [o["title"]], [c.id], {c.id: o["title"]})
        done(link, "apply_fix", f"applied '{o['title']}'")
        return {"applied": o["title"], "kind": o["kind"], "clash": c.label, "files_changed": len(out["files"])}

    @tool()
    def apply_plan(plan_id: str, ctx: Context) -> dict:
        """Keep every verified fix of a plan from plan_fixes_together or plan_root_cause."""
        link = call(ctx, "apply_plan", {"plan_id": plan_id})
        p = link.plans.get(plan_id)
        if p is None:
            raise LookupError(f"no plan {plan_id} on this link")
        check = p.get("check") or {}
        items = [it for it in p["items"] if it.get("option") and (check.get("passed")
                                                                  or check.get("items", {}).get(it["key"], {}).get("passed"))]
        if not items:
            raise LookupError("this plan has no verified fix to apply")
        before = W().scene(link.ctx.scene_id).revision
        out = plans.apply(W(), link.ctx.scene_id, [it["option"] for it in items])
        out = {**out, **W().patch(link.ctx.scene_id, out["changed"], before)}
        pairs = [[it["element_a"], o] for it in items for o in [it["element_b"], *(it.get("others") or [])]]
        titles = [it["option"]["title"] for it in items for _ in [it["element_b"], *(it.get("others") or [])]]
        _applied(link, out, pairs, titles, [cid for it in items for cid in it["clash_ids"]],
                 {cid: it["option"]["title"] for it in items for cid in it["clash_ids"]})
        done(link, "apply_plan", f"applied {len(items)} fix(es)")
        return {"applied": [it["option"]["title"] for it in items], "files_changed": len(out["files"])}

    def _applied(link: agents.Link, out: dict, pairs: list, titles: list, clash_ids: list,
                 fixed: dict[str, str]) -> None:
        """Tell the page what changed, and remember the agent's fixes (a page that resumes later marks them)."""
        link.ctx.fixed = list(dict.fromkeys([*link.ctx.fixed, *clash_ids]))
        link.applied.update(fixed)
        link.publish({"type": "ui", "action": "applied", "files": out["files"], "pieces": out["pieces"],
                      "pairs": pairs, "titles": titles, "clash_ids": clash_ids,
                      **{k: out.get(k) for k in ("scene_id", "revision_before", "revision", "meshes")}})

    # ------------------------------------------------------------------ triage, report, export

    @tool()
    def triage(ctx: Context, wait_s: float = 40) -> dict:
        """Sort every clash in the report: real problem, by design, not physical or a modelling error, with severity
        and who should act. One run per report; starting one costs one proposal, reading one is free. The person's
        Triage card follows along."""
        link = call(ctx, "triage")
        if hooks.start_triage is None or hooks.triage_state is None:
            raise RuntimeError("triage is not available here")
        r = need_report(link)
        tjob = hooks.start_triage(r.id, link.ctx.scene_id, link)
        link.publish({"type": "ui", "action": "follow_triage"})

        def summary() -> dict:
            state = hooks.triage_state(r.id, link.ctx.scene_id)
            results = state.get("results") or {}
            counts: dict[str, int] = {}
            for v in results.values():
                counts[v.get("verdict", "?")] = counts.get(v.get("verdict", "?"), 0) + 1
            real = [{"clash_id": cid, "number": f"#{r.clash(cid).number}", "severity": v.get("severity"),
                     "understanding": v.get("understanding"), "responsible": v.get("responsible")}
                    for cid, v in results.items() if v.get("verdict") == "real_clash"]
            return {"done": state.get("done", False), "verdicts": counts, "read": len(results),
                    "of": len(r.clashes), "real_clashes": real[:40]}

        deadline = time.time() + max(0.0, min(wait_s, 55.0))
        while time.time() < deadline and not getattr(tjob, "done", True):
            time.sleep(0.5)
        out = summary()
        if not out["done"]:
            j = link.start("triage", lambda: (_wait_for(lambda: getattr(tjob, "done", True)), summary())[1], hooks.spawn)
            out["job_id"] = j.id
            out["note"] = "Still sorting. Call get_job with this job_id for the final counts."
        done(link, "triage", f"{out['read']} of {out['of']} sorted")
        return out

    @tool()
    def generate_report(ctx: Context, scope: Literal["combined", "team", "model"] = "combined",
                        wait_s: float = 40) -> dict:
        """The design coordination report: a PDF (one, or one per team or per model) with BCF issues, built from the
        triage (run triage first). Returns a download link. Costs one proposal."""
        link = call(ctx, "generate_report", {"scope": scope})
        if hooks.build_document is None:
            raise RuntimeError("reports are not available here")
        r = need_report(link)
        refused = hooks.charge(link, 1)
        if refused:
            raise PermissionError(refused)
        base = base_url(ctx)

        def work():
            doc = hooks.build_document(r.id, link.ctx.scene_id, scope)
            done(link, "generate_report", doc["name"])
            return {**doc, "url": base + doc["path"] if hooks.links is not None else doc.get("file", doc["path"])}
        return link.wait(link.start("generate_report", work, hooks.spawn), wait_s)

    @tool()
    def export_models(ctx: Context) -> dict:
        """The edited models: IFC (and STEP for models opened from STEP) with every applied fix. Returns a download
        link (remote) or file paths (local)."""
        link = call(ctx, "export_models")
        sid = link.ctx.scene_id
        if sid not in W().scenes:
            raise LookupError("no models are open")
        if hooks.links is not None:
            done(link, "export_models", "download link")
            return {"url": f"{base_url(ctx)}/api/scenes/{sid}/export",
                    "note": "One file, or a zip when several models changed. 409 means nothing was applied yet."}
        import tempfile
        paths = W().export(sid, Path(tempfile.mkdtemp(prefix="orca-export-")))
        done(link, "export_models", f"{len(paths)} file(s)")
        return {"files": [str(p) for p in paths]}

    return mcp


# ---------------------------------------------------------------------------------------------------------- helpers

def _short(args: dict) -> dict:
    """Arguments as the page shows them: long lists cut."""
    return {k: (v[:6] + ["…"] if isinstance(v, list) and len(v) > 6 else v) for k, v in args.items()}


def _plan_id(event: dict) -> str:
    keys = "|".join(sorted(it.get("key", "") for it in event.get("items") or []))
    return f"p{abs(hash((event.get('kind'), keys))) % 10**8:08d}"


def _with_plan_id(result: dict, link: agents.Link) -> dict:
    """A plan tool's summary, with the id apply_plan takes (the newest plan this link built)."""
    if link.plans:
        result["plan_id"] = next(reversed(link.plans))
        result["note"] = "Apply its verified fixes with apply_plan(plan_id). The person can also accept it in ORCA."
    return result


def _wait_for(cond: Callable[[], bool], timeout: float = 600) -> None:
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        time.sleep(0.5)


def main() -> None:
    """stdio: a local session over the same workspace and helpers the web server uses."""
    from . import app as web
    local = agents.Link("local", "", "local", True, time.time(), float("inf"))
    hooks = web.mcp_hooks()
    hooks.links = None  # every call is this process's own session
    build(web.ws, hooks, local=local).run()


if __name__ == "__main__":
    main()
