"""Coordination reports: a PDF (combined, per team or per model) and BCF issues, from a clash report and its session.

What goes in:
- the clash report and its bulk triage (verdicts, readings, responsible discipline);
- the session's evidence from the browser: fixes accepted or proposed per clash, with pictures of the clash as it was
  and with the fix (the browser renders them; the server has no GPU), and the reviews people recorded;
- which team owns each model, confirmed by the user (`guess_teams` pre-fills it from what each model contains: a file
  name is not reliable).

Who acts and who reviews (`teams_for`): every team with an element in the clash reviews. The team that acts is the one
whose element a fix changes; else the discipline triage named; else the coordination rule the agent follows (structure
stays, then architecture, then site; services move). Same discipline on both sides: that team.

Real clashes and clashes with a fix get a page each, with Muse Spark's explanation and review points (marked as
AI-drafted), the Navisworks view zoomed to where the pair meets, and the original next to the fix. Modelling errors
go in a table for the models' authors; noise (by design, not physical, touching) in a compact table. The report stays
DRAFT until every page has a review from each team involved.
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import io
import json
import threading
import uuid
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import domains, owner, triage as triage_mod
from .meta_client import ChatModel, model_label, triage_model_info
from .reports import Report, ReportClash

# Team names are the user's: each model's team is typed in the report dialog. ORCA only guesses one per model to start
# from: a building discipline from the model's content, else the model's own name.
STAYS_FIRST = ["Structure", "Architecture", "Site", "MEP"]  # who keeps their element when two disciplines meet

EXPLAIN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["explanation", "recommended_action", "review_points"],
    "properties": {
        "explanation": {"type": "string"},
        "recommended_action": {"type": "string"},
        "review_points": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["team", "point"],
            "properties": {"team": {"type": "string"}, "point": {"type": "string"}}}},
    },
}
SUMMARY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "team_actions"],
    "properties": {
        "summary": {"type": "string"},
        "team_actions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["team", "actions"],
            "properties": {"team": {"type": "string"}, "actions": {"type": "array", "items": {"type": "string"}}}}},
    },
}


# ------------------------------------------------------------------------------------------------- teams per model

def _class_team(cls: str) -> str | None:
    """The discipline an IFC class almost always belongs to; None for classes every discipline uses."""
    if cls.startswith(("IfcFlow", "IfcDistribution", "IfcEnergyConversion", "IfcDuct", "IfcPipe", "IfcCable",
                       "IfcAirTerminal", "IfcLightFixture", "IfcElectric", "IfcSanitary", "IfcFireSuppression",
                       "IfcAlarm", "IfcSensor", "IfcValve", "IfcDamper", "IfcFan", "IfcPump", "IfcTank", "IfcBoiler",
                       "IfcChiller", "IfcUnitaryEquipment", "IfcProtectiveDevice", "IfcSwitchingDevice", "IfcOutlet")):
        return "MEP"
    if cls in ("IfcBeam", "IfcColumn", "IfcFooting", "IfcPile", "IfcMechanicalFastener", "IfcReinforcingBar",
               "IfcReinforcingMesh", "IfcTendon", "IfcBearing"):
        return "Structure"
    if cls in ("IfcDoor", "IfcWindow", "IfcCurtainWall", "IfcCovering", "IfcRailing", "IfcStair", "IfcStairFlight",
               "IfcRamp", "IfcRampFlight", "IfcFurniture", "IfcFurnishingElement", "IfcSpace", "IfcWallStandardCase"):
        return "Architecture"
    if cls in ("IfcGeographicElement", "IfcCivilElement", "IfcCourse", "IfcPavement", "IfcKerb", "IfcEarthworksFill"):
        return "Site"
    return None


def guess_team(classes: Counter, file_name: str = "", domain: str = domains.CONSTRUCTION) -> str:
    """A first guess at the team a model belongs to (the user types the real one). A building's model: the discipline
    most of its elements typically belong to, the file name only breaking ties (names like "Model-02.ifc" say
    nothing). A machine cell's, or a model with nothing to go on: the model's own name."""
    own = Path(file_name).stem or "Model"
    if domain != domains.CONSTRUCTION:
        return own
    score = Counter()
    for cls, n in classes.items():
        team = _class_team(cls)
        if team:
            score[team] += n
    name = file_name.lower()
    for team, words in (("MEP", ("mep", "mech", "elec", "plumb", "hvac", "services")), ("Structure", ("struct",)),
                        ("Architecture", ("arch",)), ("Site", ("site", "civil", "landscape"))):
        if any(w in name for w in words):
            score[team] += 0.5
    return score.most_common(1)[0][0] if score else own


def model_files(report: Report, scene=None) -> list[str]:
    """Every model the report or the open scene names, by file name."""
    names = {e.file for c in report.clashes for e in (c.a, c.b) if e.file}
    if scene is not None:
        names |= {p.name for p in scene.paths}
    return sorted(names)


def guess_teams(report: Report, scene=None, domain: str = domains.CONSTRUCTION) -> list[dict]:
    """[{file, guess, elements}] for the report dialog: what each model contains suggests a team; the user types it."""
    out = []
    for name in model_files(report, scene):
        classes: Counter = Counter()
        if scene is not None and name in [p.name for p in scene.paths]:
            m = scene.models[[p.name for p in scene.paths].index(name)]
            classes.update(e.is_a() for e in m.by_type("IfcElement"))
        else:
            classes.update(e.ifc_class for c in report.clashes for e in (c.a, c.b) if e.file == name and e.ifc_class)
        out.append({"file": name, "guess": guess_team(classes, name, domain), "elements": sum(classes.values())})
    return out


# ------------------------------------------------------------------------------------------------- one clash

@dataclass
class Row:
    clash: ReportClash
    model_a: str
    model_b: str
    team_a: str
    team_b: str
    acting: str
    reviewers: list[str]
    verdict: str | None
    reading: dict
    section: str                  # "page" | "author" | "noise"
    evidence: dict | None = None  # the session's fix for this clash: accepted or proposed, with pictures
    reviews: list[dict] = field(default_factory=list)
    mark: str | None = None       # the session marked it "by_design" or "author"
    ai: dict | None = None        # Muse Spark's explanation for its page


def teams_for(team_a: str, team_b: str, moved_side: str | None, responsible: str | None,
              discipline: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """(acting team, teams that review). See the module docstring for the rule. `discipline`: a typed team name's
    guessed discipline (`guess_teams`), which `STAYS_FIRST` ranks; a name with none ranks with the movers."""
    reviewers = list(dict.fromkeys([team_a, team_b]))
    if moved_side in ("a", "b"):
        return (team_a if moved_side == "a" else team_b), reviewers
    if responsible and responsible in reviewers:
        return responsible, reviewers
    if team_a == team_b:
        return team_a, reviewers
    rank = {t: i for i, t in enumerate(STAYS_FIRST)}
    of = discipline or {}
    return max((team_a, team_b), key=lambda t: rank.get(of.get(t, t), len(STAYS_FIRST))), reviewers


def build_rows(report: Report, verdicts: dict[str, dict], model_teams: dict[str, str], matches: dict | None,
               scene, evidence: dict, reviews: dict, marks: dict, guesses: dict[str, str] | None = None) -> list[Row]:
    """`model_teams`: the team the user typed for each model file; `guesses`: ORCA's guess per file (`guess_teams`),
    the names triage's "responsible" uses, which are translated to the typed ones."""
    guesses = guesses or {}
    typed = {f: model_teams.get(f) or g for f, g in guesses.items()}
    discipline = {t: guesses[f] for f, t in typed.items()}
    as_typed = {}
    for f, g in guesses.items():
        as_typed.setdefault(g, typed[f])
    rows = []
    for c in report.clashes:
        m = (matches or {}).get(c.id, {})

        def model_of(side: str) -> str:
            gid = m.get(side)
            if scene is not None and gid:
                try:
                    return scene.element(gid).source
                except KeyError:
                    pass
            return (c.a if side == "a" else c.b).file or "unknown model"

        ma, mb = model_of("a"), model_of("b")
        ta = model_teams.get(ma) or typed.get(ma) or guess_team(Counter(), ma)
        tb = model_teams.get(mb) or typed.get(mb) or guess_team(Counter(), mb)
        ev = evidence.get(c.id)
        moved_side = None
        if ev and ev.get("moved"):
            moved = set(ev["moved"])
            show = m.get("show") or [None, None]
            moved_side = ("a" if {m.get("a"), show[0]} & moved else "b" if {m.get("b"), show[1]} & moved else None)
        reading = verdicts.get(c.id, {})
        responsible = reading.get("responsible")
        acting, reviewers = teams_for(ta, tb, moved_side, as_typed.get(responsible, responsible), discipline)
        mark = marks.get(c.id)
        verdict = reading.get("verdict")
        if ev:
            section = "page"
        elif mark == "by_design":
            section = "noise"
        elif mark == "author" or verdict == "modelling_error":
            section = "author"
        elif verdict == "real_clash":
            section = "page"
        else:
            section = "noise"
        rows.append(Row(c, ma, mb, ta, tb, acting, reviewers, verdict, reading, section, ev,
                        list(reviews.get(c.id, [])), mark))
    return rows


