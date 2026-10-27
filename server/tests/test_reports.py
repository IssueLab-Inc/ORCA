import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import reports
from sightline.fixtures import build_clash_fixture
from sightline.service import Workspace

# A standard Navisworks XML export: flat smart tags, the selection-tree path, one JPEG per result.
STANDARD = """<?xml version="1.0" encoding="UTF-8"?>
<exchange units="m" filename="Fixture.nwf">
 <batchtest name="Report" units="m"><clashtests>
  <clashtest name="Structure vs Ducts" test_type="hard" status="ok" tolerance="0.010">
   <clashresults>
    <clashresult name="Clash1" guid="g-1" href="report_files\\cd000001.jpg" status="new" distance="-0.150">
     <clashpoint><pos3f x="3.0" y="0.0" z="2.8"/></clashpoint>
     <gridlocation>B-2 : Level 03</gridlocation>
     <clashobjects>
      <clashobject>
       <objectattribute><name>IfcGUID</name><value>{beam}</value></objectattribute>
       <layer>Level 03</layer>
       <pathlink><node>fixture.ifc</node><node>Level 03</node><node>IfcBeam</node><node>UB 406x178 beam</node></pathlink>
       <smarttags><smarttag><name>Item Name</name><value>UB 406x178 beam</value></smarttag>
        <smarttag><name>Item Type</name><value>IfcBeam</value></smarttag></smarttags>
      </clashobject>
      <clashobject>
       <layer>Level 03</layer>
       <pathlink><node>fixture.ifc</node><node>Level 03</node><node>IfcDuctSegment</node><node>Supply duct 400x300</node></pathlink>
       <smarttags><smarttag><name>Item Name</name><value>Supply duct 400x300</value></smarttag></smarttags>
      </clashobject>
     </clashobjects>
    </clashresult>
    <clashresult name="Clash2" guid="g-2" status="active" distance="-0.020">
     <clashobjects>
      <clashobject><pathlink><node>other.ifc</node><node>IfcWall</node><node>Wall W1</node></pathlink></clashobject>
      <clashobject><pathlink><node>fixture.ifc</node><node>IfcBeam</node><node>UB 406x178 beam</node></pathlink></clashobject>
     </clashobjects>
    </clashresult>
   </clashresults>
  </clashtest>
 </clashtests></batchtest>
</exchange>
"""

# The ClashWise three-view export: grouped tags "<node> / <category> / <property>", leaf element first.
GROUPED = """<exchange units="m"><batchtest name="Sampled"><clashtests>
 <clashtest name="IfcDistributionPort (MEP) vs IfcWall (Architecture)" test_type="hard" tolerance="0">
  <clashresults><clashresult name="Clash7" guid="g-7" status="active" distance="-0.05" href="c7/A-transparent.png">
   <clashobjects>
    <clashobject><pathlink><node>MEP.ifc</node><node>Level 02</node><node>IfcPipeSegment</node><node>CW main</node><node>Port 1</node></pathlink>
     <smarttags>
      <smarttag><name>Port 1 / Element / IfcClass</name><value>IfcDistributionPort</value></smarttag>
      <smarttag><name>Port 1 / Element / GlobalId</name><value>0FQ9jQy2DHrgb6aZcJtSST</value></smarttag>
      <smarttag><name>CW main / Element / IfcClass</name><value>IfcPipeSegment</value></smarttag>
      <smarttag><name>Level 02 / Element / IfcClass</name><value>IfcBuildingStorey</value></smarttag>
     </smarttags></clashobject>
    <clashobject><pathlink><node>Arch.ifc</node><node>Level 02</node><node>IfcWall</node><node>Core wall - lift/riser / lobby</node></pathlink>
     <smarttags>
      <smarttag><name>Core wall - lift/riser / lobby / Element / IfcClass</name><value>IfcWall</value></smarttag>
      <smarttag><name>Core wall - lift/riser / lobby / ClashWise_Demo / Level</name><value>Level 02</value></smarttag>
      <smarttag><name>Level 02 / Element / IfcClass</name><value>IfcBuildingStorey</value></smarttag>
     </smarttags></clashobject>
   </clashobjects>
  </clashresult></clashresults>
 </clashtest></clashtests></batchtest></exchange>
"""


