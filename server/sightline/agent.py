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

from . import edits, hosts, requirements, verify
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
    others: list[str] = field(default_factory=list)  # more elements A runs into (a plan's merged item): one fix for all
    # Other clashes of A or B close by in the report, per side (GlobalId → its partners): told, not required.
    nearby: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Option:
    title: str
    moved: list[str]
    delta_m: list[float]
    rationale: str
    also_needs: str
    min_clearance_m: float | None
    placements: dict[str, list[float]]  # GlobalId → new 4x4 world matrix, for the browser preview
    kind: str = "move"                  # "move" (delta_m on the run), "offset" (split, middle piece by delta_m Z)
                                        # or "trim" (one end cut back to butt the other element; delta_m: that end)
    split_m: list[float] | None = None  # offset only: split points, metres along the segment from its start
    preview: list[dict] | None = None   # offset and trim: world triangles of the changed pieces, for the browser
    before: list[dict] | None = None    # the changed elements as they are now (world triangles), to compare
    trim: dict | None = None            # trim only: {"end": "start" | "end", "by_m": metres}
    cleanup: bool = False               # a trim inside one model: tidies a joint for its author, not a coordination fix
    checked_against: int = 0            # elements the geometry check tested this fix against (proof strip)
    meets: list[str] = field(default_factory=list)  # the coordination requirements it meets, in plain words
    edit: dict | None = None            # the newer kinds' parameters (route steps, a resize, a penetration), with
                                        # "summary" (the edit in a few words) and "key" (what makes two the same fix)
    review: str | None = None           # who must review it before it is built ("structure", "services"), when
                                        # geometry alone cannot say it works


@dataclass
class Attempt:
    title: str
    delta_m: list[float]
    passed: bool
    reason: str
    kind: str = "move"
    split_m: list[float] | None = None
    hit_ids: list[str] = field(default_factory=list)  # GlobalIds it hit, worst first (at most 8), for the viewer
    trim: dict | None = None
    edit: dict | None = None                          # as Option.edit
    where: list[list[float]] = field(default_factory=list)  # where the worst hits are (world metres), for Muse


@dataclass
class Result:
    understanding: str
    options: list[Option]
    attempts: list[Attempt]   # every try, failures included: the UI streams these as agent steps
    advice: str = ""          # what a person should look at or decide, in the model's words (shown when nothing passed)
    # Under coordination requirements that allow no edit here: Muse Spark's recommended change for the designer (a
    # candidate, never tried or applied) and why ORCA could not make it.
    recommendation: dict | None = None
    requirements: str | None = None   # the requirements' label ("L3 Coordinated · Strict"), when there were some
    clearance_m: float = 0.025        # the clearance every option had to keep


def _describe(scene: IfcScene, clash: Clash, clearance_m: float = 0.025, memo: dict | None = None) -> str:
    """What Muse reads about the clash. `memo` keeps what the geometry said between rounds of one proposal (the room
    past an obstacle costs a ray scan; nothing changes between rounds: every trial is undone)."""
    a, b = scene.element(clash.element_a), scene.element(clash.element_b)
    lines = [
        f"Element A (red): {a.ifc_class} '{a.name}', level {a.storey}, GlobalId {a.global_id}",
        f"Element B (green): {b.ifc_class} '{b.name}', level {b.storey}, GlobalId {b.global_id}",
    ]
    if clash.distance_m is not None:
        lines.append(f"Reported signed distance: {clash.distance_m * 1000:.1f} mm (negative = overlap)")
    for label, this, other, more in (("A", clash.element_a, clash.element_b, clash.others),
                                     ("B", clash.element_b, clash.element_a, [])):
        if any(scene.entity(this).is_a(c) for c in edits.PENETRABLE):   # a wall or slab is not split or rerouted
            continue
        lines += _run_text(scene, label, this, other, clearance_m, more, memo)
        lines += _resize_text(scene, label, this, other, clearance_m)
        lines += _nearby_text(scene, label, this, [n for n in clash.nearby.get(this, []) if n not in (other, *more)])
    for label, this, other, name in (("A", clash.element_a, clash.element_b, "B"), ("B", clash.element_b, clash.element_a, "A")):
        lines += _joint_text(scene, label, this, other, name)
        lines += _penetration_text(scene, label, this, other, name, clearance_m)
    if clash.notes:
        lines.append(f"Notes: {clash.notes}")
    return "\n".join(lines)


def is_service(scene: IfcScene, gid: str) -> bool:
    """A duct, pipe, cable carrier or other distribution element: what a penetration lets through."""
    return scene.entity(gid).is_a("IfcDistributionElement")


def penetration_pairs(scene: IfcScene, clash: Clash) -> list[tuple[str, str, str, str]]:
    """(service label, service, host label, host) where a straight service crosses the other element through its
    depth: where a penetration could go, whatever may be done to that host."""
    out = []
    for label, gid, host_label, host in (("A", clash.element_a, "B", clash.element_b), ("B", clash.element_b, "A", clash.element_a)):
        try:
            if is_service(scene, gid) and not is_service(scene, host):
                edits.penetration(scene, gid, host, fit="fitted")   # the smallest opening: a narrow plate is read too
                out.append((label, gid, host_label, host))
        except (edits.Unsupported, KeyError, RuntimeError):
            continue
    return out


