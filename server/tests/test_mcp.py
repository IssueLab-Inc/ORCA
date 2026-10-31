"""ORCA's MCP server (mcp_server.py) and agent links (agents.py): remote over HTTP with a link token, and local."""
import asyncio
import json
import queue
import threading
import time

import pytest
from fastapi.testclient import TestClient

from sightline import agents, mcp_server, plans
from sightline import app as app_module
from sightline.fixtures import build_clash_fixture
from sightline.service import Workspace

from test_chat import PatternReader, _pattern

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json",
           "mcp-protocol-version": "2025-06-18"}


class ScriptedModel:
    """Stands in for Muse Spark: proposes dropping the duct 800 mm (clears the beam and the pipe below it)."""

    def complete_json(self, system, text, images=None, schema=None):
        return {"understanding": "The duct runs through the beam web.",
                "candidates": [{"title": "Drop duct 800 mm", "move": "A", "delta_m": [0, 0, -0.80],
                                "rationale": "Below the beam and the pipe", "also_needs": "none"}]}


def rpc(c: TestClient, token: str | None, name: str, args: dict | None = None, method: str = "tools/call"):
    """One JSON-RPC call to /mcp; for a tool, its text contents parsed (JSON when they are) and any images."""
    headers = dict(HEADERS)
    if token:
        headers["authorization"] = f"Bearer {token}"
    params = {"name": name, "arguments": args or {}} if method == "tools/call" else {}
    r = c.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if r.status_code != 200 or method != "tools/call":
        return r
    result = r.json()["result"]
    if result.get("isError"):
        raise AssertionError(result["content"][0]["text"])
    texts = [x["text"] for x in result["content"] if x["type"] == "text"]
    images = [x for x in result["content"] if x["type"] == "image"]
    try:
        return json.loads(texts[0]) if len(texts) == 1 and not images else {"texts": texts, "images": images}
    except json.JSONDecodeError:
        return {"texts": texts, "images": images}


