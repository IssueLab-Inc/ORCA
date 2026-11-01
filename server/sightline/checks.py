"""The checks kept for a set of open models, and the one clash list they make (docs/detection.md, "Kept checks").

A check is one question ORCA's detection asks of the open models: the open models (every pair and each model against
itself, or what the requirements compile to), or one check on filters ("Ducts vs Everything"). Each keeps only its
latest run: running it again replaces its clashes and says what changed since its own last run. Every kept check's
clashes make one list, the union report the page, triage, Insights, chat, MCP and the PDF read.

A clash is one thing for the whole scene: its id is issued once (from the test and the pair that first found it) and
any later check finding the same pair, of the same kind, takes it, so its #N, title, views, sign-offs and triage
reading follow it from check to check. Numbers count up for the scene and are never reused, under any requirements.

The register holds no geometry; `service.Workspace` runs the checks and keeps one register per scene.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from .detect import Run, Test
from .limits import env_int
from .reports import Report, ReportClash

MODELS = "models"               # the key of the check of the open models (every other check is one test)
MODELS_NAME = "The open models"
MAX_CHECKS = env_int("SIGHTLINE_MAX_CHECKS", 12)   # kept per scene; the oldest check on filters goes first
UNIONS_KEPT = 2                 # union reports kept per scene: the current one, and the one a page may still be on
SAME_DEPTH_M = 0.001            # a triage reading follows a clash while its depth moved no more than this


def key_of(tests: list[Test] | None) -> str:
    """Which check a run is: one test with no id of its own (a check on filters, or elements chat described) is its
    own check, keyed by the id `detect.check_id` gives it; anything else checks the open models."""
    if tests and len(tests) == 1:
        t = tests[0]
        if t.id.startswith("filter:") or t.a.on_filters() or (t.b is not None and t.b.on_filters()):
            return t.id
    return MODELS


def same_clash(a: ReportClash, b: ReportClash) -> bool:
    """Whether two rows are the same clash, unchanged: the same pair of elements, the depth moved no more than
    SAME_DEPTH_M. A triage reading holds only while this is so."""
    pair = lambda c: sorted((c.a.global_id or "", c.b.global_id or ""))
    if pair(a) != pair(b) or (a.distance_m is None) != (b.distance_m is None):
        return False
    return a.distance_m is None or abs(a.distance_m - b.distance_m) <= SAME_DEPTH_M


def pick(items, key_or_name: str):
    """A kept check by its key, or by its name as people say it (any case), among `Check`s or their summaries."""
    get = lambda x, f: x[f] if isinstance(x, dict) else getattr(x, f)
    want = str(key_or_name or "").strip()
    items = list(items)
    return (next((x for x in items if get(x, "key") == want), None)
            or next((x for x in items if str(get(x, "name")).strip().lower() == want.lower()), None))


@dataclass
class Check:
    """One check's latest run."""
    key: str
    name: str                     # "The open models", or the check's own name ("Ducts vs Everything")
    title: str                    # that run's report title ("Coordination · 3 models")
    tests: list[dict] | None      # as run; None: the defaults (or the requirements'), read afresh each time
    requirements: dict | None     # what it ran under (`Workspace.requirements_info`), None for ORCA's defaults
    revision: int                 # the scene's revision when it ran: a fix kept since leaves it stale
    ran_at: float
    order: int                    # when it was first kept: the picker lists checks in this order, the open models first
    seconds: float
    elements: int
    offset: list[float]
    coverage: list[dict]
    diff: dict
    state: dict                   # detect.Run.state: what its next run compares with (clashes, selections, contacts)
    clashes: list[ReportClash]

    @property
    def requirements_id(self) -> str | None:
        return (self.requirements or {}).get("id")

    def summary(self, revision: int | None = None) -> dict:
        """What the page and tools are told about it. `revision`: the scene's now, for `stale`."""
        return {"key": self.key, "name": self.name, "title": self.title, "tests": self.tests,
                "requirements": self.requirements, "revision": self.revision,
                "stale": revision is not None and self.revision < revision, "ran_at": self.ran_at,
                "seconds": self.seconds, "elements": self.elements, "coverage": self.coverage, "diff": self.diff,
                "clashes": len(self.clashes)}