def _penetration_text(scene: IfcScene, label: str, gid: str, host: str, host_label: str, clearance_m: float) -> list[str]:
    """When element `label` is a straight service crossing the other element, what an opening there would be, and
    what may be done to that host (`hosts.decide`)."""
    try:
        if not is_service(scene, gid) or is_service(scene, host):
            return []
        reading = hosts.decide(scene, host, requirements.current())
        pen = edits.penetration(scene, gid, host, clearance_m, reading.fit)
    except (edits.Unsupported, KeyError, RuntimeError):
        return []
    what = f"{scene.element(host).ifc_class} '{scene.element(host).name}'"
    if reading.refuses:
        return [f"Element {label} crosses element {host_label} ({what}) through its depth, but {host_label} may not take an "
                f"opening ({reading.verdict.replace('_', ' ')}: {reading.reasoning or hosts.reading_text(reading)}). "
                f"Do not propose a penetration of {host_label}."]
    problems, numbers = hosts.check_hole(scene, pen, reading)
    fit = ("a fitted gland, 1 mm round it" if pen.fit == "fitted" else f"{clearance_m * 1000:.0f} mm clear all round")
    lines = [f"Element {label} crosses element {host_label} ({what}) through its full depth "
             f"({pen.depth_m - 2 * edits.OPENING_PROUD_M:.3f} m). A \"penetration\" (move: \"{label}\") asks for a "
             f"{edits.size_text(pen)} opening ({fit}): {host_label}'s team cuts it. Reading of this kind of host: "
             f"{hosts.reading_text(reading)}."]
    if problems:
        lines.append(f"Here the opening breaks its limits: {'; '.join(problems)}. Do not propose a penetration of "
                     f"{host_label} at this point.")
    asked = edits.provision_for(scene, gid, host)
    if asked is not None:
        lines.append(f"An opening has already been requested here (provision for void '{asked.Name}'): it waits for "
                     f"{host_label}'s team to cut it. Do not ask for it again.")
    run = edits.run_of(scene, gid)
    along = float(np.asarray(pen.start) @ np.asarray(run.direction) - np.asarray(run.start) @ np.asarray(run.direction))
    if along > 0 and along + pen.depth_m < run.length_m:   # it runs out of both faces: it serves something beyond
        lines.append(f"Element {label} runs out of both faces of {host_label}: it serves something on the far side, so a fix "
                     f"that stops it crossing (moving it along its length, shortening it) cuts it off. Cross {host_label} "
                     f"through an opening, or route round its end if it has one nearby.")
    return lines


def _joint_text(scene: IfcScene, label: str, gid: str, other: str, other_label: str) -> list[str]:
    """When one element's end runs into the other, the clash is at a joint: say so, and what a trim would take."""
    try:
        cut = edits.butt_trim(scene, gid, other)
    except (edits.Unsupported, KeyError, RuntimeError):
        return []
    lines = [f"Joint: element {label}'s {cut.end} runs {cut.by_m * 1000:.0f} mm into element {other_label} along its "
             f"length. A \"trim\" of {label} cuts that end back to butt against {other_label}'s face: a connection "
             f"fix, nothing moves."]
    if scene.element(gid).source == scene.element(other).source:
        lines.append(f"Both are in the same model ({scene.element(gid).source}): an overlap at a joint like this is often "
                     "how the parts are built (a beam cast into its footing, a transom into its mullion). A trim only tidies "
                     "the model for its author; say so, and say in advice when the overlap is simply by design.")
    return lines


def _run_text(scene: IfcScene, label: str, gid: str, other: str, clearance_m: float = 0.025,
              others: list[str] = (), memo: dict | None = None) -> list[str]:
    """A straight segment's geometry, and where the other element (and any `others` it also runs into) sits along it:
    what a local offset needs."""
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
                         f"{b[other][1][2]:.3f} m. A local offset of {label} can split it either side of that: "
                         + (f"its 90° bends take up to {run.depth_m:.2f} m of run before and after each split point "
                            f"(the bend radius, about one profile depth), the riser {run.depth_m / 2:.2f} m either side "
                            f"of it, and at least 0.05 m of straight must remain at each end and in the middle."
                            if edits.default_corners() == "bends" else
                            f"a riser takes {run.depth_m:.2f} m of run, and at least 0.05 m must remain at each end."))
            try:
                holes = edits.passages(scene, gid, other, clearance_m=clearance_m)
            except RuntimeError:
                holes = []
            for h in holes:
                lines.append(f"The other element has an opening on this line from z {h['bottom_m']:.3f} to "
                             f"{h['top_m']:.3f} m: offsetting {label}'s middle piece by {h['dz_min_m']:+.3f} to "
                             f"{h['dz_max_m']:+.3f} m passes it through with {clearance_m * 1000:.0f} mm all round.")
            lines += _room_text(scene, label, gid, [other], "the other element", clearance_m, above=not holes, memo=memo)
    for o in others:
        if o not in b:
            continue
        corners = np.array([[x, y, z] for x in b[o][:, 0] for y in b[o][:, 1] for z in b[o][:, 2]])
        along = (corners - start) @ d
        lo, hi = max(along.min(), 0.0), min(along.max(), run.length_m)
        if lo < hi:
            e = scene.element(o)
            lines.append(f"Element {label} also runs into {e.ifc_class} '{e.name}' at {lo:.2f}-{hi:.2f} m along it, "
                         f"from z {b[o][0][2]:.3f} to {b[o][1][2]:.3f} m: one fix must clear it too.")
            lines += _room_text(scene, label, gid, [o], f"'{e.name}'", clearance_m, memo=memo)
    if others:
        together = _room_text(scene, label, gid, [other, *others], "all of them at once", clearance_m, above=False,
                              memo=memo)
        lines += together or [f"No side offset clears all of them in one stretch: give each obstacle its own step and "
                              f"return to the line between them."]
    return lines


