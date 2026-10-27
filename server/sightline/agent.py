"""Propose → verify → retry → rank. The model judges; the geometry check keeps it honest.

Nothing reaches the options list without passing `verify.check`.
"""
from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

import numpy as np

from . import edits, verify
from .meta_client import ChatModel
from .scene import IfcScene

PACKS = Path(__file__).parent / "domain_packs"


@dataclass
class Clash:
    element_a: str            # GlobalId (red)
    element_b: str            # GlobalId (green)
    distance_m: float | None = None
    images: list[Path] = field(default_factory=list)  # A, B, C when available
    notes: str = ""           # e.g. ceiling void depth, project type


@dataclass
class Option:
    title: str
    moved: list[str]
    delta_m: list[float]
    rationale: str
    also_needs: str
    min_clearance_m: float | None
    placements: dict[str, list[float]]  # GlobalId → new 4x4 world matrix, for the browser preview
    kind: str = "move"                  # "move" (delta_m on the run) or "offset" (split, middle piece by delta_m Z)
    split_m: list[float] | None = None  # offset only: split points, metres along the segment from its start
    preview: list[dict] | None = None   # offset only: world triangles of every piece, for the browser preview
    before: list[dict] | None = None    # the changed elements as they are now (world triangles), to compare


@dataclass
class Attempt:
    title: str
    delta_m: list[float]
    passed: bool
    reason: str
    kind: str = "move"
    split_m: list[float] | None = None
    hit_ids: list[str] = field(default_factory=list)  # GlobalIds it hit, worst first (at most 8), for the viewer


@dataclass
class Result:
    understanding: str
    options: list[Option]
    attempts: list[Attempt]   # every try, failures included: the UI streams these as agent steps


def _describe(scene: IfcScene, clash: Clash) -> str:
    a, b = scene.element(clash.element_a), scene.element(clash.element_b)
    lines = [
        f"Element A (red): {a.ifc_class} '{a.name}', level {a.storey}, GlobalId {a.global_id}",
        f"Element B (green): {b.ifc_class} '{b.name}', level {b.storey}, GlobalId {b.global_id}",
    ]
    if clash.distance_m is not None:
        lines.append(f"Reported signed distance: {clash.distance_m * 1000:.1f} mm (negative = overlap)")
    for label, this, other in (("A", clash.element_a, clash.element_b), ("B", clash.element_b, clash.element_a)):
        lines += _run_text(scene, label, this, other)
    if clash.notes:
        lines.append(f"Notes: {clash.notes}")
    return "\n".join(lines)


def _run_text(scene: IfcScene, label: str, gid: str, other: str) -> list[str]:
    """A straight segment's geometry, and where the other element sits along it: what a local offset needs."""
    try:
        run = edits.run_of(scene, gid)
    except (edits.Unsupported, KeyError):
        return []
    b = scene.bounds()
    start, d = np.asarray(run.start), np.asarray(run.direction)
    lines = [f"Element {label} is a straight segment from {np.round(start, 3).tolist()} to "
             f"{np.round(run.end, 3).tolist()} m ({run.length_m:.2f} m long, direction {np.round(d, 3).tolist()}), "
             f"profile {run.width_m * 1000:.0f} wide x {run.depth_m * 1000:.0f} deep."]
    if other in b:
        corners = np.array([[x, y, z] for x in b[other][:, 0] for y in b[other][:, 1] for z in b[other][:, 2]])
        along = (corners - start) @ d
        lo, hi = max(along.min(), 0.0), min(along.max(), run.length_m)
        if lo < hi:
            lines.append(f"The other element occupies {lo:.2f}-{hi:.2f} m along it, from z {b[other][0][2]:.3f} to "
                         f"{b[other][1][2]:.3f} m. A local offset of {label} can split it either side of that (a riser "
                         f"takes {run.depth_m:.2f} m of run, and at least 0.05 m must remain at each end).")
            try:
                holes = edits.passages(scene, gid, other)
            except RuntimeError:
                holes = []
            for h in holes:
                lines.append(f"The other element has an opening on this line from z {h['bottom_m']:.3f} to "
                             f"{h['top_m']:.3f} m: offsetting {label}'s middle piece by {h['dz_min_m']:+.3f} to "
                             f"{h['dz_max_m']:+.3f} m passes it through with 25 mm all round.")
    return lines


