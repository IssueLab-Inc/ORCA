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
    assert info == {"model": "meta-models/muse-spark-open-1026", "open_weights": True, "images": True}
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