# ------------------------------------------------------------------------------------------------- Muse Spark

def _facts(r: Row) -> str:
    lines = [triage_mod.describe(r.clash),
             f"Element A is in model {r.model_a} ({r.team_a}); element B in {r.model_b} ({r.team_b}).",
             f"Acting team: {r.acting}. Teams that must review: {', '.join(r.reviewers)}."]
    if r.reading:
        lines.append(f"Triage: {r.reading.get('verdict')} ({r.reading.get('severity')}): {r.reading.get('understanding', '')}")
    ev = r.evidence
    if ev:
        state = "applied to the model and verified" if ev.get("status") == "accepted" else "proposed and verified, not applied yet"
        lines.append(f"Fix ({state}): {ev.get('title')}. Edit: {ev.get('edit')}. "
                     f"{'Nearest clearance ' + str(round(ev['clearance_m'] * 1000)) + ' mm. ' if ev.get('clearance_m') is not None else ''}"
                     f"Rationale: {ev.get('rationale') or '-'}. Also needs: {ev.get('also_needs') or '-'}.")
    elif r.reading.get("fix_hint"):
        lines.append(f"Triage's hint: {r.reading['fix_hint']}")
    return "\n".join(lines)


def explain(model: ChatModel, rows: list[Row], emit: Callable[[dict], None], workers: int = 6,
            domain: str = domains.CONSTRUCTION) -> None:
    """Muse Spark's explanation for every page, in parallel; a failure leaves that page with the triage reading. The
    prompt names the report's teams as the user typed them."""
    pages = [r for r in rows if r.section == "page"]
    teams = ", ".join(dict.fromkeys(t for r in rows for t in (r.team_a, r.team_b)))
    from . import requirements
    doc = requirements.current()
    clear = requirements.resolve(doc).fix_clearance_mm if doc is not None else requirements.DEFAULT_CLEARANCE_MM
    system = domains.prompt("report", domain, teams=teams, clearance=f"at least {clear:.0f} mm")
    done = [0]
    lock = threading.Lock()

    def one(r: Row):
        try:
            pics = [p for _, p in r.clash.images][:3]
            r.ai = model.complete_json(system, _facts(r), pics, schema=EXPLAIN_SCHEMA)  # type: ignore[call-arg]
        except Exception as e:  # keep going: the page falls back to triage's reading
            r.ai = {"error": f"{type(e).__name__}"}
        with lock:
            done[0] += 1
            emit({"type": "progress", "step": "explaining", "done": done[0], "total": len(pages)})

    if pages:
        with ThreadPoolExecutor(workers) as pool:
            [f.result() for f in [owner.submit(pool, one, r) for r in pages]]


def summarise(model: ChatModel, rows: list[Row], domain: str = domains.CONSTRUCTION) -> dict:
    counts = Counter(r.verdict or "not triaged" for r in rows)
    pages = [r for r in rows if r.section == "page"]
    text = json.dumps({
        "results": len(rows), "by_verdict": counts,
        "for_authors": sum(r.section == "author" for r in rows),
        "need_action": [{"clash": r.clash.label, "test": r.clash.test, "acting": r.acting, "reviewers": r.reviewers,
                         "fix": (r.evidence or {}).get("status", "none"),
                         "explanation": (r.ai or {}).get("explanation") or r.reading.get("understanding", "")}
                        for r in pages],
    }, default=str)
    try:
        return model.complete_json(domains.prompt("report_summary", domain), text, None, schema=SUMMARY_SCHEMA)  # type: ignore[call-arg]
    except Exception as e:
        return {"summary": "", "team_actions": [], "error": f"{type(e).__name__}"}