def _feedback(attempts: list[Attempt]) -> str:
    if not attempts:
        return ""
    def what(t: Attempt) -> str:
        return f"offset {t.split_m} by {t.delta_m[2]:+.3f} m" if t.kind == "offset" else f"move {t.delta_m}"
    tried = "\n".join(f"- {t.title} ({what(t)}): {'passed' if t.passed else 'FAILED, ' + t.reason}" for t in attempts)
    return f"\n\nAlready tried:\n{tried}\nPropose different moves."


def resolve(scene: IfcScene | Path, clash: Clash, model: ChatModel, pack: str = "construction",
            max_rounds: int = 3, want: int = 3, clearance_m: float = 0.025,
            on_event: Callable[[dict], None] | None = None, lock=None, trials: bool = False) -> Result:
    """Rounds of propose → verify until a round yields a verified option (or `max_rounds` pass).

    `on_event` hears progress as it happens, for streaming to the UI: {"type": "thinking", "round"},
    {"type": "ideas", "round", "seconds", "understanding", "count"}, {"type": "checking", "index", "title", "kind"},
    with `trials`, {"type": "trial", "index", "kind", "moved", "delta_m", "pieces"} (the candidate in place, before it is checked:
    a move's elements and delta, or an offset's new pieces as world triangles, so the browser can show what is being
    tried) and {"type": "attempt", "index", **attempt}.

    `lock` serialises every use of the scene, so several clashes can be resolved at once: their model calls
    overlap, their geometry trials (which edit the model and undo) take turns.
    """
    lock = lock or contextlib.nullcontext()
    system = (PACKS / f"{pack}.md").read_text()
    base = scene if isinstance(scene, IfcScene) else IfcScene(scene)
    attempts: list[Attempt] = []
    options: list[Option] = []
    understanding = ""
    emit = on_event or (lambda e: None)

    def on_step(attempt: Attempt) -> None:
        emit({"type": "attempt", "index": len(attempts) - 1, **asdict(attempt)})

    for round_no in range(1, max_rounds + 1):
        emit({"type": "thinking", "round": round_no})
        started = time.perf_counter()
        with lock:
            text = _describe(base, clash) + _feedback(attempts)
        reply = model.complete_json(system, text, clash.images)
        understanding = understanding or reply.get("understanding", "")
        candidates = reply.get("candidates", [])
        emit({"type": "ideas", "round": round_no, "seconds": round(time.perf_counter() - started, 1),
              "understanding": understanding, "count": len(candidates)})
        for cand in candidates:
            emit({"type": "checking", "index": len(attempts), "title": cand.get("title", ""),
                  "kind": cand.get("kind", "move")})
            target = clash.element_a if cand.get("move", "A") == "A" else clash.element_b
            other = clash.element_b if target == clash.element_a else clash.element_a
            trial = (lambda shape, i=len(attempts): emit({"type": "trial", "index": i, **shape})) if on_event and trials else None
            with lock:
                attempt, option = (_try_offset(base, cand, target, other, clearance_m, trial) if cand.get("kind") == "offset"
                                   else _try_move(base, cand, target, clearance_m, trial))
            attempts.append(attempt)
            on_step(attempt)
            if option:
                _keep(options, option)
        # One round with a verified option is enough: another round costs a full model call (tens of seconds).
        if options:
            break

    # Rank: options with comfortable clearance (twice the minimum, or nothing near) first, then the smallest change,
    # then the most clearance. Simple and explainable; the UI shows both numbers.
    def comfortable(o: Option) -> bool:
        return o.min_clearance_m is None or o.min_clearance_m >= 2 * clearance_m - 1e-6
    options.sort(key=lambda o: (not comfortable(o), sum(abs(d) for d in o.delta_m), -(o.min_clearance_m or 1.0)))
    options = options[:want]
    for o in options:  # what each option changes, as it is now, so the UI can show before and after together
        try:
            with lock:
                o.before = edits.meshes(base, o.moved)
        except RuntimeError:
            o.before = None
    return Result(understanding, options, attempts)


