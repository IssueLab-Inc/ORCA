"""The domain follows the work (domains.py): a scene opened from STEP is a machine cell, read by the machines pack and
a mechanical integration engineer; anything else is a building, whose prompts are exactly what they were."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from sightline import domains, triage
from sightline.chat import Chat, Context
from sightline.fixtures import build_clash_fixture
from sightline.reports import Report, ReportClash, ReportElement
from sightline.service import Workspace
from tests.test_step import write_step

SHARED = ("chat", "triage", "report", "report_summary", "patterns", "root_cause")


class Recorder:
    """Muse Spark's stand-in: records each system prompt, proposes nothing (and answers the chat at once)."""

    def __init__(self):
        self.systems = []
        self.schemas = []

    def complete_json(self, system, text, images=None, **kw):
        self.systems.append(system)
        self.schemas.append(kw.get("schema"))
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
    triage.triage_one(model, c, images=False, teams=["Mechanical", "Controls"])
    assert model.systems == [domains.prompt("triage", "machines"), domains.prompt("triage"),
                             domains.prompt("triage", teams="Mechanical, Controls")]
    assert '"responsible" (the team that should act, or "none")' in model.systems[0]
    assert '"responsible" (the team that should act (Mechanical, Controls), or "none")' in model.systems[2]
    assert model.schemas[2]["properties"]["responsible"]["enum"] == ["Mechanical", "Controls", "none"]
    assert "enum" not in model.schemas[0]["properties"]["responsible"]


@pytest.mark.parametrize("name", SHARED)
def test_shared_prompts_say_who_orca_is_by_domain_and_nothing_else_differs(name):
    raw = (domains.PACKS / f"{name}.md").read_text().replace(" ({teams})", "")  # no teams named: the clause goes
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


def test_titles_and_the_rule_audit_speak_for_the_domain():
    assert "for a BIM coordination meeting" in domains.prompt("titles")
    cell = domains.prompt("titles", "machines")
    assert "for a machine cell design review" in cell and "BIM" not in cell.split(".")[0]
    assert domains.fill(triage.AUDIT).startswith("You are ORCA, a senior BIM coordinator checking one rule")
    assert domains.fill(triage.AUDIT, "machines").startswith(f"You are ORCA, {domains.ROLES['machines']} checking")


def test_team_names_are_guessed_never_fixed():
    from collections import Counter
    from sightline import document
    ducts = Counter({"IfcDuctSegment": 40, "IfcBeam": 2})
    assert document.guess_team(ducts, "Tower-Services.ifc") == "MEP"
    # Nothing to go on, or a machine cell: the model's own name, for the user to retype.
    assert document.guess_team(Counter(), "Tower-Grids.ifc") == "Tower-Grids"
    assert document.guess_team(ducts, "PC-03-Cell-RevA.ifc", "machines") == "PC-03-Cell-RevA"


def test_the_report_uses_the_typed_team_names():
    from sightline import document
    e = lambda name, cls, f: ReportElement(f"g{name}", cls, name, "Level 01", f)
    c = ReportClash("c1", "Duct × Beam", "c1", "MEP vs Structure", "hard", 0.001, "new", -0.1, None, None,
                    e("Duct", "IfcDuctSegment", "B-MEP.ifc"), e("Beam", "IfcBeam", "B-Str.ifc"))
    report = Report("r", "R", Path("."), [], [c], origin="sightline")
    guesses = {"B-MEP.ifc": "MEP", "B-Str.ifc": "Structure"}
    typed = {"B-MEP.ifc": "Acme Mechanical", "B-Str.ifc": "Frame Engineers"}
    [page] = document.build_rows(report, {"c1": {"verdict": "real_clash", "responsible": "Structure"}}, typed, None,
                                 None, {}, {}, {}, guesses)
    assert (page.team_a, page.team_b) == ("Acme Mechanical", "Frame Engineers")
    # Triage named the guessed discipline; the report names the team typed for it.
    assert page.acting == "Frame Engineers" and page.reviewers == ["Acme Mechanical", "Frame Engineers"]
    # No reading: the guessed disciplines still rank who keeps their element (structure stays, services move).
    [row] = document.build_rows(report, {}, typed, None, None, {}, {}, {}, guesses)
    assert row.acting == "Acme Mechanical"
    model = Recorder()
    document.explain(model, [page], lambda e: None)
    assert "design teams (Acme Mechanical, Frame Engineers) who" in model.systems[0]
