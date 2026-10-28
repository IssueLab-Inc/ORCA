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
from pathlib import Path
from typing import Callable

from .meta_client import ChatModel
from .reports import Report, ReportClash

PROMPT = Path(__file__).parent / "domain_packs" / "triage.md"
NON_PHYSICAL = {"IfcSpace", "IfcDistributionPort", "IfcOpeningElement", "IfcVirtualElement", "IfcZone"}
TOUCH_M = 0.001  # |distance| at or under this is a touch

SCHEMA = {
    "type": "object",
    "properties": {
        "understanding": {"type": "string"},
        "verdict": {"type": "string", "enum": ["real_clash", "by_design", "non_physical", "modelling_error"]},
        "severity": {"type": "string", "enum": ["high", "medium", "low", "none"]},
        "responsible": {"type": "string", "enum": ["Structure", "MEP", "Architecture", "Site", "none"]},
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


def triage_one(model: ChatModel, c: ReportClash, images: bool = True,
               on_reasoning: Callable[[str], None] | None = None) -> dict:
    """One verdict. With `on_reasoning`, and a model that streams its reasoning, each piece of it is passed on as the
    model writes it."""
    pics = [p for _, p in c.images] if images else []
    if on_reasoning and hasattr(model, "complete_json_streamed"):
        return model.complete_json_streamed(PROMPT.read_text(), describe(c), pics, SCHEMA, on_reasoning)  # type: ignore[attr-defined]
    return model.complete_json(PROMPT.read_text(), describe(c), pics, schema=SCHEMA)  # type: ignore[call-arg]


REASONING_KEPT = 6000      # characters of a clash's reasoning kept with its verdict
REASONING_EVERY_S = 0.6    # how often a clash's new reasoning goes to the browser


def triage_report(report: Report, model: ChatModel, emit: Callable[[dict], None] = lambda e: None,
                  workers: int = 8, images: bool = True, rules: bool = True, done: dict | None = None,
                  settled: dict | None = None, reasoning: bool = False) -> dict[str, dict]:
    """A verdict for every clash in `report`. `done` holds results already known (resumed or cached); they are kept.
    `settled` holds verdicts the open model already decides (`same_element`): no model call for those.

    Emits {"type": "clash", "id", "source": "rule" | "model", **verdict} as each one lands. With `reasoning`, also
    {"type": "reasoning", "id", "text"} with what the model has written since the last one (a few times a second per
    clash, for a model that streams its reasoning), and the verdict keeps the whole reasoning (cut to REASONING_KEPT)."""
    results: dict[str, dict] = dict(done or {})
    todo: list[ReportClash] = []
    for c in report.clashes:
        if c.id in results:
            continue
        known = (settled or {}).get(c.id) or (by_rule(c) if rules else None)
        if known:
            results[c.id] = {**known, "source": "rule"}
            emit({"type": "clash", "id": c.id, **results[c.id]})
        else:
            todo.append(c)
    lock = threading.Lock()

    def one(c: ReportClash) -> tuple[str, dict]:
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
                v = triage_one(model, c, images, heard if reasoning else None)
                out = {**v, "source": "model", "seconds": round(time.perf_counter() - started, 1)}
                if thought:
                    whole = "".join(thought).strip()
                    out["reasoning"] = whole if len(whole) <= REASONING_KEPT else whole[:REASONING_KEPT] + " …"
                return c.id, out
            except Exception as e:  # rate limits, timeouts, malformed JSON: back off and retry, then give up
                err = f"{type(e).__name__}: {e}"[:200]
                time.sleep(2 ** attempt)
        return c.id, {"verdict": "unknown", "error": err, "source": "model"}

    with ThreadPoolExecutor(max(1, workers)) as pool:
        for fut in as_completed(pool.submit(one, c) for c in todo):
            cid, v = fut.result()
            with lock:
                results[cid] = v
            emit({"type": "clash", "id": cid, **v})
    return results


def summary(results: dict[str, dict]) -> dict:
    out: dict[str, int] = {}
    for v in results.values():
        out[v.get("verdict", "unknown")] = out.get(v.get("verdict", "unknown"), 0) + 1
    out["by_rule"] = sum(1 for v in results.values() if v.get("source") == "rule")
    out["by_model"] = sum(1 for v in results.values() if v.get("source") == "model")
    return out


class Job:
    """One triage run over a report, shared by everyone who opens it: late subscribers replay what has landed."""

    def __init__(self, report: Report, model: ChatModel, info: dict, workers: int = 8):
        self.report, self.model, self.info, self.workers = report, model, info, workers
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

    def start(self) -> "Job":
        self._emit({"type": "start", "total": len(self.report.clashes), **self.info})

        def work():
            try:
                triage_report(self.report, self.model, self._emit, self.workers, self.info.get("images", True),
                              settled=dict(self.facts), reasoning=True)
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
            self.seconds = round(time.time() - self.started, 1)
            self._emit({"type": "done", "summary": summary(self.results), "seconds": self.seconds,
                        **({"error": self.error} if self.error else {})})
            with self._cond:
                self.done = True
                self._cond.notify_all()

        threading.Thread(target=work, daemon=True).start()
        return self

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
                "results": self.results, "summary": summary(self.results), "error": self.error}
