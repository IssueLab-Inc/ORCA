"""Clash titles: every clash gets a short name written by Muse from its facts, so nobody has to read "Clash39".

A clash already has a number (#N, unique across its report, `ReportClash.number`) and a plain name from its two
elements (`reports.plain_name`). This adds the title a coordinator would call it by: what hits what, how, and where,
e.g. "Cold-water main clips the transfer girder's bottom flange at grid 3".

The triage model (Muse Spark Open where configured, `meta_client.triage_model`) writes them from text only, many
clashes per call, a few calls at a time, with strict JSON output. Titles stream to the browser as they land and stay on
the clash (`ReportClash.title`), so the list, the chat, the PDF and BCF all use them. A title is wording, never evidence:
the numbers and elements stay in the clash's own fields, and nothing is decided from a title.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from . import owner
from .meta_client import ChatModel
from .reports import Report, ReportClash

PROMPT = Path(__file__).parent / "domain_packs" / "titles.md"
BATCH = 40            # clashes per model call
WORKERS = 8           # calls at a time (as triage runs on the same host)
MAX_CHARS = 90        # a title longer than this is cut at a word

SCHEMA = {
    "type": "object",
    "properties": {"titles": {"type": "array", "items": {
        "type": "object", "properties": {"number": {"type": "integer"}, "title": {"type": "string"}},
        "required": ["number", "title"], "additionalProperties": False}}},
    "required": ["titles"],
    "additionalProperties": False,
}


def facts(c: ReportClash) -> str:
    """One line per clash: its number, the two elements, the test and the depth."""
    def side(e) -> str:
        where = ", ".join(x for x in (e.level, e.system, e.file) if x)
        return f"{e.ifc_class or 'element'} '{e.name}'" + (f" ({where})" if where else "") + \
            (f", part of '{e.part_of}'" if e.part_of else "")
    if c.distance_m is None:
        how = "distance unknown"
    elif c.distance_m < 0:
        how = f"overlap {-c.distance_m * 1000:.0f} mm"
    else:
        how = f"gap {c.distance_m * 1000:.0f} mm"
    return f"#{c.number}: A {side(c.a)}; B {side(c.b)}; test '{c.test}' ({c.test_type or 'hard'}); {how}"


def _tidy(title: str) -> str:
    t = " ".join(title.split()).strip(" .\"'")
    if len(t) > MAX_CHARS:
        t = t[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return t


def title_batch(model: ChatModel, clashes: list[ReportClash]) -> dict[str, str]:
    """Titles for up to BATCH clashes in one call: {clash id: title}. A number the model leaves out stays untitled."""
    by_number = {c.number: c for c in clashes}
    reply = model.complete_json(PROMPT.read_text(), "\n".join(facts(c) for c in clashes), [],  # type: ignore[call-arg]
                                schema=SCHEMA)
    out = {}
    for item in reply.get("titles", []):
        c = by_number.get(item.get("number"))
        title = _tidy(str(item.get("title") or ""))
        if c is not None and title and c.id not in out:
            out[c.id] = title
    return out


def title_report(report: Report, model: ChatModel, emit: Callable[[dict], None] = lambda e: None,
                 batch: int = BATCH, workers: int = WORKERS) -> dict[str, str]:
    """Title every clash in `report` that has no title yet. Emits {"type": "titles", "items": {id: title}} per batch
    as it lands, and sets each clash's `title`."""
    todo = sorted((c for c in report.clashes if not c.title), key=lambda c: c.number)
    chunks = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    done: dict[str, str] = {}
    by_id = {c.id: c for c in report.clashes}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [owner.submit(pool, title_batch, model, chunk) for chunk in chunks]
        for f in as_completed(futures):
            try:
                items = f.result()
            except Exception as e:  # one failed batch leaves those clashes on their plain names
                emit({"type": "batch_error", "detail": f"{type(e).__name__}: {e}"})
                continue
            for cid, title in items.items():
                by_id[cid].title = title
            done.update(items)
            emit({"type": "titles", "items": items})
    return done


class Job:
    """One titling run over a report, shared by everyone who opens it (like triage.Job): late subscribers replay it."""

    def __init__(self, report: Report, model: ChatModel, info: dict):
        self.report, self.model, self.info = report, model, info
        self.titles: dict[str, str] = {c.id: c.title for c in report.clashes if c.title}
        self.events: list[dict] = []
        self.done = False
        self.error: str | None = None
        self.started = time.time()
        self._cond = threading.Condition()

    def _emit(self, event: dict) -> None:
        with self._cond:
            if event.get("type") == "titles":
                self.titles.update(event["items"])
            self.events.append(event)
            self._cond.notify_all()

    def start(self) -> "Job":
        missing = sum(1 for c in self.report.clashes if not c.title)
        self._emit({"type": "start", "total": len(self.report.clashes), "missing": missing, **self.info})

        def work():
            try:
                title_report(self.report, self.model, self._emit)
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
            self._emit({"type": "done", "titled": len(self.titles), "seconds": round(time.time() - self.started, 1),
                        **({"error": self.error} if self.error else {})})
            with self._cond:
                self.done = True
                self._cond.notify_all()

        owner.spawn(work)
        return self

    def follow(self):
        """Everything so far, then each new event until the run ends (pings while it is quiet)."""
        i = 0
        while True:
            with self._cond:
                while i >= len(self.events) and not self.done:
                    self._cond.wait(timeout=15)
                    if i >= len(self.events) and not self.done:
                        break
                batch, finished = self.events[i:], self.done
            i += len(batch)
            if batch:
                yield from batch
            elif not finished:
                yield {"type": "ping"}
            if finished and i >= len(self.events):
                return