def _resize_text(scene: IfcScene, label: str, gid: str, other: str, clearance_m: float) -> list[str]:
    """When a rectangular duct or tray meets an obstacle above or below it: how deep it can be there, keeping the face
    away from the obstacle level, and how wide that makes it for the same performance (a "resize")."""
    try:
        *_, width, depth, _, _ = edits._resizable(scene, scene.entity(gid))
        run = edits.run_of(scene, gid)
    except (edits.Unsupported, KeyError):
        return []
    box = scene.bounds().get(other)
    if box is None:
        return []
    centre = run.start[2]
    bottom, top = centre - depth / 2, centre + depth / 2
    if box[0][2] >= centre:
        keep, room, where = "bottom", box[0][2] - clearance_m - bottom, "under"
    elif box[1][2] <= centre:
        keep, room, where = "top", top - (box[1][2] + clearance_m), "over"
    else:
        return []
    room = float(np.floor(round(room / edits.SIZE_STEP_M, 6)) * edits.SIZE_STEP_M)
    if not 0 < room < depth - 1e-4:
        return []
    try:
        size = edits.resize_size(scene, gid, room)
    except edits.Unsupported as e:
        return [f"Element {label} cannot be made flat enough to pass {where} the other element ({room * 1000:.0f} mm deep "
                f"would fit): {e}."]
    lt = edits.transition_length(width, depth, size["width_m"], size["depth_m"], keep)
    return [f"A \"resize\" of {label} (move: \"{label}\"): keeping its {keep} level, {room * 1000:.0f} mm deep passes "
            f"{where} the other element with {clearance_m * 1000:.0f} mm clear; it is then {size['width_m'] * 1000:.0f} mm "
            f"wide ({size['performance']}). The resized stretch (split_m) must cover the other element; each transition "
            f"takes {lt:.2f} m of run outside it, and 0.05 m must remain at each end. It changes how the service performs: "
            f"its designer reviews it, so prefer a move, offset or route when one clears."]


def _nearby_text(scene: IfcScene, label: str, gid: str, nearby: list[str]) -> list[str]:
    """Other clashes of this element close by, along its run: worth clearing in the same fix, never required."""
    try:
        run = edits.run_of(scene, gid)
    except (edits.Unsupported, KeyError):
        return []
    b = scene.bounds()
    start, d = np.asarray(run.start), np.asarray(run.direction)
    lines = []
    for o in nearby:
        if o not in b:
            continue
        corners = np.array([[x, y, z] for x in b[o][:, 0] for y in b[o][:, 1] for z in b[o][:, 2]])
        along = (corners - start) @ d
        lo, hi = max(along.min(), 0.0), min(along.max(), run.length_m)
        if lo < hi:
            e = scene.element(o)
            lines.append(f"Element {label} also clashes nearby with {e.ifc_class} '{e.name}' at {lo:.2f}-{hi:.2f} m along "
                         f"it (another clash in this report): a fix that clears both fixes both, but only this one is "
                         f"required.")
    return lines


def _compass(v) -> str:
    v = np.asarray(v, float)
    return ("east" if v[0] > 0 else "west") if abs(v[0]) >= abs(v[1]) else ("north" if v[1] > 0 else "south")


def _room_text(scene: IfcScene, label: str, gid: str, obstacles: list[str], what: str, clearance_m: float,
               above: bool = True, memo: dict | None = None) -> list[str]:
    """The room a route has past `obstacles`: side offsets (and up offsets when `above`) at which the run's profile
    clears everything along their stretch (`edits.free_bands`), once per proposal when given a `memo`."""
    key = ("room", gid, tuple(obstacles), what, clearance_m, above)
    if memo is not None and key in memo:
        return memo[key]
    try:
        run = edits.run_of(scene, gid)
        _, side = edits.run_frame(run.direction)
    except (edits.Unsupported, KeyError):
        return []
    lines = []
    for axis in ("side", "up") if above else ("side",):
        try:
            bands = edits.free_bands(scene, gid, obstacles, axis, clearance_m)
        except RuntimeError:
            continue
        if bands:
            ranges = ", ".join(f"{b['from_m']:+.2f} to {b['to_m']:+.2f}" for b in bands)
            meaning = (f"side offsets (+ is {_compass(side)}, - {_compass(-side)})" if axis == "side"
                       else "up offsets (+ up, - down)")
            lines.append(f"Room past {what} for element {label}: {meaning} of {ranges} m keep {clearance_m * 1000:.0f} mm "
                         f"clear of everything along that stretch (a route step can use them).")
    if memo is not None:
        memo[key] = lines
    return lines


def edit_text(kind: str, delta_m: list[float], split_m: list[float] | None = None, trim: dict | None = None,
              edit: dict | None = None) -> str:
    """The edit an idea makes, in a few words: Muse's feedback, plan summaries and chat use it."""
    if edit and edit.get("summary"):
        return edit["summary"]
    if kind == "offset":
        return f"offset {split_m} by {delta_m[2]:+.3f} m"
    if kind == "trim":
        return f"trim the {trim['end']} end by {trim['by_m'] * 1000:.0f} mm" if trim else "trim at the joint"
    return f"move {delta_m}"


def _feedback(attempts: list[Attempt]) -> str:
    if not attempts:
        return ""

    def outcome(t: Attempt) -> str:
        if t.passed:
            return "passed"
        where = f" at {', '.join(str(p) for p in t.where)}" if t.where else ""
        return f"FAILED, {t.reason}{where}"
    tried = "\n".join(f"- {t.title} ({edit_text(t.kind, t.delta_m, t.split_m, t.trim, t.edit)}): {outcome(t)}"
                      for t in attempts)
    return f"\n\nAlready tried:\n{tried}\nPropose different fixes."


# Kinds that change more than where something is rank below plain geometry fixes, whatever their size: a resize changes
# how a service performs, a penetration needs another team to build it. Neither ends the search on its own either.
TIERS = {"resize": 1, "penetration": 2}


def tier(kind: str | None, edit: dict | None = None) -> float:
    """How an option ranks by kind; an opening in anything but a wall or slab (a beam's web, a plate) after one in a
    wall or slab."""
    return TIERS.get(kind or "move", 0) + (0.5 if kind == "penetration" and edit and not edit.get("plain_host", True) else 0)


