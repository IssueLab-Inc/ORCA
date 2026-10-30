"""The PC-03 palletising cell opened from STEP: conversion, detection, a move fix, and the STEP written back.

The demo-models repo's `palletising-cell/` writes the same cell as STEP and IFC from one parts list, with an answer key
(`verify_cell.PLANTED`: eight planted problems, 17 part pairs in Rev A, none in Rev B; `BY_DESIGN`: contacts the cell is
built with). This opens the STEP files the way the app does (`Workspace.open`: convert, name the parts' classes with
the titles' model, triangulate), then checks:
- every part converted, names unique, and the classes the model picked against the parts list's own classes;
- detection on Rev A finds every planted pair and nothing that is neither planted nor by design; Rev B none planted;
- C2 (the CT-301 cable ladder through fence post W5): moving the ladder run 150 mm up, as Rev B does, clears it;
- C1 (the air pipe through both conveyor rails): Fix together makes one job and finds a verified fix;
- C3 (a fence rail 40 mm into post SE): trimmed back to the post's face;
- C6 (the PL-302 branch through plant columns C3 and C4): the designer's route (200 mm out round each column) passes
  the check; Fix together on both clashes makes one job, and Muse's fix is a verified route;
- C7 (the plant's compressed-air main through the west wall): only an opening clears; a single proposal offers a
  penetration, and kept (no requirements) the opening is cut;
- export writes the STEP again: the ladder 150 mm higher, the pipe's offset pieces added, the rail shorter, the west
  wall cut and the provision for void added to the compressed-air group, see-through;
- C8 (the 400 V feed conduit through EP-301's top gland plate): Muse reads the gland plate (allowed, a fitted gland),
  a single proposal offers the gland hole, kept and cut; the exported plate has the hole.

    cd server
    uv run python ../evals/step_cell.py --cell $DEMO_MODELS/palletising-cell \
        --out ../evals/runs/<date>-cell-step
"""
from __future__ import annotations

import argparse
import os
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A clone of IssueLab's demo-models repo (CLAUDE.md, "Demo data"): $DEMO_MODELS, else ../demo-models.
DEMO = Path(os.environ.get("DEMO_MODELS", ROOT.parent / "demo-models"))
sys.path.insert(0, str(ROOT / "server"))

from sightline import detect, edits, plans, step, verify  # noqa: E402
from sightline.meta_client import triage_model  # noqa: E402
from sightline.service import Workspace  # noqa: E402