def _try_move(scene: IfcScene, cand: dict, target: str, clearance_m: float,
              on_trial: Callable[[dict], None] | None = None) -> tuple[Attempt, Option | None]:
    """Move `target`'s straight run, check it, undo it. Re-serialising a large model per attempt costs seconds."""
    run = scene.connected_run(target)
    delta = [float(v) for v in cand.get("delta_m", [0, 0, 0])]
    # The fittings at the run's ends are meant to stay attached, so they don't count as hits.
    neighbours = {c for g in run for c in scene.element(g).connected} - set(run)
    if on_trial:
        on_trial({"kind": "move", "moved": run, "delta_m": delta, "pieces": None})
    placements = scene.translate(run, tuple(delta))
    try:
        v = verify.check(scene, run, clearance_m=clearance_m, ignore=neighbours)
    finally:
        scene.translate(run, tuple(-d for d in delta))
    attempt = Attempt(cand.get("title", "move"), delta, v.passed, _reason(v.hits), hit_ids=_hit_ids(v.hits))
    if not v.passed:
        return attempt, None
    return attempt, Option(cand.get("title", "move"), run, delta, cand.get("rationale", ""), cand.get("also_needs", ""),
                           v.min_clearance_m, placements)


def _reason(hits: list[verify.Hit]) -> str:
    """What a failed attempt hit, one entry per kind and class: "collision with IfcDuctSegment x5 (worst -249 mm)"."""
    groups: dict[tuple[str, str], list[float]] = {}
    for h in hits:
        groups.setdefault((h.kind, h.other_class), []).append(h.distance_m)
    return ", ".join(f"{kind} with {cls}" + (f" x{len(ds)} (worst {min(ds) * 1000:+.0f} mm)" if len(ds) > 1
                                              else f" ({ds[0] * 1000:+.0f} mm)")
                     for (kind, cls), ds in groups.items())


def _hit_ids(hits: list[verify.Hit], limit: int = 8) -> list[str]:
    """The elements hit, worst first, each once."""
    out: list[str] = []
    for h in sorted(hits, key=lambda h: h.distance_m):
        if h.other not in out:
            out.append(h.other)
    return out[:limit]


def _keep(options: list[Option], new: Option) -> None:
    """Add a verified option unless it is the same fix as one already kept (same kind and change, within 10 mm)."""
    for i, o in enumerate(options):
        if o.kind == new.kind and o.moved == new.moved and all(abs(x - y) < 0.01 for x, y in zip(o.delta_m, new.delta_m)):
            if (new.min_clearance_m or 1.0) > (o.min_clearance_m or 1.0):
                options[i] = new
            return
    options.append(new)


def _try_offset(scene: IfcScene, cand: dict, target: str, other: str, clearance_m: float,
                on_trial: Callable[[dict], None] | None = None) -> tuple[Attempt, Option | None]:
    """Split `target` around the obstacle and raise or lower the middle, check it, undo it.

    Only the new pieces (risers and middle) are checked against everything; the shortened end pieces only against
    the obstacle, since they lost length and cannot have gained a clash anywhere else.
    """
    title = cand.get("title", "local offset")
    split = [float(v) for v in cand.get("split_m", [])]
    dz = float(cand.get("dz_m", 0.0))
    delta = [0.0, 0.0, dz]
    if len(split) != 2:
        return Attempt(title, delta, False, "an offset needs two split points", "offset", split), None
    try:
        with edits.trial(scene, target):
            off = edits.apply_offset(scene, target, split[0], split[1], dz)
            shape = edits.meshes(scene, off.pieces) if on_trial else None
            if on_trial:
                on_trial({"kind": "offset", "moved": [target], "delta_m": delta, "pieces": shape})
            ignore = set(off.pieces) | {c for g in off.pieces for c in scene.element(g).connected}
            v = verify.check(scene, off.pieces[1:4], clearance_m=clearance_m, ignore=ignore)
            ends = verify.check(scene, [off.pieces[0], off.pieces[-1]], clearance_m=clearance_m, ignore=ignore)
            hits = v.hits + [h for h in ends.hits if h.other == other]
            preview = (shape or edits.meshes(scene, off.pieces)) if not hits else None
    except edits.Unsupported as e:
        return Attempt(title, delta, False, f"cannot offset this element: {e}", "offset", split), None
    reason = _reason(hits)
    attempt = Attempt(title, delta, not hits, reason, "offset", split, _hit_ids(hits))
    if hits:
        return attempt, None
    return attempt, Option(title, [target], delta, cand.get("rationale", ""), cand.get("also_needs", ""),
                           v.min_clearance_m, {}, "offset", split, preview)


def to_json(result: Result) -> str:
    return json.dumps(asdict(result), default=str)
