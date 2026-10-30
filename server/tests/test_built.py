"""Show it built (docs/show-it-built.md): the passes, the pixel gate, the judges, retries, the cache and the API."""
import base64
import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sightline import app as app_module, built, settings, spend
from sightline.fixtures import build_clash_fixture
from sightline.service import Workspace

N = 512


def _png(a: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(a.astype(np.uint8)).save(buf, "PNG")
    return buf.getvalue()


def _url(b: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(b).decode()


def scene(boxes=((100, 300, 100, 400, (180, 90, 60)), (250, 450, 300, 480, (60, 120, 200)))):
    """A small rendered scene: ids, normals and a shaded look of a few boxes on ORCA's blue-grey background."""
    ids = np.zeros((N, N, 3), np.uint8)
    normals = np.zeros((N, N, 3), np.uint8)
    look = np.zeros((N, N, 3), np.uint8)
    look[:] = (223, 230, 238)
    for k, (y0, y1, x0, x1, colour) in enumerate(boxes, 1):
        ids[y0:y1, x0:x1] = (k, 0, 0)
        normals[y0:y1, x0:x1] = (128, 128, 255) if k % 2 else (255, 128, 128)
        shade = np.linspace(0.8, 1.0, x1 - x0)[None, :, None]
        look[y0:y1, x0:x1] = (np.array(colour)[None, None, :] * shade).astype(np.uint8)
    return _png(look), _png(ids), _png(normals), look


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(built, "CACHE", tmp_path / "built")
    spend.reset()
    yield
    spend.reset()


class Judge:
    def __init__(self, verdict="faithful", differences=()):
        self.verdict, self.differences, self.calls = verdict, list(differences), 0

    def complete_json(self, system, text, images, schema):
        self.calls += 1
        assert len(images) == 3 and "Image 3" in system   # the look, the picture and the ids picture
        return {"model_view_objects": ["box"], "differences": self.differences, "verdict": self.verdict}


def test_the_passes_give_an_outline_an_ids_picture_and_a_stable_key():
    look, ids, normals, _ = scene()
    p = built.passes(_url(look), _url(ids), _url(normals))
    assert p.lines[100:300, 99:101].any() and p.lines[249:252, 299:302].any() and not p.lines[20, 20]
    colours = np.asarray(Image.open(io.BytesIO(built.ids_picture(p.ids))).convert("RGB"))
    assert tuple(colours[5, 5]) == (255, 255, 255) and tuple(colours[150, 150]) != tuple(colours[400, 450])
    assert p.key == built.passes(look, ids, normals).key
    other = built.passes(scene(((90, 300, 100, 400, (180, 90, 60)),))[0], ids, normals)
    assert other.key != p.key
    with pytest.raises(built.Refused):
        built.passes(_url(b"not a png"), ids, normals)
    with pytest.raises(built.Refused):
        built.passes(_png(np.zeros((300, 400, 3))), ids, normals)


def test_the_gate_passes_a_restyle_and_rejects_an_added_object_or_another_scene():
    look, ids, normals, arr = scene()
    p = built.passes(look, ids, normals)
    restyled = np.clip(arr.astype(int) + np.random.default_rng(1).integers(-6, 6, arr.shape), 0, 255).astype(np.uint8)
    assert built.gate(restyled, p)["passed"]
    added = arr.copy()
    added[0:96, :] = (200, 200, 200)              # an invented ceiling grid where the model has nothing (S0's cw)
    for k in range(0, N, 32):
        added[0:96, k:k + 3] = (90, 90, 90)
    for k in range(0, 96, 32):
        added[k:k + 3, :] = (90, 90, 90)
    g = built.gate(added, p)
    assert not g["passed"] and g["tile"] > built.TILE_MAX
    _, _, _, elsewhere = scene(((20, 120, 20, 120, (90, 160, 90)), (350, 500, 30, 200, (200, 200, 60))))
    assert not built.gate(elsewhere, p)["passed"]


def test_a_picture_both_judges_pass_is_kept_and_cached():
    look, ids, normals, arr = scene()
    p = built.passes(look, ids, normals)
    drawn, judges, events = [], [], []

    def restyle(look_png, lines_png, extra=""):
        drawn.append(extra)
        return _png(arr)

    def judge_model():
        judges.append(Judge())
        return judges[-1]
    out = built.make(p, events.append, restyle_fn=restyle, judge_model_fn=judge_model)

    assert out["status"] == "done" and out["image_url"] == f"/api/built/{p.key}.jpg"
    assert (built.CACHE / f"{p.key}.jpg").exists() and built.path_of(f"{p.key}-lines.png")
    assert len(drawn) == built.PICTURES and len(judges) >= built.JUDGES
    assert [e["type"] for e in events][:1] == ["drawing"] and any(e["type"] == "judged" for e in events)
    again = built.make(p, restyle_fn=lambda *a, **k: pytest.fail("drawn again"), judge_model_fn=judge_model)
    assert again["cached"] and again["key"] == p.key
    assert built.path_of("../etc/passwd") is None and built.path_of("x.jpg") is None


def test_a_judge_that_finds_a_change_sends_it_back_then_the_request_fails():
    look, ids, normals, arr = scene()
    p = built.passes(look, ids, normals)
    extras, events = [], []

    def restyle(look_png, lines_png, extra=""):
        extras.append(extra)
        return _png(arr)
    out = built.make(p, events.append, restyle_fn=restyle, judge_model_fn=lambda: Judge(
        "unfaithful", [{"kind": "added", "what": "a vertical pipe", "where": "centre", "size": "medium"}]))

    assert out["status"] == "failed" and "a vertical pipe" in out["why"]
    assert any(e["type"] == "retry" and "a vertical pipe" in e["why"] for e in events)
    assert extras[:2] == ["", ""] and "a vertical pipe" in extras[-1]   # the second pair is told
    assert not (built.CACHE / f"{p.key}.jpg").exists()


def test_a_picture_off_the_model_never_reaches_the_judges():
    look, ids, normals, _ = scene()
    p = built.passes(look, ids, normals)
    _, _, _, elsewhere = scene(((20, 120, 20, 120, (90, 160, 90)),))
    out = built.make(p, restyle_fn=lambda *a, **k: _png(elsewhere),
                     judge_model_fn=lambda: pytest.fail("judged a picture the gate rejected"))
    assert out["status"] == "failed" and out["tried"] == built.PICTURES * built.ROUNDS


def test_the_api_follows_the_switch_the_kind_and_the_caps(tmp_path, monkeypatch):
    build_clash_fixture(tmp_path / "f.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    monkeypatch.setattr(app_module, "built_limit", app_module.ProposeLimit(1, 0, noun="built views"))
    calls = []
    monkeypatch.setattr(built, "make", lambda p, emit, **kw: calls.append((p.key, kw.get("judged_by"))) or
                        {"status": "done", "key": p.key, "judge": kw.get("judged_by", "Muse Wonder")})
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["f.ifc"]}).json()["id"]
    look, ids, normals, _ = scene()
    body = {"look": _url(look), "ids": _url(ids), "normals": _url(normals), "fix_kind": "offset"}

    assert c.get("/api/models").json()["built_views"] is False
    assert c.post(f"/api/scenes/{sid}/built/stream", json=body).status_code == 403
    settings.update({"built_views": True})
    assert c.get("/api/models").json()["built_views"] is True
    assert c.post(f"/api/scenes/{sid}/built/stream", json={**body, "fix_kind": "trim"}).status_code == 422
    assert c.post(f"/api/scenes/{sid}/built/stream", json={**body, "look": "data:image/png;base64,AAAA"}).status_code == 422
    lines = [json.loads(x) for x in c.post(f"/api/scenes/{sid}/built/stream", json=body).text.splitlines()]
    assert lines[-1]["type"] == "result" and lines[-1]["status"] == "done" and calls == [(calls[0][0], None)]
    assert c.post(f"/api/scenes/{sid}/built/stream", json=body).status_code == 429   # one an hour here
    # The day's Muse Wonder budget nearly spent: the pictures still come, checked by Muse Spark's three judges.
    monkeypatch.setattr(app_module, "built_limit", app_module.ProposeLimit(5, 0, noun="built views"))
    monkeypatch.setenv("SIGHTLINE_WONDER_MAX_USD_DAY", "1")
    spend.charge(0.9)
    lines = [json.loads(x) for x in c.post(f"/api/scenes/{sid}/built/stream", json=body).text.splitlines()]
    assert lines[-1]["judge"] == "Muse Spark" and calls[-1][1] == "Muse Spark"
    spend.charge(0.1)   # and nothing at all once the pictures don't fit either
    assert c.post(f"/api/scenes/{sid}/built/stream", json=body).status_code == 429
    assert c.get("/api/built/nothing.jpg").status_code == 404
    classes = c.get(f"/api/scenes/{sid}/classes").json()
    assert sorted({c for c, _ in classes.values()}) == ["IfcBeam", "IfcDuctSegment", "IfcPipeSegment"]
    assert "UB 406x178 beam" in {n for _, n in classes.values()}


def test_built_views_setting_validates_and_the_owner_wins():
    from sightline import owner
    with pytest.raises(ValueError):
        settings.update({"built_views": "yes"})
    settings.update({"built_views": True})
    assert settings.built_views() is True
    tokens = owner.enter(True, json.dumps({"built_views": False}))
    try:
        assert settings.built_views() is False
    finally:
        owner.leave(tokens)


def test_the_pdf_takes_a_built_view_by_its_url_and_nothing_else():
    from sightline import document
    look, ids, normals, arr = scene()
    p = built.passes(look, ids, normals)
    out = built._keep(p.key, arr, b"lines", {"f": 0.8, "tile": 0.1, "passed": True}, [], 2, 30.0)
    assert document._built_img({"built_img": out["image_url"]}).startswith("data:image/jpeg;base64,")
    for bad in ("/api/built/../../etc/passwd", "file:///etc/passwd", "/api/built/" + "0" * 32 + ".jpg", None):
        assert document._built_img({"built_img": bad}) is None


def test_a_huge_pass_is_refused_from_its_header_and_judges_keep_their_effort(monkeypatch):
    from sightline import meta_client, owner
    big = io.BytesIO()
    Image.new("L", (6000, 6000)).save(big, "PNG")   # small file, 36 M pixels: never decoded
    with pytest.raises(built.Refused, match="256 to 2048"):
        built.passes(big.getvalue(), big.getvalue(), big.getvalue())
    monkeypatch.setenv("META_API_KEY", "k")
    settings.update({"effort": "low"})
    tokens = owner.enter(True, json.dumps({"effort": "minimal"}))
    try:
        assert built.judge_model().effort == "medium" and built.spark_judge_model().effort == "medium"
        assert meta_client.MetaChatModel(api_key="k").effort == "minimal"   # the others still follow the settings
    finally:
        owner.leave(tokens)


def test_one_picture_is_made_once_and_a_lighter_check_is_redone_with_wonder():
    import threading
    look, ids, normals, arr = scene()
    p = built.passes(look, ids, normals)
    drawn, gate_open = [], threading.Event()

    def restyle(look_png, lines_png, extra=""):
        drawn.append(1)
        gate_open.wait(5)
        return _png(arr)
    results = []
    first = threading.Thread(target=lambda: results.append(built.make(p, restyle_fn=restyle, judge_model_fn=Judge)))
    first.start()
    while not built.running(p.key):
        pass
    second = threading.Thread(target=lambda: results.append(built.make(p, restyle_fn=restyle, judge_model_fn=Judge)))
    second.start()
    gate_open.set()
    first.join(); second.join()
    assert len(drawn) == built.PICTURES and [r["status"] for r in results] == ["done", "done"]

    look2, ids2, normals2, arr = scene(((120, 320, 100, 400, (180, 90, 60)), (250, 450, 300, 480, (60, 120, 200))))
    other = built.passes(look2, ids2, normals2)
    light = built.make(other, restyle_fn=lambda *a, **k: _png(arr), judge_model_fn=Judge, judges=3, judged_by="Muse Spark")
    assert light["judge"] == "Muse Spark"
    assert built.make(other, restyle_fn=lambda *a, **k: pytest.fail("reused"), judge_model_fn=Judge,
                      judges=3, judged_by="Muse Spark")["cached"]
    redone = []
    again = built.make(other, restyle_fn=lambda *a, **k: redone.append(1) or _png(arr), judge_model_fn=Judge)
    assert redone and again["judge"] == "Muse Wonder"