# ------------------------------------------------------------------------------------------------- pictures

def _zone_crop(path: Path, side_px: int = 560) -> str | None:
    """A Navisworks picture cropped to where the red and green elements meet (the same colour reading as the browser's
    clashImage.ts), as a JPEG data URL; the whole picture when no zone is found."""
    from PIL import Image
    try:
        img = Image.open(path).convert("RGB")
    except OSError:
        return None
    small = np.asarray(img.resize((256, 256), Image.NEAREST)).astype(int)
    r, g, b = small[..., 0], small[..., 1], small[..., 2]
    green = (g > r + 40) & (g > b + 40)
    reddish = (r > g + 20) & (r > b + 30)
    blend = reddish & (g > 0.25 * r) & (b < 0.6 * g + 12)
    red = reddish & ~blend & (r > g + 40)
    near = lambda m: np.pad(m, 3)[0:256, 0:256] | np.pad(m, 3)[6:262, 6:262] | np.pad(m, 3)[0:256, 6:262] | np.pad(m, 3)[6:262, 0:256]
    zone = blend | (red & near(green)) | (green & near(red))
    pick = zone if zone.any() else (red | green)
    if pick.any():
        ys, xs = np.nonzero(pick)
        cx, cy = (xs.min() + xs.max() + 1) / 2 / 256, (ys.min() + ys.max() + 1) / 2 / 256
        side = min(1.0, max(0.22, max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) / 256 * 2.6))
        x0 = min(max(cx - side / 2, 0), 1 - side)
        y0 = min(max(cy - side / 2, 0), 1 - side)
        w, h = img.size
        img = img.crop((int(x0 * w), int(y0 * h), int((x0 + side) * w), int((y0 + side) * h)))
    img = img.resize((side_px, side_px))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _data_url_ok(url: str | None) -> str | None:
    return url if isinstance(url, str) and url.startswith(("data:image/jpeg;base64,", "data:image/png;base64,")) else None


def _built_img(ev: dict) -> str | None:
    """A fix's built view (Show it built, docs/show-it-built.md): a checked picture the page names by its URL
    (`/api/built/<key>.jpg`), read from the cache as a data URL; None when there is none."""
    url = ev.get("built_img")
    if not isinstance(url, str) or not url.startswith("/api/built/"):
        return None
    from . import built
    path = built.path_of(url.rsplit("/", 1)[-1])
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode() if path else None


# ------------------------------------------------------------------------------------------------- HTML → PDF

def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _mm(m: float | None) -> str:
    return "—" if m is None else f"{m * 1000:+.0f} mm"


VERDICT_LABEL = {"real_clash": "Real problem", "by_design": "By design", "non_physical": "Not physical",
                 "modelling_error": "Model error", None: "Not triaged"}


