"""Propose → verify → retry → rank. The model judges; the geometry check keeps it honest.

Nothing reaches the options list without passing `verify.check`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

from . import verify
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


@dataclass
class Attempt:
    title: str
    delta_m: list[float]
    passed: bool
    reason: str


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
    if clash.notes:
        lines.append(f"Notes: {clash.notes}")
    return "\n".join(lines)


def _feedback(attempts: list[Attempt]) -> str:
    if not attempts:
        return ""
    tried = "\n".join(f"- {t.title} {t.delta_m}: {'passed' if t.passed else 'FAILED, ' + t.reason}" for t in attempts)
    return f"\n\nAlready tried:\n{tried}\nPropose different moves."


def resolve(scene: IfcScene | Path, clash: Clash, model: ChatModel, pack: str = "construction",
            max_rounds: int = 3, want: int = 3, clearance_m: float = 0.025,
            on_step: Callable[[Attempt], None] | None = None) -> Result:
    system = (PACKS / f"{pack}.md").read_text()
    base = scene if isinstance(scene, IfcScene) else IfcScene(scene)
    attempts: list[Attempt] = []
    options: list[Option] = []
    understanding = ""

    for _ in range(max_rounds):
        reply = model.complete_json(system, _describe(base, clash) + _feedback(attempts), clash.images)
        understanding = understanding or reply.get("understanding", "")
        for cand in reply.get("candidates", []):
            target = clash.element_a if cand.get("move", "A") == "A" else clash.element_b
            run = base.connected_run(target)
            delta = [float(v) for v in cand["delta_m"]]
            # Try the move in place and undo it: re-serialising a large model per attempt costs seconds.
            # The fittings at the run's ends are meant to stay attached, so they don't count as hits.
            neighbours = {c for g in run for c in base.element(g).connected} - set(run)
            placements = base.translate(run, tuple(delta))
            try:
                v = verify.check(base, run, clearance_m=clearance_m, ignore=neighbours)
            finally:
                base.translate(run, tuple(-d for d in delta))
            reason = "" if v.passed else ", ".join(
                f"{h.kind} with {h.other_class} ({h.distance_m * 1000:+.0f} mm)" for h in v.hits)
            attempt = Attempt(cand.get("title", "move"), delta, v.passed, reason)
            attempts.append(attempt)
            if on_step:
                on_step(attempt)
            if v.passed:
                options.append(Option(cand.get("title", "move"), run, delta, cand.get("rationale", ""),
                                      cand.get("also_needs", ""), v.min_clearance_m, placements))
        if len(options) >= want:
            break

    # Rank: smallest move first, then most clearance. Simple and explainable; the UI shows both numbers.
    options.sort(key=lambda o: (sum(abs(d) for d in o.delta_m), -(o.min_clearance_m or 0)))
    return Result(understanding, options[:want], attempts)


def to_json(result: Result) -> str:
    return json.dumps(asdict(result), default=str)