@pytest.fixture()
def server(tmp_path, monkeypatch):
    build_clash_fixture(tmp_path / "fixture-clash.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path, model=ScriptedModel()))
    monkeypatch.setattr(app_module, "EXPORTS", tmp_path)
    with TestClient(app_module.app) as c:
        yield c


def _link(c: TestClient, **ctx) -> tuple[str, agents.Link]:
    token = c.post("/api/links", json=ctx).json()["token"]
    return token, app_module.links.get(token)


def test_tools_are_registered():
    tools = asyncio.run(mcp_server.build(Workspace()).list_tools())
    names = {t.name for t in tools}
    assert {"get_session", "open_models", "detect_clashes", "list_clashes", "get_clash_images", "capture_view",
            "check_move", "check_offset", "check_route", "check_resize", "check_penetration", "propose_fixes", "get_job", "apply_fix", "apply_plan", "triage",
            "generate_report", "export_models", "show_clash", "set_view", "set_filters", "clear_filters"} <= names
    read_only = {t.name for t in tools if t.annotations and t.annotations.read_only_hint}
    assert {"get_session", "list_clashes", "get_clash_images", "check_move", "check_offset", "check_route",
            "check_resize", "check_penetration", "capture_view"} <= read_only
    assert not read_only & {"propose_fixes", "apply_fix", "apply_plan", "detect_clashes", "triage", "generate_report",
                            "open_models", "find_patterns"}  # these change the model or the report, or spend


def test_mcp_needs_a_live_link_token(server):
    assert rpc(server, None, "", method="tools/list").status_code == 401
    assert rpc(server, "orca_not-a-token", "", method="tools/list").status_code == 401
    token, _ = _link(server)
    r = rpc(server, token, "", method="tools/list")
    assert r.status_code == 200 and "get_session" in {t["name"] for t in r.json()["result"]["tools"]}
    r = server.post(f"/mcp?key={token}", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 200  # a client that cannot set headers puts the token in the URL
    server.delete(f"/api/links/{token}")
    assert rpc(server, token, "", method="tools/list").status_code == 401


def test_an_agent_finds_checks_proposes_applies_and_exports(server):
    token, link = _link(server)
    assert rpc(server, token, "get_session")["models"] is None
    opened = rpc(server, token, "open_models", {"names": ["fixture-clash.ifc"]})  # no browser: opened on the server
    assert opened["status"] == "open" and opened["clashes"] >= 1
    page = link.subscribe()  # from here a page follows the link, as the browser does
    clashes = rpc(server, token, "list_clashes", {"query": "duct beam"})["clashes"]
    cid = clashes[0]["clash_id"]
    duct = rpc(server, token, "find_elements", {"query": "duct", "ifc_class": "IfcDuctSegment"})["elements"][0]["global_id"]
    assert rpc(server, token, "check_move", {"global_ids": [duct], "delta_m": [0, 0, -0.4]})["passed"] is False

    proposal = rpc(server, token, "propose_fixes", {"clash_id": cid, "wait_s": 30})
    assert proposal["status"] == "done"
    option = proposal["result"]["verified_options"][0]
    assert option["title"] == "Drop duct 800 mm" and option["option"] == 1

    applied = rpc(server, token, "apply_fix", {"clash_id": cid, "option": 1})
    assert applied["applied"] == "Drop duct 800 mm" and cid in link.ctx.fixed
    assert server.get(f"/api/links/{token}").json()["applied"] == {cid: "Drop duct 800 mm"}  # for a page that resumes
    events = []
    while not page.empty():
        events.append(page.get_nowait())
    kinds = {(e["type"], e.get("action")) for e in events}
    assert ("agent_call", None) in kinds and ("agent_result", None) in kinds
    assert ("proposal", None) in kinds and ("ui", "applied") in kinds
    assert next(e for e in events if e.get("action") == "applied")["clash_ids"] == [cid]

    url = rpc(server, token, "export_models")["url"]
    assert url.endswith(f"/api/scenes/{link.ctx.scene_id}/export")
    assert server.get(url.split("testserver", 1)[1]).content.startswith(b"ISO-10303-21")


def test_the_page_follows_and_answers_for_pictures(server):
    token, link = _link(server)
    sid = server.post("/api/scenes", json={"samples": ["fixture-clash.ifc"]}).json()["id"]
    server.put(f"/api/links/{token}/context", json={"scene_id": sid})
    assert link.ctx.scene_id == sid
    page = link.subscribe()

    def browser():  # answer the first capture request with a tiny PNG
        while True:
            e = page.get(timeout=10)
            if e["type"] == "capture_request":
                png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f"
                       b"\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00"
                       b"\x00\x00IEND\xaeB`\x82")
                server.post(f"/api/links/{token}/captures/{e['id']}", content=png)
                return

    t = threading.Thread(target=browser)
    t.start()
    shot = rpc(server, token, "capture_view")
    t.join()
    assert shot["images"] and shot["images"][0]["mimeType"] == "image/png"

    rpc(server, token, "set_view", {"mode": "xray", "section_box": True})
    seen = []
    while not page.empty():
        seen.append(page.get_nowait())
    assert {"type": "ui", "action": "set_view", "mode": "xray", "section_box": True} in seen
    assert rpc(server, token, "set_filters", {"filters": [{"classes": ["IfcBeam"], "action": "isolate"}]}) == {
        "filters": [{"filter": "isolate", "elements": 1}]}
    rpc(server, token, "clear_filters")
    seen = []
    while not page.empty():
        seen.append(page.get_nowait())
    sent = [e for e in seen if e.get("action") == "filters"]
    assert sent[0]["filters"][0]["when"] == [{"facet": "class", "op": "is", "values": ["IfcBeam"]}]
    assert sent[1] == {"type": "ui", "action": "filters", "mode": "clear"}
    link.unsubscribe(page)
    assert rpc(server, token, "capture_view")["texts"][0].startswith("No browser answered")


def test_links_expire_and_are_capped(server, monkeypatch):
    token, link = _link(server)
    assert server.get(f"/api/links/{token}").status_code == 200
    monkeypatch.setattr(agents.time, "time", lambda: link.expires + 1)
    assert server.get(f"/api/links/{token}").status_code == 404
    monkeypatch.undo()
    monkeypatch.setattr(app_module, "link_limit", app_module.ProposeLimit(1, 0, noun="agent links"))
    assert server.post("/api/links", json={}).status_code == 200
    assert server.post("/api/links", json={}).status_code == 429


def test_a_long_proposal_becomes_a_job(server):
    token, link = _link(server)
    rpc(server, token, "open_models", {"names": ["fixture-clash.ifc"]})
    cid = rpc(server, token, "list_clashes", {"query": "duct beam"})["clashes"][0]["clash_id"]
    started = rpc(server, token, "propose_fixes", {"clash_id": cid, "wait_s": 0})
    assert started["status"] in ("running", "done") and started["job_id"]
    deadline = time.time() + 30
    state = started
    while state["status"] == "running" and time.time() < deadline:
        state = rpc(server, token, "get_job", {"job_id": started["job_id"], "wait_s": 5})
    assert state["status"] == "done" and state["result"]["verified_options"]


def test_stdio_works_on_its_own_session(tmp_path):
    build_clash_fixture(tmp_path / "fixture-clash.ifc")
    ws = Workspace(samples=tmp_path, model=ScriptedModel())
    local = agents.Link("local", "", "local", True, time.time(), float("inf"))
    mcp = mcp_server.build(ws, mcp_server.Hooks(), local=local)

    def call(name, args=None):
        out = asyncio.run(mcp.call_tool(name, args or {}))
        return json.loads(out.content[0].text)

    assert call("open_models", {"names": ["fixture-clash.ifc"]})["status"] == "open"
    assert local.ctx.scene_id in ws.scenes and local.ctx.report_id in ws.reports
    assert call("report_summary")["clashes"] >= 1


def test_the_expiry_slides_with_use_and_stops_at_a_day(server, monkeypatch):
    token, link = _link(server)
    state = server.get(f"/api/links/{token}").json()
    assert state["max_expires_at"] == pytest.approx(link.created + agents.MAX_AGE)
    assert abs(state["server_time"] - time.time()) < 5
    page = link.subscribe()
    clock = [time.time() + 3 * 3600]
    monkeypatch.setattr(agents.time, "time", lambda: clock[0])
    rpc(server, token, "get_session")                       # three hours later: an agent call renews it to 12 h
    assert link.expires == pytest.approx(clock[0] + agents.TTL)
    assert page.get_nowait()["expires_at"] == pytest.approx(link.expires)
    clock[0] = link.created + 14 * 3600                     # renewed again, but never past a day from creation
    rpc(server, token, "get_session")
    assert link.expires == pytest.approx(link.created + agents.MAX_AGE)
    assert server.get(f"/api/links/{token}").json()["expires_at"] == pytest.approx(link.expires)


def test_a_closed_page_leaves_the_agent_working_and_says_so(server):
    token, link = _link(server)
    rpc(server, token, "open_models", {"names": ["fixture-clash.ifc"]})
    session = rpc(server, token, "get_session")
    assert session["browser_connected"] is False and "page is closed" in session["note"]
    assert rpc(server, token, "report_summary")["clashes"] >= 1


def test_a_page_that_closes_stops_counting_at_once(server):
    token, link = _link(server)
    first, second = link.subscribe(), link.subscribe()  # two tabs follow the link
    assert server.post(f"/api/links/{token}/leave/{first.stream_id}").json() == {"left": True}
    assert link.browser and first.get_nowait() == {"type": "bye"}  # the other tab still counts
    server.post(f"/api/links/{token}/leave/{second.stream_id}")
    assert not link.browser
    assert server.post(f"/api/links/{token}/leave/nothing").json() == {"left": False}


def test_an_agents_detection_runs_are_charged_to_whoever_made_the_link(server, monkeypatch):
    monkeypatch.setattr(app_module, "detect_limit", app_module.ProposeLimit(2, 0, noun="detection runs"))
    token, link = _link(server)
    assert rpc(server, token, "open_models", {"names": ["fixture-clash.ifc"]})["clashes"] >= 1   # no browser: run 1
    assert rpc(server, token, "detect_clashes")["clashes"] >= 1                                     # run 2
    assert "detection runs this hour" in rpc(server, token, "detect_clashes")["error"]
    opened = rpc(server, token, "open_models", {"names": ["fixture-clash.ifc"]})
    assert opened["status"] == "open" and opened["clashes"] is None and opened["note"].startswith("Opened, not checked")
    # The page of the visitor who made the link shares the cap.
    assert server.post(f"/api/scenes/{link.ctx.scene_id}/detect/stream", json={}).status_code == 429
    link.owner = True   # the owner's links have no caps
    assert rpc(server, token, "detect_clashes")["clashes"] >= 1


def test_an_agents_pattern_reading_costs_one_proposal_once(server, monkeypatch):
    monkeypatch.setattr(app_module, "propose_limit", app_module.ProposeLimit(1, 0))
    token, link = _link(server)
    rpc(server, token, "open_models", {"names": ["fixture-clash.ifc"]})
    app_module.ws._model = reader = PatternReader()
    pats = [_pattern()]
    monkeypatch.setattr(plans, "patterns", lambda *a, **k: pats)
    first = rpc(server, token, "find_patterns")
    assert first["patterns"][0]["verdict"] == "by_design"
    assert rpc(server, token, "find_patterns") == first and reader.calls == 1   # kept: no second call or charge
    # The page asks for the same reading: it has it, free.
    r = server.post(f"/api/reports/{link.ctx.report_id}/patterns/{link.ctx.scene_id}/triage", json={})
    assert r.status_code == 200 and r.json() == {pats[0]["id"]: {k: first["patterns"][0][k]
                                                                for k in ("verdict", "cause", "action", "rule")}}
    pats[:] = [_pattern(2)]   # a new reading: the hour's one proposal is spent
    assert "this hour" in rpc(server, token, "find_patterns")["error"] and reader.calls == 1