def resolve(scene: IfcScene | Path, clash: Clash, model: ChatModel, pack: str = "construction",
            max_rounds: int = 3, want: int = 3, clearance_m: float = 0.025,
            on_event: Callable[[dict], None] | None = None, lock=None, trials: bool = False,
            policy: dict | None = None, guidance: str = "", recommend: str | None = None, doc=None,
            hosts_model: ChatModel | None = None) -> Result:
    """Rounds of propose → verify until a round yields a verified option (or `max_rounds` pass).

    `on_event` hears progress as it happens, for streaming to the UI: {"type": "thinking", "round"},
    {"type": "ideas", "round", "seconds", "understanding", "count"}, {"type": "checking", "index", "title", "kind"},
    with `trials`, {"type": "reasoning", "round", "text"} (a summary of what Muse Spark is working out, as it thinks;
    when the model streams them) and {"type": "trial", "index", "kind", "moved", "delta_m", "pieces"} (the candidate in place, before it is checked:
    a move's elements and delta, or an offset's new pieces as world triangles, so the browser can show what is being
    tried) and {"type": "attempt", "index", **attempt}.

    `lock` serialises every use of the scene, so several clashes can be resolved at once: their model calls
    overlap, their geometry trials (which edit the model and undo) take turns.

    Under coordination requirements (`Workspace.fix_settings`): `policy` (GlobalId → requirements.Policy) refuses a
    candidate they forbid before it is tried, as a failed attempt Muse is told about; `guidance` is added to the
    system prompt; each verified option says what it `meets` of `doc`; with `recommend` (why nothing may be edited),
    Muse Spark is still asked, once, and its best idea comes back as a recommendation, never tried or applied.

    `hosts_model` (the triage model) reads, once per kind, what may be done to a host a service crosses
    (`hosts.read`) before the first round, so Muse is told whether an opening there is possible.
    """
    lock = lock or contextlib.nullcontext()
    system = (PACKS / f"{pack}.md").read_text() + guidance
    if recommend:
        return _recommend(scene, clash, model, system + requirements.RECOMMEND.format(why=recommend), recommend,
                          clearance_m, on_event, lock, trials, doc)
    base = scene if isinstance(scene, IfcScene) else IfcScene(scene)
    attempts: list[Attempt] = []
    options: list[Option] = []
    understanding = ""
    advice = ""
    emit = on_event or (lambda e: None)
    memo: dict = {}   # what the geometry tells Muse, kept between rounds (every trial is undone)

    def on_step(attempt: Attempt) -> None:
        emit({"type": "attempt", "index": len(attempts) - 1, **asdict(attempt)})

    for round_no in range(1, max_rounds + 1):
        emit({"type": "thinking", "round": round_no})
        started = time.perf_counter()
        if round_no == 1 and hosts_model is not None:   # what may be done to a host the service crosses, once per kind
            with lock:
                profiles = [hosts.profile(base, host) for *_, host in penetration_pairs(base, clash)
                            if not hosts.hard_rule(base, host)]
            if profiles:
                try:
                    hosts.read(hosts_model, profiles)
                except Exception as e:   # a reading that fails leaves the defaults: walls and slabs only
                    emit({"type": "note", "text": f"Could not read the host: {e}"})
        with lock:
            text = _describe(base, clash, clearance_m, memo) + _feedback(attempts)
        if trials and on_event and getattr(model, "streams_reasoning", False):  # someone is watching: show the thinking
            reply = model.complete_json_reasoning(system, text, clash.images, None,
                                                  lambda note, r=round_no: emit({"type": "reasoning", "round": r, "text": note}))
        else:
            reply = model.complete_json(system, text, clash.images)
        understanding = understanding or reply.get("understanding", "")
        advice = reply.get("advice") or advice  # the latest round knows the most
        candidates = reply.get("candidates", [])
        emit({"type": "ideas", "round": round_no, "seconds": round(time.perf_counter() - started, 1),
              "understanding": understanding, "count": len(candidates)})
        for cand in candidates:
            emit({"type": "checking", "index": len(attempts), "title": cand.get("title", ""),
                  "kind": cand.get("kind", "move")})
            target = clash.element_a if cand.get("move", "A") == "A" else clash.element_b
            other = clash.element_b if target == clash.element_a else clash.element_a
            trial = (lambda shape, i=len(attempts): emit({"type": "trial", "index": i, **shape})) if on_event and trials else None
            kind = cand.get("kind") or "move"
            if kind not in TRIES:
                unknown = Attempt(cand.get("title", kind), [0.0, 0.0, 0.0], False,
                                  f"unknown kind {kind!r}: use one of {', '.join(TRIES)}", kind)
                attempts.append(unknown)
                on_step(unknown)
                continue
            refused = _refused(base, cand, target, other, policy) if policy else None
            if refused:
                attempts.append(refused)
                on_step(refused)
                continue
            with lock:
                attempt, option = TRIES[kind](base, cand, target, other, clearance_m, trial, others=clash.others)
            attempts.append(attempt)
            on_step(attempt)
            if option:
                _keep(options, option)
        # One round with a verified option is enough: another round costs a full model call (tens of seconds). Only
        # a plain geometry fix ends the search at once; a resize or a penetration gets one more round to beat it.
        if any(tier(o.kind) == 0 for o in options) or (options and round_no >= 2):
            break

    # Rank: plain geometry fixes before a resize before a penetration; then options with comfortable clearance (twice
    # the minimum, or nothing near), then the smallest change, then the most clearance. Simple and explainable; the
    # UI shows both numbers.
    def comfortable(o: Option) -> bool:
        return o.min_clearance_m is None or o.min_clearance_m >= 2 * clearance_m - 1e-6
    options.sort(key=lambda o: (tier(o.kind, o.edit), not comfortable(o), sum(abs(d) for d in o.delta_m),
                                -(o.min_clearance_m or 1.0)))
    options = options[:want]
    for o in options:  # what each option changes, as it is now, so the UI can show before and after together
        try:
            with lock:
                o.before = edits.meshes(base, o.moved)
        except RuntimeError:
            o.before = None
        if policy and doc is not None:
            mine = clash.element_a if clash.element_a in o.moved else clash.element_b
            if o.kind == "penetration":   # its team asks; the host is the other side
                mine = o.edit["service"]
            theirs = clash.element_b if mine == clash.element_a else clash.element_a
            o.meets = requirements.meets(doc, policy[mine], policy[theirs], clearance_m, o.min_clearance_m,
                                         o.delta_m, o.kind, fitted=(o.edit or {}).get("fit") == "fitted")
    return Result(understanding, options, attempts, advice,
                  requirements=requirements.label(doc) if doc is not None else None, clearance_m=clearance_m)


