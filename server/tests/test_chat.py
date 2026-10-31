import json
import threading

import pytest

from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import plans
from sightline.chat import Chat, Context
from sightline.fixtures import build_run_fixture
from sightline.limits import ProposeLimit
from sightline.service import Workspace

from test_reports import GROUPED


class Scripted:
    """Stands in for Muse Spark: plays tool calls in order, then answers."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.seen = []

    def chat(self, messages, tools):
        self.seen.append(messages[-1])
        step = self.steps.pop(0)
        if isinstance(step, str):
            return {"role": "assistant", "content": step}
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(step)]}


def _setup(tmp_path):
    build_run_fixture(tmp_path / "run.ifc")
    (tmp_path / "reports" / "r" / "c7").mkdir(parents=True)
    (tmp_path / "reports" / "r" / "report.xml").write_text(GROUPED)
    for n in ("A-transparent.png", "B-context.png", "C-alternate.png"):
        (tmp_path / "reports" / "r" / "c7" / n).write_bytes(b"\x89PNG")
    ws = Workspace(samples=tmp_path)
    return ws, ws.open(["run.ifc"]), ws.open_report_sample("r").id


def test_tools_run_and_images_reach_the_model(tmp_path):
    ws, sid, rid = _setup(tmp_path)
    model = Scripted([
        [("report_summary", {}), ("list_clashes", {"query": "port"})],
        [("look_at_clash_images", {"clash_id": "c0001"}), ("show_clash", {"clash_id": "c0001"})],
        "Clash7 is a port touching a wall: not a real clash.",
    ])
    events = []
    chat = Chat(ws, model)
    s = chat.session(None)
    answer = chat.turn(s, "What is this one?", Context(sid, rid, "c0001"), events.append)

    assert answer.startswith("Clash7")
    kinds = [e["type"] for e in events]
    assert kinds.count("tool") == 4 and kinds[-1] == "message"
    assert {"type": "ui", "action": "select_clash", "clash_id": "c0001"} in events
    assert "the user has clash c0001 selected" in s.messages[1]["content"]
    images = model.seen[2]  # after the images tool, the next model call starts with the images
    assert images["role"] == "user" and sum(p["type"] == "image_url" for p in images["content"]) == 3


def test_tool_errors_go_back_to_the_model(tmp_path):
    ws, sid, rid = _setup(tmp_path)
    model = Scripted([[("get_clash", {"clash_id": "nope"})], "That clash does not exist."])
    events = []
    chat = Chat(ws, model)
    chat.turn(chat.session(None), "Tell me about nope", Context(sid, rid), events.append)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["summary"].startswith("failed")
    assert "error" in model.seen[1]["content"]


def test_chat_endpoint_streams_a_session_then_the_answer(tmp_path, monkeypatch):
    ws, sid, rid = _setup(tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    monkeypatch.setattr(app_module, "_chat", Chat(ws, Scripted([[("set_view", {"mode": "xray"})], "Done."])))
    c = TestClient(app_module.app)
    r = c.post("/api/chat", json={"message": "x-ray please", "scene_id": sid, "report_id": rid})
    events = [json.loads(line) for line in r.text.splitlines()]
    assert events[0]["type"] == "session" and events[-1] == {"type": "done"}
    assert {"type": "ui", "action": "set_view", "mode": "xray"} in events
    assert any(e == {"type": "message", "text": "Done."} for e in events)


def test_the_pages_filters_reach_chat_by_name(tmp_path, monkeypatch):
    ws, sid, rid = _setup(tmp_path)
    model = Scripted(["Noted."])
    monkeypatch.setattr(app_module, "ws", ws)
    monkeypatch.setattr(app_module, "_chat", Chat(ws, model))
    c = TestClient(app_module.app)
    mine = [{"id": "u1", "name": "Ducts on L2", "when": [{"facet": "class", "op": "is", "values": ["IfcDuctSegment"]}]}]
    r = c.post("/api/chat", json={"message": "hi", "scene_id": sid, "report_id": rid, "filters": mine})
    assert r.status_code == 200
    assert 'the user\'s filters: "Ducts on L2"' in model.seen[0]["content"]
    too_many = c.post("/api/chat", json={"message": "hi", "scene_id": sid, "filters": [{"name": "x"}] * 101})
    assert too_many.status_code == 422


def test_chat_sets_and_clears_filters_by_what_the_model_says(tmp_path):
    ws, sid, rid = _setup(tmp_path)
    model = Scripted([[("set_filters", {"filters": [
        {"classes": ["DuctSegment"], "levels": ["level 02"], "action": "colour", "colour": "#318181"},
        {"action": "colour_by_value", "by": "class"},
        {"where": [{"property": "Name", "op": "contains", "values": ["beam"]}], "action": "hide", "invert": True}],
        "grey_rest": True})], [("clear_filters", {})], "Done."])
    events = []
    chat = Chat(ws, model)
    chat.turn(chat.session(None), "Colour the ducts on level 2", Context(sid, rid), events.append)
    ui = [e for e in events if e.get("type") == "ui" and e.get("action") == "filters"]
    assert ui[0]["mode"] == "replace" and ui[0]["grey_rest"] is True
    ducts, by_class, rest = ui[0]["filters"]
    assert ducts["when"] == [{"facet": "class", "op": "is", "values": ["IfcDuctSegment"]},
                             {"facet": "storey", "op": "is", "values": ["Level 02"]}]
    assert ducts["origin"] == "chat" and ducts["colour"] == "#318181" and ducts["action"] == "colour"
    assert by_class["action"] == "byValue" and by_class["by"] == {"facet": "class"}
    told = json.loads(next(m for m in model.seen if m.get("role") == "tool" and "filters" in (m.get("content") or ""))["content"])
    assert {"value": "IfcBeam", "elements": 1} in told["filters"][1]["values"], "the model hears what it coloured, by name"
    assert rest["invert"] is True and rest["when"][0] == {"facet": "attr:Name", "op": "contains", "values": ["beam"]}
    assert ui[1] == {"type": "ui", "action": "filters", "mode": "clear"}
    found = next(e for e in events if e["type"] == "tool_result" and e["name"] == "set_filters")["summary"]
    n = len(ws.facets(sid)["elements"])
    beams = sum(1 for g in ws.facets(sid)["elements"] if ws.scene(sid).element(g).ifc_class == "IfcBeam")
    assert found == f"{n - beams} elements, {n} elements, {n - beams} elements" or found.count("elements") == 3


def test_a_filter_on_what_the_models_lack_says_what_is_there(tmp_path):
    ws, sid, rid = _setup(tmp_path)
    model = Scripted([[("set_filters", {"filters": [{"classes": ["DuctSegmnt"], "action": "hide"}]})], "Sorry."])
    events = []
    chat = Chat(ws, model)
    chat.turn(chat.session(None), "Hide the ducts", Context(sid, rid), events.append)
    assert not [e for e in events if e.get("action") == "filters"], "nothing reaches the page"
    assert "Closest: IfcDuctSegment" in model.seen[1]["content"]


def test_chat_finds_root_causes_and_builds_a_plan(tmp_path):
    from test_plans import _setup as plan_setup

    ws, sid, rid, main, beam = plan_setup(tmp_path)
    model = Scripted([[("find_root_causes", {})], [("plan_fixes_together", {"clash_ids": ["c0001"]})], "Planned."])
    events = []
    chat = Chat(ws, model)
    chat.turn(chat.session(None), "fix c0001", Context(sid, rid), events.append)
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["kind"] == "batch" and plan["check"]["passed"]
    assert any(e["type"] == "plan_event" for e in events)
    result = next(e for e in events if e["type"] == "tool_result" and e["name"] == "plan_fixes_together")
    assert result["summary"] == "1 of 1 clash fixed, verified together"


def _pattern(n: int = 1) -> dict:
    """A pattern as plans.patterns gives it (the run fixture has too few pairs to make one)."""
    return {"id": f"IfcBeam|IfcDuctSegment|S{n}|M", "classes": ["IfcBeam", "IfcDuctSegment"], "files": [f"S{n}", "M"],
            "cross_discipline": True, "clashes": 3, "pairs": 3, "levels": ["Level 02"], "min_mm": -30, "max_mm": -30,
            "constant": True, "clash_ids": ["c0001"], "examples": ["IfcBeam 'B' x IfcDuctSegment 'D' (-30 mm)"]}


class PatternReader:
    """Muse Spark's one call over the patterns (plans.triage_patterns), counted."""

    def __init__(self):
        self.calls = 0

    def complete_json(self, system, text, images=None):
        self.calls += 1
        return {"patterns": [{"id": "P1", "verdict": "by_design", "cause": "c", "action": "a", "rule": "r"}]}


