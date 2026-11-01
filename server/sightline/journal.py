"""The edit log: every edit kept to a scene's models, whoever made it (docs/manual-edits.md).

Muse's fixes, plans, wider fixes and the edits people make by hand all land here, one `Entry` per keep: what changed,
in words and numbers, which clash it is for and which earlier entries it amends (`follows`: a hand edit made after a
fix was accepted, on what that fix changed or made). The reports, the export, chat, the fix agent and MCP read it.

Undo and redo walk it. Every keep is one IfcOpenShell transaction per file it changes (`edits.kept_files`), and those
stay on each file's history; the entry holds them, so undo rolls them back and redo commits them again. A wider fix
(`context_planner.accept`) replaces the scene's state wholesale; its entry keeps the state before and after instead.
Undo takes only the newest live entry: an edit kept outside the log since then (each file's history no longer ends in
the entry's transactions) fences it. Undo and redo always move the scene's revision forward (caches are keyed on it).

A model taken out of the scene (`drop_file`) takes its transactions with it: an entry that changed it stays in the log,
marked `model_removed`, and is never undone or redone; undo passes over it to the newest entry it can undo.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

import numpy as np

SOURCES = ("you", "muse", "agent", "fix", "plan", "wider")
PICTURE_MAX_BYTES = 400_000   # one small picture per entry, as a data URL (the page takes it; the server has no GPU)


class Fenced(RuntimeError):
    """Undo or redo is not possible: another edit came after, or there is nothing to undo."""


@dataclass
class Entry:
    id: str                    # "E7": per scene, in the order kept
    seq: int
    at: float                  # epoch seconds
    source: str                # who: you (by hand, on the page), muse (chat or voice), agent (MCP), fix, plan, wider
    kind: str                  # the edit: push_pull, split, ... or the fix kind (offset, move, ...)
    title: str
    summary: str               # in words, with numbers
    actor: str | None = None   # e.g. the agent's name on an MCP link
    params: dict = field(default_factory=dict)      # the op or the option's parameters, no meshes
    elements: list[str] = field(default_factory=list)   # changed: there before and after
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)  # GlobalId -> "IfcClass 'Name'", removed ones too
    files: list[int] = field(default_factory=list)
    revision: int = 0
    clashes: list[dict] = field(default_factory=list)   # [{"id": clash id or None, "pair": [A, B]}]
    follows: list[str] = field(default_factory=list)    # earlier entries this one amends
    check: dict | None = None  # what the check found: cleared, new, worse, accepted_clashes, min_clearance_m
    warnings: list[dict] = field(default_factory=list)  # [{"rule", "text", "review"}]: kept anyway, for review
    requirements: str | None = None
    status: dict | None = None   # where the clash stands after a follow-up: {"clash": id, "resolved", "depth_m"}
    state: str = "kept"        # kept | undone
    picture: str | None = None
    model_removed: str | None = None   # the model it changed was taken out of the scene (its name): never undone again
    # Private: what undo and redo need.
    _tx: dict = field(default_factory=dict, repr=False)          # file index -> [Transaction]
    _models: dict = field(default_factory=dict, repr=False)      # file index -> the ifcopenshell.file it was kept in
    _bounds: tuple = field(default=({}, {}), repr=False)         # (before, after): GlobalId -> box or None
    _edited: tuple = field(default=(set(), set()), repr=False)   # (before, after)
    _swap: tuple | None = field(default=None, repr=False)        # a wider fix: (state before, state after)
    _tail: dict = field(default_factory=dict, repr=False)        # after undo: file index -> its history's last item
    _layout: int = field(default=0, repr=False)                  # the scene's layout when kept (a wider fix's state)

    def to_dict(self, picture: bool = False) -> dict:
        out = {k: v for k, v in self.__dict__.items() if not k.startswith("_") and k != "picture"}
        out["when"] = datetime.fromtimestamp(self.at, timezone.utc).isoformat(timespec="seconds")
        out["has_picture"] = self.picture is not None
        if picture:
            out["picture"] = self.picture
        return out

    def touched(self) -> list[str]:
        return list(dict.fromkeys([*self.elements, *self.created, *self.removed]))


@dataclass
class Recording:
    """What the code keeping an edit tells the log about it; the log works out the rest from the models."""
    changed: list[str] = field(default_factory=list)
    summary: str = ""
    title: str = ""
    params: dict = field(default_factory=dict)
    clashes: list[dict] = field(default_factory=list)
    check: dict | None = None
    warnings: list[dict] = field(default_factory=list)
    files: list[int] = field(default_factory=list)   # when the models were replaced (a wider fix): what it changed
    entry: Entry | None = None    # set when the block ends: the new entry (None when nothing changed)


def _names(scene) -> dict[str, str]:
    return {e.GlobalId: f"{e.is_a()} '{getattr(e, 'Name', None) or e.is_a()[3:]}'"
            for m in scene.models for e in m.by_type("IfcElement")}


class Journal:
    def __init__(self):
        self.entries: list[Entry] = []
        self._redo: list[Entry] = []
        self._seq = 0
        self.lineage: dict[str, list[str]] = {}   # GlobalId -> the entries that changed or made it
        self.lock = threading.RLock()
        self._reran: set[str] = set()                # entries kept with clashes whose free detection rerun was used

    # ------------------------------------------------------------------------------------------------- recording

    @contextmanager
    def record(self, scene, source: str, kind: str, *, title: str = "", summary: str = "", actor: str | None = None,
               requirements: str | None = None) -> Iterator[Recording]:
        """Wrap the code that keeps an edit (it makes its own `edits.kept_files`). When it ends without an error, the
        new transactions on each file, the boxes that changed and the elements made or removed become one entry.
        Nothing is recorded when the block raises, or when it changed nothing."""
        if source not in SOURCES:
            raise ValueError(f"unknown source {source!r}")
        rec = Recording(summary=summary, title=title)
        state = dict(scene.__dict__)
        models = list(scene.models)
        alive = [list(m.history) for m in models]   # held for the block: ids of freed objects can be reused
        held = [{id(t) for t in h} for h in alive]
        before_bounds = dict(scene.bounds())
        before_edited = set(scene._edited)
        before_names = _names(scene)
        yield rec
        swapped = len(scene.models) != len(models) or any(a is not b for a, b in zip(scene.models, models))
        tx = {} if swapped else {i: [t for t in m.history if id(t) not in held[i] and t.operations]
                                 for i, m in enumerate(scene.models)}
        tx = {i: ts for i, ts in tx.items() if ts}
        after_bounds = scene.bounds()
        after_names = _names(scene)
        if not tx and not swapped:
            return
        created = [g for g in after_names if g not in before_names]
        removed = [g for g in before_names if g not in after_names]
        if swapped:   # a private copy came in whole: every box is a new array, so compare them by value
            moved = [g for g in after_bounds if g in before_bounds and not np.array_equal(after_bounds[g], before_bounds[g])]
        else:         # boxes are replaced when they change, never edited in place
            moved = [g for g in after_bounds if g in before_bounds and after_bounds[g] is not before_bounds[g]]
        new_box = [g for g in after_bounds if g not in before_bounds and g not in created]
        changed = [g for g in dict.fromkeys([*rec.changed, *moved, *new_box])
                   if g in after_names and g not in created]
        keys = set(moved) | set(new_box) | set(created) | {g for g in removed if g in before_bounds}
        with self.lock:
            self._seq += 1
            names = {g: (after_names.get(g) or before_names.get(g)) for g in [*changed, *created, *removed]}
            e = Entry(id=f"E{self._seq}", seq=self._seq, at=time.time(), source=source, kind=kind,
                      title=rec.title or title or kind, summary=rec.summary or summary, actor=actor,
                      params=rec.params, elements=changed, created=created, removed=removed, names=names,
                      files=sorted(rec.files or tx or range(len(scene.models))), revision=scene.revision,
                      clashes=[dict(c) for c in rec.clashes], check=rec.check, warnings=list(rec.warnings),
                      requirements=requirements, _tx=tx, _models={i: scene.models[i] for i in tx},
                      _bounds=({g: before_bounds.get(g) for g in keys}, {g: after_bounds.get(g) for g in keys}),
                      _edited=(before_edited, set(scene._edited)),
                      _swap=(state, dict(scene.__dict__)) if swapped else None, _layout=getattr(scene, "layout", 0))
            e.follows = self._follows([*changed, *removed])
            for f in e.follows:   # a follow-up carries the clashes of the fixes it amends
                for c in self.get(f).clashes:
                    if not any(c.get("pair") == x.get("pair") and c.get("id") == x.get("id") for x in e.clashes):
                        e.clashes.append(dict(c))
            for g in [*changed, *created]:
                self.lineage.setdefault(g, []).append(e.id)
            self.entries.append(e)
            self._redo.clear()
        rec.entry = e

    def _follows(self, gids: list[str]) -> list[str]:
        out = []
        for g in gids:
            for eid in self.lineage.get(g, []):
                if eid not in out and self.get(eid).state == "kept":
                    out.append(eid)
        return out

    # ------------------------------------------------------------------------------------------------- reading

    def get(self, entry_id: str) -> Entry:
        for e in self.entries:
            if e.id == entry_id:
                return e
        raise KeyError(entry_id)

    def kept(self) -> list[Entry]:
        return [e for e in self.entries if e.state == "kept"]

    def for_elements(self, gids, kept_only: bool = True) -> list[Entry]:
        """Entries that changed, made or removed any of these elements, oldest first."""
        want = set(gids)
        return [e for e in self.entries if (not kept_only or e.state == "kept") and want & set(e.touched())]

    def for_clash(self, clash_id: str | None, pair: list[str] | None = None) -> list[Entry]:
        """The kept entries tied to a clash, by its id or its pair, oldest first."""
        p = sorted(pair) if pair else None
        return [e for e in self.kept()
                if any((clash_id and c.get("id") == clash_id) or (p and c.get("pair") and sorted(c["pair"]) == p)
                       for c in e.clashes)]

    def made_from(self, gid: str) -> list[str]:
        """`gid` and every element an entry made while changing it (an offset's pieces from its segment), so a clash
        can be measured again after its fix split the element."""
        out, todo = [gid], [gid]
        while todo:
            g = todo.pop()
            for e in self.kept():
                if g in e.elements or g in e.removed:
                    for c in e.created:
                        if c not in out:
                            out.append(c)
                            todo.append(c)
        return out

    def summary(self) -> dict:
        top = self._top()
        return {"entries": [e.to_dict() for e in self.entries],
                "can_undo": top is not None, "can_redo": bool(self._redo),
                "undo": top.id if top else None, "redo": self._redo[-1].id if self._redo else None}

    def _top(self) -> Entry | None:
        """The newest kept entry undo can take: one whose model was removed is passed over."""
        live = [e for e in self.kept() if not e.model_removed]
        return live[-1] if live else None

    @staticmethod
    def _gone(e: Entry, verb: str) -> Fenced:
        return Fenced(f"{e.id} changed {e.model_removed}, which was removed from the open models: it can't be {verb}")

    def _named(self, entry_id: str | None) -> Entry | None:
        return next((e for e in self.entries if e.id == entry_id), None) if entry_id else None

    # ------------------------------------------------------------------------------------------------- undo, redo

    def undo(self, scene, entry_id: str | None = None) -> Entry:
        """Undo the newest kept entry (named, it must be that one). Raises Fenced with why when it cannot."""
        with self.lock:
            named = self._named(entry_id)
            if named is not None and named.model_removed:
                raise self._gone(named, "undone")
            e = self._top()
            if e is None:
                raise Fenced("nothing to undo")
            if entry_id and entry_id != e.id:
                raise Fenced(f"only the newest edit, {e.id}, can be undone next")
            if e._swap is not None:
                self._same_layout(scene, e, "undone")
                self._restore(scene, e._swap[0])
            else:
                self._fence(scene, e)
                for i, txs in e._tx.items():
                    m = scene.models[i]
                    for _ in txs:
                        m.undo()
                        m.future.pop()   # the entry holds them: a trial since would otherwise be redone
                self._boxes(scene, e._bounds[0])
                scene._edited = set(e._edited[0])
                e._tail = {i: (scene.models[i].history[-1] if scene.models[i].history else None) for i in e._tx}
            scene.bump(e.files)
            e.state = "undone"
            self._redo.append(e)
            return e

    def redo(self, scene, entry_id: str | None = None) -> Entry:
        with self.lock:
            named = self._named(entry_id)
            if named is not None and named.model_removed:
                raise self._gone(named, "redone")
            if not self._redo:
                raise Fenced("nothing to redo")
            e = self._redo[-1]
            if entry_id and entry_id != e.id:
                raise Fenced(f"only {e.id} can be redone next")
            if e._swap is not None:
                self._same_layout(scene, e, "redone")
                self._restore(scene, e._swap[1])
            else:
                for i in e._tx:
                    m = scene.models[i]
                    last = m.history[-1] if m.history else None
                    if m is not e._models[i] or m.transaction is not None or last is not e._tail.get(i):
                        raise Fenced("the model changed since it was undone")
                for i, txs in e._tx.items():
                    m = scene.models[i]
                    for t in txs:
                        t.commit()
                        m.history.append(t)
                self._boxes(scene, e._bounds[1])
                scene._edited = set(e._edited[1])
            scene.bump(e.files)
            e.state = "kept"
            self._redo.pop()
            return e

    @staticmethod
    def _same_layout(scene, e: Entry, verb: str) -> None:
        """A wider fix's saved state holds the files as they were: once one was added or removed, it can't come back."""
        if e._layout != getattr(scene, "layout", 0):
            raise Fenced(f"models were added or removed since this wider fix: it can't be {verb}")

    def drop_file(self, index: int, name: str, elements) -> int:
        """A model was taken out of the scene (`Workspace.remove_model`), after `IfcScene.remove_file`: every entry that
        changed it is marked `model_removed` (it stays in the log, never undone or redone, and leaves the redo list),
        every later file index moves down one, and its elements' boxes are forgotten. Returns how many kept entries
        changed it."""
        gone = set(elements)
        shift = lambda i: i - (i > index)
        remap = lambda d: {shift(i): v for i, v in d.items() if i != index}
        kept = 0
        with self.lock:
            for e in self.entries:
                if index in e.files or index in e._tx:
                    e.model_removed = e.model_removed or name
                    kept += e.state == "kept"
                e.files = [shift(i) for i in e.files if i != index]
                e._tx, e._models, e._tail = remap(e._tx), remap(e._models), remap(e._tail)
                e._edited = tuple({shift(i) for i in marks if i != index} for marks in e._edited)
                e._bounds = tuple({g: b for g, b in boxes.items() if g not in gone} for boxes in e._bounds)
            self._redo = [e for e in self._redo if not e.model_removed]
        return kept

    def _fence(self, scene, e: Entry) -> None:
        for i, txs in e._tx.items():
            m = scene.models[i] if i < len(scene.models) else None
            if m is not e._models.get(i):
                raise Fenced("a wider fix replaced the models since")
            if m.transaction is not None:
                raise Fenced("the model is being edited")
            tail = m.history[-len(txs):]
            if len(tail) != len(txs) or any(a is not b for a, b in zip(tail, txs)):
                raise Fenced("an edit outside the log came after it")

    @staticmethod
    def _boxes(scene, boxes: dict) -> None:
        b = scene.bounds()
        for g, box in boxes.items():
            if box is None:
                b.pop(g, None)
            else:
                b[g] = box

    @staticmethod
    def _restore(scene, state: dict) -> None:
        """A wider fix's state back (or forward), keeping the revision and history moving forward."""
        revision, history = scene.revision, scene.history
        scene.__dict__ = dict(state)
        scene.revision, scene.history = revision, history

    def free_rerun(self, entry_id: str | None) -> bool:
        """Whether a detection run to list what this entry was kept with goes uncharged: the newest kept entry, kept
        with clashes, and only once."""
        with self.lock:
            top = self._top()
            if not entry_id or top is None or top.id != entry_id or entry_id in self._reran:
                return False
            if not (top.check or {}).get("accepted_clashes"):
                return False
            self._reran.add(entry_id)
            return True

    # ------------------------------------------------------------------------------------------------- pictures

    def attach_picture(self, entry_id: str, data_url: str) -> None:
        if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
            raise ValueError("a picture is a data:image/ URL")
        if len(data_url) > PICTURE_MAX_BYTES:
            raise ValueError(f"the picture is over {PICTURE_MAX_BYTES // 1000} kB")
        self.get(entry_id).picture = data_url


def entry_lines(entries: list[Entry], limit: int = 3, names: bool = True) -> list[str]:
    """Plain lines for Muse: "E4 (you, 14:05): east end of 'B-12' extended 150 mm; follows E2 (clash s1a2b3c4d)"."""
    out = []
    for e in entries[-limit:]:
        when = datetime.fromtimestamp(e.at, timezone.utc).strftime("%H:%M UTC")
        tie = ""
        if e.follows:
            tie = f"; follows {', '.join(e.follows)}"
        ids = [c["id"] for c in e.clashes if c.get("id")]
        if ids:
            tie += f" (clash {', '.join(str(i) for i in ids[:3])})"   # its id, not a #N number
        state = " [undone]" if e.state == "undone" else ""
        out.append(f"{e.id} ({e.source}, {when}): {e.summary or e.title}{tie}{state}")
    return out