def _review_table(r: Row) -> str:
    rows = []
    for team in r.reviewers:
        recorded = [v for v in r.reviews if v.get("team") == team]
        if recorded:
            for v in recorded:
                rows.append(f"<tr><td>{_e(team)}{' (acts)' if team == r.acting else ''}</td><td>{_e(v.get('name'))}</td>"
                            f"<td>{_e((v.get('at') or '')[:10])}</td><td class='dec {_e(v.get('decision'))}'>{_e(v.get('decision'))}</td>"
                            f"<td>{_e(v.get('note'))}</td></tr>")
        else:
            rows.append(f"<tr class='blank'><td>{_e(team)}{' (acts)' if team == r.acting else ''}</td><td></td><td></td>"
                        f"<td>Approve / Reject</td><td></td></tr>")
    return ("<table class='review'><thead><tr><th>Team</th><th>Name</th><th>Date</th><th>Decision</th><th>Comment</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def _page(r: Row, n: int) -> str:
    c, ev, ai = r.clash, r.evidence or {}, r.ai or {}
    # Coordinated captures colour edit groups, so their colours do not identify the report's A/B pair.
    label_a, label_b = ("A", "B") if ev.get("kind") == "context" else ("A (red)", "B (green)")
    crop = _zone_crop(c.images[0][1]) if c.images else None
    found_by = "ORCA" if c.source == "sightline" else "Navisworks"  # who detected it, and whose depth this is
    shown = [(u, cap) for u, cap in [
        (crop, f"{found_by} view, zoomed to where they meet (red A, green B)"),
        (_data_url_ok(ev.get("before_img")), "The model as it is"),
        (_data_url_ok(ev.get("after_img")), "With the fix" + (" (applied)" if ev.get("status") == "accepted" else " (proposed)")),
        (_built_img(ev), "As it could look built (illustration by Muse Image from ORCA's view; the model is the record)"),
    ] if u]
    pics = "".join(f"<figure><img src='{_e(u)}'/><figcaption>{_e(cap)}</figcaption></figure>" for u, cap in shown)
    if ev.get("built_note") and not _built_img(ev):   # Show it built tried, and no picture kept to the model
        pics += f"<p class='note'>No built view: {_e(ev['built_note'])}</p>"
    fix = ""
    if ev and ev.get("status") == "recommended" and ev.get("kind") == "penetration":  # asked for: the host's team cuts it
        fix = (f"<div class='fix'><h4>Opening requested: {_e(ev.get('title'))} <span class='tag'>provision for void only</span>"
               f"</h4><dl><dt>Opening</dt><dd>{_e(ev.get('edit'))}</dd>"
               f"<dt>Not cut</dt><dd>{_e(ev.get('blocked_by') or 'the host may not be edited')}</dd>"
               f"<dt>Also needs</dt><dd>{_e(ev.get('also_needs') or 'nothing noted')}</dd></dl></div>")
    elif ev and ev.get("status") == "recommended":  # the requirements allow no edit here: Muse's recommendation stands
        fix = (f"<div class='fix'><h4>Recommended for the designer: {_e(ev.get('title'))} <span class='tag'>not edited</span></h4><dl>"
               f"<dt>Why not edited</dt><dd>{_e(ev.get('blocked_by') or 'the coordination requirements allow no edit')}</dd>"
               f"<dt>Change</dt><dd>{_e(ev.get('edit'))}</dd>"
               f"<dt>Also needs</dt><dd>{_e(ev.get('also_needs') or 'nothing noted')}</dd></dl></div>")
    elif ev:
        status = "Applied to the model" if ev.get("status") == "accepted" else "Proposed, not applied"
        fix = (f"<div class='fix'><h4>Fix: {_e(ev.get('title'))} <span class='tag verified'>verified by geometry</span>"
               f" <span class='tag'>{status}</span></h4><dl>"
               f"<dt>Edit</dt><dd>{_e(ev.get('edit'))}</dd>"
               f"<dt>Clearance</dt><dd>{_e(ev.get('clearance'))}</dd>"
               + (f"<dt>Meets</dt><dd>{_e('; '.join(ev['meets']))}</dd>" if isinstance(ev.get("meets"), list) and ev["meets"] else "")
               + f"<dt>Also needs</dt><dd>{_e(ev.get('also_needs') or 'nothing noted')}</dd></dl></div>")
    explanation = ai.get("explanation") or r.reading.get("understanding") or "No explanation available."
    action = ai.get("recommended_action") or r.reading.get("fix_hint") or ev.get("advice") or ""
    points = "".join(f"<li><b>{_e(p.get('team'))}:</b> {_e(p.get('point'))}</li>" for p in ai.get("review_points", []))
    source = "Muse Spark" if ai.get("explanation") else "triage reading"
    return f"""
<section class='clash'>
  <h2><span class='num'>#{c.number}</span> {_e(c.title or c.name)} <span class='test'>{_e(c.test)}{' · Navisworks ' + _e(c.ref) if c.ref else ''}</span></h2>
  <table class='facts'>
    <tr><th>{label_a}</th><td>{_e(c.a.ifc_class)} · {_e(c.a.name)}</td><td>{_e(r.model_a)} · {_e(r.team_a)}</td></tr>
    <tr><th>{label_b}</th><td>{_e(c.b.ifc_class)} · {_e(c.b.name)}</td><td>{_e(r.model_b)} · {_e(r.team_b)}</td></tr>
    <tr><th>Distance</th><td>{found_by} {_mm(c.distance_m)}{' · tolerance ' + _mm(c.tolerance_m) if c.tolerance_m else ''}</td>
        <td>{_e(c.a.level or c.b.level or 'Level unknown')}{' · grid ' + _e(c.grid) if c.grid else ''}</td></tr>
    <tr><th>Triage</th><td>{_e(VERDICT_LABEL.get(r.verdict, r.verdict))}{' · ' + _e(r.reading.get('severity')) if r.reading.get('severity') not in (None, 'none') else ''}</td>
        <td><b>Acts:</b> {_e(r.acting)} · <b>Reviews:</b> {_e(', '.join(r.reviewers))}</td></tr>
  </table>
  <div class='pics{" four" if len(shown) > 3 else ""}'>{pics}</div>
  <div class='ai'><span class='ai-tag'>AI-drafted ({source}) · to be reviewed</span>
    <p>{_e(explanation)}</p>
    {f"<p><b>Recommended:</b> {_e(action)}</p>" if action else ""}
    {f"<ul>{points}</ul>" if points else ""}
  </div>
  {fix}
  <h4>Review</h4>
  {_review_table(r)}
</section>"""


# The ORCA wordmark (assets/brand/orca/svg/wordmarks), navy, with "by IssueLab": the cover's lockup.
LOCKUP = ("<svg class='lockup' xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1077 330' width='150' height='46' fill='#052640'"
          " role='img' aria-label='ORCA by IssueLab'>"
          + "".join(f"<path d='{d}'/>" for d in (
              "M 31.35038 211.9217 C -12.70846 161.18071 -10.02719 85.00785 37.49033 37.49033 C 85.00785 -10.02719 161.18071 -12.70846 211.9217 31.35038 L 172.14842 71.12366 C 143.48543 48.87496 102.74539 51.43123 77.08831 77.08831 C 51.43123 102.74539 48.87496 143.48543 71.12366 172.14842 Z",
              "M 224.64962 44.0783 C 268.70846 94.81929 266.02719 170.99215 218.50967 218.50967 C 170.99215 266.02719 94.81929 268.70846 44.0783 224.64962 L 83.85158 184.87634 C 112.51457 207.12504 153.25461 204.56877 178.91169 178.91169 C 204.56877 153.25461 207.12504 112.51457 184.87634 83.85158 Z",
              "M 292 0 L 441 0 C 499 0 530 30 530 80 C 530 126 504 154 455 162 L 543 256 L 466 256 L 347 143 L 320 115 L 435 115 C 460 115 473 102 473 82 C 473 63 458 54 435 54 L 292 54 Z",
              "M 292 121 L 351 180 L 351 256 L 292 256 Z",
              "M 791.05369 45.72319 C 756.46465 4.50157 699.78721 -10.6851 649.22142 7.71934 C 598.65563 26.12379 565 74.18901 565 128 C 565 181.81099 598.65563 229.87621 649.22142 248.28066 C 699.78721 266.6851 756.46465 251.49843 791.05369 210.27681 L 748.1552 174.28071 C 728.69887 197.46786 696.81781 206.01037 668.37455 195.65787 C 639.93129 185.30537 621 158.26868 621 128 C 621 97.73132 639.93129 70.69463 668.37455 60.34213 C 696.81781 49.98963 728.69887 58.53214 748.1552 81.71929 Z",
              "M 805 256 L 941 0 L 975 64 L 877 256 Z", "M 988 88 L 1077 256 L 1004 256 L 951 157 Z"))
          + "<text x='1077' y='326' text-anchor='end' font-family='Helvetica, Arial, sans-serif' font-size='58' letter-spacing='6'"
            " fill='#52636E'>BY ISSUELAB</text></svg>")

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; font-family: "DejaVu Sans", sans-serif;
  @top-left { content: string(doc-title); font-size: 8pt; color: #5d6a7a; }
  @top-right { content: string(draft); font-size: 8pt; color: #b8352a; font-weight: bold; }
  @bottom-left { content: "ORCA · AI-assisted design coordination report"; font-size: 8pt; color: #5d6a7a; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font-size: 8pt; color: #5d6a7a; } }
@page cover { @top-left { content: none; } @top-right { content: none; } }
body { font-family: "IBM Plex Sans", "DejaVu Sans", sans-serif; font-size: 9.5pt; color: #16202b; line-height: 1.45; }
h1 { font-size: 24pt; margin: 0 0 6pt; string-set: doc-title content(); }
.draft-mark { string-set: draft content(); color: transparent; font-size: 1pt; }
h2 { font-size: 13pt; margin: 0 0 8pt; color: #16202b; }
h3 { font-size: 11pt; margin: 14pt 0 6pt; color: #2f5d8a; }
h4 { font-size: 10pt; margin: 10pt 0 4pt; }
.cover { page: cover; padding-top: 40mm; }
.cover .lockup { display: block; margin-bottom: 18pt; }
.cover .eyebrow { font-family: monospace; letter-spacing: .08em; color: #2f5d8a; font-size: 9pt; text-transform: uppercase; }
.stamp { display: inline-block; border: 2pt solid #b8352a; color: #b8352a; padding: 4pt 10pt; font-weight: bold;
  font-size: 12pt; margin: 14pt 0; transform: rotate(-2deg); }
.stamp.ok { border-color: #1d7f47; color: #1d7f47; }
.meta { margin-top: 18pt; border-collapse: collapse; } .meta th { text-align: left; color: #5d6a7a; font-weight: normal; padding: 2pt 14pt 2pt 0; vertical-align: top; }
.counts { display: flex; gap: 8pt; margin: 10pt 0; } .count { border: 1pt solid #d7dde5; border-radius: 4pt; padding: 6pt 10pt; }
.count b { display: block; font-size: 16pt; color: #2f5d8a; }
.ai { border-left: 3pt solid #7a6bd1; background: #f6f4fd; padding: 6pt 10pt; margin: 8pt 0; }
.ai-tag { font-size: 7.5pt; font-weight: bold; color: #5a4bb4; text-transform: uppercase; letter-spacing: .04em; }
.ai p { margin: 4pt 0; } .ai ul { margin: 4pt 0 0 14pt; padding: 0; }
.clash { page-break-before: always; } .clash h2 .num { color: #2f5d8a; font-family: monospace; }
.clash h2 .test { display: block; font-size: 8.5pt; font-weight: normal; color: #5d6a7a; margin-top: 2pt; }
table { border-collapse: collapse; width: 100%; } .facts th { text-align: left; width: 18%; color: #5d6a7a; font-weight: normal; }
.facts td, .facts th { padding: 3pt 6pt 3pt 0; border-bottom: .5pt solid #e9edf2; vertical-align: top; }
.pics { margin: 8pt 0; } .pics figure { margin: 0 1.5% 0 0; width: 31.5%; display: inline-block; vertical-align: top; }
.pics.four figure { width: 23.5%; } .pics .note { font-size: 8pt; color: #5d6a7a; margin: 2pt 0 0; }
.pics img { width: 100%; max-height: 54mm; object-fit: cover; border-radius: 3pt; border: .5pt solid #d7dde5; } .pics figcaption { font-size: 7.5pt; color: #5d6a7a; }
.fix { border: 1pt solid #b9e2c8; background: #f1faf4; padding: 6pt 10pt; border-radius: 3pt; }
.fix h4 { margin: 0 0 4pt; } .fix dl { margin: 0; display: grid; grid-template-columns: 22% 78%; }
.fix dt { color: #5d6a7a; } .fix dd { margin: 0 0 2pt; }
.tag { font-size: 7pt; border: .5pt solid #8aa0b8; border-radius: 6pt; padding: 0 5pt; font-weight: normal; color: #2f5d8a; }
.tag.verified { border-color: #1d7f47; color: #1d7f47; }
.review { page-break-inside: avoid; }
.review th, .review td { border: .5pt solid #c9d2dc; padding: 5pt; text-align: left; vertical-align: top; }
.review th { background: #f2f4f7; font-size: 8pt; } .review tr.blank td { height: 16pt; color: #9aa7b4; }
.dec.approve { color: #1d7f47; font-weight: bold; } .dec.reject { color: #b8352a; font-weight: bold; }
.list th, .list td { border-bottom: .5pt solid #e9edf2; padding: 3pt 4pt; text-align: left; font-size: 8pt; vertical-align: top; }
.list th { color: #5d6a7a; font-weight: normal; }
.section-break { page-break-before: always; }
"""


def requirements_html(doc) -> str:
    """The coordination requirements a report was checked against: level, strictness, the numbers they set, the
    checks, who moves, the by-design rules and the guidance Muse Spark was given."""
    from . import requirements
    p = requirements.resolve(doc)
    names = {g.id: g.name for g in doc.groups}
    groups = "".join(f"<tr><td>{_e(g.name)}</td><td>{_e(g.role)}</td><td>{_e(', '.join(g.teams + [c.removeprefix('Ifc') for c in g.classes]) or '—')}</td></tr>"
                     for g in doc.groups)
    checks = "".join(f"<tr><td>{_e(names.get(c.a, c.a))}</td><td>{_e(names.get(c.b, c.b) if c.b else '(within)')}</td>"
                     f"<td>{_e(c.check + (f' {c.clearance_mm:.0f} mm' if c.check == 'clearance' and c.clearance_mm else ''))}</td>"
                     f"<td>{_e(c.reason)}</td></tr>" for c in doc.checks)
    movers = "".join(f"<tr><td>{i + 1}</td><td>{_e(names.get(m.group, m.group))}</td><td>{_e(m.edits)}</td>"
                     f"<td>{_e(f'{m.max_move_mm:.0f} mm' if m.max_move_mm else '—')}</td><td>{'yes' if m.trims else 'no'}</td></tr>"
                     for i, m in enumerate(doc.who_moves))
    rules = "".join(f"<li>{_e(requirements._pair_text(r))}{' (' + _e(r.reason) + ')' if r.reason else ''}</li>" for r in doc.by_design)
    guidance = "".join(f"<p><b>{k.title()}:</b> {_e(v)}</p>" for k, v in doc.guidance.items() if v)
    return f"""
<section class='section-break'>
  <h2>Coordination requirements</h2>
  <p><b>{_e(doc.name)}</b> · version {doc.version} · {_e(requirements.label(doc))} · id <code>{requirements.doc_id(doc)}</code></p>
  <p>{_e(requirements.LEVELS[doc.level]['meaning'])} {_e(requirements.STRICTNESS[doc.strictness]['meaning'])}
  Hard clashes count from {p.tolerance_mm:g} mm{f'; elements under {p.min_size_mm:.0f} mm are not checked' if p.min_size_mm else ''}.
  Fixes clear by at least {p.fix_clearance_mm:.0f} mm{f' and move at most {p.max_move_mm:.0f} mm' if p.max_move_mm else ''};
  {_e(requirements.TRIM_TEXT[p.trims])}.</p>
  <h3>Groups</h3><table class='list'><thead><tr><th>Group</th><th>Role</th><th>Selects</th></tr></thead><tbody>{groups}</tbody></table>
  <h3>Checks</h3><table class='list'><thead><tr><th>Group</th><th>With</th><th>Check</th><th>Why</th></tr></thead><tbody>{checks}</tbody></table>
  <h3>Who moves</h3><table class='list'><thead><tr><th>Order</th><th>Group</th><th>Edits</th><th>Largest move</th><th>Trims</th></tr></thead><tbody>{movers}</tbody></table>
  <h3>Declared by design</h3>{f'<ul>{rules}</ul>' if rules else '<p>None.</p>'}
  {f'<h3>Guidance for Muse Spark</h3>{guidance}' if guidance else ''}
</section>"""


def triage_by(info: dict | None) -> str:
    """The triage model as the report names it: "an open-weights model (Muse Spark Open)" or "Muse Spark (Meta)"."""
    info = info or triage_model_info()
    name = model_label(str(info.get("model") or ""))
    return f"an open-weights model ({name})" if info.get("open_weights") else f"{name} (Meta)"


def render_html(title: str, subtitle: str, rows: list[Row], summary: dict, context: dict, requirements_doc=None,
                triage_info: dict | None = None) -> str:
    """`triage_info`: the model the triage ran on (`meta_client.triage_model_info`'s shape), named in "How this report
    was made"; by default the one triage would run on now."""
    pages = [r for r in rows if r.section == "page"]
    author = [r for r in rows if r.section == "author"]
    noise = [r for r in rows if r.section == "noise"]
    reviewed = sum(1 for r in pages if all(any(v.get("team") == t for v in r.reviews) for t in r.reviewers))
    final = bool(pages) and reviewed == len(pages)
    counts = Counter(VERDICT_LABEL.get(r.verdict, r.verdict) for r in rows)
    teams = sorted({t for r in pages for t in r.reviewers})
    actions = {a.get("team"): a.get("actions", []) for a in summary.get("team_actions", [])}
    action_html = ""
    for team in teams:
        mine = [r for r in pages if team in r.reviewers]
        lines = "".join(
            f"<tr><td>#{r.clash.number}</td><td>{_e(r.clash.title or r.clash.name)}<br><span style='color:#5d6a7a'>{_e(r.clash.test)}</span></td>"
            f"<td>{'Acts' if r.acting == team else 'Reviews'}</td>"
            f"<td>{_e({'accepted': 'Fix applied', 'proposed': 'Fix proposed'}.get((r.evidence or {}).get('status'), 'No fix yet'))}</td>"
            f"<td>{'Reviewed' if any(v.get('team') == team for v in r.reviews) else 'Waiting'}</td></tr>"
            for i, r in ((pages.index(r) + 1, r) for r in mine))
        todo = "".join(f"<li>{_e(a)}</li>" for a in actions.get(team, []))
        action_html += (f"<h3>{_e(team)}</h3>" + (f"<div class='ai'><span class='ai-tag'>AI-drafted · to be reviewed</span>"
                        f"<ul>{todo}</ul></div>" if todo else "") +
                        "<table class='list'><thead><tr><th>#</th><th>Clash</th><th>Role</th><th>Fix</th><th>Review</th>"
                        f"</tr></thead><tbody>{lines}</tbody></table>")

    def table(items: list[Row], note: str) -> str:
        body = "".join(
            f"<tr><td>{_e(r.clash.label)}</td><td>{_e(r.clash.test)}</td><td>{_e(r.clash.a.name)} / {_e(r.clash.b.name)}</td>"
            f"<td>{_mm(r.clash.distance_m)}</td><td>{_e(VERDICT_LABEL.get(r.verdict, r.verdict))}"
            f"{' · marked ' + _e(r.mark.replace('_', ' ')) if r.mark else ''}</td>"
            f"<td>{_e((r.reading.get('understanding') or '')[:180])}</td></tr>" for r in items)
        return (f"<p>{note}</p><table class='list'><thead><tr><th>Clash</th><th>Test</th><th>Elements</th><th>Distance</th>"
                f"<th>Reading</th><th>Why</th></tr></thead><tbody>{body}</tbody></table>")

    def grouped(items: list[Row], note: str) -> str:
        tests: dict[str, list[Row]] = {}
        for r in items:
            tests.setdefault(r.clash.test, []).append(r)
        body = ""
        for test, rs in sorted(tests.items(), key=lambda kv: -len(kv[1])):
            readings = Counter(("marked " + r.mark.replace("_", " ")) if r.mark else VERDICT_LABEL.get(r.verdict, r.verdict) for r in rs)
            ds = [r.clash.distance_m for r in rs if r.clash.distance_m is not None]
            span = f"{_mm(min(ds))} to {_mm(max(ds))}" if ds else "—"
            why = next((r.reading.get("understanding") for r in rs if r.reading.get("understanding")), "")
            body += (f"<tr><td>{_e(test)}</td><td>{len(rs)}</td><td>{_e(', '.join(f'{k} {v}' for k, v in readings.most_common()))}</td>"
                     f"<td>{span}</td><td>{_e(why[:160])}</td></tr>")
        return (f"<p>{note}</p><table class='list'><thead><tr><th>Test</th><th>Results</th><th>Reading</th><th>Distance</th>"
                f"<th>Typical reason</th></tr></thead><tbody>{body}</tbody></table>")

    meta = "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in context.items())
    from . import requirements
    clear_mm = f"{requirements.resolve(requirements_doc).fix_clearance_mm:.0f}" if requirements_doc is not None else f"{requirements.DEFAULT_CLEARANCE_MM}"
    stamp = (f"<div class='stamp ok'>REVIEWED · {reviewed} of {len(pages)}</div>" if final else
             f"<div class='stamp'>DRAFT · AI-assisted · {reviewed} of {len(pages)} reviewed</div>")
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>{_e(title)}</title><style>{CSS}</style></head><body>
<section class='cover'>
  {LOCKUP}
  <div class='eyebrow'>ORCA · design coordination</div>
  <h1>{_e(title)}</h1>
  <div style='font-size:12pt;color:#5d6a7a'>{_e(subtitle)}</div>
  <span class='draft-mark'>{'' if final else 'DRAFT · requires review'}</span>
  {stamp}
  <table class='meta'>{meta}</table>
  <div class='counts'>
    <div class='count'><b>{len(rows)}</b>results</div>
    <div class='count'><b>{len(pages)}</b>need action</div>
    <div class='count'><b>{len(author)}</b>for the models' authors</div>
    <div class='count'><b>{len(noise)}</b>noise</div>
  </div>
  <p style='color:#5d6a7a;font-size:8.5pt'>Text marked AI-drafted was written by Muse Spark (Meta) from the clash data,
  the clash pictures and ORCA's geometry checks, and must be reviewed by the teams named before anyone acts on it.
  Fixes marked verified were checked against the whole federated model: the clash is gone, at least {clear_mm} mm clear, and
  nothing new is hit. They are not structural, cost or site approvals.</p>
</section>
<section class='section-break'>
  <h2>Summary</h2>
  <div class='ai'><span class='ai-tag'>AI-drafted (Muse Spark) · to be reviewed</span>
    <p>{_e(summary.get('summary') or 'Summary not available.')}</p></div>
  <p>By reading: {_e(', '.join(f'{k} {v}' for k, v in counts.most_common()))}.</p>
  <h2>Actions by team</h2>
  {action_html or '<p>Nothing needs action.</p>'}
</section>
{''.join(_page(r, i + 1) for i, r in enumerate(pages))}
<section class='section-break'>
  <h2>For the models' authors</h2>
  {table(author, 'Modelling errors: duplicated or misplaced elements. Not coordination clashes; the model author cleans them up.') if author else '<p>None.</p>'}
  <h2 style='margin-top:14pt'>Noise</h2>
  {grouped(noise, 'By design, not physical, or only touching, grouped by clash test. No action; most can be hidden with a clash rule.') if noise else '<p>None.</p>'}
  <h2 style='margin-top:14pt'>How this report was made</h2>
  <p>Verdicts come from ORCA's triage: sure cases by rule (spaces, ports and openings are not physical; results
  within 1 mm only touch), the rest by {_e(triage_by(triage_info))}. Fixes come from ORCA's agent: Muse
  Spark proposes edits to real IFC elements and a geometry engine (IfcOpenShell) checks each against the whole model.
  Who acts: the team whose element a fix changes, else the discipline triage named, else the coordination rule
  (structure stays, then architecture, then site; services move). Every team with an element in a clash reviews it.</p>
</section>
{requirements_html(requirements_doc) if requirements_doc is not None else ''}
</body></html>"""


def to_pdf(html_text: str) -> bytes:
    import weasyprint
    return weasyprint.HTML(string=html_text).write_pdf()


# ------------------------------------------------------------------------------------------------- BCF 2.1

def _bcf_camera(scene, gids: list[str], point: list[float] | None):
    """A camera looking at where the pair meets, from above and to one side (IFC axes, metres)."""
    target, size = None, 3.0
    if scene is not None:
        boxes = [scene.bounds()[g] for g in gids if g and g in scene.bounds()]
        if len(boxes) == 2:
            lo = np.maximum(boxes[0][0], boxes[1][0])
            hi = np.minimum(boxes[0][1], boxes[1][1])
            target = (np.minimum(lo, hi) + np.maximum(lo, hi)) / 2
            size = max(float(np.linalg.norm(np.abs(hi - lo))), 1.0)
    if target is None and point and all(v is not None for v in point):
        target = np.asarray(point, float)
    if target is None:
        return None
    direction = np.array([-1.0, 1.0, -0.8])
    direction /= np.linalg.norm(direction)
    eye = target - direction * (size * 2.5 + 3)
    up = np.cross(np.cross(direction, [0, 0, 1]), direction)
    return eye, direction, up / np.linalg.norm(up)


def _xyz(tag: str, v) -> str:
    return f"<{tag}><X>{v[0]:.4f}</X><Y>{v[1]:.4f}</Y><Z>{v[2]:.4f}</Z></{tag}>"


def bcf_zip(rows: list[Row], matches: dict | None, scene, author: str = "ORCA", checked_against: str = "") -> bytes:
    """BCF 2.1: one topic per clash that needs action, assigned to its acting team, with the AI explanation and the
    recorded reviews as comments, the pair selected and coloured in a viewpoint, and a snapshot."""
    from PIL import Image
    buf = io.BytesIO()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bcf.version", '<?xml version="1.0" encoding="UTF-8"?>\n<Version VersionId="2.1" '
                   'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><DetailedVersion>2.1</DetailedVersion></Version>')
        for r in (x for x in rows if x.section == "page"):
            topic, view = str(uuid.uuid4()), str(uuid.uuid4())
            m = (matches or {}).get(r.clash.id, {})
            ga, gb = m.get("a") or r.clash.a.global_id, m.get("b") or r.clash.b.global_id
            ai = r.ai or {}
            desc = " ".join(filter(None, [ai.get("explanation") or r.reading.get("understanding"),
                                          ai.get("recommended_action"),
                                          f"Fix: {r.evidence.get('title')} ({r.evidence.get('status')}, verified by geometry)." if r.evidence else ""]))
            comments = [(author + " (AI-drafted, to be reviewed)", desc)]
            if checked_against:
                comments.append((author, f"Checked against coordination requirements {checked_against}."))
            comments += [(f"{v.get('name')} ({v.get('team')})", f"{v.get('decision')}: {v.get('note') or ''}".strip(": "))
                         for v in r.reviews]
            priority = {"high": "Critical", "medium": "Major", "low": "Minor"}.get(r.reading.get("severity"), "Normal")
            markup = ['<?xml version="1.0" encoding="UTF-8"?>\n<Markup xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
                      f'<Topic Guid="{topic}" TopicType="Clash" TopicStatus="Open">',
                      f"<Title>{_e(r.clash.label)}</Title>",
                      f"<Priority>{priority}</Priority>",
                      f"<Labels>{_e(r.acting)}</Labels>" + "".join(f"<Labels>{_e(t)}</Labels>" for t in r.reviewers if t != r.acting),
                      f"<CreationDate>{now}</CreationDate><CreationAuthor>{_e(author)}</CreationAuthor>",
                      f"<AssignedTo>{_e(r.acting)}</AssignedTo>",
                      f"<Description>{_e(desc)}</Description></Topic>"]
            for who, text in comments:
                markup.append(f'<Comment Guid="{uuid.uuid4()}"><Date>{now}</Date><Author>{_e(who)}</Author>'
                              f'<Comment>{_e(text)}</Comment><Viewpoint Guid="{view}"/></Comment>')
            snap = _data_url_ok((r.evidence or {}).get("after_img")) or (
                _zone_crop(r.clash.images[0][1]) if r.clash.images else None)
            # Name the snapshot only when there is one: a detected clash with no captured view has none.
            markup.append(f'<Viewpoints Guid="{view}"><Viewpoint>viewpoint.bcfv</Viewpoint>'
                          + ("<Snapshot>snapshot.png</Snapshot>" if snap else "") + "</Viewpoints></Markup>")
            z.writestr(f"{topic}/markup.bcf", "".join(markup))
            comps = "".join(f'<Component IfcGuid="{g}"/>' for g in (ga, gb) if g)
            colours = "".join(f'<Color Color="{c}"><Component IfcGuid="{g}"/></Color>'
                              for c, g in (("FFD0342C", ga), ("FF1F9D3A", gb)) if g)
            cam = _bcf_camera(scene, list(m.get("show") or [ga, gb]), r.clash.point)
            camera = (f"<PerspectiveCamera>{_xyz('CameraViewPoint', cam[0])}{_xyz('CameraDirection', cam[1])}"
                      f"{_xyz('CameraUpVector', cam[2])}<FieldOfView>60</FieldOfView></PerspectiveCamera>") if cam else ""
            z.writestr(f"{topic}/viewpoint.bcfv",
                       f'<?xml version="1.0" encoding="UTF-8"?>\n<VisualizationInfo Guid="{view}" '
                       'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Components>'
                       f"<Selection>{comps}</Selection><Visibility DefaultVisibility=\"true\"/>"
                       f"<Coloring>{colours}</Coloring></Components>{camera}</VisualizationInfo>")
            if snap:
                png = io.BytesIO()
                Image.open(io.BytesIO(base64.b64decode(snap.split(",", 1)[1]))).convert("RGB").save(png, "PNG")
                z.writestr(f"{topic}/snapshot.png", png.getvalue())
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------- the whole job

def generate(report: Report, verdicts: dict[str, dict], model: ChatModel, *, scope: str, model_teams: dict[str, str],
             matches: dict | None, scene, evidence: dict, reviews: dict, marks: dict, include_bcf: bool,
             emit: Callable[[dict], None] = lambda e: None, triage_info: dict | None = None,
             domain: str = domains.CONSTRUCTION) -> tuple[bytes, str, str]:
    """Build the report(s). Returns (bytes, file name, media type): one PDF for a combined report without BCF, else a zip
    of the PDFs (one per team or per model) and the BCF. `triage_info`: the model the verdicts came from (a triage
    run's `info`), else the one triage would run on now. `domain`: the scene's (`domains.of`), whose voice the
    explanations and the summary take."""
    triage_info = triage_info or triage_model_info()
    guesses = {g["file"]: g["guess"] for g in guess_teams(report, scene, domain)}
    rows = build_rows(report, verdicts, model_teams, matches, scene, evidence, reviews, marks, guesses)
    emit({"type": "progress", "step": "explaining", "done": 0, "total": sum(r.section == "page" for r in rows)})
    explain(model, rows, emit, domain=domain)
    emit({"type": "progress", "step": "summarising"})
    summary = summarise(model, rows, domain)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    models = sorted({r.model_a for r in rows} | {r.model_b for r in rows})
    base_ctx = {"Clashes from": "ORCA's check of the models" if report.origin == "sightline" else f"Navisworks report {report.title}", "Models": ", ".join(f"{m} ({model_teams.get(m, '?')})" for m in models),
                "Generated": stamp, "Scope": {"combined": "All clashes", "team": "Per team", "model": "Per model"}[scope]}
    from . import requirements
    req_doc = requirements.current()
    checked = (f"{req_doc.name} v{req_doc.version}, {requirements.label(req_doc)} ({requirements.doc_id(req_doc)})"
               if req_doc is not None else "")
    if checked:
        base_ctx["Requirements"] = checked

    if scope == "team":
        groups = {t: [r for r in rows if t in r.reviewers] for t in sorted({t for r in rows for t in r.reviewers})}
        label = "Team"
    elif scope == "model":
        groups = {m: [r for r in rows if m in (r.model_a, r.model_b)] for m in models}
        label = "Model"
    else:
        groups = {"": rows}
        label = ""
    emit({"type": "progress", "step": "rendering", "done": 0, "total": len(groups)})
    files: list[tuple[str, bytes]] = []
    for i, (key, items) in enumerate(groups.items()):
        title = "Design coordination report" + (f": {key}" if key else "")
        sub = f"{report.title} · {len(items)} results" + (f" involving {label.lower()} {key}" if key else "")
        html_text = render_html(title, sub, items, summary, {**base_ctx, **({label: key} if key else {})}, req_doc,
                                triage_info)
        files.append((f"orca-report{('-' + _slug(key)) if key else ''}.pdf", to_pdf(html_text)))
        emit({"type": "progress", "step": "rendering", "done": i + 1, "total": len(groups)})
    if include_bcf:
        emit({"type": "progress", "step": "bcf"})
        files.append(("orca-issues.bcfzip", bcf_zip(rows, matches, scene, checked_against=checked)))
    if len(files) == 1:
        return files[0][1], files[0][0], "application/pdf"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            z.writestr(name, data)
    return out.getvalue(), "orca-report.zip", "application/zip"


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in s).strip("-").lower() or "part"
