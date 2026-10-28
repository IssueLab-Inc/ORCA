import json
import threading

import httpx
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import meta_client, reports, triage
from sightline.service import Workspace
from tests.test_reports import GROUPED, STANDARD


class Scripted:
    """A triage model that answers every clash the same way and records what it was asked."""

    def __init__(self):
        self.asked: list[str] = []
        self.lock = threading.Lock()

    def complete_json(self, system, text, images=None, schema=None):
        assert schema == triage.SCHEMA
        with self.lock:
            self.asked.append(text)
        return {"understanding": "Duct through beam.", "verdict": "real_clash", "severity": "high",
                "responsible": "MEP", "action": "move_B", "fix_hint": "Lower the duct.", "confidence": 0.9}


def _report(tmp_path):
    (tmp_path / "a.xml").write_text(STANDARD.replace("{beam}", "0FQ9jQy2DHrgb6aZcJtSSS"))
    (tmp_path / "b.xml").write_text(GROUPED)
    return reports.load("r", tmp_path, [tmp_path / "a.xml", tmp_path / "b.xml"], "t")


def test_sure_cases_cost_no_model_call(tmp_path):
    report = _report(tmp_path)
    model, events = Scripted(), []
    results = triage.triage_report(report, model, events.append, workers=2, images=False)
    assert set(results) == {c.id for c in report.clashes}
    port = next(c for c in report.clashes if c.a.ifc_class == "IfcDistributionPort" or c.b.ifc_class == "IfcDistributionPort")
    assert results[port.id]["verdict"] == "non_physical" and results[port.id]["source"] == "rule"
    assert len(model.asked) == len(report.clashes) - 1  # the port result was settled by rule
    assert "Signed distance: -150.0 mm" in "\n".join(model.asked)
    assert triage.summary(results)["by_rule"] == 1 and len(events) == len(report.clashes)


def test_a_host_without_structured_output_falls_back_to_json_mode(monkeypatch):
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body["response_format"]["type"])
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": "response_format json_schema not supported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '```json\n{"verdict": "by_design"}\n```'}}]})

    model = meta_client.MetaChatModel("https://open.example/v1", "k", "muse-spark-open", reasoning_effort="")
    model.client = httpx.Client(transport=httpx.MockTransport(handler))
    assert model.complete_json("s", "t", schema=triage.SCHEMA) == {"verdict": "by_design"}
    assert model.complete_json("s", "t", schema=triage.SCHEMA) == {"verdict": "by_design"}
    assert sent == ["json_schema", "json_object", "json_object"]  # remembered after the first refusal


