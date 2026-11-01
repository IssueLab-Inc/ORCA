"""Muse and hand edits (chat.py, docs/manual-edits.md): it checks and the page previews; only the person's own words
keep an edit or undo one, and an edit that makes clashes needs them to say so. Voice is chat with words spoken."""
import json

import pytest

from sightline import chat as chat_module
from sightline.chat import Chat, Context, consents
from sightline.fixtures import build_edit_fixture
from sightline.service import Workspace


class Scripted:
    def __init__(self, steps):
        self.steps, self.seen = list(steps), []

    def chat(self, messages, tools):
        self.seen.append(messages[-1])
        step = self.steps.pop(0)
        if isinstance(step, str):
            return {"role": "assistant", "content": step}
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(step)]}


@pytest.fixture
def setup(tmp_path):
    build_edit_fixture(tmp_path / "edit.ifc")
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["edit.ifc"])
    ids = {e.Name: e.GlobalId for e in ws.scene(sid).models[0].by_type("IfcElement") if e.Name}
    return ws, sid, ids


def test_only_the_persons_own_words_keep_or_undo():
    for yes in ("keep it", "Yes", "apply it please", "do it", "ok keep that", "go ahead and keep it, no problem"):
        assert consents(yes), yes
    for no in ("don't keep it", "what would that hit?", "no, wait", "cancel that", "make it longer", "looks good"):
        assert not consents(no), no
    assert consents("undo that", undo=True) and consents("take it back", undo=True) and not consents("keep it", undo=True)


def test_muse_checks_the_page_previews_and_only_keep_it_keeps(setup):
    ws, sid, g = setup
    op = {"op": "push_pull", "element": "selected", "face": "east end", "by_m": 0.2}
    model = Scripted([[("list_faces", {"element": "selected"}), ("edit_check", {"op": op})], "It clears everything.",
                      [("edit_keep", {})], "I'll wait.", [("edit_keep", {})], "Kept."])
    events = []
    c = Chat(ws, model)
    s = c.session(None)
    ctx = Context(sid, selected={"element": g["W1"], "face": "east end"})
    c.turn(s, "make this wall 200 mm longer at the east end", ctx, events.append)
    assert "the user has element wall 'W1' selected" in model.seen[0]["content"]
    preview = next(e for e in events if e.get("action") == "edit_preview")
    assert preview["check"]["passed"] and preview["check"]["preview"]
    assert ws.scene(sid).bounds()[g["W1"]][1][0] == pytest.approx(4.0)   # nothing kept by a check
    c.turn(s, "looks fine to me", ctx, events.append)                     # not the person's word to keep
    assert not ws.journal(sid).entries
    tool = json.loads(next(m["content"] for m in s.messages if m["role"] == "tool" and "only the user" in m["content"]))
    assert "keep it" in tool["error"]
    c.turn(s, "keep it", ctx, events.append)
    (e,) = ws.journal(sid).entries
    assert e.source == "muse" and ws.scene(sid).bounds()[g["W1"]][1][0] == pytest.approx(4.2)
    kept = next(x for x in events if x.get("action") == "edit_kept")["kept"]
    assert kept["revision"] == 1 and [m["global_id"] for m in kept["meshes"]] == [g["W1"]]


def test_an_edit_with_clashes_needs_them_said_and_undo_needs_undo(setup):
    ws, sid, g = setup
    op = {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 1.2}
    model = Scripted([[("edit_check", {"op": op})], "It hits column C1.", [("edit_keep", {"accept_clashes": 1})], "Say so.",
                      [("edit_keep", {"accept_clashes": 1})], "Kept with the clash.", [("undo_edit", {})], "No.",
                      [("undo_edit", {})], "Undone.", [("list_edits", {})], "One edit, undone."])
    events = []
    c = Chat(ws, model)
    s = c.session(None)
    ctx = Context(sid)
    c.turn(s, "push the east end 1.2 m", ctx, events.append)
    c.turn(s, "keep it", ctx, events.append)
    assert not ws.journal(sid).entries                      # it makes a clash: "keep it" alone is not enough
    c.turn(s, "keep it with the clash", ctx, events.append)
    assert len(ws.journal(sid).kept()) == 1 and ws.journal(sid).entries[0].check["accepted_clashes"] == 1
    c.turn(s, "hmm", ctx, events.append)
    assert len(ws.journal(sid).kept()) == 1
    c.turn(s, "undo that", ctx, events.append)
    assert not ws.journal(sid).kept()
    assert next(x for x in events if x.get("action") == "edit_stepped")["step"]["entry"]["state"] == "undone"
    c.turn(s, "what did we change?", ctx, events.append)
    assert "edits kept so far" in model.seen[-1]["content"] or "E1" in json.dumps(s.messages[-2])


def test_proposals_hear_about_edits_already_made(setup):
    ws, sid, g = setup
    from sightline import manual
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 0.3})
    clash = ws.clash_for(g["W1"], g["C1"], scene_id=sid)
    assert "Edits already made to these elements" in clash.notes and "east end of wall 'W1' pushed 300 mm out" in clash.notes
    assert ws.clash_for(g["P1"], g["S1"], scene_id=sid).notes == ""


def test_the_face_chosen_in_the_edit_tool_reaches_muse_as_its_pick(setup):
    ws, sid, g = setup
    pick = {"point": [1.0, 2.495, 2.7], "normal": [0.0, -1.0, 0.0]}   # the beam's web: only a pick places it
    ctx = Context(sid, selected={"element": g["B1"], "face": "south side 2", "pick": pick})
    op = {"op": "align", "element": "selected", "face": "selected", "to": {"element": g["P1"], "face": "round side"}, "how": "move"}
    model = Scripted([[("edit_check", {"op": op})], "Checked."])
    events = []
    c = Chat(ws, model)
    c.turn(c.session(None), "move this face down to the pipe", ctx, events.append)
    check = next(e for e in events if e.get("action") == "edit_preview")["check"]
    assert check["blocked"] is None and check["op"]["face"] == pick
    assert Chat._chosen_face(ctx, g["B1"], "south side 2") == pick and Chat._chosen_face(ctx, g["P1"], "selected") == "selected"


def test_an_open_joint_is_kept_from_chat_only_when_the_person_says_joint(tmp_path):
    from sightline.fixtures import build_run_fixture
    build_run_fixture(tmp_path / "run.ifc")
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["run.ifc"])
    main = next(e for e in ws.scene(sid).model.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    op = {"op": "push_pull", "element": main, "face": "east end", "by_m": -0.2, "alone": True}
    model = Scripted([[("edit_check", {"op": op})], "It leaves the joint open.", [("edit_keep", {})], "Say so.",
                      [("edit_keep", {})], "Kept."])
    c = Chat(ws, model)
    s = c.session(None)
    ctx = Context(sid)
    c.turn(s, "shorten the main's east end by 200 mm on its own", ctx, lambda e: None)
    c.turn(s, "keep it", ctx, lambda e: None)
    assert not ws.journal(sid).entries
    assert any("joint(s) open" in m["content"] for m in s.messages if m["role"] == "tool")
    c.turn(s, "yes keep it with the open joint", ctx, lambda e: None)
    (e,) = ws.journal(sid).entries
    assert e.source == "muse" and e.check["open_joints"]
