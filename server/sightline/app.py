"""Web API for the browser app. Run: uv run uvicorn sightline.app:app --reload"""
from __future__ import annotations

import json
import os
import queue
import shutil
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chat, edits, plans
from .limits import ProposeLimit, client_id
from .service import Workspace

app = FastAPI(title="ClashWise Sightline")
ws = Workspace()
EXPORTS = Path(tempfile.gettempdir()) / "sightline-exports"
EXPORTS.mkdir(exist_ok=True)
propose_limit = ProposeLimit.from_env()
chat_limit = ProposeLimit.chat_from_env()
# The built web app (`cd web && npm run build`), served from the same origin when present.
WEB_DIST = Path(os.environ.get("SIGHTLINE_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))


class Open(BaseModel):
    samples: list[str]


class Move(BaseModel):
    moved: list[str]
    delta_m: list[float]
    clearance_m: float = 0.025


class Propose(BaseModel):
    element_a: str
    element_b: str
    distance_m: float | None = None
    notes: str = ""
    report_id: str | None = None  # a clash from an open report: its distance and images go to the model
    clash_id: str | None = None


class Offset(BaseModel):
    element: str
    split_m: list[float]
    dz_m: float
    other: str | None = None   # the obstacle, for checking
    clearance_m: float = 0.025


class ChatTurn(BaseModel):
    message: str
    session_id: str | None = None
    scene_id: str | None = None
    report_id: str | None = None
    clash_id: str | None = None
    fixed: list[str] = []


class PlanRequest(BaseModel):
    report_id: str
    clash_ids: list[str] = []   # fix these together
    hub: str | None = None      # or: fix the root cause around this element
    fixed: list[str] = []


class PlanApply(BaseModel):
    options: list[dict]


class OpenReport(BaseModel):
    sample: str


# Uploaded clash reports: XML plus the images it links to, kept in a temp folder while the report is open.
UPLOADS = Path(tempfile.gettempdir()) / "sightline-reports"
UPLOAD_MAX_MB = int(os.environ.get("SIGHTLINE_UPLOAD_MAX_MB", "200"))
UPLOAD_MAX_FILES = int(os.environ.get("SIGHTLINE_UPLOAD_MAX_FILES", "5000"))
UPLOAD_TYPES = {".xml", ".png", ".jpg", ".jpeg"}


def _scene(scene_id: str):
    if scene_id not in ws.scenes:
        raise HTTPException(404, "Model not loaded. Open it again from the sample list.")
    return scene_id


@app.get("/api/samples")
def samples():
    return ws.list_samples()


@app.post("/api/scenes")
def open_scene(body: Open):
    try:
        return {"id": ws.open(body.samples), "files": body.samples}
    except FileNotFoundError as e:
        raise HTTPException(404, f"No model called {e.args[0]}.")


@app.get("/api/scenes/{scene_id}/files/{index}")
def scene_file(scene_id: str, index: int):
    paths = ws.scene(_scene(scene_id)).paths
    if not 0 <= index < len(paths):
        raise HTTPException(404, "No such file in this model set.")
    # Never cached: after an accepted edit the same URL serves the edited model.
    return FileResponse(ws.file(scene_id, index, EXPORTS), media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/scenes/{scene_id}/elements/{global_id}")
def element(scene_id: str, global_id: str):
    return ws.describe(_scene(scene_id), global_id)


@app.post("/api/scenes/{scene_id}/verify")
def verify_move(scene_id: str, body: Move):
    return ws.verify_move(_scene(scene_id), body.moved, body.delta_m, body.clearance_m)


@app.post("/api/scenes/{scene_id}/propose")
def propose(scene_id: str, body: Propose, request: Request):
    _scene(scene_id)
    refused = propose_limit.take(client_id(request.headers, request.client.host if request.client else None))
    if refused:
        raise HTTPException(429, refused)
    if body.report_id:
        _report(body.report_id)
    return ws.propose(_scene(scene_id), body.element_a, body.element_b, body.distance_m, notes=body.notes,
                      report_id=body.report_id, clash_id=body.clash_id)


@app.post("/api/scenes/{scene_id}/propose/stream")
def propose_stream(scene_id: str, body: Propose, request: Request):
    """The same as /propose, as newline-delimited JSON events while it works: the agent's progress
    (see agent.resolve), then {"type": "result", ...} or {"type": "error", "detail": ...}."""
    _scene(scene_id)
    if body.report_id:
        _report(body.report_id)
    refused = propose_limit.take(client_id(request.headers, request.client.host if request.client else None))
    if refused:
        raise HTTPException(429, refused)
    events: queue.Queue = queue.Queue()

    def work():
        try:
            result = ws.propose(scene_id, body.element_a, body.element_b, body.distance_m, notes=body.notes,
                                report_id=body.report_id, clash_id=body.clash_id, on_event=events.put)
            events.put({"type": "result", **result})
        except Exception as e:  # the model or the check failed: tell the browser rather than cut the stream
            events.put({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/scenes/{scene_id}/apply")
def apply(scene_id: str, body: Move):
    return ws.apply(_scene(scene_id), body.moved, body.delta_m)


@app.post("/api/scenes/{scene_id}/offset/check")
def check_offset(scene_id: str, body: Offset):
    if not body.other:
        raise HTTPException(422, "Say which element the offset goes around (other).")
    return ws.check_offset(_scene(scene_id), body.element, body.other, body.split_m, body.dz_m, body.clearance_m)


@app.post("/api/scenes/{scene_id}/offset/apply")
def apply_offset(scene_id: str, body: Offset):
    try:
        return ws.apply_offset(_scene(scene_id), body.element, body.split_m, body.dz_m)
    except edits.Unsupported as e:
        raise HTTPException(422, f"Cannot offset this element: {e}")


@app.get("/api/scenes/{scene_id}/export")
def export(scene_id: str):
    """The edited file. With edits in several discipline files, they come back as one zip."""
    out = EXPORTS / scene_id
    out.mkdir(exist_ok=True)
    paths = ws.export(_scene(scene_id), out)
    if not paths:
        raise HTTPException(409, "Nothing has been changed yet. Accept a fix first.")
    if len(paths) == 1:
        return FileResponse(paths[0], filename=paths[0].name, media_type="application/octet-stream")
    archive = shutil.make_archive(str(EXPORTS / f"{scene_id}-sightline"), "zip", out)
    return FileResponse(archive, filename=Path(archive).name, media_type="application/zip")


def _report(report_id: str):
    if report_id not in ws.reports:
        raise HTTPException(404, "Clash report not loaded. Open it again.")
    return report_id


def _safe_relpath(name: str) -> Path | None:
    """A browser-supplied relative path (folder uploads send "folder/sub/file.png"), without any way out."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return Path(*parts) if parts else None


@app.get("/api/reports/samples")
def report_samples():
    return ws.list_report_samples()


@app.post("/api/reports")
def open_report(body: OpenReport):
    try:
        return ws.report_summary(ws.open_report_sample(body.sample).id)
    except FileNotFoundError:
        raise HTTPException(404, f"No clash report called {body.sample}.")


@app.post("/api/reports/upload")
async def upload_report(files: list[UploadFile] = File(...)):
    """Navisworks XML report(s) and their images. Send a whole export folder so the images' links resolve."""
    if len(files) > UPLOAD_MAX_FILES:
        raise HTTPException(413, f"Too many files (limit {UPLOAD_MAX_FILES}).")
    UPLOADS.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(dir=UPLOADS))
    total = 0
    try:
        for f in files:
            rel = _safe_relpath(f.filename or "")
            if rel is None or rel.suffix.lower() not in UPLOAD_TYPES:
                continue  # the rest of an export folder (HTML gallery, logs) is not needed
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as out:
                while chunk := await f.read(1 << 20):
                    total += len(chunk)
                    if total > UPLOAD_MAX_MB << 20:
                        raise HTTPException(413, f"Upload is over {UPLOAD_MAX_MB} MB.")
                    out.write(chunk)
        if not any(root.rglob("*.xml")):
            raise HTTPException(400, "No XML file in the upload. Export the clash report from Navisworks as XML.")
        tops = list(root.iterdir())
        title = tops[0].name if len(tops) == 1 and tops[0].is_dir() else min(root.rglob("*.xml")).stem  # folder name
        return ws.report_summary(ws.open_report_folder(root, title).id)
    except HTTPException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    except Exception as e:  # not a clash report, or malformed XML
        shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(400, f"Could not read the clash report: {e}")


@app.get("/api/reports/{report_id}")
def report(report_id: str):
    return ws.report_summary(_report(report_id))


@app.get("/api/reports/{report_id}/clashes/{clash_id}/images/{index}")
def report_image(report_id: str, clash_id: str, index: int):
    try:
        path = ws.report_image(_report(report_id), clash_id, index)
    except (KeyError, IndexError):
        raise HTTPException(404, "No such image.")
    return FileResponse(path)


@app.get("/api/reports/{report_id}/match/{scene_id}")
def match(report_id: str, scene_id: str):
    return ws.match(_report(report_id), _scene(scene_id))


@app.get("/api/reports/{report_id}/clashes/{clash_id}/measure/{scene_id}")
def measure(report_id: str, clash_id: str, scene_id: str):
    try:
        return ws.measure(_report(report_id), clash_id, _scene(scene_id))
    except KeyError:
        raise HTTPException(404, "No such clash in this report.")


@app.get("/api/reports/{report_id}/root_causes/{scene_id}")
def root_causes(report_id: str, scene_id: str, fixed: str = ""):
    """Elements in several real clashes, with clashes the geometry finds that the report lacks."""
    return plans.root_causes(ws, _scene(scene_id), _report(report_id), [f for f in fixed.split(",") if f])


class PatternTriage(BaseModel):
    fixed: list[str] = []


@app.get("/api/reports/{report_id}/patterns/{scene_id}")
def patterns(report_id: str, scene_id: str, fixed: str = ""):
    """The same kind of clash many times over (no model call)."""
    return plans.patterns(ws, _scene(scene_id), _report(report_id), [f for f in fixed.split(",") if f])


@app.post("/api/reports/{report_id}/patterns/{scene_id}/triage")
def triage_patterns(report_id: str, scene_id: str, body: PatternTriage, request: Request):
    """Ask Muse Spark what each pattern is (one call for all). Counts as one proposal."""
    pats = plans.patterns(ws, _scene(scene_id), _report(report_id), body.fixed)
    key = (report_id, scene_id, tuple(p["id"] for p in pats))
    if key not in _pattern_triage:
        refused = propose_limit.take(client_id(request.headers, request.client.host if request.client else None))
        if refused:
            raise HTTPException(429, refused)
        _pattern_triage[key] = plans.triage_patterns(ws, pats)
    return _pattern_triage[key]


_pattern_triage: dict[tuple, dict] = {}


@app.post("/api/scenes/{scene_id}/plan/stream")
def plan_stream(scene_id: str, body: PlanRequest, request: Request):
    """Fix several clashes together (clash_ids), or the root cause around one element (hub). Streams progress as
    newline-delimited JSON, then {"type": "plan", ...}. Each clash pair costs one proposal from the allowance."""
    _scene(scene_id)
    _report(body.report_id)
    who = client_id(request.headers, request.client.host if request.client else None)
    if body.hub:
        n = 1  # the cause; the fixes are charged only if the cause calls for edits (see plans.build_root_cause)
    else:
        if not body.clash_ids:
            raise HTTPException(422, "Pick the clashes to fix.")
        n = len(plans.pairs_for(ws, scene_id, body.report_id, body.clash_ids)[0][: plans.MAX_ITEMS])
    refused = propose_limit.take_many(who, max(n, 1))
    if refused:
        raise HTTPException(429, refused)
    events: queue.Queue = queue.Queue()

    def work():
        try:
            plan = (plans.build_root_cause(ws, scene_id, body.report_id, body.hub, body.fixed, events.put,
                                           charge=lambda k: propose_limit.take_many(who, k)) if body.hub
                    else plans.build_batch(ws, scene_id, body.report_id, body.clash_ids, events.put))
            events.put({"type": "plan", **json.loads(plans.to_json(plan))})
        except Exception as e:
            events.put({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/scenes/{scene_id}/plan/apply")
def plan_apply(scene_id: str, body: PlanApply):
    try:
        return plans.apply(ws, _scene(scene_id), body.options)
    except edits.Unsupported as e:
        raise HTTPException(422, f"Cannot apply the plan: {e}")


_chat: chat.Chat | None = None


def _chat_for(request: Request) -> chat.Chat:
    global _chat
    if _chat is None or _chat.ws is not ws:  # tests swap the workspace
        _chat = chat.Chat(ws)
    who = client_id(request.headers, request.client.host if request.client else None)
    _chat.propose_allowed = lambda: propose_limit.take(who)
    _chat.propose_allowed_many = lambda n: propose_limit.take_many(who, n)
    return _chat


@app.post("/api/chat")
def chat_turn(body: ChatTurn, request: Request):
    """One chat message, answered by Muse Spark with tools over the open report and model. Newline-delimited JSON
    events (see chat.py): {"type": "session", "id"} first, then the agent's steps, then {"type": "done"}."""
    if not body.message.strip():
        raise HTTPException(422, "Say something.")
    refused = chat_limit.take(client_id(request.headers, request.client.host if request.client else None))
    if refused:
        raise HTTPException(429, refused)
    c = _chat_for(request)
    session = c.session(body.session_id)
    ctx = chat.Context(body.scene_id, body.report_id, body.clash_id, body.fixed)
    events: queue.Queue = queue.Queue()
    events.put({"type": "session", "id": session.id})

    def work():
        try:
            c.turn(session, body.message[:4000], ctx, events.put)
        except Exception as e:
            events.put({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        events.put({"type": "done"})
        events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# Last, so /api routes win over static files.
if (WEB_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
