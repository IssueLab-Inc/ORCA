"""Bulk triage: a verdict on every clash in a report, from an open-weights model where one is configured.

Most raw clash results are noise. Before anyone opens a clash, every result gets a verdict (real clash, by design,
non-physical, modelling error), a severity, the discipline that should act and one sentence of understanding.

Sure cases are settled by rule and cost no model call: a space, port or opening on either side is not physical, and
a result within 1 mm is a touch. The rest go to the triage model one call per clash, many at a time. The model is
Muse Spark Open (open weights, served by Baseten) when `TRIAGE_API_KEY` is set (see `meta_client.triage_model`),
otherwise Muse Spark on Meta's API; every result says which model produced it.

The evaluation over the Northbank Navisworks package (`evals/navisworks_triage.py`) uses the same prompt, schema
and rules, so its scores describe what the app does.
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from . import domains, owner, requirements as reqs
from .meta_client import ChatModel
from .reports import Report, ReportClash

NON_PHYSICAL = {"IfcSpace", "IfcDistributionPort", "IfcOpeningElement", "IfcVirtualElement", "IfcZone"}
TOUCH_M = 0.001  # |distance| at or under this is a touch

SCHEMA = {
    "type": "object",
    "properties": {
        "understanding": {"type": "string"},
        "verdict": {"type": "string", "enum": ["real_clash", "by_design", "non_physical", "modelling_error"]},
        "severity": {"type": "string", "enum": ["high", "medium", "low", "none"]},
        "responsible": {"type": "string"},  # a team of the report's models (`teams`), or "none": schema_for
        "action": {"type": "string", "enum": ["move_A", "move_B", "modify_A", "modify_B", "exclude_with_rule",
                                              "fix_model", "none"]},
        "fix_hint": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["understanding", "verdict", "severity", "responsible", "action", "fix_hint", "confidence"],
    "additionalProperties": False,
}


def describe(c: ReportClash) -> str:
    """The clash as text: classes, names, files, levels, signed distance, point."""
    def line(label: str, colour: str, e) -> str:
        s = f"Element {label} ({colour}): {e.ifc_class} '{e.name}', {e.file}, level {e.level}"
        if e.part_of:
            s += f", part of '{e.part_of}'"
        if e.system:
            s += f", system {e.system}"
        if e.description:
            s += f" ({e.description})"
        return s
    lines = [f"Clash test: {c.test} ({c.test_type or 'hard'}, tolerance {(c.tolerance_m or 0) * 1000:.0f} mm)",
             line("A", "red", c.a), line("B", "green", c.b)]
    if c.distance_m is not None:
        lines.append(f"Signed distance: {c.distance_m * 1000:.1f} mm (negative = overlap)")
    if c.point:
        lines.append(f"Clash point: {[round(v, 3) for v in c.point if v is not None]} m, Z up")
    return "\n".join(lines)


def _kind(cls: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", cls.removeprefix("Ifc")).lower()


def not_a_clash(basis: str, understanding: str, fix_hint: str) -> dict:
    """A settled "this needs no fix" verdict. `basis` says what settled it: non_physical, touch, same_element."""
    return {"verdict": "by_design" if basis != "non_physical" else "non_physical", "severity": "none",
            "responsible": "none", "action": "exclude_with_rule", "understanding": understanding,
            "fix_hint": fix_hint, "confidence": 1.0, "basis": basis}


def by_rule(c: ReportClash) -> dict | None:
    """The verdict when it is certain without a model, else None. Says why, and the clash rule that stops it
    coming back in the next run."""
    np = next((e for e in (c.a, c.b) if e.ifc_class in NON_PHYSICAL), None)
    if np:
        other = c.b if np is c.a else c.a
        return not_a_clash(
            "non_physical",
            f"Not a clash: {np.name or 'one side'} is a {_kind(np.ifc_class)}, which takes no space on site, so it "
            f"cannot collide with {other.name or 'the other element'}.",
            f"In the clash test, leave {_kind(np.ifc_class)}s out of the selection sets (or add a rule that ignores "
            f"{np.ifc_class}).")
    if c.distance_m is not None and abs(c.distance_m) <= TOUCH_M:
        return not_a_clash(
            "touch",
            f"Not a clash: {c.a.name or 'A'} and {c.b.name or 'B'} only touch ({abs(c.distance_m) * 1000:.0f} mm), "
            "which is how parts meet when they are built.",
            "Run hard tests with a small tolerance (e.g. 10 mm) or as Hard (conservative) so touching faces are not "
            "reported.")
    return None


def same_element(c: ReportClash) -> dict:
    """Both sides are one model element (a port and its own valve, two Navisworks parts of one door)."""
    ports = sum(1 for e in (c.a, c.b) if (e.ifc_class or "").endswith("Port"))
    what = ("two of its ports" if ports == 2 else "a port with the element it belongs to" if ports == 1
            else "two parts of it")
    name = c.a.part_of or c.b.part_of or c.a.name
    return not_a_clash(
        "same_element",
        f"Not a clash: both sides are the same element in the model ({name}); Navisworks clashed {what}. There is "
        "nothing to move.",
        "Add a clash rule that ignores items within the same composite object (Navisworks: Rules, \"Items in same "
        "composite object\").")


def schema_for(teams: list[str] | tuple[str, ...] = ()) -> dict:
    """SCHEMA with "responsible" held to the teams the models belong to (the user names them; `document.guess_teams`
    until then), or "none"; free text when no team is known."""
    if not teams:
        return SCHEMA
    return {**SCHEMA, "properties": {**SCHEMA["properties"],
                                     "responsible": {"type": "string", "enum": [*dict.fromkeys(teams), "none"]}}}


def triage_one(model: ChatModel, c: ReportClash, images: bool = True,
               on_reasoning: Callable[[str], None] | None = None, note: str = "", guidance: str = "",
               domain: str = domains.CONSTRUCTION, teams: list[str] | tuple[str, ...] = ()) -> dict:
    """One verdict. With `on_reasoning`, and a model that streams its reasoning, each piece of it is passed on as the
    model writes it. `note` is added to the clash's facts (see `alike_groups`); `guidance` (the project's coordination
    requirements, `requirements.prompt_text`) to the system prompt. `domain` (`domains.of`) says who ORCA is; `teams`
    are the teams the models belong to, one of which is "responsible"."""
    pics = [p for _, p in c.images] if images else []
    text = describe(c) + (f"\n{note}" if note else "")
    system = domains.prompt("triage", domain, teams=", ".join(dict.fromkeys(teams))) + guidance
    schema = schema_for(teams)
    if on_reasoning and hasattr(model, "complete_json_streamed"):
        return model.complete_json_streamed(system, text, pics, schema, on_reasoning)  # type: ignore[attr-defined]
    return model.complete_json(system, text, pics, schema=schema)  # type: ignore[call-arg]


# Alike clashes: a model is checked against itself, so the same joint repeats many times (48 holding-down bolts in
# their pad footings, 44 beams into columns). Each group of ALIKE_MIN or more is read once, through its deepest member,
# and the verdict applies to all of it: Northbank's 633 detected clashes are about 60 groups.
ALIKE_MIN = 3
_GRID = re.compile(r"\b(grid|gridline|level|lvl|axis)\s*[-:]?\s*[A-Za-z]{0,2}\d*[A-Za-z]?\b", re.I)
_SIZE = re.compile(r"^\d+(x\d+){1,2}$", re.I)            # a section size: 457x191x67 stays
_TAG = re.compile(r"^[A-Za-z]{0,3}\d+[A-Za-z]{0,3}$|^[A-Z]$")  # a tag or number: A4, C3, L02, 12, B
DEPTH_BANDS_MM = (5, 20, 60, 150, 400)


def _stem(name: str | None) -> str:
    """A name without its grid, level or tag: "UB 457x191x67 - grid C" and "... - grid 4" are the same member type,
    "UB 356x171x45" is not."""
    words = _GRID.sub(r"\1 #", name or "").split()
    return " ".join("#" if _TAG.match(w) and not _SIZE.match(w) else w for w in words)


def _band(distance_m: float | None) -> int:
    d = abs(distance_m or 0.0) * 1000
    return next((b for b in DEPTH_BANDS_MM if d <= b), 9999)


def alike_groups(clashes: list[ReportClash]) -> list[list[ReportClash]]:
    """Clashes that are the same thing over and over: one test, the same kinds of element with the same names apart
    from grid, level or tag, and overlapping by about as much. Deepest first in each group; singles stay single."""
    groups: dict[tuple, list[ReportClash]] = {}
    for c in clashes:
        sides = sorted([(c.a.ifc_class or "", _stem(c.a.name)), (c.b.ifc_class or "", _stem(c.b.name))])
        groups.setdefault((c.test, *sides, _band(c.distance_m)), []).append(c)
    out: list[list[ReportClash]] = []
    for g in groups.values():
        g.sort(key=lambda c: (c.distance_m if c.distance_m is not None else 0.0, c.number))
        out.extend([g] if len(g) >= ALIKE_MIN else [[c] for c in g])
    return out


def _alike_note(group: list[ReportClash]) -> str:
    if len(group) < 2:
        return ""
    mm = sorted(abs(c.distance_m or 0) * 1000 for c in group)
    return (f"This clash stands for {len(group)} alike clashes in the report: the same kinds of element, named the same "
            f"apart from grid, level or tag, overlapping {mm[0]:.0f} to {mm[-1]:.0f} mm. Your verdict applies to all of "
            "them, so write the understanding and the fix hint so they are true of every one.")


REASONING_KEPT = 6000      # characters of a clash's reasoning kept with its verdict
REASONING_EVERY_S = 0.6    # how often a clash's new reasoning goes to the browser


def triage_report(report: Report, model: ChatModel, emit: Callable[[dict], None] = lambda e: None,
                  workers: int = 8, images: bool = True, rules: bool = True, done: dict | None = None,
                  settled: dict | None = None, reasoning: bool = False, alike: bool = True,
                  requirements: "reqs.Doc | None" = None, domain: str = domains.CONSTRUCTION,
                  teams: list[str] | tuple[str, ...] = (), only: set[str] | None = None) -> dict[str, dict]:
    """A verdict for every clash in `report`. `done` holds results already known (resumed or cached); they are kept.
    `settled` holds verdicts the open model already decides (`same_element`): no model call for those. `only`: the
    clashes the model may be asked about (the rest get what the rules settle, or nothing).

    Emits {"type": "clash", "id", "source": "rule" | "model", **verdict} as each one lands. With `reasoning`, also
    {"type": "reasoning", "id", "text"} with what the model has written since the last one (a few times a second per
    clash, for a model that streams its reasoning), and the verdict keeps the whole reasoning (cut to REASONING_KEPT).

    With `alike`, each group of alike clashes (`alike_groups`) is read once, through its deepest member; the others
    get the same verdict with "alike_of" (that member's id) and "alike" (the group's size).

    Under coordination `requirements`: a clash a by-design rule covers is settled without a model call (over a known
    result, whose reading is kept), the model is told the requirements, and its answers pass the strictness overlay."""
    doc = requirements
    results: dict[str, dict] = dict(done or {})
    guidance = reqs.prompt_text(doc, "triage") if doc is not None else ""
    todo: list[ReportClash] = []
    for c in report.clashes:
        rule = reqs.settle(doc, c) if doc is not None and rules else None
        if c.id in results and not rule:
            continue
        known = (settled or {}).get(c.id) or (by_rule(c) if rules else None) or rule
        if known:
            prior = results.get(c.id)
            if known is rule and prior and prior.get("source") == "model" and prior.get("understanding"):
                known = {**known, "model_reading": f"{prior.get('verdict', '').replace('_', ' ')}: {prior['understanding']}"}
            results[c.id] = {**known, "source": "rule"}
            emit({"type": "clash", "id": c.id, **results[c.id]})
        elif only is None or c.id in only:
            todo.append(c)
    lock = threading.Lock()

    def one(group: list[ReportClash]) -> tuple[list[ReportClash], dict]:
        c = group[0]
        for attempt in range(3):
            started = time.perf_counter()
            thought: list[str] = []
            pending: list[str] = []
            sent = [time.perf_counter()]

            def heard(piece: str) -> None:
                thought.append(piece)
                pending.append(piece)
                if time.perf_counter() - sent[0] >= REASONING_EVERY_S:
                    emit({"type": "reasoning", "id": c.id, "text": "".join(pending)})
                    pending.clear()
                    sent[0] = time.perf_counter()

            try:
                v = triage_one(model, c, images, heard if reasoning else None, _alike_note(group), guidance, domain, teams)
                out = {**v, "source": "model", "seconds": round(time.perf_counter() - started, 1)}
                if doc is not None:
                    out = reqs.overlay(doc, out)
                if thought:
                    whole = "".join(thought).strip()
                    out["reasoning"] = whole if len(whole) <= REASONING_KEPT else whole[:REASONING_KEPT] + " …"
                return group, out
            except Exception as e:  # rate limits, timeouts, malformed JSON: back off and retry, then give up
                err = f"{type(e).__name__}: {e}"[:200]
                time.sleep(2 ** attempt)
        return group, {"verdict": "unknown", "error": err, "source": "model"}

    units = alike_groups(todo) if alike else [[c] for c in todo]
    with ThreadPoolExecutor(max(1, workers)) as pool:
        for fut in as_completed(owner.submit(pool, one, g) for g in units):
            group, v = fut.result()
            for k, c in enumerate(group):
                mine = v if k == 0 else {**{x: y for x, y in v.items() if x != "reasoning"}, "alike_of": group[0].id}
                if len(group) > 1:
                    mine = {**mine, "alike": len(group)}
                with lock:
                    results[c.id] = mine
                emit({"type": "clash", "id": c.id, **mine})
    return results


AUDIT = """You are ORCA, {role} checking one rule in a project's coordination requirements.
The rule declares a pair of element kinds "by design" (meant to meet: no fix needed), so the clashes it covers are set
aside without being read. You are shown up to three of them, deepest first (element A is red, element B is green in any
pictures). Answer "consistent" when they look like what the rule describes, "looks_real" when any of them looks like a
genuine conflict the rule would hide (say which, by its number), "unsure" otherwise. In "note", one or two plain
sentences on why. Return JSON only."""
AUDIT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer", "note"],
                "properties": {"answer": {"type": "string", "enum": ["consistent", "looks_real", "unsure"]},
                               "note": {"type": "string"}}}
AUDIT_SAMPLES = 3
AUDIT_RULES = 8


def audit_rules(model: ChatModel, report: Report, doc: "reqs.Doc", results: dict[str, dict],
                images: bool = True, domain: str = domains.CONSTRUCTION) -> dict[int, dict]:
    """Muse checks the rules that set clashes aside: one call per by-design rule that settled any (at most
    AUDIT_RULES), on its deepest AUDIT_SAMPLES clashes. {rule index: {answer, note, rule, samples, settled}}."""
    by_rule_index: dict[int, list[ReportClash]] = {}
    for c in report.clashes:
        v = results.get(c.id) or {}
        if v.get("basis") == "requirement" and isinstance(v.get("rule"), int):
            by_rule_index.setdefault(v["rule"], []).append(c)
    out: dict[int, dict] = {}
    for i in sorted(by_rule_index)[:AUDIT_RULES]:
        if i >= len(doc.by_design):
            continue
        r = doc.by_design[i]
        clashes = sorted(by_rule_index[i], key=lambda c: (c.distance_m if c.distance_m is not None else 0.0))
        samples = clashes[:AUDIT_SAMPLES]
        text = (f"The rule: {reqs._pair_text(r)} is by design" + (f" ({r.reason})." if r.reason else ".")
                + f" It set aside {len(clashes)} clashes.\n\n"
                + "\n\n".join(f"Clash #{c.number or k + 1}:\n{describe(c)}" for k, c in enumerate(samples)))
        pics = [p for _, p in samples[0].images] if images and samples[0].images else []
        try:
            reply = model.complete_json(domains.fill(AUDIT, domain) + reqs.prompt_text(doc, "triage", rules=False), text, pics,
                                        schema=AUDIT_SCHEMA)  # type: ignore[call-arg]
        except Exception as e:
            reply = {"answer": "unsure", "note": f"Could not check: {type(e).__name__}"}
        answer = reply.get("answer") if reply.get("answer") in ("consistent", "looks_real", "unsure") else "unsure"
        out[i] = {"answer": answer, "note": str(reply.get("note", ""))[:400], "rule": reqs._pair_text(r),
                  "samples": [c.id for c in samples], "settled": [c.id for c in clashes]}
    return out


def summary(results: dict[str, dict]) -> dict:
    out: dict[str, int] = {}
    for v in results.values():
        out[v.get("verdict", "unknown")] = out.get(v.get("verdict", "unknown"), 0) + 1
    out["by_rule"] = sum(1 for v in results.values() if v.get("source") == "rule")
    out["by_model"] = sum(1 for v in results.values() if v.get("source") == "model")
    return out


class Job:
    """One triage run over a report, shared by everyone who opens it: late subscribers replay what has landed."""

    def __init__(self, report: Report, model: ChatModel, info: dict, workers: int = 8,
                 requirements: "reqs.Doc | None" = None, seed: dict[str, dict] | None = None,
                 domain: str = domains.CONSTRUCTION, teams: list[str] | tuple[str, ...] = (),
                 only: set[str] | None = None, scope: str | None = None,
                 on_reading: Callable[[ReportClash, dict], None] | None = None):
        """`requirements`: the coordination requirements this run reads under. `seed`: model readings from an earlier
        run under the same prompt (only the rules changed, or ORCA's checks carrying readings to a new list of their
        clashes): kept, so only what they no longer settle is asked. `domain`: the scene's (`domains.of`), whose voice
        the triage prompt takes. `teams`: the teams the models belong to (`document.guess_teams`), which "responsible"
        names. `only`: the clashes the model may be asked about (None: all), and `scope` the kept check they are in
        (shown, not used). `on_reading`: told every reading the model makes, as it lands (the checks keep them)."""
        self.report, self.model, self.info, self.workers = report, model, info, workers
        self.requirements = requirements
        self.domain = domain
        self.teams = tuple(teams)
        self.only, self.scope, self.on_reading = only, scope, on_reading
        ids = {c.id for c in report.clashes}
        # A reading kept from another list: only for clashes here, and without its alike group (read again here).
        self.seed = {k: {x: y for x, y in v.items() if x not in ("alike", "alike_of")}
                     for k, v in (seed or {}).items() if v.get("source") == "model" and k in ids}
        self._by_id = {c.id: c for c in report.clashes}
        self.audit: dict[int, dict] = {}
        self.results: dict[str, dict] = {}
        self.events: list[dict] = []
        self.done = False
        self.error: str | None = None
        self.started = time.time()
        self.seconds: float | None = None
        self._cond = threading.Condition()
        self.facts: dict[str, dict] = {}  # clash id -> settled verdict known from the open model (same element)

    def _settle(self, cid: str, v: dict) -> dict:
        """A model answer for a clash the open model already settles: the settled verdict, with the model's reading."""
        fact = self.facts.get(cid)
        if not fact or v.get("source") == "rule":
            return v
        out = {**fact, "source": "rule"}
        if v.get("understanding"):
            out["model_reading"] = f"{v.get('verdict', '').replace('_', ' ')}: {v['understanding']}"
        return out

    def learn(self, facts: dict[str, dict]) -> None:
        """Facts from the open model (see `same_element`). Results already in are corrected and re-sent."""
        with self._cond:
            new = {k: v for k, v in facts.items() if k not in self.facts}
            self.facts.update(new)
            fixed = [(cid, self._settle(cid, self.results[cid])) for cid in new if cid in self.results]
            fixed = [(cid, v) for cid, v in fixed if v is not self.results[cid]]
            if not fixed:
                return
            # A finished run ends with "done", where listeners stop reading: corrections go in before it.
            tail = self.events.pop() if self.done and self.events and self.events[-1].get("type") == "done" else None
            for cid, v in fixed:
                self.results[cid] = v
                self.events.append({"type": "clash", "id": cid, **v})
            if tail:
                self.events.append({**tail, "summary": summary(self.results)})
            self._cond.notify_all()

    def _emit(self, event: dict) -> None:
        with self._cond:
            if event.get("type") == "clash":
                event = {"type": "clash", "id": event["id"], **self._settle(event["id"], event)}
                self.results[event["id"]] = {k: v for k, v in event.items() if k not in ("type", "id")}
            self.events.append(event)
            self._cond.notify_all()
        if (event.get("type") == "clash" and self.on_reading is not None and event.get("source") == "model"
                and not event.get("carried") and event["id"] in self._by_id):
            self.on_reading(self._by_id[event["id"]], self.results[event["id"]])

    def start(self) -> "Job":
        self._emit({"type": "start", "total": len(self.report.clashes), **self.info,
                    **({"asking": len(self.only), "scope": self.scope} if self.only is not None else {})})

        # Readings kept from an earlier run are in at once, so a page asking right away sees them.
        for cid, v in self.seed.items():
            self._emit({"type": "clash", "id": cid, **v})

        def work():
            try:
                triage_report(self.report, self.model, self._emit, self.workers, self.info.get("images", True),
                              done=dict(self.seed), settled=dict(self.facts), reasoning=True,
                              requirements=self.requirements, domain=self.domain, teams=self.teams, only=self.only)
                if self.requirements is not None and self.requirements.by_design:
                    self._audit()
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
            self.seconds = round(time.time() - self.started, 1)
            self._emit({"type": "done", "summary": summary(self.results), "seconds": self.seconds,
                        **({"error": self.error} if self.error else {})})
            with self._cond:
                self.done = True
                self._cond.notify_all()

        owner.spawn(work)  # with the starter's settings (the owner's triage effort)
        return self

    def _audit(self) -> None:
        """Muse checks the by-design rules on the clashes they set aside; a rule it disputes marks them."""
        with self._cond:
            results = dict(self.results)
        found = audit_rules(self.model, self.report, self.requirements, results, self.info.get("images", True),
                            self.domain)
        with self._cond:
            self.audit = found
        for i, a in found.items():
            if a["answer"] != "looks_real":
                continue
            for cid in a["settled"]:
                with self._cond:
                    v = self.results.get(cid)
                if v is not None:
                    self._emit({"type": "clash", "id": cid, **v, "audit": "disputed", "audit_note": a["note"]})
        self._emit({"type": "audit", "rules": {str(k): v for k, v in found.items()}})

    def follow(self):
        """Every event so far, then each new one until the run ends. Reasoning is live only: a late subscriber skips the
        reasoning already sent (each verdict keeps its own)."""
        i = 0
        with self._cond:
            joined = len(self.events)
        while True:
            with self._cond:
                while i >= len(self.events) and not self.done:
                    self._cond.wait(timeout=15)
                    if i >= len(self.events) and not self.done:
                        break  # no news for a while: yield a keep-alive
                batch, finished = self.events[i:], self.done
            first = i
            i += len(batch)
            if batch:
                yield from (e for k, e in enumerate(batch, first) if k >= joined or e.get("type") != "reasoning")
            elif not finished:
                yield {"type": "ping"}
            if finished and i >= len(self.events):
                return

    def state(self) -> dict:
        return {**self.info, "total": len(self.report.clashes), "done": self.done, "seconds": self.seconds,
                "results": self.results, "summary": summary(self.results), "error": self.error,
                "audit": {str(k): v for k, v in self.audit.items()}}
