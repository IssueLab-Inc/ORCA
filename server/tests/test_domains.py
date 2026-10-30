"""The domain follows the work (domains.py): a scene opened from STEP is a machine cell, read by the machines pack and
a mechanical integration engineer; anything else is a building, whose prompts are exactly what they were."""
from types import SimpleNamespace

import pytest

from sightline import domains, triage
from sightline.chat import Chat, Context
from sightline.fixtures import build_clash_fixture
from sightline.reports import ReportClash, ReportElement
from sightline.service import Workspace
from tests.test_step import write_step

SHARED = ("chat", "triage", "report", "report_summary", "patterns", "root_cause")


class Recorder:
    """Muse Spark's stand-in: records each system prompt, proposes nothing (and answers the chat at once)."""

    def __init__(self):
        self.systems = []

    def complete_json(self, system, text, images=None, **kw):
        self.systems.append(system)
        return {"understanding": "", "candidates": [], "advice": ""}

    def chat(self, messages, tools):
        self.systems.append(messages[0]["content"])
        return {"role": "assistant", "content": "ok"}


@pytest.fixture()
def ws(tmp_path):
    write_step(tmp_path / "Test-cell.step")
    build_clash_fixture(tmp_path / "f.ifc")
    return Workspace(samples=tmp_path, model=Recorder())


def test_a_scene_from_step_is_machines_and_anything_else_construction(ws):
    assert domains.of(ws, ws.open(["Test-cell.step"])) == "machines"
    assert domains.of(ws, ws.open(["f.ifc"])) == "construction"
    assert domains.of(ws, ws.open(["f.ifc", "Test-cell.step"])) == "construction"   # a machine in a building: not yet
    assert domains.of(ws, None) == domains.of(ws, "gone") == "construction"
    assert domains.of(SimpleNamespace(), "s") == "construction"   # a stand-in workspace (tests)


def _pair(ws, sid, a_name, b_name):
    s = ws.scene(sid)
    by = {s.entity(g).Name: g for g in s.bounds()}
    return by[a_name], by[b_name]


def test_a_proposal_reads_the_pack_of_its_scene(ws):
    cell = ws.open(["Test-cell.step"])
    ladder, post = _pair(ws, cell, "Ladder run 1", "Post P1")
    ws.propose(cell, ladder, post)
    assert ws.model.systems[0] == (domains.PACKS / "machines.md").read_text()

    building = ws.open(["f.ifc"])
    s = ws.scene(building)
    duct, beam = s.model.by_type("IfcDuctSegment")[0].GlobalId, s.model.by_type("IfcBeam")[0].GlobalId
    ws.model.systems.clear()
    ws.propose(building, duct, beam)
    assert ws.model.systems[0] == (domains.PACKS / "construction.md").read_text()


def test_the_chat_speaks_as_the_open_scenes_domain(ws):
    chat = Chat(ws, ws.model)
    session = chat.session(None)
    chat.turn(session, "hi", Context(ws.open(["Test-cell.step"])), lambda e: None)
    chat.turn(session, "hi", Context(ws.open(["f.ifc"])), lambda e: None)
    assert ws.model.systems == [domains.prompt("chat", "machines"), domains.prompt("chat")]


def test_triage_takes_the_domain_it_is_given(tmp_path):
    model = Recorder()
    e = lambda name, cls: ReportElement(f"g{name}", cls, name, "Level 01", "Cell.ifc")
    c = ReportClash("c1", "Air pipe × Rail", "c1", "Cell (within)", "hard", 0.001, "new", -0.1, None, None,
                    e("Rail", "IfcMember"), e("Air pipe", "IfcPipeSegment"))
    triage.triage_one(model, c, images=False, domain="machines")
    triage.triage_one(model, c, images=False)
    assert model.systems == [domains.prompt("triage", "machines"), domains.prompt("triage")]


@pytest.mark.parametrize("name", SHARED)
def test_shared_prompts_say_who_orca_is_by_domain_and_nothing_else_differs(name):
    raw = (domains.PACKS / f"{name}.md").read_text()
    assert raw.count("{role}") == 1 and "BIM coordinator" not in raw
    building, cell = domains.prompt(name), domains.prompt(name, "machines")
    # A building's prompt is the file with the role it always had: byte for byte what Northbank was read with.
    assert building == raw.replace("{role}", "a senior BIM coordinator")
    assert building.startswith("You are ORCA, a senior BIM coordinator")
    assert cell == raw.replace("{role}", domains.ROLES["machines"])
    assert "BIM" not in cell and "mechanical integration engineer" in cell


def test_the_machines_pack_keeps_the_contract_and_claims_only_static_geometry():
    building = (domains.PACKS / "construction.md").read_text()
    cell = (domains.PACKS / "machines.md").read_text()
    # The fix kinds and the JSON Muse returns are the construction pack's, word for word: parsing is unchanged.
    tail = building[building.index("Six kinds of fix:"):]
    assert cell.endswith(tail)
    assert "BIM" not in cell and "mechanical integration engineer" in cell
    assert "static geometry only" in cell and "does not simulate robot motion" in cell
    for word in ("guarding", "fencing", "conveyor", "pallet", "robot base", "cable chain", "pneumatic",
                 "maintenance access"):
        assert word in cell.lower(), word