@dataclass
class Register:
    """The checks kept for one scene, and what a clash keeps from check to check."""
    root: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="sightline-checks-")))
    checks: dict[str, Check] = field(default_factory=dict)
    ids: dict[str, dict] = field(default_factory=dict)      # every clash id issued → {kind, a, b, test, name}
    numbers: dict[str, int] = field(default_factory=dict)   # clash id → #N
    titles: dict[str, str] = field(default_factory=dict)    # clash id → Muse's title
    views: dict[str, dict[str, Path]] = field(default_factory=dict)  # clash id → label → captured picture
    # Triage readings by the triage prompt they were read under (`requirements.model_key`, "" without requirements):
    # clash id → {a, b, distance_m, verdict}, so a reading follows its clash while the clash is unchanged.
    readings: dict[str, dict[str, dict]] = field(default_factory=dict)
    report_id: str | None = None                             # the current union report
    unions: list[str] = field(default_factory=list)          # union reports made, oldest first
    serial: int = 0                                          # bumped by every union: a page ignores an older one
    order: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)  # titles, views and readings

    # ------------------------------------------------------------------ runs

    def previous(self, key: str, requirements_id: str | None) -> dict | None:
        """What a check's run compares with: its own last run, under the same requirements (the same tests)."""
        c = self.checks.get(key)
        return c.state if c is not None and c.requirements_id == requirements_id else None

    def known(self) -> dict:
        """What `detect.run` reads to keep a clash's id and number: every id issued, the numbers, and the clashes in
        the open list now (a check's first run calls new only what the list does not already hold)."""
        return {"clashes": self.ids, "numbers": self.numbers,
                "open": {c.id for check in list(self.checks.values()) for c in check.clashes}}

    def keep(self, key: str, run: Run, tests: list[dict] | None, requirements: dict | None, revision: int,
             name: str | None = None) -> Check:
        """A check's new run: its clashes replace only its own. New ids and numbers join the scene's."""
        for cid, was in run.state.get("clashes", {}).items():
            self.ids.setdefault(cid, {k: was.get(k) for k in ("kind", "a", "b", "test", "name")})
        for cid, n in run.state.get("numbers", {}).items():
            self.numbers.setdefault(cid, n)
        old = self.checks.get(key)
        if old is None:
            self.order += 1
        check = Check(key=key, name=name or (MODELS_NAME if key == MODELS else (tests or [{}])[0].get("name") or key),
                      title=run.report.title, tests=tests, requirements=requirements, revision=revision,
                      ran_at=time.time(), order=old.order if old is not None else self.order,
                      seconds=run.seconds, elements=run.elements, offset=run.offset,
                      coverage=[asdict(c) for c in run.coverage], diff=run.diff,
                      state={k: v for k, v in run.state.items() if k != "numbers"}, clashes=run.report.clashes)
        self.checks[key] = check
        self.checks = dict(sorted(self.checks.items(), key=lambda kv: (kv[0] != MODELS, kv[1].order)))
        while len(self.checks) > max(1, MAX_CHECKS):
            others = [c for c in self.checks.values() if c.key not in (MODELS, key)]
            if not others:
                break
            self.checks.pop(min(others, key=lambda c: c.ran_at).key)
        return check

    def remove(self, key: str) -> Check:
        """Drop a check on filters (KeyError: none such; ValueError: the open models are run again, not removed)."""
        if key == MODELS:
            raise ValueError("The check of the open models is run again, not removed.")
        return self.checks.pop(key)

    def drop_file(self, name: str, elements) -> int:
        """A model was taken out of the scene: the clashes with any of its elements (`elements`, or a side in the file
        `name`) leave every kept check, and what each check compares its next run with forgets them, so they are
        neither listed nor said to be resolved. Ids, numbers, titles and readings stay (a number is never reused).
        Returns how many clashes went."""
        gone = set(elements)
        hit = lambda a, b, fa=None, fb=None: a in gone or b in gone or name in (fa, fb)
        dropped: set[str] = set()
        for check in list(self.checks.values()):
            keep = []
            for c in check.clashes:
                if hit(c.a.global_id, c.b.global_id, c.a.file, c.b.file):
                    dropped.add(c.id)
                else:
                    keep.append(c)
            check.clashes = keep
            st = check.state
            st["clashes"] = {cid: was for cid, was in st.get("clashes", {}).items()
                             if cid not in dropped and not hit(was.get("a"), was.get("b"))}
            st["contacts"] = [p for p in st.get("contacts", []) if not gone & set(p)]
            for sel in st.get("selections", {}).values():
                sel["a"] = set(sel["a"]) - gone
                if sel.get("b") is not None:
                    sel["b"] = set(sel["b"]) - gone
            d = check.diff
            check.diff = {**d, "new": [i for i in d.get("new", []) if i not in dropped],
                          "resolved": [x for x in d.get("resolved", []) if not hit(x.get("a"), x.get("b"))],
                          "no_longer_checked": [x for x in d.get("no_longer_checked", []) if not hit(x.get("a"), x.get("b"))]}
        return len(dropped)

    def find(self, key_or_name: str) -> Check | None:
        """A kept check by its key, or by its name as people say it (`pick`)."""
        return pick(self.checks.values(), key_or_name)

    def contacts(self) -> list:
        """What only touches, from every kept check (what rests on or meets what: `connections.graph`)."""
        seen: dict[tuple, list] = {}
        for c in list(self.checks.values()):   # a snapshot: another request may add or drop a check meanwhile
            for p in c.state.get("contacts", []):
                seen.setdefault(tuple(p), list(p))
        return list(seen.values())

    def summaries(self, revision: int | None = None) -> list[dict]:
        return [c.summary(revision) for c in list(self.checks.values())]

    # ------------------------------------------------------------------ what a clash keeps

    def absorb(self, report: Report | None) -> None:
        """Titles written straight onto a union's clashes (a titling run): kept for the next union."""
        if report is None:
            return
        with self.lock:
            for c in report.clashes:
                if c.title and c.id in self.ids:
                    self.titles.setdefault(c.id, c.title)

    def keep_titles(self, items: dict[str, str]) -> None:
        with self.lock:
            self.titles.update({k: v for k, v in items.items() if k in self.ids and v})

    def save_view(self, clash_id: str, label: str, png: bytes) -> Path:
        """A captured view, kept with the register (not a report), so a report dropped from memory loses none."""
        folder = self.root / "views"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{clash_id}-{label}.png"
        path.write_bytes(png)
        with self.lock:
            self.views.setdefault(clash_id, {})[label] = path
        return path

    def images(self, clash_id: str) -> list[tuple[str, Path]]:
        with self.lock:
            return sorted((label, p) for label, p in self.views.get(clash_id, {}).items() if p.exists())

    def keep_reading(self, model_key: str, clash: ReportClash, verdict: dict) -> None:
        """A triage verdict the model read, kept with the clash's pair and depth (docs/detection.md, "Kept checks")."""
        # Only a reading the model made: a failed read (an error, no verdict) stays unread, to be asked again.
        if (clash.id not in self.ids or verdict.get("source") != "model" or verdict.get("error")
                or verdict.get("verdict") in (None, "unknown")):
            return
        v = {k: x for k, x in verdict.items() if k not in ("alike", "alike_of", "audit", "audit_note", "carried")}
        with self.lock:
            self.readings.setdefault(model_key, {})[clash.id] = {
                "pair": sorted((clash.a.global_id or "", clash.b.global_id or "")),
                "distance_m": clash.distance_m, "verdict": v}

    def carried(self, report: Report, model_key: str) -> dict[str, dict]:
        """The readings that still hold for the report's clashes: the same pair, read under the same prompt, at a
        depth that moved no more than SAME_DEPTH_M."""
        with self.lock:
            held = dict(self.readings.get(model_key, {}))
        out = {}
        for c in report.clashes:
            r = held.get(c.id)
            if r is None or r["verdict"].get("error") or r["verdict"].get("verdict") in (None, "unknown"):
                continue
            read = replace(c, distance_m=r["distance_m"], a=replace(c.a, global_id=r["pair"][0]),
                           b=replace(c.b, global_id=r["pair"][1]))
            if same_clash(read, c):
                out[c.id] = {**r["verdict"], "carried": True}
        return out

    # ------------------------------------------------------------------ the one list

    def union(self, report_id: str, sources: list[str], scene_id: str, revision: int | None = None) -> Report | None:
        """Every kept check's clashes as one report (None when no check is kept). A clash two checks found is one row:
        its test as the first check found it (the open models first), its measure from the newest run."""
        kept = list(self.checks.values())   # a snapshot, in order: the open models first
        if not kept:
            return None
        newest = sorted(kept, key=lambda c: c.ran_at, reverse=True)
        latest: dict[str, tuple[ReportClash, set]] = {}
        for check in newest:
            fresh = set(check.diff.get("new", []))
            for c in check.clashes:
                latest.setdefault(c.id, (c, fresh))
        rows: dict[str, ReportClash] = {}
        found: dict[str, dict[str, str]] = {}
        for check in kept:
            for c in check.clashes:
                found.setdefault(c.id, {})[check.key] = c.test
                if c.id in rows:
                    continue
                now, fresh = latest[c.id]
                rows[c.id] = replace(c, distance_m=now.distance_m, point=now.point, a=now.a, b=now.b,
                                     status="new" if c.id in fresh else "active")
        with self.lock:
            for cid, c in rows.items():
                c.number = self.numbers.get(cid, c.number)
                c.title = self.titles.get(cid) or c.title
                c.images = sorted((label, p) for label, p in self.views.get(cid, {}).items() if p.exists())
                c.checks = found[cid]
        models = next((c for c in kept if c.key == MODELS), None)
        others = [c for c in kept if c.key != MODELS]
        if models is not None:
            title = models.title + (f" + {len(others)} check{'s' if len(others) != 1 else ''}" if others else "")
        elif len(others) == 1:
            title = others[0].title
        else:
            title = f"Coordination · {len(others)} checks"
        self.serial += 1
        rid = (models or newest[0]).requirements_id
        report = Report(id=report_id, title=title, root=self.root, sources=list(sources),
                        clashes=sorted(rows.values(), key=lambda c: c.number), temporary=False, origin="sightline",
                        requirements_id=rid, scene_id=scene_id, serial=self.serial,
                        checks=self.summaries(revision))
        self.report_id = report_id
        self.unions.append(report_id)
        return report

    def drop(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
