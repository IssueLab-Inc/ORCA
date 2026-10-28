"""Clash titles (titles.py): numbers across the report, plain names at once, Muse titles in batches."""
import json
import re

from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import detect, titles
from sightline.fixtures import build_detection_fixtures
from sightline.service import Workspace


class Titler:
    """Stands in for the triage model: titles every number it is sent, and records the batches."""

    def __init__(self, skip=()):
        self.batches, self.skip = [], set(skip)

    def complete_json(self, system, text, images=None, schema=None):
        numbers = [int(n) for n in re.findall(r"^#(\d+):", text, re.M)]
        self.batches.append(numbers)
        assert "IfcPipeSegment" in system or "title" in system.lower()
        return {"titles": [{"number": n, "title": f"Title for {n}."} for n in numbers if n not in self.skip]}


def _workspace(tmp_path):
    paths = build_detection_fixtures(tmp_path / "models")
    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    ws = Workspace(samples=tmp_path)
    sid = ws.open([p.name for p in paths])
    return ws, sid, ws.detect(sid)["report"]["id"]


def test_titles_land_in_batches_and_stay_on_the_clash(tmp_path):
    ws, sid, rid = _workspace(tmp_path)
    report = ws.report(rid)
    model, events = Titler(skip={2}), []
    done = titles.title_report(report, model, events.append, batch=2, workers=1)
    n = len(report.clashes)
    assert [len(b) for b in model.batches] == [2] * (n // 2) + [1] * (n % 2)
    assert sorted(sum(model.batches, [])) == sorted(c.number for c in report.clashes)
    assert all(e["type"] == "titles" for e in events)
    by_number = {c.number: c for c in report.clashes}
    assert by_number[1].title == "Title for 1" and by_number[1].label == "#1 Title for 1"   # tidied: no full stop
    assert by_number[2].title is None and by_number[2].label == f"#2 {by_number[2].name}"  # left out: plain name
    assert len(done) == len(report.clashes) - 1
    # Running again asks only for what is missing.
    again = Titler()
    titles.title_report(report, again, batch=40, workers=1)
    assert again.batches == [[2]]


def test_facts_say_what_meets_what_and_how_deep(tmp_path):
    ws, sid, rid = _workspace(tmp_path)
    c = next(c for c in ws.report(rid).clashes if c.test == "MEP vs Structure")
    line = titles.facts(c)
    assert line.startswith(f"#{c.number}: A IfcDuctSegment 'Duct D1'") and "overlap 350 mm" in line and "MEP vs Structure" in line


def test_a_clash_is_found_by_its_number(tmp_path):
    ws, sid, rid = _workspace(tmp_path)
    report = ws.report(rid)
    c = report.clashes[0]
    assert report.clash(f"#{c.number}") is c and report.clash(str(c.number)) is c and report.clash(c.id) is c


def test_titles_survive_detect_again(tmp_path):
    ws, sid, rid = _workspace(tmp_path)
    titles.title_report(ws.report(rid), Titler(), workers=1)
    again = ws.detect(sid)["report"]
    assert all(c["title"] == f"Title for {c['number']}" for c in again["clashes"])


def test_titles_api_streams_and_is_shared(tmp_path, monkeypatch):
    ws, sid, rid = _workspace(tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    monkeypatch.setattr(app_module, "triage_model", lambda: (Titler(), {"model": "scripted", "open_weights": True}))
    monkeypatch.setattr(app_module, "_title_jobs", {})
    c = TestClient(app_module.app)
    events = [json.loads(x) for x in c.post(f"/api/reports/{rid}/titles/stream").text.splitlines()]
    assert events[0]["type"] == "start" and events[-1]["type"] == "done"
    got = c.get(f"/api/reports/{rid}/titles").json()
    assert got["running"] is False and len(got["titles"]) == len(ws.report(rid).clashes)
    assert all(x["title"] for x in c.get(f"/api/reports/{rid}").json()["clashes"])