def _candidate_delta(cand: dict, scene: IfcScene | None = None, target: str | None = None) -> tuple[str, list[float]]:
    kind = cand.get("kind") or "move"
    if kind == "resize":   # how far its moving face goes, when the scene can say
        try:
            size = edits.resize_size(scene, target, float(cand.get("depth_m")))
            return kind, [0.0, 0.0, round(size["depth_m"] - size["before"][1], 4)]
        except (edits.Unsupported, KeyError, TypeError, ValueError, AttributeError):
            return kind, [0.0, 0.0, 0.0]
    if kind == "offset":
        return kind, [0.0, 0.0, float(cand.get("dz_m", 0.0) or 0.0)]
    if kind in ("trim", "penetration"):
        return kind, [0.0, 0.0, 0.0]
    if kind == "route":
        try:
            big = max(((float(st.get("up_m") or 0), float(st.get("side_m") or 0)) for st in cand.get("steps") or []),
                      key=lambda x: x[0] ** 2 + x[1] ** 2, default=(0.0, 0.0))
        except (AttributeError, TypeError, ValueError):
            big = (0.0, 0.0)
        return kind, [0.0, big[1], big[0]]
    try:
        return kind, [float(v) for v in cand.get("delta_m", [0, 0, 0])]
    except (TypeError, ValueError):
        return kind, [0.0, 0.0, 0.0]


def _refused(scene: IfcScene, cand: dict, target: str, other: str, policy: dict) -> Attempt | None:
    """A candidate the coordination requirements forbid, as a failed attempt (so Muse hears why), or None."""
    kind, delta = _candidate_delta(cand, scene, target)
    if kind == "penetration":   # the service's team asks: its policy decides; the host's only whether it is cut
        target, other = penetration_sides(scene, target, other)
    same_model = scene.element(target).source == scene.element(other).source
    why = requirements.blocked(policy[target], policy.get(other), kind, delta, same_model)
    if not why:
        return None
    return Attempt(cand.get("title", kind), delta, False, why, kind,
                   [float(v) for v in cand.get("split_m", [])] if kind == "offset" else None,
                   edit={k: cand[k] for k in PARAMS.get(kind, ()) if k in cand} or None)


def _recommend(scene: IfcScene | Path, clash: Clash, model: ChatModel, system: str, why: str, clearance_m: float,
               on_event, lock, trials: bool, doc) -> Result:
    """No edit is allowed: one round of Muse Spark, its best candidate kept as a recommendation for the designer."""
    emit = on_event or (lambda e: None)
    base = scene if isinstance(scene, IfcScene) else IfcScene(scene)
    emit({"type": "thinking", "round": 1})
    started = time.perf_counter()
    with lock:
        text = _describe(base, clash, clearance_m)
    if trials and on_event and getattr(model, "streams_reasoning", False):
        reply = model.complete_json_reasoning(system, text, clash.images, None,
                                              lambda note: emit({"type": "reasoning", "round": 1, "text": note}))
    else:
        reply = model.complete_json(system, text, clash.images)
    candidates = reply.get("candidates", [])
    emit({"type": "ideas", "round": 1, "seconds": round(time.perf_counter() - started, 1),
          "understanding": reply.get("understanding", ""), "count": len(candidates)})
    rec = None
    if candidates:
        best = candidates[0]
        kind, delta = _candidate_delta(best)
        target = clash.element_a if best.get("move", "A") == "A" else clash.element_b
        rec = {"title": best.get("title", ""), "kind": kind, "element": target, "delta_m": delta,
               "split_m": best.get("split_m"), "edit": {k: best[k] for k in PARAMS.get(kind, ()) if k in best},
               "rationale": best.get("rationale", ""),
               "also_needs": best.get("also_needs", ""), "blocked_by": why,
               "others": [c.get("title", "") for c in candidates[1:3]]}
    return Result(reply.get("understanding", ""), [], [], reply.get("advice", ""), recommendation=rec,
                  requirements=requirements.label(doc) if doc is not None else None, clearance_m=clearance_m)


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
    attempt = Attempt(cand.get("title", "move"), delta, v.passed, _reason(v.hits), hit_ids=_hit_ids(v.hits),
                      where=_where(v.hits))
    if not v.passed:
        return attempt, None
    return attempt, Option(cand.get("title", "move"), run, delta, cand.get("rationale", ""), cand.get("also_needs", ""),
                           v.min_clearance_m, placements, checked_against=v.checked_against)


def _reason(hits: list[verify.Hit]) -> str:
    """What a failed attempt hit, one entry per kind and class: "collision with IfcDuctSegment x5 (worst -249 mm)"."""
    groups: dict[tuple[str, str], list[float]] = {}
    for h in hits:
        groups.setdefault((h.kind, h.other_class), []).append(h.distance_m)
    return ", ".join(f"{kind} with {cls}" + (f" x{len(ds)} (worst {min(ds) * 1000:+.0f} mm)" if len(ds) > 1
                                              else f" ({ds[0] * 1000:+.0f} mm)")
                     for (kind, cls), ds in groups.items())


def _where(hits: list[verify.Hit], limit: int = 3) -> list[list[float]]:
    """Where the worst hits are, world metres to the centimetre: tells Muse which part of an idea ran into something."""
    return [[round(float(c), 2) for c in h.location] for h in sorted(hits, key=lambda h: h.distance_m)
            if h.location is not None][:limit]


def _hit_ids(hits: list[verify.Hit], limit: int = 8) -> list[str]:
    """The elements hit, worst first, each once."""
    out: list[str] = []
    for h in sorted(hits, key=lambda h: h.distance_m):
        if h.other not in out:
            out.append(h.other)
    return out[:limit]