def zmin(part) -> float:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.Add_s(part.shape, box)
    return box.CornerMin().Z()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", type=Path, default=DEMO / "palletising-cell")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-classes", action="store_true", help="convert without the model (every part a proxy)")
    args = ap.parse_args()
    sys.path.insert(0, str(args.cell / "Code"))
    from celllayout import build
    from verify_cell import PLANTED, by_design

    args.out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp())
    for rev in ("A", "B"):
        shutil.copy(args.cell / "STEP" / f"PC-03-Palletising-Cell-Rev{rev}.step", work)
    model = None if args.no_classes else triage_model()[0]
    lines = ["# The PC-03 palletising cell from STEP", ""]
    ok = True
    for rev in ("A", "B"):
        layout = build(rev)
        key_of = {p.name: p.key for p in layout.parts}
        cls_of = {p.key: p.ifc_class for p in layout.parts}
        ws = Workspace(samples=work)
        t0 = time.perf_counter()
        sid = ws.open([f"PC-03-Palletising-Cell-Rev{rev}.step"], classify_with=model)
        opened = time.perf_counter() - t0
        scene = ws.scene(sid)
        manifest = json.loads(Path(ws.sources[sid][0]["manifest"]).read_text())
        gids = list(manifest["parts"])
        keys = {g: key_of[scene.entity(g).Name] for g in gids}
        same = sum(1 for g in gids if scene.entity(g).is_a() == cls_of[keys[g]])
        t1 = time.perf_counter()
        run = detect.run(scene)
        seconds = time.perf_counter() - t1
        found = {frozenset((keys[c.a.global_id], keys[c.b.global_id])) for c in run.report.clashes}
        planted = {frozenset((a, b)): label for label, a, b in PLANTED}
        hit = {p: label for p, label in planted.items() if p in found}
        unexpected = sorted(sorted(p) for p in found if p not in planted and not by_design(*sorted(p)))
        designed = sum(1 for p in found if p not in planted and by_design(*sorted(p)))
        want = len(planted) if rev == "A" else 0
        good = len(hit) == want and not unexpected and len(gids) == len(layout.parts)
        ok &= good
        lines += [f"## Rev {rev}: {'pass' if good else 'FAIL'}", "",
                  f"- Opened from STEP in {opened:.1f} s: {len(gids)} of {len(layout.parts)} parts "
                  f"({'classes by the model' if manifest['classified'] else 'no classes: proxies'}; "
                  f"{same} of {len(gids)} match the parts list's own IFC class).",
                  f"- Detection: {len(run.report.clashes)} clashes in {seconds:.1f} s; {len(hit)} of the "
                  f"{len(planted)} planted pairs (expected {want}), {designed} by design, {len(unexpected)} unexpected.",
                  *[f"  - unexpected: {a} × {b}" for a, b in unexpected[:20]], ""]
        missed = [label for p, label in planted.items() if p not in hit]
        if rev == "A" and missed:
            lines += [f"- Missed: {', '.join(sorted(set(missed)))}", ""]

        if rev == "A":
            gid_of = {k: g for g, k in keys.items()}
            ladder = scene.connected_run(gid_of["ct/h2"])
            post = gid_of["fence/post/W5"]
            names = sorted(scene.entity(g).Name for g in ladder)
            before = verify.check(scene, ladder)
            ws.apply(sid, ladder, (0.0, 0.0, 0.15))
            after = verify.check(scene, ladder)
            hits_post = any(h.other == post and h.kind == "collision" for h in after.hits)

            # C1: the air pipe through both conveyor rails. Fix together makes it one job (one movable pipe, two
            # rails); the exact pipe (a cylinder in the STEP, an extrusion here) can be split and dropped under them.
            c1_lines, c1_ok, kinds = [], True, []
            if model is not None:
                rid = ws.detect(sid)["report"]["id"]
                pipe = gid_of["air/seg2"]
                rails = {gid_of["cv/rail/north"], gid_of["cv/rail/south"]}
                ids = [c.id for c in ws.report(rid).clashes if pipe in (c.a.global_id, c.b.global_id)
                       and {c.a.global_id, c.b.global_id} & rails]
                t2 = time.perf_counter()
                plan = plans.build_batch(ws, sid, rid, ids)
                kinds = [it.option["kind"] if it.option else None for it in plan.items]
                c1_ok = len(plan.items) == 1 and kinds[0] is not None and plan.check["passed"]  # any verified fix
                if c1_ok:
                    plans.apply(ws, sid, [it.option for it in plan.items])
                item = plan.items[0] if plan.items else None
                c1_lines = [f"## C1 fix together: {'pass' if c1_ok else 'FAIL'}", "",
                            f"- {len(ids)} clashes → {len(plan.items)} job ({item.label if item else '-'}), "
                            f"{time.perf_counter() - t2:.0f} s.",
                            f"- Fix: {item.option['title'] if item and item.option else (item.error if item else '-')}"
                            f" ({kinds[0] if kinds else '-'}); checked together: "
                            f"{'clear' if plan.check['passed'] else 'not clear'}.", ""]
            ok &= c1_ok

            # C6: PL-302 runs through both plant columns. Only a detour round each column clears (the columns are full
            # height, the wall is behind, ES-2 stands between them on the open side).
            c6_lines, c6_ok, c6_kind = [], True, None
            seg3, cols = gid_of["air/pl302/seg3"], {gid_of["bldg/column/C3"], gid_of["bldg/column/C4"]}
            designer = [{"from_m": 1.75, "to_m": 2.55, "side_m": 0.2}, {"from_m": 4.25, "to_m": 5.05, "side_m": 0.2}]
            with edits.trial(scene, seg3):
                r6 = edits.apply_route(scene, seg3, designer)
                own = set(r6.pieces) | {c for g in r6.pieces for c in scene.element(g).connected}
                mid = verify.check(scene, r6.pieces[1:-1], ignore=own)
                ends = verify.check(scene, [r6.pieces[0], r6.pieces[-1]], ignore=own)
                designer_ok = mid.passed and not [h for h in ends.hits if h.other in cols]
            c6_ok &= designer_ok
            c6_lines = [f"- The designer's route ({edits.route_summary(r6.steps, (0, 1, 0))}): "
                        f"{'clear' if designer_ok else 'NOT clear'}, nearest {(mid.min_clearance_m or 0) * 1000:.0f} mm, "
                        f"{len(r6.pieces)} pieces."]
            if model is not None:
                rid6 = ws.detect(sid)["report"]["id"]
                ids6 = [c.id for c in ws.report(rid6).clashes if seg3 in (c.a.global_id, c.b.global_id)
                        and {c.a.global_id, c.b.global_id} & cols]
                t6 = time.perf_counter()
                plan6 = plans.build_batch(ws, sid, rid6, ids6)
                it6 = plan6.items[0] if plan6.items else None
                c6_kind = it6.option["kind"] if it6 and it6.option else None
                muse_ok = len(plan6.items) == 1 and c6_kind == "route" and plan6.check["passed"]
                c6_ok &= muse_ok
                if muse_ok:
                    plans.apply(ws, sid, [it6.option])
                c6_lines += [f"- Fix together: {len(ids6)} clashes → {len(plan6.items)} job, "
                             f"{time.perf_counter() - t6:.0f} s, {it6.tried if it6 else 0} ideas tried; fix: "
                             f"{(it6.option['title'] + ' (' + c6_kind + ': ' + it6.option['edit']['summary'] + ')') if c6_kind == 'route' else (it6.option['title'] + ' (' + str(c6_kind) + ')') if c6_kind else (it6.error if it6 else '-')}; "
                             f"checked together: {'clear' if plan6.check.get('passed') else 'not clear'}."]
            ok &= c6_ok
            c6_lines = [f"## C6 route: {'pass' if c6_ok else 'FAIL'}", "", *c6_lines, ""]

            # C7: the plant's compressed-air main runs through the west wall with no opening. The wall is full height
            # and runs the length of the plant: nothing goes round it, so an opening is asked for (and, with no
            # requirements, cut).
            main, wall = gid_of["air/main"], gid_of["bldg/wall/west"]
            pen = edits.penetration(scene, main, wall)
            c7_lines, c7_kinds = [f"- The opening the main needs: {edits.size_text(pen)}, {pen.depth_m * 1000:.0f} mm "
                                  f"deep (the wall and 10 mm proud of each face)."], []
            if model is not None:
                rid7 = ws.detect(sid)["report"]["id"]
                c7 = next(c for c in ws.report(rid7).clashes if {c.a.global_id, c.b.global_id} == {main, wall})
                t7 = time.perf_counter()
                r7 = ws.propose(sid, c7.a.global_id, c7.b.global_id, report_id=rid7, clash_id=c7.id)
                c7_kinds = [o["kind"] for o in r7["options"]]
                first = next((o for o in r7["options"] if o["kind"] == "penetration"), None)
                c7_lines += [f"- Single proposal on #{c7.number}: {time.perf_counter() - t7:.0f} s, "
                             f"{len(r7['attempts'])} ideas tried, options {c7_kinds or 'none'}"
                             + (f"; first penetration: {first['title']} ({first['edit']['summary']}, "
                                f"review: {first['review']}, also needs: {first['also_needs'] or 'nothing'})" if first else "")
                             + "."]
                c7_lines += [f"  - option {k + 1}: {o['title']} ({o['kind']}, {len(o['moved'])} element(s), "
                             f"{[round(v, 2) for v in o['delta_m']]})" for k, o in enumerate(r7["options"])]
            kept7 = ws.apply_penetration(sid, main, wall)
            c7_clear = not [h for h in verify.check(scene, [main]).hits if h.other == wall]
            c7_ok = kept7["cut"] and c7_clear and (model is None or "penetration" in c7_kinds)
            c7_lines += [f"- Kept: provision for void written, opening {'cut' if kept7['cut'] else 'not cut'}; the main "
                         f"{'clears' if c7_clear else 'still hits'} the wall."]
            ok &= c7_ok

            # C8: the plant's 400 V feed drops into EP-301 through its top gland plate, which has no hole. Muse reads the
            # gland plate (made to be drilled for cables, with a fitted gland) and the opening is a gland hole.
            conduit, plate = gid_of["elec/c302"], gid_of["gland/ep301-top"]
            c8_lines, c8_option = [], None
            if model is not None:
                rid8 = ws.detect(sid)["report"]["id"]
                c8 = next(c for c in ws.report(rid8).clashes if {c.a.global_id, c.b.global_id} == {conduit, plate})
                t8 = time.perf_counter()
                r8 = ws.propose(sid, c8.a.global_id, c8.b.global_id, report_id=rid8, clash_id=c8.id)
                c8_option = next((o for o in r8["options"] if o["kind"] == "penetration"), None)
                c8_lines += [f"- Single proposal on #{c8.number}: {time.perf_counter() - t8:.0f} s, {len(r8['attempts'])} ideas "
                             f"tried, options {[o['kind'] for o in r8['options']] or 'none'}."]
                if c8_option:
                    e8 = c8_option["edit"]
                    c8_lines += [f"- {c8_option['title']}: {e8['summary']} ({e8['fit']}); host: {e8['host_reading']} "
                                 f"({e8['reading_source']}); hole: {'; '.join(e8['numbers'])}; review: "
                                 f"{c8_option['review'] or 'none'}; also needs: {c8_option['also_needs'] or 'nothing'}."]
            kept8 = ws.apply_penetration(sid, conduit, plate)
            c8_clear = not [h for h in verify.check(scene, [conduit], clearance_m=0.0).hits
                            if h.other == plate and h.distance_m < -0.001]
            c8_ok = kept8["cut"] and kept8["fit"] == "fitted" and c8_clear and (model is None or c8_option is not None)
            c8_lines += [f"- Kept: a {kept8['width_m'] * 1000:.0f} mm {kept8['shape']} {kept8['fit']} hole, "
                         f"{'cut' if kept8['cut'] else 'not cut'}; the conduit "
                         f"{'clears' if c8_clear else 'still runs into'} the plate."]
            ok &= c8_ok

            # C3: the fence top rail 40 mm into post SE: trimmed back to the post's face (both bars are exact).
            rail, post_se = gid_of["fence/rail/S5-SE"], gid_of["fence/post/SE"]
            trim = edits.butt_trim(scene, rail, post_se)
            ws.apply_trim(sid, rail, trim.end, trim.by_m)
            c3_ok = abs(trim.by_m - 0.04) < 0.002
            ok &= c3_ok

            out = ws.export(sid, Path(tempfile.mkdtemp()))  # written to a temporary folder: the run keeps its README
            step_out = next(p for p in out if p.suffix == ".step")
            src = {p.name: p for p in step.parts(work / "PC-03-Palletising-Cell-RevA.step")[0]}
            new = {p.name: p for p in step.parts(step_out)[0]}
            moved = {n for n in src if abs(zmin(new[n]) - zmin(src[n])) > 1e-3}
            dz = sorted({round(zmin(new[n]) - zmin(src[n]), 1) for n in moved if n in names})
            air_before = sum(1 for n in src if src[n].group == "Compressed air")
            air_after = sum(1 for p in step.parts(step_out)[0] if p.group == "Compressed air")
            rail_name = scene.entity(rail).Name
            shorter = round(length(src[rail_name]) - length(new[rail_name]), 1)
            wall_name = scene.entity(wall).Name
            cut_cm3 = round(volume(src[wall_name]) - volume(new[wall_name]), 0)
            provision = [p for p in step.parts(step_out)[0] if p.name.startswith("Provision for void")]
            c7_step = cut_cm3 > 0 and len(provision) == 2 and all(p.alpha < 0.5 for p in provision)
            c7_lines += [f"- Exported STEP: `{wall_name}` {cut_cm3:.0f} cm³ smaller (the opening cut), "
                         f"{len(provision)} provision for void parts (C7 and C8)"
                         + (f" in {', '.join(sorted({p.group for p in provision}))} (alpha {provision[0].alpha:.2f})"
                            if provision else "") + "."]
            c7_ok &= c7_step
            ok &= c7_step
            c7_lines = [f"## C7 penetration: {'pass' if c7_ok else 'FAIL'}", "", *c7_lines, ""]
            plate_name = scene.entity(plate).Name
            gland_cm3 = round(volume(src[plate_name]) - volume(new[plate_name]), 2)
            c8_step = gland_cm3 > 0
            c8_lines += [f"- Exported STEP: `{plate_name}` {gland_cm3} cm³ smaller (the gland hole)."]
            c8_ok &= c8_step
            ok &= c8_step
            c8_lines = [f"## C8 gland hole: {'pass' if c8_ok else 'FAIL'}", "", *c8_lines, ""]
            fix_ok = set(names) <= moved and dz == [150.0] and not hits_post and shorter == 40.0 \
                and (air_after > air_before if kinds[:1] == ["offset"] or c6_kind == "route" else True)
            ok &= fix_ok
            lines += [f"## C2 fix and export: {'pass' if fix_ok else 'FAIL'}", "",
                      f"- The run that moves with `CT-301` h2 (same STEP group, touching): {len(names)} parts, "
                      f"{', '.join(names)}.",
                      f"- Check before: {_summary(before)}; after +150 mm: {_summary(after)}"
                      f"{'; still hits post W5' if hits_post else '; clear of post W5'}.",
                      f"- Exported {', '.join(p.name for p in out)}; re-read: the {len(names)} ladder parts {dz} mm "
                      f"higher; the compressed-air line {air_before} → {air_after} parts"
                      f"{' (the offset' + chr(39) + 's pieces)' if air_after > air_before else ''}; "
                      f"`{rail_name}` {shorter} mm shorter (C3 trim, at its {trim.end}).", "", *c1_lines, *c6_lines,
                      *c7_lines, *c8_lines]
    lines.insert(1, f"Result: {'pass' if ok else 'FAIL'}")
    (args.out / "README.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    shutil.rmtree(work, ignore_errors=True)
    sys.exit(0 if ok else 1)


def volume(part) -> float:
    """A part's volume in cm³ (the STEP is in millimetres)."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(part.shape, props)
    return props.Mass() / 1000


def length(part) -> float:
    """The longest side of a part's box, in the STEP's units."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.Add_s(part.shape, box)
    lo, hi = box.CornerMin(), box.CornerMax()
    return max(hi.X() - lo.X(), hi.Y() - lo.Y(), hi.Z() - lo.Z())


def _summary(v) -> str:
    """"clear", or what it hits: "2 collisions (Fence post W5 -120 mm), 1 too close"."""
    if v.passed:
        return "clear"
    hard = [h for h in v.hits if h.kind == "collision"]
    return f"{len(hard)} collisions, {len(v.hits) - len(hard)} too close"


if __name__ == "__main__":
    main()