def test_grouped_tags_find_the_element_its_parent_and_all_three_views(tmp_path):
    (tmp_path / "report.xml").write_text(GROUPED)
    (tmp_path / "c7").mkdir()
    for name in ("A-transparent.png", "B-context.png", "C-alternate.png"):
        (tmp_path / "c7" / name).write_bytes(b"png")
    c = reports.load("r", tmp_path, [tmp_path / "report.xml"], "t").clashes[0]
    assert (c.a.ifc_class, c.a.name, c.a.part_of, c.a.level) == ("IfcDistributionPort", "Port 1", "CW main", "Level 02")
    assert (c.b.ifc_class, c.b.name) == ("IfcWall", "Core wall - lift/riser / lobby")  # " / " inside a name
    assert [label for label, _ in c.images] == ["A", "B", "C"]


def test_upload_match_measure_and_images(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    build_clash_fixture(models / "fixture.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=models))
    monkeypatch.setattr(app_module, "UPLOADS", tmp_path / "uploads")
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["fixture.ifc"]}).json()["id"]
    beam = app_module.ws.scene(sid).model.by_type("IfcBeam")[0].GlobalId

    xml = STANDARD.replace("{beam}", beam).encode()
    files = [
        ("files", ("export/report.xml", xml, "text/xml")),
        ("files", ("export/copy/report.xml", xml, "text/xml")),          # the same results again: kept once
        ("files", ("export/report_files/cd000001.jpg", b"jpeg", "image/jpeg")),
        ("files", ("export/report.html", b"<html>", "text/html")),       # not needed, skipped
        ("files", ("../../escape.xml", xml, "text/xml")),                # stays inside the upload folder
    ]
    r = c.post("/api/reports/upload", files=files)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert [x["name"] for x in rep["clashes"]] == ["Clash1", "Clash2"]
    first = rep["clashes"][0]
    assert first["a"]["global_id"] == beam and first["a"]["ifc_class"] == "IfcBeam" and first["a"]["level"] == "Level 03"
    assert first["b"]["ifc_class"] == "IfcDuctSegment" and first["images"] == ["Navisworks"]
    assert not (tmp_path / "escape.xml").exists()

    img = c.get(f"/api/reports/{rep['id']}/clashes/{first['id']}/images/0")
    assert img.status_code == 200 and img.content == b"jpeg"

    m = c.get(f"/api/reports/{rep['id']}/match/{sid}").json()
    assert m[first["id"]]["a"] == beam and m[first["id"]]["how"] == ["globalid", "name"]  # duct: no GUID, unique name
    assert m[rep["clashes"][1]["id"]]["a"] is None  # the wall is not in the open model

    measured = c.get(f"/api/reports/{rep['id']}/clashes/{first['id']}/measure/{sid}").json()
    assert measured["matched"] and measured["distance_m"] < -0.1  # the duct sits inside the beam


def test_upload_without_xml_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    monkeypatch.setattr(app_module, "UPLOADS", tmp_path / "uploads")
    c = TestClient(app_module.app)
    r = c.post("/api/reports/upload", files=[("files", ("a.png", b"png", "image/png"))])
    assert r.status_code == 400
    assert not any((tmp_path / "uploads").iterdir())  # nothing left behind


def test_sample_reports_are_folders_under_samples_reports(tmp_path, monkeypatch):
    (tmp_path / "reports" / "demo").mkdir(parents=True)
    (tmp_path / "reports" / "demo" / "report.xml").write_text(GROUPED)
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    c = TestClient(app_module.app)
    assert c.get("/api/reports/samples").json() == ["demo"]
    assert c.post("/api/reports", json={"sample": "demo"}).json()["clashes"][0]["name"] == "Clash7"
    assert c.post("/api/reports", json={"sample": "../reports"}).status_code == 404


