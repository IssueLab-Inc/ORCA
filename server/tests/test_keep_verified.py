"""Keeping a fix never trusts the option the page sends: it is tried again as its proposal tried it, with the clearance
and requirements of its clash, on the model as it is now, and kept all or nothing (plans.apply, docs/architecture/07)."""
import pytest
from fastapi.testclient import TestClient

from sightline import edits, plans
from sightline import app as app_module
from sightline import requirements as req
from sightline.fixtures import build_joint_fixture, build_run_fixture
from sightline.service import Workspace


class Scripted:
    """Stands in for Muse Spark: the same reply every round."""

    def __init__(self, reply):
        self.reply = reply

    def complete_json(self, system, text, images=None):
        return self.reply


OFFSET = {"title": "Offset up 400", "kind": "offset", "move": "A", "split_m": [2.6, 3.4], "dz_m": 0.4}


@pytest.fixture
def run(tmp_path, monkeypatch):
    """The run fixture behind the API: the supply main (centre z 2.8, 300 deep) through a beam (z 2.6-3.0) under a
    slab (soffit 3.4). An offset up 400 mm leaves 50 mm both sides; a drop of 400 mm leaves 50 mm under the beam."""
    build_run_fixture(tmp_path / "run.ifc")
    build_joint_fixture(tmp_path / "joint.ifc")
    ws = Workspace(samples=tmp_path, model=Scripted({"candidates": [OFFSET]}))
    monkeypatch.setattr(app_module, "ws", ws)
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["run.ifc"]}).json()["id"]
    s = ws.scene(sid)
    main = next(e for e in s.model.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    return c, ws, sid, s, main, s.model.by_type("IfcBeam")[0].GlobalId, s.model.by_type("IfcSlab")[0].GlobalId


def move(moved, dz, pair, **more):
    return {"title": f"Move {dz * 1000:+.0f} mm", "kind": "move", "moved": [moved], "delta_m": [0, 0, dz],
            "pair": pair, **more}


def unchanged(s, main):
    """Nothing kept: no revision, no file marked for export, the main where it was (its underside at z 2.65)."""
    return s.revision == 0 and not s._edited and s.bounds()[main][0][2] == pytest.approx(2.65, abs=1e-4)


def test_a_proposal_says_which_clash_its_options_were_verified_for(run):
    c, ws, sid, s, main, beam, _ = run
    o = ws.propose(sid, main, beam)["options"][0]
    assert o["pair"] == [main, beam] and o["others"] == []
    r = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": {**o, "preview": None, "before": None}})
    assert r.status_code == 200, r.text
    assert len(r.json()["pieces"]) == 9 and r.json()["verified"][0]["min_clearance_m"] == pytest.approx(0.05, abs=0.002)


def test_a_tampered_move_that_would_clash_is_refused_and_nothing_is_kept(run):
    c, ws, sid, s, main, beam, _ = run
    for option in (move(main, -0.2, [main, beam]),        # still 150 mm into the beam
                   move(main, 0.6, [main, beam])):        # up through the slab
        r = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": option})
        assert r.status_code == 409, r.text
        assert "does not pass ORCA's check" in r.json()["detail"] and "collision with" in r.json()["detail"]
        assert unchanged(s, main)
    # The old move route is tried again the same way.
    r = c.post(f"/api/scenes/{sid}/apply", json={"moved": [main], "delta_m": [0, 0, -0.2], "obstacles": [beam]})
    assert r.status_code == 409 and unchanged(s, main)


def test_a_tampered_offset_is_refused_whatever_split_or_height_it_claims(run):
    c, ws, sid, s, main, beam, _ = run
    good = {"title": "Offset", "kind": "offset", "moved": [main], "delta_m": [0, 0, 0.4], "split_m": [2.6, 3.4],
            "pair": [main, beam]}
    for bad in ({**good, "split_m": [0.5, 1.5]},      # raised away from the beam: its end piece still runs through it
                {**good, "delta_m": [0, 0, 0.6]},     # into the slab
                {**good, "delta_m": [0, 0, 0.1]}):    # not high enough to clear the beam
        r = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": bad})
        assert r.status_code == 409, (bad, r.text)
        assert unchanged(s, main)
    r = c.post(f"/api/scenes/{sid}/offset/apply", json={"element": main, "other": beam, "split_m": [0.5, 1.5], "dz_m": 0.4})
    assert r.status_code == 409 and unchanged(s, main)
    assert c.post(f"/api/scenes/{sid}/fix/apply", json={"option": good}).status_code == 200


def test_an_option_proposed_before_the_model_changed_is_refused(run):
    c, ws, sid, s, main, beam, slab = run
    o = ws.propose(sid, main, beam)["options"][0]   # up 400 mm: 50 mm under the slab
    # Another fix is kept first: the slab comes down 100 mm (clear of the duct and the beam as they are).
    lowered = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": move(slab, -0.1, [slab, main])})
    assert lowered.status_code == 200, lowered.text
    r = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": {**o, "preview": None, "before": None}})
    assert r.status_code == 409
    assert "collision with IfcSlab" in r.json()["detail"] and "changed since it was proposed" in r.json()["detail"]
    assert s.revision == 1 and s.history == [(1, [0])]   # only the slab's move


def test_the_clearance_and_limits_are_the_requirements_not_the_page(run, monkeypatch):
    c, ws, sid, s, main, beam, _ = run
    near = move(main, -0.38, [main, beam])   # 30 mm under the beam: enough without requirements
    strict = req.register(req.parse({**req.default_doc(s).to_dict(), "strictness": "strict"}))      # 40 mm
    exacting = req.register(req.parse({**req.default_doc(s).to_dict(), "strictness": "exacting"}))  # 300 mm at most
    report_only = req.register(req.parse({**req.default_doc(s).to_dict(), "level": 5}))

    r = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": near}, headers={req.HEADER: strict})
    assert r.status_code == 409 and "clearance with IfcBeam (+30 mm)" in r.json()["detail"] and unchanged(s, main)
    r = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": move(main, -0.4, [main, beam])},
               headers={req.HEADER: exacting})
    assert r.status_code == 409 and "more than the 300 mm" in r.json()["detail"] and unchanged(s, main)
    r = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": move(main, -0.4, [main, beam])},
               headers={req.HEADER: report_only})
    assert r.status_code == 409 and "nothing may be edited here" in r.json()["detail"] and unchanged(s, main)
    assert c.post(f"/api/scenes/{sid}/fix/apply", json={"option": near}).status_code == 200


