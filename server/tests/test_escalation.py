"""A second try on a larger model (docs/escalation.md), and the combined fix it may propose."""
import json

import pytest
from fastapi.testclient import TestClient

from sightline import agent, app as app_module, escalation, meta_client, plans, settings, spend
from sightline.fixtures import build_clash_fixture
from sightline.scene import IfcScene
from sightline.service import Workspace


@pytest.fixture(autouse=True)
def fresh_budget():
    spend.reset()
    yield
    spend.reset()


def _ids(s: IfcScene):
    return (s.model.by_type("IfcDuctSegment")[0].GlobalId, s.model.by_type("IfcBeam")[0].GlobalId,
            s.model.by_type("IfcPipeSegment")[0].GlobalId)


class Script:
    """A model that replies with the next scripted answer and keeps what it read."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.texts: list[str] = []
        self.systems: list[str] = []

    def complete_json(self, system, text, images=None):
        self.systems.append(system)
        self.texts.append(text)
        return self.replies.pop(0) if self.replies else {"candidates": []}


DROP_INTO_PIPE = {"understanding": "The duct crosses the beam.", "advice": "Look below the beam.",
                  "candidates": [{"title": "Drop duct 400 mm", "move": "A", "delta_m": [0, 0, -0.4]}]}


def combined(*steps, title="Pipe down, duct under the beam"):
    return {"title": title, "kind": "combined", "steps": list(steps), "rationale": "room below"}


# ------------------------------------------------------------------------------------------------- the combined fix

def test_a_combined_fix_moves_the_neighbour_and_the_duct_together(tmp_path):
    s = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    duct, beam, pipe = _ids(s)
    model = Script({"candidates": [combined({"kind": "move", "move": pipe, "delta_m": [0, 0, -0.5]},
                                            {"kind": "move", "move": "A", "delta_m": [0, 0, -0.4]})]})

    result = agent.resolve(s, agent.Clash(duct, beam), model, max_rounds=1)

    assert [a.passed for a in result.attempts] == [True]
    o = result.options[0]
    assert o.kind == "combined" and set(o.moved) == {duct, pipe}
    assert o.edit["pair"] == [duct, beam] and len(o.edit["steps"]) == 2
    assert "LTHW pipe DN50: move [0, 0, -500] mm" in o.edit["summary"]
    assert o.preview   # both elements' new places, for the page, each with its run's element and part
    assert {m["origin"] for m in o.preview} == {duct, pipe} and {m["part"] for m in o.preview} == {"moved"}
    assert s.placement(duct)[2, 3] == pytest.approx(2.65) and s.placement(pipe)[2, 3] == pytest.approx(2.25)  # undone


def test_combined_steps_are_checked_against_each_other(tmp_path):
    s = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    duct, beam, pipe = _ids(s)
    # the pipe moves up into the place the duct drops to
    model = Script({"candidates": [combined({"kind": "move", "move": pipe, "delta_m": [0, 0, 0.1]},
                                            {"kind": "move", "move": "A", "delta_m": [0, 0, -0.4]})]})
    result = agent.resolve(s, agent.Clash(duct, beam), model, max_rounds=1)
    assert not result.options and not result.attempts[0].passed
    assert "IfcDuctSegment" in result.attempts[0].reason or "IfcPipeSegment" in result.attempts[0].reason


@pytest.mark.parametrize("steps,why", [
    ([{"kind": "move", "move": "B", "delta_m": [0, 0, 1]}], "structure"),
    ([{"kind": "move", "move": "PIPE", "delta_m": [0, 0, -0.5]}], "one step must change A or B"),
    ([{"kind": "trim", "move": "A"}], "not a trim"),
    ([{"kind": "move", "move": "A", "delta_m": [0, 0, 0]}], "not all zero"),
    ([{"kind": "move", "move": "nope", "delta_m": [0, 0, 1]}], "not a physical element"),
    ([{"kind": "move", "move": "A", "delta_m": [0, 0, -1]}, {"kind": "move", "move": "A", "delta_m": [0, 0, 1]}],
     "different element"),
    ([], "1 to 3 steps"),
])
def test_combined_fixes_that_cannot_be_tried_say_why(tmp_path, steps, why):
    s = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    duct, beam, pipe = _ids(s)
    steps = [{**st, "move": pipe} if st.get("move") == "PIPE" else st for st in steps]
    result = agent.resolve(s, agent.Clash(duct, beam), Script({"candidates": [combined(*steps)]}), max_rounds=1)
    assert not result.options
    assert why in result.attempts[0].reason


def test_a_combined_fix_is_kept_with_its_steps_checked_again(tmp_path):
    build_clash_fixture(tmp_path / "f.ifc")
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["f.ifc"])
    s = ws.scene(sid)
    duct, beam, pipe = _ids(s)
    model = Script({"candidates": [combined({"kind": "move", "move": pipe, "delta_m": [0, 0, -0.5]},
                                            {"kind": "move", "move": "A", "delta_m": [0, 0, -0.4]})]})
    o = agent.resolve(s, agent.Clash(duct, beam), model, max_rounds=1).options[0]

    kept = plans.apply(ws, sid, [json.loads(json.dumps(agent.asdict(o)))])

    assert set(kept["changed"]) == {duct, pipe}
    assert s.placement(duct)[2, 3] == pytest.approx(2.25) and s.placement(pipe)[2, 3] == pytest.approx(1.75)
    # a step that would now move structure is refused when kept, whatever the page sends
    bad = json.loads(json.dumps(agent.asdict(o)))
    bad["edit"]["steps"][0]["target"] = beam
    with pytest.raises(agent.Refused):
        plans.apply(ws, sid, [bad])


# ------------------------------------------------------------------------------------------------- the second try

def test_a_second_try_reads_the_first_and_names_its_model(tmp_path):
    build_clash_fixture(tmp_path / "f.ifc")
    spark = Script(DROP_INTO_PIPE)
    wonder = Script({"understanding": "The pipe is in the way of a drop.",
                     "candidates": [combined({"kind": "move", "move": "PIPE", "delta_m": [0, 0, -0.5]},
                                             {"kind": "move", "move": "A", "delta_m": [0, 0, -0.4]})]})
    ws = Workspace(samples=tmp_path, model=spark, escalation_model=wonder)
    sid = ws.open(["f.ifc"])
    duct, beam, pipe = _ids(ws.scene(sid))
    wonder.replies[0]["candidates"][0]["steps"][0]["move"] = pipe

    first = ws.propose(sid, duct, beam)
    assert not first["options"]
    events = []
    second = ws.escalate(sid, duct, beam, on_event=events.append)

    text = wonder.texts[0]
    assert "## The first try" in text and "Drop duct 400 mm" in text and "FAILED" in text
    assert "LTHW pipe DN50" in text                 # what it ran into, by name
    assert "Around the clash" in text and pipe in text
    assert "combined" in text and "A second try" in wonder.systems[0]
    assert second["escalated"] and second["model"] == "Muse Wonder"
    assert [o["kind"] for o in second["options"]] == ["combined"] and second["options"][0]["model"] == "Muse Wonder"
    assert [a["model"] for a in second["attempts"]] == ["", "Muse Wonder"]   # the first try's, then the second's
    assert events[0]["type"] == "escalating" and events[0]["model"] == "Muse Wonder" and events[0]["first"]
    assert [a["title"] for a in events[0]["first_try"]["attempts"]] == ["Drop duct 400 mm"]
    assert all(e.get("model") == "Muse Wonder" for e in events[1:])
    assert ws.last_try(sid, beam, duct)["escalated"]   # either order of the pair


def test_a_better_fix_keeps_the_first_tries_fixes_in_one_ranked_list(tmp_path):
    build_clash_fixture(tmp_path / "f.ifc")
    spark = Script({"candidates": [{"title": "Shift duct 3.5 m east", "move": "A", "delta_m": [3.5, 0, 0]}]})
    wonder = Script({"candidates": [{"title": "Drop duct 800 mm", "move": "A", "delta_m": [0, 0, -0.8]}]})
    ws = Workspace(samples=tmp_path, model=spark, escalation_model=wonder)
    sid = ws.open(["f.ifc"])
    duct, beam, _ = _ids(ws.scene(sid))
    assert len(ws.propose(sid, duct, beam)["options"]) == 1

    second = ws.escalate(sid, duct, beam)

    assert "It verified these fixes" in wonder.texts[0] and "Shift duct 3.5 m east" in wonder.texts[0]
    assert [o["title"] for o in second["options"]] == ["Drop duct 800 mm", "Shift duct 3.5 m east"]  # smaller first
    assert {o["title"]: o["model"] for o in second["options"]}["Drop duct 800 mm"] == "Muse Wonder"


def test_automatic_second_tries_follow_the_setting_and_the_caps(tmp_path):
    build_clash_fixture(tmp_path / "f.ifc")
    ws = Workspace(samples=tmp_path, model=Script(DROP_INTO_PIPE, DROP_INTO_PIPE),
                   escalation_model=Script({"candidates": [{"title": "Drop duct 800 mm", "move": "A",
                                                             "delta_m": [0, 0, -0.8]}]}))
    sid = ws.open(["f.ifc"])
    duct, beam, _ = _ids(ws.scene(sid))

    settings.update({"escalation": "auto"})
    events = []
    refused = ws.propose(sid, duct, beam, on_event=events.append, escalate_check=lambda: "caps used")
    assert not refused.get("escalated") and {"type": "note", "text": "No second try: caps used"} in events
    auto = ws.propose(sid, duct, beam, escalate_check=lambda: None)
    assert auto["escalated"] and auto["options"][0]["title"] == "Drop duct 800 mm"


def test_no_second_try_where_nothing_may_be_edited(tmp_path, monkeypatch):
    build_clash_fixture(tmp_path / "f.ifc")
    ws = Workspace(samples=tmp_path, model=Script(), escalation_model=Script())
    sid = ws.open(["f.ifc"])
    duct, beam, _ = _ids(ws.scene(sid))
    monkeypatch.setattr(Workspace, "fix_settings", lambda self, *a: {"recommend": "L5 As-built: report only"})
    with pytest.raises(ValueError, match="no second try"):
        ws.escalate(sid, duct, beam)


def test_the_brief_stays_within_its_budget(tmp_path):
    s = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    duct, beam, _ = _ids(s)
    text = escalation.brief(s, agent.Clash(duct, beam), None)
    assert "No first try was made" in text and "Kinds of fix ORCA can try: " in text and "combined" in text
    assert len(text) <= escalation.MAX_CHARS


# ------------------------------------------------------------------------------------------------- the API and costs

def test_the_api_refuses_second_tries_when_off_over_budget_or_capped(tmp_path, monkeypatch):
    build_clash_fixture(tmp_path / "f.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path, model=Script(DROP_INTO_PIPE),
                                                   escalation_model=Script()))
    monkeypatch.setattr(app_module, "escalate_limit", app_module.ProposeLimit(1, 0, noun="second tries"))
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["f.ifc"]}).json()["id"]
    duct, beam, _ = _ids(app_module.ws.scene(sid))
    body = {"element_a": duct, "element_b": beam, "escalate": True}

    settings.update({"escalation": "off"})
    assert c.post(f"/api/scenes/{sid}/propose", json=body).status_code == 403
    settings.update({"escalation": "button"})
    monkeypatch.setenv("SIGHTLINE_WONDER_MAX_USD_DAY", "5")
    spend.charge(5.0)
    r = c.post(f"/api/scenes/{sid}/propose/stream", json=body)
    assert r.status_code == 429 and "budget" in r.json()["detail"]
    spend.reset()
    assert c.post(f"/api/scenes/{sid}/propose", json=body).json()["escalated"] is True
    assert c.post(f"/api/scenes/{sid}/propose", json=body).status_code == 429   # one an hour here
    assert c.get("/api/models").json()["escalation"]["mode"] == "button"


def test_a_priced_model_counts_its_tokens_and_charges_the_day(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key")
    m = meta_client.MetaChatModel(api_key="k", model="muse-wonder-1.0")
    charged = []
    m.on_cost = charged.append
    m._count({"prompt_tokens": 3000, "completion_tokens": 1500, "completion_tokens_details": {"reasoning_tokens": 900}})
    m._count({"input_tokens": 1000, "output_tokens": 500, "output_tokens_details": {"reasoning_tokens": 100}})
    u = m.usage.as_dict(m.model)
    assert (u["calls"], u["input_tokens"], u["output_tokens"], u["reasoning_tokens"]) == (2, 4000, 2000, 1000)
    assert u["usd"] == pytest.approx(4000 * 4e-6 + 2000 * 20e-6)
    assert charged == pytest.approx([0.042, 0.014])
    spark = meta_client.MetaChatModel(api_key="k", model="muse-spark-1.3-contributor")
    spark.on_cost = charged.append
    spark._count({"prompt_tokens": 9999, "completion_tokens": 9999})
    assert len(charged) == 2   # not billed per token here


def test_the_day_budget_resets_and_spares_the_owner(monkeypatch):
    monkeypatch.setenv("SIGHTLINE_WONDER_MAX_USD_DAY", "1")
    spend.charge(0.6)
    assert spend.refused(0.3) is None and spend.refused(0.5)
    assert spend.refused(0.5, exempt=True) is None
    monkeypatch.setenv("SIGHTLINE_WONDER_MAX_USD_DAY", "0")
    assert spend.refused(100) is None


def test_escalation_settings_validate_and_the_owner_wins(monkeypatch):
    from sightline import owner
    monkeypatch.setenv("META_API_KEY", "test-key")
    with pytest.raises(ValueError):
        settings.update({"escalation": "always"})
    settings.update({"escalation": "auto", "escalation_effort": "high"})
    assert settings.escalation() == "auto" and settings.effort_for("escalation") == "high"
    tokens = owner.enter(True, json.dumps({"escalation": "off", "escalation_effort": "low"}))
    try:
        assert settings.escalation() == "off" and owner.effort("escalation") == "low"
        assert meta_client.escalation_model().effort == "low"
    finally:
        owner.leave(tokens)
    assert meta_client.escalation_model().effort == "high"


def test_the_chat_asks_for_a_second_try_only_when_allowed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from sightline import chat

    calls = []
    empty = {"understanding": "u", "options": [], "attempts": [], "advice": "a"}
    rules = {}
    ws = SimpleNamespace(propose=lambda *a, **k: calls.append(("propose", k.get("escalate_check"))) or empty,
                         escalate=lambda *a, **k: calls.append(("escalate", None)) or {**empty, "escalated": True},
                         fix_settings=lambda *a: rules)
    c = chat.Chat(ws)
    clash = SimpleNamespace(id="c1")
    monkeypatch.setattr(chat.Chat, "_report", lambda self, ctx: SimpleNamespace(id="r", clash=lambda cid: clash))
    monkeypatch.setattr(chat.Chat, "_scene", lambda self, ctx: "s")
    monkeypatch.setattr(chat.Chat, "_matches", lambda self, ctx: {"c1": {"a": "A", "b": "B"}})
    ctx = chat.Context("s", "r")

    out, summary, _ = c._run("propose_fixes", {"clash_id": "c1"}, ctx, lambda e: None, escalate_allowed=lambda: None)
    assert calls[-1][0] == "propose" and calls[-1][1] is not None
    assert "escalate true" in out["note"]
    out, summary, _ = c._run("propose_fixes", {"clash_id": "c1", "escalate": True}, ctx, lambda e: None,
                             escalate_allowed=lambda: "Second tries are switched off.")
    assert out == {"error": "Second tries are switched off."} and summary == "refused: no second try"
    out, _, _ = c._run("propose_fixes", {"clash_id": "c1", "escalate": True}, ctx, lambda e: None,
                       escalate_allowed=lambda: None)
    assert calls[-1][0] == "escalate" and "second try on Muse Wonder" in out["note"]
    rules["recommend"] = "L5 As-built: report only"   # nothing may be edited: refused before any cap is asked
    asked = []
    out, summary, _ = c._run("propose_fixes", {"clash_id": "c1", "escalate": True}, ctx, lambda e: None,
                             escalate_allowed=lambda: asked.append(1))
    assert "Nothing may be edited" in out["error"] and not asked and summary == "no second try: recommendation only"
    rules.clear()
    settings.update({"escalation": "off"})
    out, _, _ = c._run("propose_fixes", {"clash_id": "c1"}, ctx, lambda e: None)
    assert "escalate true" not in out["note"]


# ------------------------------------------------------------------------------------------------- after the review

def test_a_first_try_is_not_carried_once_an_edit_was_kept_or_the_rules_changed(tmp_path, monkeypatch):
    build_clash_fixture(tmp_path / "f.ifc")
    spark = Script({"candidates": [{"title": "Drop duct 800 mm", "move": "A", "delta_m": [0, 0, -0.8]}]},
                   {"candidates": [{"title": "Drop duct 800 mm", "move": "A", "delta_m": [0, 0, -0.8]}]})
    ws = Workspace(samples=tmp_path, model=spark, escalation_model=Script(), )
    sid = ws.open(["f.ifc"])
    duct, beam, _ = _ids(ws.scene(sid))
    first = ws.propose(sid, duct, beam)
    assert ws.last_try(sid, duct, beam) is not None

    plans.apply(ws, sid, [first["options"][0]])   # kept: the scene moves on a revision
    assert ws.last_try(sid, duct, beam) is None
    second = ws.escalate(sid, duct, beam)
    assert not second["options"]                  # "Drop duct 800 mm" is not offered again as verified

    ws.propose(sid, duct, beam)
    from sightline import requirements
    monkeypatch.setattr(requirements, "current_id", lambda: "other-rules")
    assert ws.last_try(sid, duct, beam) is None


def test_combined_steps_never_move_structure_or_anything_but_services_beside_a_and_b(tmp_path, monkeypatch):
    import ifcopenshell
    s = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    duct, beam, pipe = _ids(s)
    move_pipe = {"kind": "move", "move": pipe, "delta_m": [0, 0, -0.5]}
    move_duct = {"kind": "move", "move": "A", "delta_m": [0, 0, -0.4]}
    monkeypatch.setattr(agent, "is_service", lambda scene, gid: gid != pipe)   # the pipe as if it were a door
    with pytest.raises(agent.Refused, match="only services move"):
        agent.combined_steps(s, {"steps": [move_pipe, move_duct]}, duct, beam)
    old = ifcopenshell.file(schema="IFC2X3")
    for cls in ("IfcWallStandardCase", "IfcPile", "IfcBeam"):
        monkeypatch.setattr(s, "entity", lambda gid, e=old.create_entity(cls): e)
        assert agent.stays(s, pipe), cls


def test_a_combined_fix_kept_part_way_is_undone(tmp_path, monkeypatch):
    from sightline import edits
    build_clash_fixture(tmp_path / "f.ifc")
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["f.ifc"])
    s = ws.scene(sid)
    duct, beam, pipe = _ids(s)
    option = {"kind": "combined", "moved": [pipe, duct], "delta_m": [0, 0, -0.5], "title": "t",
              "edit": {"pair": [duct, beam], "steps": [
                  {"kind": "move", "target": pipe, "delta_m": [0, 0, -0.5]},
                  {"kind": "offset", "target": duct, "split_m": [2.0, 4.0], "delta_m": [0, 0, -0.4]}]}}

    def fails(*a, **k):
        raise edits.Unsupported("not here")
    monkeypatch.setattr(edits, "apply_offset", fails)
    revision = s.revision
    with pytest.raises(edits.Unsupported):
        plans.apply(ws, sid, [option])
    assert s.placement(pipe)[2, 3] == pytest.approx(2.25) and s.revision == revision   # the pipe's move undone


def test_the_apply_endpoint_returns_every_run_of_a_combined_fix(tmp_path, monkeypatch):
    from sightline.fixtures import build_run_fixture
    build_run_fixture(tmp_path / "run.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["run.ifc"]}).json()["id"]
    m = app_module.ws.scene(sid).model
    main = next(e for e in m.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    beam = m.by_type("IfcBeam")[0].GlobalId
    option = {"kind": "combined", "moved": [main], "delta_m": [0, 0, 0.4], "title": "t",
              "edit": {"pair": [main, beam], "steps": [
                  {"kind": "offset", "target": main, "split_m": [2.0, 4.0], "delta_m": [0, 0, 0.4]}]}}
    r = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": option}).json()
    assert len(r["groups"]) == 1 and r["groups"][0][0] == main and len(r["groups"][0]) == 9
    assert r["pieces"] == r["groups"][0]   # the split run's pieces, the original first


def test_an_automatic_second_try_that_fails_keeps_the_first(tmp_path):
    build_clash_fixture(tmp_path / "f.ifc")

    class Broken:
        def complete_json(self, *a, **k):
            raise RuntimeError("Muse Wonder failed")
    ws = Workspace(samples=tmp_path, model=Script(DROP_INTO_PIPE), escalation_model=Broken())
    sid = ws.open(["f.ifc"])
    duct, beam, _ = _ids(ws.scene(sid))
    settings.update({"escalation": "auto"})
    events = []
    out = ws.propose(sid, duct, beam, on_event=events.append, escalate_check=lambda: None)
    assert out["understanding"] == "The duct crosses the beam." and "second try failed" in out["note"]
    assert any(e.get("type") == "note" and "second try failed" in e["text"] for e in events)


def test_a_second_try_takes_both_caps_or_neither():
    from sightline.limits import ProposeLimit
    second, proposals = ProposeLimit(5, 0), ProposeLimit(1, 0)
    assert ProposeLimit.take_all("v", second, proposals) is None
    assert ProposeLimit.take_all("v", second, proposals)        # no proposal left this hour
    assert len(second._clients["v"]) == 1                        # and no second try was counted for it


def test_running_work_holds_its_estimate_and_any_wonder_version_is_priced(monkeypatch):
    monkeypatch.setenv("SIGHTLINE_WONDER_MAX_USD_DAY", "2")
    spend.charge(0.5)
    with spend.held(1.0):
        assert spend.refused(1.0)                  # 0.5 spent + 1.0 running + 1.0 asked > 2
        assert spend.refused(0.4) is None
    assert spend.refused(1.0) is None
    assert meta_client.cost("muse-wonder-1.1-preview", 1000, 1000) == pytest.approx(0.024)
    assert meta_client.cost("muse-spark-1.3-contributor", 1000, 1000) == 0


def test_a_spark_run_reports_no_usage_of_its_shared_client(tmp_path):
    s = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    duct, beam, _ = _ids(s)
    spark = meta_client.MetaChatModel(api_key="k", model="muse-spark-1.3-contributor")
    spark._count({"prompt_tokens": 5000, "completion_tokens": 100})   # another visitor's call
    spark.complete_json = lambda *a, **k: {"candidates": []}
    assert agent.resolve(s, agent.Clash(duct, beam), spark, max_rounds=1).usage is None
    wonder = meta_client.MetaChatModel(api_key="k", model="muse-wonder-1.0")
    wonder._count({"prompt_tokens": 5000, "completion_tokens": 100})   # before this run

    def reply(*a, **k):
        wonder._count({"prompt_tokens": 1000, "completion_tokens": 200})
        return {"candidates": []}
    wonder.complete_json = reply
    u = agent.resolve(s, agent.Clash(duct, beam), wonder, max_rounds=1).usage
    assert (u["calls"], u["input_tokens"], u["output_tokens"]) == (1, 1000, 200)


def test_a_request_claims_its_estimate_at_once_and_its_work_takes_the_claim_over(monkeypatch):
    import contextvars
    monkeypatch.setenv("SIGHTLINE_WONDER_MAX_USD_DAY", "2")
    spend.charge(0.5)

    def request(amount, then=None):
        """One request in its own context, as each HTTP request has: a claim, then (maybe) its work."""
        def run():
            why = spend.claim(amount)
            if why is None and then:
                then(amount)
            return why
        return contextvars.copy_context().run(run)

    assert request(1.0) is None                  # claimed and still held: its work hasn't run yet
    assert request(1.0)                          # 0.5 spent + 1.0 claimed + 1.0 > 2: refused at once
    spend.reset(); spend.charge(0.5)
    inside = []

    def work(amount):
        with spend.held(amount):                 # takes the claim over: not counted twice
            inside.append(spend.refused(0.4))
    assert request(1.0, work) is None and inside == [None]
    assert spend.refused(1.4) is None            # the claim ended with its work
    ctx = contextvars.copy_context()
    assert ctx.run(spend.claim, 1.0) is None
    ctx.run(spend.unclaim, 1.0)                  # a cap refused it after the budget let it through
    assert spend.refused(1.4) is None
