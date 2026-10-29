"""A second, longer try at a clash on a larger model (docs/escalation.md).

When Muse Spark's propose → verify loop ends with no verified fix (or only a resize or an opening), the clash can go
to Muse Wonder with more to read: the first try's ideas and exactly why each failed, a wider neighbourhood, the
openings and room past the elements those ideas ran into, and every kind of edit there is, a combined fix included
(agent._try_combined). The ideas are tried and checked the same way: nothing reaches a person unverified.

`brief` is what Wonder reads beyond `agent._describe`; `Workspace.escalate` (service.py) runs it.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from . import agent, edits
from .scene import IfcScene

PACK = agent.PACKS / "escalation.md"
NEAR_M = 5.0        # the neighbourhood: elements whose boxes come this close to where A and B meet
NEAR_MAX = 80       # at most this many of them, nearest first
BLOCKERS = 3        # the elements the first try ran into most: openings and room past each are worked out
MAX_CHARS = 60_000  # about 15k tokens of brief; the 1M context needs no trimming, but every token is billed


def zone(scene: IfcScene, a: str, b: str) -> np.ndarray:
    """Where A and B meet: their boxes' overlap, or the gap between them on an axis where they do not overlap."""
    boxes = scene.bounds()
    lo = np.maximum(boxes[a][0], boxes[b][0])
    hi = np.minimum(boxes[a][1], boxes[b][1])
    return np.array([np.minimum(lo, hi), np.maximum(lo, hi)])


def _gap(box: np.ndarray, z: np.ndarray) -> float:
    return float(np.linalg.norm(np.maximum(0, np.maximum(box[0] - z[1], z[0] - box[1]))))


def neighbourhood(scene: IfcScene, a: str, b: str, near_m: float = NEAR_M, most: int = NEAR_MAX) -> list[str]:
    """The elements around the clash, nearest first: GlobalId, class, name, level, box, how far from where A and B
    meet, and whether it stays (structure) or is joined to A or B."""
    boxes = scene.bounds()
    if a not in boxes or b not in boxes:
        return []
    z = zone(scene, a, b)
    joined = set(scene.element(a).connected) | set(scene.element(b).connected)
    near = sorted((_gap(box, z), g) for g, box in boxes.items() if g not in (a, b))
    near = [(d, g) for d, g in near if d <= near_m][:most]
    if not near:
        return []
    lines = [f"Around the clash (within {near_m:.0f} m of where A and B meet, {len(near)} nearest; boxes are "
             "[min x, y, z] to [max x, y, z] m):"]
    for d, g in near:
        e = scene.element(g)
        tags = (["stays (structure)"] if e.fixed else []) + (["joined to A or B"] if g in joined else [])
        lo, hi = np.round(boxes[g], 3).tolist()
        lines.append(f"- {g} {e.ifc_class} '{e.name}', level {e.storey}, {lo} to {hi}, {d:.2f} m away"
                     + (f" ({', '.join(tags)})" if tags else ""))
    return lines


def first_try(first: dict | None, scene: IfcScene) -> list[str]:
    """What the first try read, proposed and found, in words: its understanding and advice, every idea with why it
    failed (what it hit, by name), and the fixes it verified."""
    if not first:
        return ["No first try was made: this is the first look."]
    names = {}

    def name(g: str) -> str:
        if g not in names:
            try:
                e = scene.element(g)
                names[g] = f"{e.ifc_class} '{e.name}' ({g})"
            except KeyError:
                names[g] = g
        return names[g]
    lines = [f"The first try ({first.get('model') or 'Muse Spark'}) read the clash as: "
             f"{first.get('understanding') or 'no reading given'}"]
    if first.get("advice"):
        lines.append(f"Its advice: {first['advice']}")
    tries = first.get("attempts") or []
    if tries:
        lines.append(f"It tried {len(tries)} idea{'s' if len(tries) != 1 else ''}:")
    for t in tries:
        edit = agent.edit_text(t.get("kind") or "move", t.get("delta_m") or [0, 0, 0], t.get("split_m"), t.get("trim"),
                               t.get("edit"))
        if t.get("passed"):
            outcome = "passed"
        else:
            hit = ", ".join(name(g) for g in (t.get("hit_ids") or [])[:4])
            where = f" at {t['where'][:2]}" if t.get("where") else ""
            outcome = f"FAILED: {t.get('reason') or 'no reason given'}" + (f"; hit {hit}" if hit else "") + where
        lines.append(f"- {t.get('title', '')} ({t.get('kind') or 'move'}: {edit}): {outcome}")
    found = first.get("options") or []
    if found:
        lines.append("It verified these fixes (they stay on offer; propose better ones, or none):")
        for o in found:
            clear = o.get("min_clearance_m")
            lines.append(f"- {o.get('title', '')} ({o.get('kind') or 'move'}: "
                         f"{agent.edit_text(o.get('kind') or 'move', o.get('delta_m') or [0, 0, 0], o.get('split_m'), o.get('trim'), o.get('edit'))})"
                         + (f", {clear * 1000:.0f} mm clear" if clear is not None else "")
                         + (f", needs {o['review']} review" if o.get("review") else ""))
    else:
        lines.append("It found no fix that passed.")
    return lines


def blockers(scene: IfcScene, clash: agent.Clash, first: dict | None, clearance_m: float,
             top: int = BLOCKERS) -> list[str]:
    """For the elements the first try ran into most (not A or B): openings through each on the line of A or B, and
    the room beside or above it, as the first try was told for B."""
    counts: Counter = Counter()
    for t in (first or {}).get("attempts") or []:
        for g in t.get("hit_ids") or []:
            if g not in (clash.element_a, clash.element_b):
                counts[g] += 1
    lines: list[str] = []
    boxes = scene.bounds()
    for g, n in counts.most_common(top):
        if g not in boxes:
            continue
        e = scene.element(g)
        lines.append(f"The first try ran into {e.ifc_class} '{e.name}' ({g}) {n} time{'s' if n != 1 else ''}"
                     + (" (it stays: structure)." if e.fixed else " (a service: it may move in a combined fix)."))
        for label, run in (("A", clash.element_a), ("B", clash.element_b)):
            if scene.element(run).fixed:
                continue
            try:
                holes = edits.passages(scene, run, g, clearance_m=clearance_m)
            except (RuntimeError, KeyError, edits.Unsupported):
                holes = []
            for h in holes:
                lines.append(f"  It has an opening on {label}'s line from z {h['bottom_m']:.3f} to {h['top_m']:.3f} m: "
                             f"offsetting {label} by {h['dz_min_m']:+.3f} to {h['dz_max_m']:+.3f} m passes through it.")
            try:
                lines += ["  " + x for x in agent._room_text(scene, label, run, [g], f"'{e.name}'", clearance_m,
                                                             above=not holes)]
            except (RuntimeError, KeyError, edits.Unsupported):
                pass
    return lines


def brief(scene: IfcScene, clash: agent.Clash, first: dict | None, clearance_m: float = 0.025) -> str:
    """What the second try reads beyond `agent._describe`: the first try, the elements it ran into, the
    neighbourhood, and the kinds of fix there are (from the registry, so none is offered that is not)."""
    parts = ["", "", "## The first try", *first_try(first, scene)]
    near = blockers(scene, clash, first, clearance_m)
    if near:
        parts += ["", "## What the first try ran into", *near]
    around = neighbourhood(scene, clash.element_a, clash.element_b)
    if around:
        parts += ["", *around]
    parts += ["", "Kinds of fix ORCA can try: " + ", ".join(agent.TRIES) + "."]
    text = "\n".join(parts)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n(cut short)"