def _lines(r) -> list[dict]:
    return [json.loads(line) for line in r.text.splitlines()]


def test_find_patterns_costs_one_proposal_once_and_shares_the_routes_reading(tmp_path, monkeypatch):
    ws, sid, rid = _setup(tmp_path)
    ws._model = reader = PatternReader()
    pats = [_pattern()]
    monkeypatch.setattr(plans, "patterns", lambda *a, **k: pats)
    monkeypatch.setattr(app_module, "ws", ws)
    monkeypatch.setattr(app_module, "propose_limit", ProposeLimit(per_day=1))
    c = TestClient(app_module.app)

    # The page reads the patterns first: one proposal, the day's only one.
    r = c.post(f"/api/reports/{rid}/patterns/{sid}/triage", json={})
    assert r.status_code == 200 and r.json()[pats[0]["id"]]["verdict"] == "by_design"
    assert c.post(f"/api/reports/{rid}/patterns/{sid}/triage", json={}).status_code == 200   # cached: free
    # The chat asks twice: it gets the same reading, no model call and nothing charged.
    monkeypatch.setattr(app_module, "_chat", Chat(ws, Scripted([[("find_patterns", {})], [("find_patterns", {})], "x"])))
    events = _lines(c.post("/api/chat", json={"message": "noise?", "scene_id": sid, "report_id": rid}))
    results = [e for e in events if e["type"] == "tool_result"]
    assert [e["summary"] for e in results] == ["1 pattern(s)", "1 pattern(s)"] and reader.calls == 1

    # Patterns nobody has read yet: a new reading, which the spent allowance refuses (no model call).
    pats[:] = [_pattern(2)]
    monkeypatch.setattr(app_module, "_chat", Chat(ws, Scripted([[("find_patterns", {})], "x"])))
    events = _lines(c.post("/api/chat", json={"message": "noise?", "scene_id": sid, "report_id": rid}))
    assert next(e for e in events if e["type"] == "tool_result")["summary"] == "refused: allowance used"
    assert reader.calls == 1
    assert c.post(f"/api/reports/{rid}/patterns/{sid}/triage", json={}).status_code == 429


