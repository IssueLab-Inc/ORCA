import json

from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline.chat import Chat, Context
from sightline.fixtures import build_run_fixture
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
