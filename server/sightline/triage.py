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


def by_rule(c: ReportClash) -> dict | None:
    """The verdict when it is certain without a model, else None."""
    classes = {c.a.ifc_class, c.b.ifc_class}
    if classes & NON_PHYSICAL:
        cls = next(iter(classes & NON_PHYSICAL)).replace("Ifc", "").lower()
        return {"verdict": "non_physical", "severity": "none", "responsible": "none", "action": "exclude_with_rule",
                "understanding": f"One side is a {cls}, not a physical element.", "fix_hint": "", "confidence": 1.0}
    if c.distance_m is not None and abs(c.distance_m) <= TOUCH_M:
        return {"verdict": "by_design", "severity": "none", "responsible": "none", "action": "exclude_with_rule",
                "understanding": "The two elements only touch (within 1 mm).", "fix_hint": "", "confidence": 1.0}
    return None


def triage_one(model: ChatModel, c: ReportClash, images: bool = True) -> dict:
    pics = [p for _, p in c.images] if images else []
    return model.complete_json(PROMPT.read_text(), describe(c), pics, schema=SCHEMA)  # type: ignore[call-arg]


def triage_report(report: Report, model: ChatModel, emit: Callable[[dict], None] = lambda e: None,
                  workers: int = 8, images: bool = True, rules: bool = True, done: dict | None = None) -> dict[str, dict]:
    """A verdict for every clash in `report`. `done` holds results already known (resumed or cached); they are kept.

    Emits {"type": "clash", "id", "source": "rule" | "model", **verdict} as each one lands."""
    results: dict[str, dict] = dict(done or {})
    todo: list[ReportClash] = []
    for c in report.clashes:
        if c.id in results:
            continue
        settled = by_rule(c) if rules else None
        if settled:
            results[c.id] = {**settled, "source": "rule"}
            emit({"type": "clash", "id": c.id, **results[c.id]})
        else:
            todo.append(c)
    lock = threading.Lock()

    def one(c: ReportClash) -> tuple[str, dict]:
        for attempt in range(3):
            started = time.perf_counter()
            try:
                v = triage_one(model, c, images)
                return c.id, {**v, "source": "model", "seconds": round(time.perf_counter() - started, 1)}
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

    def _emit(self, event: dict) -> None:
        with self._cond:
            if event.get("type") == "clash":
                self.results[event["id"]] = {k: v for k, v in event.items() if k not in ("type", "id")}
            self.events.append(event)
            self._cond.notify_all()

    def start(self) -> "Job":
        self._emit({"type": "start", "total": len(self.report.clashes), **self.info})

        def work():
            try:
                triage_report(self.report, self.model, self._emit, self.workers, self.info.get("images", True))
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
        """Every event so far, then each new one until the run ends."""
        i = 0
        while True:
            with self._cond:
                while i >= len(self.events) and not self.done:
                    self._cond.wait(timeout=15)
                    if i >= len(self.events) and not self.done:
                        break  # no news for a while: yield a keep-alive
                batch, finished = self.events[i:], self.done
            i += len(batch)
            if batch:
                yield from batch
            elif not finished:
                yield {"type": "ping"}
            if finished and i >= len(self.events):
                return

    def state(self) -> dict:
        return {**self.info, "total": len(self.report.clashes), "done": self.done, "seconds": self.seconds,
                "results": self.results, "summary": summary(self.results), "error": self.error}