def _keep(options: list[Option], new: Option) -> None:
    """Add a verified option unless it is the same fix as one already kept (same kind and change, within 10 mm, and
    the same edit key: two routes can share their largest offset and still differ)."""
    for i, o in enumerate(options):
        if (o.kind == new.kind and o.moved == new.moved and all(abs(x - y) < 0.01 for x, y in zip(o.delta_m, new.delta_m))
                and (o.edit or {}).get("key") == (new.edit or {}).get("key")):
            if (new.min_clearance_m or 1.0) > (o.min_clearance_m or 1.0):
                options[i] = new
            return
    options.append(new)


def _try_offset(scene: IfcScene, cand: dict, target: str, other: str, clearance_m: float,
                on_trial: Callable[[dict], None] | None = None, *, others: list[str] = ()) -> tuple[Attempt, Option | None]:
    """Split `target` around the obstacle and raise or lower the middle, check it, undo it.

    Only the new pieces (risers and middle) are checked against everything; the shortened end pieces only against
    the obstacles (`other` and `others`), since they lost length and cannot have gained a clash anywhere else.
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
            v = verify.check(scene, off.pieces[1:-1], clearance_m=clearance_m, ignore=ignore)  # bends, risers, middle
            ends = verify.check(scene, [off.pieces[0], off.pieces[-1]], clearance_m=clearance_m, ignore=ignore)
            hits = v.hits + [h for h in ends.hits if h.other == other or h.other in others]
            preview = (shape or edits.meshes(scene, off.pieces)) if not hits else None
    except edits.Unsupported as e:
        return Attempt(title, delta, False, f"cannot offset this element: {e}", "offset", split), None
    reason = _reason(hits)
    attempt = Attempt(title, delta, not hits, reason, "offset", split, _hit_ids(hits), where=_where(hits))
    if hits:
        return attempt, None
    return attempt, Option(title, [target], delta, cand.get("rationale", ""), cand.get("also_needs", ""),
                           v.min_clearance_m, {}, "offset", split, preview, checked_against=v.checked_against)


def _try_trim(scene: IfcScene, cand: dict, target: str, other: str, clearance_m: float,
              on_trial: Callable[[dict], None] | None = None, *, others: list[str] = ()) -> tuple[Attempt, Option | None]:
    """Cut `target`'s end back to butt against `other`, check it, undo it.

    A joint is meant to touch: the trimmed end may touch `other` but not run into it. Elsewhere the member already
    touches what it is framed into (a transom its panels and the mullion at its far end), so only contacts that are
    new, or worse than before the trim, count against it: nothing new hit."""
    title = cand.get("title", "trim at the joint")
    tol = 0.002
    # A trim tidies a joint between two members that stay put (a transom into a mullion). When the other side is a
    # service that can move (a cable tray over a fence post), it moves: cutting the post would weaken the guarding.
    if scene.element(target).fixed and not scene.element(other).fixed:
        return Attempt(title, [0.0, 0.0, 0.0], False,
                       f"cannot trim this element: {scene.element(other).name} can move instead; a trim only tidies a "
                       "joint between members that stay put", "trim"), None
    try:
        cut = edits.butt_trim(scene, target, other)
        by = float(cand["by_m"]) if cand.get("by_m") is not None else cut.by_m
        _, _, d, _ = edits.member_axis(scene, scene.entity(target))
        delta = [round(float(v), 4) for v in (d * by if cut.end == "start" else -d * by)]
        before = {h.other: h.distance_m for h in verify.check(scene, [target], clearance_m=clearance_m).hits}
        with edits.trial(scene, target):
            edits.apply_trim(scene, target, cut.end, by)
            shape = edits.meshes(scene, [target])
            if on_trial:
                on_trial({"kind": "trim", "moved": [target], "delta_m": delta, "pieces": shape})
            v = verify.check(scene, [target], clearance_m=clearance_m)
    except edits.Unsupported as e:
        return Attempt(title, [0.0, 0.0, 0.0], False, f"cannot trim this element: {e}", "trim"), None
    hits = [h for h in v.hits
            if (h.distance_m < -tol if h.other == other else h.other not in before or h.distance_m < before[h.other] - tol)]
    trim = {"end": cut.end, "by_m": round(by, 4)}
    attempt = Attempt(title, delta, not hits, _reason(hits), "trim", None, _hit_ids(hits), trim, where=_where(hits))
    if hits:
        return attempt, None
    same_model = scene.element(target).source == scene.element(other).source
    return attempt, Option(title, [target], delta, cand.get("rationale", ""), cand.get("also_needs", ""),
                           v.min_clearance_m, {}, "trim", None, shape, trim=trim, cleanup=same_model, checked_against=v.checked_against)


def _try_route(scene: IfcScene, cand: dict, target: str, other: str, clearance_m: float,
               on_trial: Callable[[dict], None] | None = None, *, others: list[str] = ()) -> tuple[Attempt, Option | None]:
    """Reroute a stretch of `target` in steps (edits.apply_route), check it, undo it: the new pieces against
    everything, the shortened end pieces against the obstacles, as an offset. A single step straight up or down is an
    offset, and is tried (and kept) as one."""
    title = cand.get("title", "reroute")
    raw = cand.get("steps")
    try:
        # Only a level run that is not drainage: an offset takes neither a slope nor the drainage rule a route keeps.
        level = abs(float(np.asarray(edits.run_of(scene, target).direction)[2])) < 1e-3 and not edits.is_gravity(
            scene.entity(target))
        if (level and isinstance(raw, list) and len(raw) == 1 and not float(raw[0].get("side_m") or 0)
                and float(raw[0].get("up_m") or 0)):
            one = raw[0]
            return _try_offset(scene, {**cand, "kind": "offset", "split_m": [one["from_m"], one["to_m"]],
                                       "dz_m": one["up_m"]}, target, other, clearance_m, on_trial, others=others)
    except (AttributeError, KeyError, TypeError, ValueError, edits.Unsupported):
        pass
    try:
        run = edits.run_of(scene, target)
        steps = edits.route_steps(raw, run.length_m)
        up, side = edits.run_frame(run.direction)
    except (edits.Unsupported, KeyError) as e:
        return Attempt(title, [0.0, 0.0, 0.0], False, f"cannot reroute this element: {e}", "route"), None
    big = max(steps, key=lambda st: st["up_m"] ** 2 + st["side_m"] ** 2)
    delta = [round(float(x), 4) for x in up * big["up_m"] + side * big["side_m"]]
    edit = {"steps": steps, "summary": edits.route_summary(steps, side),
            "key": json.dumps([[round(st[k], 2) for k in ("from_m", "to_m", "up_m", "side_m")] for st in steps])}
    try:
        with edits.trial(scene, target):
            r = edits.apply_route(scene, target, steps)
            shape = edits.meshes(scene, r.pieces) if on_trial else None
            if on_trial:
                on_trial({"kind": "route", "moved": [target], "delta_m": delta, "pieces": shape, "summary": edit["summary"]})
            ignore = set(r.pieces) | {c for g in r.pieces for c in scene.element(g).connected}
            v = verify.check(scene, r.pieces[1:-1], clearance_m=clearance_m, ignore=ignore)  # bends, risers, middles
            ends = verify.check(scene, [r.pieces[0], r.pieces[-1]], clearance_m=clearance_m, ignore=ignore)
            hits = v.hits + [h for h in ends.hits if h.other == other or h.other in others]
            preview = (shape or edits.meshes(scene, r.pieces)) if not hits else None
    except edits.Unsupported as e:
        return Attempt(title, delta, False, f"cannot reroute this element: {e}", "route", edit=edit), None
    attempt = Attempt(title, delta, not hits, _reason(hits), "route", None, _hit_ids(hits), edit=edit, where=_where(hits))
    if hits:
        return attempt, None
    return attempt, Option(title, [target], delta, cand.get("rationale", ""), cand.get("also_needs", ""),
                           v.min_clearance_m, {}, "route", None, preview, checked_against=v.checked_against, edit=edit)


def may_cut(scene: IfcScene, host: str) -> bool:
    """Whether the opening would be cut in `host` under the requirements in use (none: yes)."""
    doc = requirements.current()
    return doc is None or requirements.can_cut(requirements.policy(doc, requirements.Matcher(scene, doc), host))


def penetration_sides(scene: IfcScene, target: str, other: str) -> tuple[str, str]:
    """(service, host) of a penetration: Muse names the service as the element that "moves" (its team asks); when it
    names the host instead (the one that is not a service), the two are swapped."""
    if not is_service(scene, target) and is_service(scene, other):
        return other, target
    return target, other


def _host_kind(scene: IfcScene, host: str) -> dict:
    """The kind of host (hosts.profile's key, and its name): "Add to requirements" scopes its rule to it."""
    prof = hosts.profile(scene, host)
    return {"host_kind": prof["key"], "host_kind_name": prof["facts"]["name"]}


def _group_of(scene: IfcScene, gid: str) -> str | None:
    doc = requirements.current() or requirements.default_doc(scene)
    g = requirements.Matcher(scene, doc).group_of(gid)
    return g.id if g else None


def _try_penetration(scene: IfcScene, cand: dict, target: str, other: str, clearance_m: float,
                     on_trial: Callable[[dict], None] | None = None, *, others: list[str] = ()) -> tuple[Attempt, Option | None]:
    """Ask for an opening through the host (edits.penetration) where `hosts.decide` allows one: cut it in a trial
    (provision for void in the service's model, the opening in the host's), check the hole against the host's limits
    (`hosts.check_hole`) and the service against the host (clear by the clearance, or touching a fitted gland) and
    everything else (nothing new), undo. Kept, the host is cut only when the requirements allow its team's model to
    be edited (`plans.KEEP`)."""
    title = cand.get("title", "request a penetration")
    zero = [0.0, 0.0, 0.0]
    try:
        service, host = penetration_sides(scene, target, other)
        if not is_service(scene, service):
            raise edits.Unsupported("an opening is for a service (a duct, pipe or cable carrier) to pass through")
        reading = hosts.decide(scene, host, requirements.current())
        if reading.refuses:
            raise edits.Unsupported(f"{scene.element(host).name} {reading.verdict.replace('_', ' ')}: "
                                    f"{reading.reasoning or hosts.reading_text(reading)}")
        pen = edits.penetration(scene, service, host, clearance_m, reading.fit)
        problems, numbers = hosts.check_hole(scene, pen, reading)
        if problems:
            raise edits.Unsupported("; ".join(problems))
        asked = edits.provision_for(scene, service, host)
        if asked is not None and not may_cut(scene, host):
            raise edits.Unsupported(f"an opening was already requested here ('{asked.Name}'); it waits for the host's "
                                    "team to cut it")
    except (edits.Unsupported, KeyError) as e:
        return Attempt(title, zero, False, f"cannot request an opening here: {e}", "penetration"), None
    h = scene.element(host)
    summary = f"{edits.size_text(pen)} opening through {h.ifc_class[3:]} '{h.name}'"
    edit = {"service": service, "host": host, "shape": pen.shape, "width_m": pen.width_m, "height_m": pen.height_m,
            "depth_m": pen.depth_m, "clearance_m": clearance_m, "fit": pen.fit, "summary": summary,
            "key": f"{host}|{edits.size_text(pen)}", "host_reading": hosts.reading_text(reading),
            "reading_source": reading.source, "verdict": reading.verdict, "numbers": numbers,
            "plain_host": any(scene.entity(host).is_a(c) for c in edits.PENETRABLE),
            # The host's group under the requirements in use, or those the page would start from the models: "Add to
            # requirements" turns the reading into a rule for it.
            "host_group": _group_of(scene, host), **_host_kind(scene, host)}
    ignore = set(scene.element(service).connected)
    before = {x.other: x.distance_m for x in verify.check(scene, [service], clearance_m=clearance_m, ignore=ignore).hits}
    files = {scene.index_of(service), scene.index_of(host)}
    with edits.trial_files(scene, files):
        edits.apply_penetration(scene, pen, cut=True)
        shape = edits.meshes(scene, [pen.provision, host])
        if on_trial:
            on_trial({"kind": "penetration", "moved": [host], "delta_m": zero, "pieces": shape, "summary": summary})
        v = verify.check(scene, [service], clearance_m=clearance_m, ignore=ignore)
    # The service stays where it is: what it touched before (a valve beside it) is not this fix's. The host must clear
    # by the clearance, or, through a fitted gland, touch at most; every other element this fix is for must clear too
    # (a plan's merged item: one opening does not clear a second wall).
    def counts(x) -> bool:
        if x.other == host:
            return pen.fit != "fitted" or x.distance_m < -0.001
        if x.other in others:
            return True
        return x.other not in before or x.distance_m < before[x.other] - 0.002
    hits = [x for x in v.hits if counts(x)]
    attempt = Attempt(title, zero, not hits, _reason(hits), "penetration", None, _hit_ids(hits), edit=edit, where=_where(hits))
    if hits:
        return attempt, None
    also = "; ".join(x for x in (cand.get("also_needs", ""), *reading.conditions) if x)
    # Its clearance is the opening's gap round the service (what it was sized for), not a contact the service already had.
    return attempt, Option(title, [host], zero, cand.get("rationale", ""), also, pen.gap_m, {}, "penetration",
                           None, shape, checked_against=v.checked_against, edit=edit, review=reading.reviewer)


def _try_resize(scene: IfcScene, cand: dict, target: str, other: str, clearance_m: float,
                on_trial: Callable[[dict], None] | None = None, *, others: list[str] = ()) -> tuple[Attempt, Option | None]:
    """Make a stretch of a rectangular duct or tray flatter (edits.apply_resize), keeping what it carries; check the
    new pieces against everything and the shortened ends against the obstacles, as an offset; undo. Its services
    designer reviews it: the section changes how it performs."""
    title = cand.get("title", "resize the section")
    try:
        split = [float(v) for v in cand.get("split_m") or []]
        depth = float(cand.get("depth_m"))
    except (TypeError, ValueError):
        return Attempt(title, [0.0, 0.0, 0.0], False, "a resize needs split_m (two points) and depth_m", "resize"), None
    keep = cand.get("keep") or "bottom"
    try:
        size = edits.resize_size(scene, target, depth)
        if len(split) != 2:
            raise edits.Unsupported("a resize needs two split points")
    except (edits.Unsupported, KeyError) as e:
        return Attempt(title, [0.0, 0.0, 0.0], False, f"cannot resize this element: {e}", "resize", split), None
    (w0, h0), w1, h1 = size["before"], size["width_m"], size["depth_m"]
    moving = {"bottom": h1 - h0, "top": h0 - h1}.get(keep, (h1 - h0) / 2)   # how far the face that moves goes (+ up)
    delta = [0.0, 0.0, round(moving, 4)]
    edit = {"split_m": sorted(split), "depth_m": h1, "width_m": w1, "keep": keep, "before": [w0, h0],
            "performance": size["performance"], "summary": edits.resize_summary(sorted(split), w1, h1, keep),
            "key": json.dumps([round(x, 2) for x in sorted(split)] + [round(h1, 3), keep])}
    try:
        with edits.trial(scene, target):
            r = edits.apply_resize(scene, target, split, depth, keep)
            shape = edits.meshes(scene, r.pieces) if on_trial else None
            if on_trial:
                on_trial({"kind": "resize", "moved": [target], "delta_m": delta, "pieces": shape, "summary": edit["summary"]})
            ignore = set(r.pieces) | {c for g in r.pieces for c in scene.element(g).connected}
            v = verify.check(scene, r.pieces[1:-1], clearance_m=clearance_m, ignore=ignore)  # transitions, middle
            ends = verify.check(scene, [r.pieces[0], r.pieces[-1]], clearance_m=clearance_m, ignore=ignore)
            hits = v.hits + [h for h in ends.hits if h.other == other or h.other in others]
            preview = (shape or edits.meshes(scene, r.pieces)) if not hits else None
    except edits.Unsupported as e:
        return Attempt(title, delta, False, f"cannot resize this element: {e}", "resize", split, edit=edit), None
    attempt = Attempt(title, delta, not hits, _reason(hits), "resize", split, _hit_ids(hits), edit=edit, where=_where(hits))
    if hits:
        return attempt, None
    also = "; ".join(x for x in (cand.get("also_needs", ""), f"the services designer to confirm the new section "
                                 f"({size['performance']})") if x)
    return attempt, Option(title, [target], delta, cand.get("rationale", ""), also, v.min_clearance_m, {}, "resize",
                           split, preview, checked_against=v.checked_against, edit=edit, review="services")


def _try_move_fix(scene: IfcScene, cand: dict, target: str, other: str, clearance_m: float,
                  on_trial: Callable[[dict], None] | None = None, *, others: list[str] = ()) -> tuple[Attempt, Option | None]:
    return _try_move(scene, cand, target, clearance_m, on_trial)


# Each kind of fix Muse may propose, and how to try it: (scene, candidate, target, other, clearance, on_trial,
# others=) → (Attempt, Option or None). A kind not listed here is refused, never tried as a move.
TRIES: dict[str, Callable] = {"move": _try_move_fix, "offset": _try_offset, "trim": _try_trim, "route": _try_route,
                              "resize": _try_resize, "penetration": _try_penetration}
# The candidate fields each kind is described by, carried into a recommendation (never tried) as its "edit".
PARAMS: dict[str, tuple[str, ...]] = {"move": ("delta_m",), "offset": ("split_m", "dz_m"), "trim": ("by_m",),
                                      "route": ("steps",), "resize": ("split_m", "depth_m", "keep"), "penetration": ()}


def to_json(result: Result) -> str:
    return json.dumps(asdict(result), default=str)
