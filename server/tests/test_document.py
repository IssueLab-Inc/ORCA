import base64
import io
import json
import zipfile
from collections import Counter

from PIL import Image

from sightline import document, triage
from tests.test_triage import _report


class Writer:
    """A report model: explains every page and drafts a summary."""

    def __init__(self):
        self.asked = []

    def complete_json(self, system, text, images=None, schema=None):
        self.asked.append(schema)
        if schema == document.SUMMARY_SCHEMA:
            return {"summary": "Three real clashes.", "team_actions": [{"team": "MEP", "actions": ["Raise the duct."]}]}
        return {"explanation": "The duct runs through the beam.", "recommended_action": "Raise the duct 400 mm.",
                "review_points": [{"team": "Structure", "point": "Confirm the web opening."}]}


def _jpeg() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 60)).save(buf, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def test_team_guess_comes_from_content_not_the_name():
    assert document.guess_team(Counter({"IfcDuctSegment": 40, "IfcBeam": 2}), "Model-02.ifc") == "MEP"
    assert document.guess_team(Counter({"IfcBeam": 30, "IfcColumn": 10, "IfcDuctSegment": 3}), "Level2.ifc") == "Structure"
    assert document.guess_team(Counter({"IfcSlab": 5}), "Northbank-Architecture.ifc") == "Architecture"


def test_who_acts_and_who_reviews():
    assert document.teams_for("Structure", "MEP", None, None) == ("MEP", ["Structure", "MEP"])
    assert document.teams_for("Structure", "MEP", "a", None) == ("Structure", ["Structure", "MEP"])  # the fix moved A
    assert document.teams_for("Structure", "Architecture", None, "Structure") == ("Structure", ["Structure", "Architecture"])
    assert document.teams_for("MEP", "MEP", None, "Structure") == ("MEP", ["MEP"])  # triage named a team not involved


def test_pdfs_per_team_and_bcf(tmp_path):
    report = _report(tmp_path)
    verdicts = triage.triage_report(report, _AllReal(), lambda e: None, workers=1, images=False)
    first = report.clashes[0]
    evidence = {first.id: {"status": "accepted", "title": "Raise the duct", "edit": "+400 mm", "clearance": "50 mm",
                           "clearance_m": 0.05, "before_img": _jpeg(), "after_img": _jpeg()}}
    reviews = {first.id: [{"team": "MEP", "name": "A. Engineer", "decision": "approve", "note": "ok", "at": "2026-10-27"}]}
    model, events = Writer(), []
    data, name, media = document.generate(
        report, verdicts, model, scope="team", model_teams={}, matches=None, scene=None, evidence=evidence,
        reviews=reviews, marks={}, include_bcf=True, emit=events.append)
    assert media == "application/zip" and name.endswith(".zip")
    z = zipfile.ZipFile(io.BytesIO(data))
    pdfs = [n for n in z.namelist() if n.endswith(".pdf")]
    assert pdfs and all(z.read(n).startswith(b"%PDF") for n in pdfs)
    bcf = zipfile.ZipFile(io.BytesIO(z.read("sightline-issues.bcfzip")))
    topics = [n for n in bcf.namelist() if n.endswith("markup.bcf")]
    pages = sum(1 for c in report.clashes if verdicts[c.id]["verdict"] == "real_clash" or c.id == first.id)
    assert len(topics) == pages and "bcf.version" in bcf.namelist()
    assert any("A. Engineer" in bcf.read(t).decode() for t in topics)
    assert any(e.get("step") == "explaining" for e in events) and document.SUMMARY_SCHEMA in model.asked


def test_combined_without_bcf_is_one_pdf_and_stays_draft(tmp_path):
    report = _report(tmp_path)
    verdicts = {c.id: {"verdict": "real_clash", "severity": "high", "responsible": "MEP"} for c in report.clashes}
    rows = document.build_rows(report, verdicts, {}, None, None, {}, {}, {})
    html_text = document.render_html("t", "s", rows, {"summary": "x"}, {})
    assert "DRAFT" in html_text
    data, name, media = document.generate(report, verdicts, Writer(), scope="combined", model_teams={}, matches=None,
                                          scene=None, evidence={}, reviews={}, marks={}, include_bcf=False)
    assert media == "application/pdf" and data.startswith(b"%PDF")


class _AllReal:
    def complete_json(self, system, text, images=None, schema=None):
        return {"understanding": "Clash.", "verdict": "real_clash", "severity": "high", "responsible": "MEP",
                "action": "move_B", "fix_hint": "Move it.", "confidence": 0.9}