def test_find_patterns_in_chat_is_charged_and_kept_like_the_route(tmp_path, monkeypatch):
    ws, sid, rid = _setup(tmp_path)
    ws._model = reader = PatternReader()
    monkeypatch.setattr(plans, "patterns", lambda *a, **k: [_pattern()])
    charged = []
    chat = Chat(ws, Scripted([[("find_patterns", {})], [("find_patterns", {})], "Two looks, one reading."]))
    chat.turn(chat.session(None), "what is this noise", Context(sid, rid), lambda e: None,
              propose_allowed=lambda: charged.append(1))
    assert charged == [1] and reader.calls == 1
    monkeypatch.setattr(plans, "patterns", lambda *a, **k: [])   # nothing to read: nothing charged
    events = []
    again = Chat(ws, Scripted([[("find_patterns", {})], "None."]))
    again.turn(again.session(None), "and now?", Context(sid, rid), events.append, propose_allowed=lambda: "spent")
    assert next(e for e in events if e["type"] == "tool_result")["summary"] == "0 pattern(s)"


def test_chat_detection_takes_a_detection_run(tmp_path, monkeypatch):
    ws, sid, rid = _setup(tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    monkeypatch.setattr(app_module, "detect_limit", ProposeLimit(1, 0, noun="detection runs"))
    monkeypatch.setattr(app_module, "_chat", Chat(ws, Scripted([[("detect_clashes", {})], [("detect_clashes", {})],
                                                                 "Checked once."])))
    c = TestClient(app_module.app)
    events = _lines(c.post("/api/chat", json={"message": "check it twice", "scene_id": sid}))
    summaries = [e["summary"] for e in events if e["type"] == "tool_result"]
    assert "clashes found by ORCA" in summaries[0]
    assert summaries[1] == "refused: detection runs used"
    assert sum(1 for e in events if e.get("action") == "open_report") == 1
    # The route shares the cap: this visitor has used their run.
    assert c.post(f"/api/scenes/{sid}/detect/stream", json={}).status_code == 429


@pytest.mark.parametrize('cancel_older', [True, False])
def test_immediate_resume_preserves_newer_history_when_older_model_returns_late(cancel_older):
    entered, release, cancel = threading.Event(), threading.Event(), threading.Event()
    inputs, results, errors, old_events = {}, {}, [], []
    class Model:
        def chat(self, messages, tools):
            question = messages[-1]['content'].split('\n\n')[-1]
            inputs[question] = json.loads(json.dumps(messages))
            if question == 'Older question':
                entered.set()
                assert release.wait(5)
                return dict(role='assistant', content='Older answer')
            return dict(role='assistant', content='Newer answer')
    chat = Chat(Workspace(), Model()); session = chat.session(None)
    def old_turn():
        try:
            results['old'] = chat.turn(session, 'Older question', Context(), old_events.append, cancel=cancel)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=old_turn); thread.start()
    try:
        assert entered.wait(5)
        if cancel_older: cancel.set()
        # A resumed request finishes while the older model request remains blocked.
        results['new'] = chat.turn(session, 'Newer question', Context(), lambda e: None)
        completed = json.loads(json.dumps(session.messages))
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive() and not errors
    assert results == {'old': '' if cancel_older else 'Older answer', 'new': 'Newer answer'}
    assert session.messages == completed
    assert len(completed) == 3 and completed[-1]['content'] == 'Newer answer'
    assert [m['role'] for m in inputs['Newer question']] == ['system', 'user']
    assert inputs['Newer question'][-1]['content'].endswith('Newer question')
    if cancel_older:
        assert not any(e['type'] == 'message' for e in old_events)


def test_final_emit_cancellation_cannot_publish_or_erase_a_newer_turn():
    cancel, entered, release = threading.Event(), threading.Event(), threading.Event()
    class Model:
        def chat(self, messages, tools):
            if messages[-1]['content'].endswith('Older question'):
                entered.set(); assert release.wait(3)
                return dict(role='assistant', content='Older answer')
            return dict(role='assistant', content='Newer answer')
    chat = Chat(Workspace(), Model()); session = chat.session(None); answers, errors = [], []
    def emit(event):
        if event['type'] == 'message':
            cancel.set()
    def old_turn():
        try:
            answers.append(chat.turn(session, 'Older question', Context(), emit, cancel=cancel))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=old_turn, daemon=True); thread.start()
    try:
        assert entered.wait(3)
        chat.turn(session, 'Newer question', Context(), lambda e: None)
        newer = json.loads(json.dumps(session.messages))
    finally:
        release.set(); thread.join(3)
    assert not thread.is_alive() and not errors and answers == [''] and session.messages == newer
    assert session._published_turn == 2 and session.messages[-1]['content'] == 'Newer answer'