def test_a_plan_is_kept_all_or_nothing(run, monkeypatch):
    c, ws, sid, s, main, beam, slab = run
    offset = {"title": "Offset", "kind": "offset", "moved": [main], "delta_m": [0, 0, 0.4], "split_m": [2.6, 3.4],
              "pair": [main, beam]}
    lower_slab = move(slab, -0.1, [slab, main])
    # Each passes alone; together the raised middle runs into the lowered slab: neither is kept.
    r = c.post(f"/api/scenes/{sid}/plan/apply", json={"options": [offset, lower_slab]})
    assert r.status_code == 409 and "of 2" in r.json()["detail"] and "other fixes in place" in r.json()["detail"]
    assert unchanged(s, main) and s.placement(slab)[2, 3] == pytest.approx(3.4)
    # A later option that does not pass alone stops the plan before anything is kept.
    r = c.post(f"/api/scenes/{sid}/plan/apply", json={"options": [lower_slab, move(main, -0.2, [main, beam])]})
    assert r.status_code == 409 and "Fix 2 of 2" in r.json()["detail"]
    assert unchanged(s, main) and s.placement(slab)[2, 3] == pytest.approx(3.4)
    # One refused while being kept (after both passed their checks) undoes the one kept before it.
    real, calls = plans.KEEP["move"], []

    def refused_second(ws_, scene_id, o):
        calls.append(o["moved"])
        if len(calls) > 1:
            raise edits.Unsupported("refused part way")
        return real(ws_, scene_id, o)
    monkeypatch.setitem(plans.KEEP, "move", refused_second)
    with pytest.raises(edits.Unsupported):
        plans.apply(ws, sid, [move(main, -0.4, [main, beam]), move(slab, 0.1, [slab, main])])
    assert len(calls) == 2 and unchanged(s, main) and s.placement(slab)[2, 3] == pytest.approx(3.4)
    monkeypatch.setitem(plans.KEEP, "move", real)
    kept = plans.apply(ws, sid, [lower_slab, move(main, -0.4, [main, beam])])
    assert s.revision == 2 and s.placement(slab)[2, 3] == pytest.approx(3.3) and len(kept["verified"]) == 2


def test_the_server_keeps_what_it_checked_not_what_the_page_says(run):
    c, ws, sid, s, main, beam, _ = run
    kept = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": move(main, -0.4, [main, beam])}).json()
    assert set(kept["changed"]) == set(s.connected_run(main)) and len(kept["changed"]) == 2   # the whole run, not one segment
    jid = c.post("/api/scenes", json={"samples": ["joint.ifc"]}).json()["id"]
    j = ws.scene(jid)
    transom, mullion = (next(e.GlobalId for e in j.model.by_type("IfcMember") if e.Name.startswith(n))
                        for n in ("Transom", "Mullion"))
    trim = {"element": transom, "other": mullion, "by_m": 0.06}
    r = c.post(f"/api/scenes/{jid}/trim/apply", json={**trim, "end": "start"})
    assert r.status_code == 409 and "the joint is at the 'end' end" in r.json()["detail"] and j.revision == 0
    assert c.post(f"/api/scenes/{jid}/trim/apply", json={**trim, "end": "end"}).status_code == 200


def test_a_fix_must_say_which_clash_it_is_for(run):
    c, ws, sid, s, main, beam, slab = run
    option = move(main, -0.4, [main, beam])
    for bad, code in (({**option, "pair": None}, 400), ({**option, "pair": [slab, beam]}, 400),   # main is in neither
                      ({**option, "pair": [main, "0000000000000000000000"]}, 400)):
        r = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": bad})
        assert r.status_code == code, (bad, r.text)
    assert c.post(f"/api/scenes/{sid}/apply", json={"moved": [main], "delta_m": [0, 0, -0.4]}).status_code == 422
    assert c.post(f"/api/scenes/{sid}/offset/apply",
                  json={"element": main, "split_m": [2.6, 3.4], "dz_m": 0.4}).status_code == 422
    assert c.post(f"/api/scenes/{sid}/trim/apply", json={"element": main, "end": "end", "by_m": 0.1}).status_code == 422
    assert unchanged(s, main)


def test_kept_files_restores_marks_and_revision_and_leaves_a_held_file_to_the_outer_one(run):
    c, ws, sid, s, main, beam, _ = run
    with pytest.raises(RuntimeError):
        with edits.kept_files(s, {0}):
            s.translate([main], (0, 0, -0.4))
            with edits.kept_files(s, {0}):   # file 0 is held: the inner one neither begins nor ends a transaction
                assert s.models[0].transaction is not None
                s.mark_edited(main)
                s.bump([0])
            raise RuntimeError("later")
    assert unchanged(s, main) and s.history == [] and s.models[0].transaction is None