def test_triage_model_prefers_the_open_weights_host(monkeypatch):
    monkeypatch.setattr(meta_client, "load_env", lambda: None)
    monkeypatch.setenv("META_API_KEY", "m")
    monkeypatch.delenv("TRIAGE_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    model, info = meta_client.triage_model()
    assert not info["open_weights"] and model.base_url == "https://api.meta.ai/v1"
    monkeypatch.setenv("BASETEN_API_KEY", "b")
    model, info = meta_client.triage_model()
    assert info == {"model": "meta-models/muse-spark-open", "open_weights": True, "images": True}
    assert model.base_url == "https://inference.baseten.co/v1" and model.reasoning_effort == ""


def test_triage_stream_is_shared_and_replayed(tmp_path, monkeypatch):
    (tmp_path / "reports" / "demo").mkdir(parents=True)
    (tmp_path / "reports" / "demo" / "report.xml").write_text(STANDARD.replace("{beam}", "0FQ9jQy2DHrgb6aZcJtSSS"))
    model = Scripted()
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    monkeypatch.setattr(app_module, "_triage_jobs", {})
    monkeypatch.setattr(app_module, "triage_model", lambda: (model, {"model": "scripted", "open_weights": True}))
    c = TestClient(app_module.app)
    rid = c.post("/api/reports", json={"sample": "demo"}).json()["id"]
    assert c.get(f"/api/reports/{rid}/triage").json()["results"] == {}
    events = [json.loads(l) for l in c.post(f"/api/reports/{rid}/triage/stream").text.splitlines()]
    assert events[0] == {"type": "start", "total": 2, "model": "scripted", "open_weights": True}
    assert events[-1]["type"] == "done" and events[-1]["summary"]["real_clash"] == 2
    # A second visitor opening the same sample gets the same run without another model call.
    rid2 = c.post("/api/reports", json={"sample": "demo"}).json()["id"]
    again = [json.loads(l) for l in c.post(f"/api/reports/{rid2}/triage/stream").text.splitlines()]
    assert [e["type"] for e in again] == [e["type"] for e in events] and len(model.asked) == 2
    assert c.get(f"/api/reports/{rid2}/triage").json()["done"] is True


def test_rule_verdicts_say_why_and_how_to_stop_them(tmp_path):
    report = _report(tmp_path)
    port = next(c for c in report.clashes if "IfcDistributionPort" in (c.a.ifc_class, c.b.ifc_class))
    v = triage.by_rule(port)
    assert v["basis"] == "non_physical" and v["understanding"].startswith("Not a clash")
    assert "distribution port" in v["understanding"] and v["fix_hint"]


def test_what_the_open_model_settles_is_not_asked_and_corrects_answers(tmp_path):
    report = _report(tmp_path)
    beam = next(c for c in report.clashes if c.distance_m == -0.15)
    model = Scripted()
    job = triage.Job(report, model, {"model": "scripted"}, workers=1)
    job.learn({beam.id: triage.same_element(beam)})
    job.start()
    events = list(job.follow())
    assert job.results[beam.id]["basis"] == "same_element" and len(model.asked) == len(report.clashes) - 2
    # A fact learned after the run corrects a model answer and keeps what the model said.
    other = next(c for c in report.clashes if job.results[c.id]["source"] == "model")
    job.learn({other.id: triage.same_element(other)})
    v = job.results[other.id]
    assert v["basis"] == "same_element" and v["model_reading"].startswith("real clash: Duct through beam")
    replay = list(job.follow())
    assert replay[-1]["type"] == "done" and replay[-2] == {"type": "clash", "id": other.id, **v}
    assert len(replay) == len(events) + 1


class Thinking(Scripted):
    """A triage model that streams its reasoning before answering, like Muse Spark Open."""

    def complete_json_streamed(self, system, text, images, schema, on_reasoning):
        for piece in ("Duct crosses ", "the girder web; ", "no opening on its line."):
            on_reasoning(piece)
        return self.complete_json(system, text, images, schema)


def test_reasoning_streams_and_stays_with_the_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(triage, "REASONING_EVERY_S", 0)  # pass every piece on at once
    report = _report(tmp_path)
    events = []
    results = triage.triage_report(report, Thinking(), events.append, workers=2, images=False, reasoning=True)
    asked = [cid for cid, v in results.items() if v["source"] == "model"]
    assert asked and all(results[cid]["reasoning"] == "Duct crosses the girder web; no opening on its line." for cid in asked)
    said = [e for e in events if e["type"] == "reasoning"]
    assert {e["id"] for e in said} == set(asked) and "".join(e["text"] for e in said if e["id"] == asked[0]).startswith("Duct crosses")
    # Without `reasoning` (the eval scripts), no reasoning is asked for or kept.
    assert not any("reasoning" in v for v in triage.triage_report(report, Thinking(), workers=2, images=False).values())


def test_a_late_subscriber_skips_old_reasoning(tmp_path):
    job = triage.Job(_report(tmp_path), Scripted(), {"model": "m"})
    job._emit({"type": "start", "total": 1})
    job._emit({"type": "reasoning", "id": "c1", "text": "old thought"})
    job._emit({"type": "clash", "id": "c1", "verdict": "real_clash", "source": "model"})
    follower = job.follow()
    assert [next(follower)["type"], next(follower)["type"]] == ["start", "clash"]
    job._emit({"type": "reasoning", "id": "c2", "text": "new thought"})
    assert next(follower) == {"type": "reasoning", "id": "c2", "text": "new thought"}


def test_streamed_completion_reads_reasoning_then_json():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["stream"])
        chunks = ['{"choices":[{"delta":{"reasoning_content":"Think"}}]}', '{"choices":[{"delta":{"reasoning_content":"ing."}}]}',
                  '{"choices":[{"delta":{"content":"{\\"verdict\\": "}}]}', '{"choices":[{"delta":{"content":"\\"by_design\\"}"}}]}']
        return httpx.Response(200, text="".join(f"data: {c}\n\n" for c in chunks) + "data: [DONE]\n\n")

    model = meta_client.MetaChatModel("https://open.example/v1", "k", "muse-spark-open", reasoning_effort="")
    model.client = httpx.Client(transport=httpx.MockTransport(handler))
    heard = []
    assert model.complete_json_streamed("s", "t", None, triage.SCHEMA, heard.append) == {"verdict": "by_design"}
    assert heard == ["Think", "ing."] and sent == [True]


def test_triage_reads_alike_clashes_once(tmp_path):
    """48 bolts in 48 footings are one question: the deepest is read, the verdict applies to all (triage.alike_groups)."""
    from sightline import triage
    from sightline.reports import Report, ReportClash, ReportElement

    def clash(n, a, b, mm, test="Structure (within)"):
        e = lambda name, cls: ReportElement(f"g{name}", cls, name, "Level 01", "S.ifc")
        return ReportClash(f"s{n}", f"{a} × {b}", f"s{n}", test, "hard", 0.001, "new", -mm / 1000, None, None,
                           e(a, "IfcMechanicalFastener"), e(b, "IfcFooting"), number=n)

    bolts = [clash(i, "Holding-down bolt M24", f"Pad footing 1800x1800x600 - {g}", 340 + i) for i, g in
             enumerate(["A1", "A2", "B1", "B2", "C3"], 1)]
    lone = clash(6, "Holding-down bolt M24", "Pad footing 1800x1800x600 - D4", 30)   # much shallower: its own question
    duct = clash(7, "Supply air main L02 600x300", "Transfer plate girder 1000 deep - grid 3", 300, "MEP vs Structure")
    groups = triage.alike_groups(bolts + [lone, duct])
    assert sorted(len(g) for g in groups) == [1, 1, 5]
    assert next(g for g in groups if len(g) == 5)[0].number == 5          # the deepest stands for the group

    asked = []

    class Model:
        def complete_json(self, system, text, images=None, schema=None):
            asked.append(text)
            return {"understanding": "Bolts cast into their footing.", "verdict": "by_design", "severity": "none",
                    "responsible": "none", "action": "exclude_with_rule", "fix_hint": "", "confidence": 0.9}

    report = Report("r", "t", tmp_path, [], bolts + [lone, duct])
    out = triage.triage_report(report, Model(), workers=1)
    assert len(asked) == 3 and sum("stands for 5 alike clashes" in t for t in asked) == 1
    assert all(out[c.id]["verdict"] == "by_design" for c in bolts)
    assert out["s1"]["alike_of"] == "s5" and out["s1"]["alike"] == 5 and "alike_of" not in out["s5"]
    assert "alike" not in out["s6"] and "alike" not in out["s7"]
    assert len(triage.triage_report(Report("r2", "t", tmp_path, [], bolts), Model(), workers=1, alike=False)) == 5
    assert len(asked) == 8