def test_proposing_a_report_clash_sends_its_navisworks_images_and_distance(tmp_path, monkeypatch):
    class Recorder:
        def __init__(self):
            self.calls = []

        def complete_json(self, system, text, images=None):
            self.calls.append((text, images))
            return {"understanding": "", "candidates": []}

    models = tmp_path / "models"
    models.mkdir()
    build_clash_fixture(models / "fixture.ifc")
    recorder = Recorder()
    monkeypatch.setattr(app_module, "ws", Workspace(samples=models, model=recorder))
    monkeypatch.setattr(app_module, "UPLOADS", tmp_path / "uploads")
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["fixture.ifc"]}).json()["id"]
    scene = app_module.ws.scene(sid).model
    beam, duct = scene.by_type("IfcBeam")[0].GlobalId, scene.by_type("IfcDuctSegment")[0].GlobalId
    rep = c.post("/api/reports/upload", files=[
        ("files", ("x/report.xml", STANDARD.replace("{beam}", beam).encode(), "text/xml")),
        ("files", ("x/report_files/cd000001.jpg", b"jpeg", "image/jpeg")),
    ]).json()

    r = c.post(f"/api/scenes/{sid}/propose", json={"element_a": duct, "element_b": beam,
                                                    "report_id": rep["id"], "clash_id": rep["clashes"][0]["id"]})
    assert r.status_code == 200
    text, images = recorder.calls[0]
    assert "-150.0 mm" in text and "Structure vs Ducts" in text
    assert [p.name for p in images] == ["cd000001.jpg"]


def test_match_shows_a_ports_owner(tmp_path, monkeypatch):
    from sightline.fixtures import build_run_fixture
    import ifcopenshell.util.system as system
    build_run_fixture(tmp_path / "run.ifc")
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["run.ifc"])
    model = ws.scene(sid).model
    main = next(e for e in model.by_type("IfcDuctSegment") if e.Tag == "SA-1")
    port = system.get_ports(main)[0]
    xml = GROUPED.replace("0FQ9jQy2DHrgb6aZcJtSST", port.GlobalId)
    (tmp_path / "reports" / "r").mkdir(parents=True)
    (tmp_path / "reports" / "r" / "report.xml").write_text(xml)
    rid = ws.open_report_sample("r").id
    m = next(iter(ws.match(rid, sid).values()))
    assert m["a"] == port.GlobalId and m["show"][0] == main.GlobalId


def test_sample_exclusions_drop_whole_tests_and_renumber(tmp_path):
    (tmp_path / "flat.xml").write_text(STANDARD)
    (tmp_path / "grouped.xml").write_text(GROUPED)
    xmls = [tmp_path / "flat.xml", tmp_path / "grouped.xml"]
    assert len(reports.load("r", tmp_path, xmls, "t").clashes) == 3
    # Named in the test, or on either side of any result: the whole test goes, and ids stay contiguous.
    kept = reports.load("r", tmp_path, xmls, "t", exclude=("IfcDistributionPort",)).clashes
    assert [(c.id, c.test) for c in kept] == [("c0001", "Structure vs Ducts"), ("c0002", "Structure vs Ducts")]
    with pytest.raises(ValueError):  # Clash2 has a wall, so "Structure vs Ducts" goes too: nothing is left
        reports.load("r", tmp_path, xmls, "t", exclude=("IfcWall",))


def _wav(seconds=0.5):
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\0\0" * int(16000 * seconds))
    return buf.getvalue()


def test_voice_transcribes_a_wav_biased_to_the_reports_clash_names(tmp_path, monkeypatch):
    from sightline.limits import ProposeLimit
    (tmp_path / "report.xml").write_text(STANDARD)
    ws = Workspace(samples=tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    seen = {}

    def fake(wav, words):
        seen["wav"], seen["words"] = wav, words
        return {"transcript": "Fix clash one", "duration_ms": 500}

    monkeypatch.setattr(app_module, "transcribe", fake)
    monkeypatch.setattr(app_module, "voice_limit", ProposeLimit(per_client_hour=2))
    report = ws.open_report_folder(tmp_path, "t")
    c = TestClient(app_module.app)
    ok = c.post("/api/transcribe", files={"audio": ("clip.wav", _wav(), "audio/wav")}, data={"report_id": report.id})
    assert ok.status_code == 200 and ok.json()["transcript"] == "Fix clash one"
    assert seen["wav"][:4] == b"RIFF" and "transom" in seen["words"] and "Clash1" in seen["words"]
    assert c.post("/api/transcribe", files={"audio": ("x.webm", b"not a wav file", "audio/webm")}).status_code == 422
    assert c.post("/api/transcribe", files={"audio": ("clip.wav", _wav(), "audio/wav")}).status_code == 200
    assert c.post("/api/transcribe", files={"audio": ("clip.wav", _wav(), "audio/wav")}).status_code == 429  # the cap
