"""Web API for the browser app. Run: uv run uvicorn sightline.app:app --reload"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import queue
import shutil
import tempfile
import threading
import uuid
import wave
from dataclasses import asdict
from http.cookies import CookieError, SimpleCookie
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict
from starlette.routing import Route

from . import agents, chat, context_planner, detect, document, edits, mcp_server, owner, plans, settings, step, titles, triage
from .meta_client import load_env, transcribe, triage_model, triage_model_info
from .limits import ProposeLimit, client_id
from .service import MODEL_SUFFIXES, MODELS, Workspace

load_env()  # the repo's .env, before anything reads a setting (caps, owner token); real environment variables win
app = FastAPI(title="ORCA")


class _OwnerContext:
    """Each request knows whether it is the owner's (the signed cookie) and carries the owner's settings (owner.py)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        jar = SimpleCookie()
        try:
            jar.load(headers.get(b"cookie", b"").decode("latin-1"))
        except CookieError:
            pass
        signed = jar[owner.COOKIE].value if owner.COOKIE in jar else None
        tokens = owner.enter(owner.cookie_ok(signed), headers.get(owner.HEADER.encode(), b"").decode("utf-8", "replace") or None)
        try:
            await self.inner(scope, receive, send)
        finally:
            owner.leave(tokens)


app.add_middleware(_OwnerContext)
ws = Workspace()
EXPORTS = Path(tempfile.gettempdir()) / "sightline-exports"
EXPORTS.mkdir(exist_ok=True)
# Progress streams (newline-delimited JSON) go out uncompressed. Modal's edge zstd-compresses for browsers that accept
# it and holds the stream back until a buffer fills: the first triage verdicts reached the browser after 77-170 s
# instead of under a second, and Muse Spark's reasoning arrived with its result. It ignores "no-transform"; an explicit
# "Content-Encoding: identity" makes it pass the stream through.
NDJSON_HEADERS = {"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no", "Content-Encoding": "identity"}


def _ndjson(events) -> StreamingResponse:
    return StreamingResponse(events, media_type="application/x-ndjson", headers=NDJSON_HEADERS)


class _RequestEvents:
    """Never wait for a reader, including when an emit runs under Workspace.lock.

    Keep at most 64 events. On saturation discard progress (including wrapped trial
    meshes), evicting queued progress to make room for canonical results/errors/done
    and the end sentinel. If canonical events alone fill the queue, explicitly cancel
    the request with an error and an end sentinel rather than silently lose a result.
    A connected non-reader can retain this bounded queue, but cannot retain a worker.
    """
    def __init__(self, request):
        self.request = request
        self.queue = queue.Queue(maxsize=64)
        self.cancel = threading.Event()
        self._closed = False

    @staticmethod
    def _progress(event):
        if event is None:
            return False
        if event.get('type') in ('agent', 'context_event', 'plan_event'):
            return _RequestEvents._progress(event.get('event'))
        return event.get('type') in {'thinking', 'tool', 'tool_result', 'trial', 'reasoning',
                                    'ideas', 'checking', 'attempt', 'context_progress', 'item', 'checking_plan'}

    def put(self, event):
        # Consumers only use get_nowait; guard eviction and append with Queue's same
        # mutex so concurrent producers cannot displace a canonical event by accident.
        with self.queue.mutex:
            if self.cancel.is_set() or self._closed:
                return
            pending = self.queue.queue
            if len(pending) == self.queue.maxsize:
                if self._progress(event):
                    return
                for i, queued in enumerate(pending):
                    if self._progress(queued):
                        del pending[i]
                        break
                else:
                    pending.clear()
                    pending.append(dict(type='error', detail='Request cancelled: too many unread result events. Please retry.'))
                    pending.append(None)
                    self._closed = True
                    self.cancel.set()
                    return
            pending.append(event)
            if event is None:
                self._closed = True

    async def stream(self):
        completed = False
        try:
            while not await self.request.is_disconnected():
                try:
                    event = self.queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(.05)
                    continue
                if event is None:
                    completed = True
                    break
                yield json.dumps(event, default=str) + '\n'
        finally:
            # Successful consumption can finish before the worker commits chat
            # history. Only disconnection/abandonment cancels that pending publish.
            if not completed:
                self.cancel.set()


propose_limit = ProposeLimit.from_env()
chat_limit = ProposeLimit.chat_from_env()
unlock_limit = ProposeLimit(5, 50, noun="unlock attempts")  # wrong owner tokens, per visitor and for everyone
# Clash titles: one titling run per report (a few model calls for a whole report): SIGHTLINE_TITLES_PER_HOUR per visitor.
title_limit = ProposeLimit(int(os.environ.get("SIGHTLINE_TITLES_PER_HOUR", "0")),
                           int(os.environ.get("SIGHTLINE_TITLES_PER_DAY", "0")), noun="titling runs")
# Detection runs cost no model call but take the server's CPU for seconds: SIGHTLINE_DETECT_PER_HOUR per visitor.
detect_limit = ProposeLimit(int(os.environ.get("SIGHTLINE_DETECT_PER_HOUR", "0")),
                            int(os.environ.get("SIGHTLINE_DETECT_PER_DAY", "0")), noun="detection runs")
voice_limit = ProposeLimit(int(os.environ.get("SIGHTLINE_VOICE_PER_HOUR", "0")),
                           int(os.environ.get("SIGHTLINE_VOICE_PER_DAY", "0")), noun="voice messages")
# Model uploads (IFC or STEP): each takes disk, memory and, for STEP, a conversion and one model call to name its parts.
model_upload_limit = ProposeLimit(int(os.environ.get("SIGHTLINE_MODEL_UPLOADS_PER_HOUR", "0")),
                                  int(os.environ.get("SIGHTLINE_MODEL_UPLOADS_PER_DAY", "0")), noun="model uploads")

MAX_VOICE_BYTES = 3_000_000  # a minute of 16 kHz mono 16-bit PCM is 1.9 MB; the browser stops recording at 60 s
# Words Muse Voice Transcribe should lean toward: what people say to ORCA about a building model.
VOICE_WORDS = ["ORCA", "Orca", "Northbank", "clash", "clashes", "duct", "ductwork", "supply air", "cable tray", "pipe",
               "transfer girder", "girder", "beam", "column", "slab", "mullion", "transom", "curtain wall", "web opening",
               "offset", "trim", "clearance", "Level 01", "Level 02", "Level 03", "MEP", "IFC", "BCF", "Navisworks",
               "triage", "root cause", "x-ray", "section box", "isolate", "Muse Spark"]
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


class DetectRequest(BaseModel):
    tests: list[dict] | None = None  # None: the default tests (GET /detect/tests); see detect.Test.from_dict


# Uploaded clash reports: XML plus the images it links to, kept in a temp folder while the report is open.
UPLOADS = Path(tempfile.gettempdir()) / "sightline-reports"
UPLOAD_MAX_MB = int(os.environ.get("SIGHTLINE_UPLOAD_MAX_MB", "200"))
UPLOAD_MAX_FILES = int(os.environ.get("SIGHTLINE_UPLOAD_MAX_FILES", "5000"))
UPLOAD_TYPES = {".xml", ".png", ".jpg", ".jpeg"}
MODEL_UPLOAD_MAX_MB = int(os.environ.get("SIGHTLINE_MODEL_UPLOAD_MAX_MB", str(UPLOAD_MAX_MB)))
MODEL_UPLOAD_MAX_FILES = 8


def _scene(scene_id: str):
    if scene_id not in ws.scenes:
        raise HTTPException(404, "Model not loaded. Open it again.")
    return scene_id


def _take(limit: ProposeLimit, request: Request) -> str | None:
    """One use of a demo cap for this visitor: why not, or None. The owner has none (unless they switch them on)."""
    if owner.no_caps():
        return None
    return limit.take(client_id(request.headers, request.client.host if request.client else None))


class Unlock(BaseModel):
    token: str


@app.get("/api/owner")
def owner_state():
    return {"available": owner.available(), "owner": owner.is_owner()}


@app.post("/api/owner/unlock")
def owner_unlock(body: Unlock, request: Request, response: Response):
    """The owner token, once, for a signed cookie scripts cannot read. Wrong tokens are capped per visitor."""
    if not owner.available():
        raise HTTPException(404, "No owner is configured on this server.")
    if not owner.check_token(body.token.strip()):
        refused = unlock_limit.take(client_id(request.headers, request.client.host if request.client else None))
        raise HTTPException(429 if refused else 403, refused or "That is not the owner token.")
    response.set_cookie(owner.COOKIE, owner.cookie_value(), max_age=owner.DAYS * 86400, httponly=True, secure=True,
                        samesite="strict", path="/api")
    return {"owner": True}


@app.post("/api/owner/lock")
def owner_lock(response: Response):
    response.delete_cookie(owner.COOKIE, path="/api", secure=True, httponly=True, samesite="strict")
    return {"owner": False}


def _settings_state() -> dict:
    host = bool(os.environ.get("TRIAGE_API_KEY") or os.environ.get("BASETEN_API_KEY"))
    return {"everyone": asdict(settings.current()), "defaults": settings.defaults(), "host": host}


@app.get("/api/models")
def models():
    """Which model this request's titles and triage would use (the owner's choice, else everyone's), for the copy."""
    return {"triage": triage_model_info()}


@app.get("/api/settings")
def get_settings():
    """The settings for everyone (settings.py): the owner's to read and change."""
    if not owner.is_owner():
        raise HTTPException(403, "Only the owner can see these settings.")
    return _settings_state()


@app.put("/api/settings")
def put_settings(body: dict):
    if not owner.is_owner():
        raise HTTPException(403, "Only the owner can change these settings.")
    try:
        settings.update(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _settings_state()


@app.get("/api/samples")
def samples():
    return ws.list_samples()


def _classifier():
    """The model that names a STEP file's parts (the titles' and triage's model), or None without one."""
    try:
        return triage_model()[0]
    except Exception:
        return None


@app.post("/api/scenes")
def open_scene(body: Open):
    """Open sample models. A STEP sample is converted to IFC first (cached by its contents, so only the first
    opening pays for it)."""
    try:
        needs = any(Path(n).suffix.lower() in step.SUFFIXES for n in body.samples)
        sid = ws.open(body.samples, classify_with=_classifier() if needs else None)
        return {"id": sid, "files": body.samples, "step": ws.step_files(sid)}
    except FileNotFoundError as e:
        raise HTTPException(404, f"No model called {e.args[0]}.")
    except step.StepError as e:
        raise HTTPException(400, str(e))


@app.post("/api/models/upload")
async def upload_models(request: Request, files: list[UploadFile] = File(...)):
    """Open your own models: IFC, or STEP (converted to IFC to check; Export gives the STEP back with the fixes).
    Files that share coordinates open together. Capped per visitor (SIGHTLINE_MODEL_UPLOADS_PER_HOUR/DAY) and in size
    (SIGHTLINE_MODEL_UPLOAD_MAX_MB for all files together)."""
    if not files or len(files) > MODEL_UPLOAD_MAX_FILES:
        raise HTTPException(400, f"Choose 1 to {MODEL_UPLOAD_MAX_FILES} model files.")
    names = [Path(f.filename or "").name for f in files]
    bad = [n for n in names if Path(n).suffix.lower() not in MODEL_SUFFIXES]
    if bad:
        raise HTTPException(400, f"{bad[0]} is not an IFC or STEP file (.ifc, .step, .stp).")
    refused = _take(model_upload_limit, request)
    if refused:
        raise HTTPException(429, refused)
    MODELS.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(dir=MODELS))
    total, paths = 0, []
    try:
        for f, name in zip(files, names):
            dest = root / name
            if dest in paths:
                raise HTTPException(400, f"{name} was given twice.")
            with dest.open("wb") as out:
                while chunk := await f.read(1 << 20):
                    total += len(chunk)
                    if total > MODEL_UPLOAD_MAX_MB << 20:
                        raise HTTPException(413, f"Upload is over {MODEL_UPLOAD_MAX_MB} MB.")
                    out.write(chunk)
            paths.append(dest)
        needs = any(p.suffix.lower() in step.SUFFIXES for p in paths)
        classifier = _classifier() if needs else None
        sid = await run_in_threadpool(lambda: ws.open_paths(paths, root, classify_with=classifier))
        return {"id": sid, "files": names, "step": ws.step_files(sid)}
    except HTTPException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    except step.StepError as e:  # open_paths already removed the folder
        raise HTTPException(400, str(e))
    except Exception as e:  # not a model IfcOpenShell can read
        shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(400, f"Could not open the models: {type(e).__name__}: {e}")


@app.get("/api/scenes/{scene_id}")
def scene_info(scene_id: str):
    """A scene the page had open (to resume after a reload or a closed tab): 404 once the server no longer holds it."""
    return ws.scene_info(_scene(scene_id))


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
    refused = _take(propose_limit, request)
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
    refused = _take(propose_limit, request)
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

    owner.spawn(work)

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event) + "\n"

    return _ndjson(stream())


@app.post("/api/scenes/{scene_id}/apply")
def apply(scene_id: str, body: Move):
    return ws.apply(_scene(scene_id), body.moved, body.delta_m)


class ContextObjective(BaseModel):
    model_config = ConfigDict(extra='forbid')
    element_a: str
    element_b: str
    report_id: str | None = None
    clash_id: str | None = None


class ContextApply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    proposal_id: str
    acknowledged_conditions: list[str]


@app.post('/api/scenes/{scene_id}/context/stream')
def context_stream(scene_id: str, body: ContextObjective, request: Request):
    _scene(scene_id)
    try:
        objective = context_planner.validate_objective(ws, scene_id, body.model_dump(exclude_none=True))
    except context_planner.ContextError as exc:
        raise HTTPException(exc.status, str(exc))
    who = client_id(request.headers, request.client.host if request.client else None)
    refused = None if owner.no_caps() else propose_limit.take_many(who, 3)
    if refused:
        raise HTTPException(429, refused)
    events = _RequestEvents(request)

    def work():
        try:
            events.put(context_planner.build(ws, scene_id, objective, events.put, cancel=events.cancel))
        except Exception as exc:
            events.put(dict(type='error', detail=f'{type(exc).__name__}: {exc}'))
        finally:
            events.put(None)

    owner.spawn(work)

    return _ndjson(events.stream())


@app.post('/api/scenes/{scene_id}/context/apply')
def context_apply(scene_id: str, body: ContextApply):
    _scene(scene_id)
    try:
        return context_planner.accept(ws, scene_id, body.proposal_id, body.acknowledged_conditions)
    except context_planner.ContextError as exc:
        raise HTTPException(exc.status, str(exc))


@app.post("/api/scenes/{scene_id}/offset/check")
def check_offset(scene_id: str, body: Offset):
    if not body.other:
        raise HTTPException(422, "Say which element the offset goes around (other).")
    return ws.check_offset(_scene(scene_id), body.element, body.other, body.split_m, body.dz_m, body.clearance_m)


class TrimBody(BaseModel):
    element: str
    end: str
    by_m: float


@app.post("/api/scenes/{scene_id}/trim/apply")
def apply_trim(scene_id: str, body: TrimBody):
    try:
        return ws.apply_trim(_scene(scene_id), body.element, body.end, body.by_m)
    except edits.Unsupported as e:
        raise HTTPException(422, f"Cannot trim this element: {e}")


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


MAX_VIEW_BYTES = 4_000_000


@app.post("/api/reports/{report_id}/clashes/{clash_id}/images")
async def save_view(report_id: str, clash_id: str, label: str = Form(...), image: UploadFile = File(...)):
    """A view of a clash ORCA detected, captured in the browser (A, B or C)."""
    data = await image.read(MAX_VIEW_BYTES + 1)
    if len(data) > MAX_VIEW_BYTES:
        raise HTTPException(413, "That picture is too large.")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(415, "Send a PNG.")
    try:
        return {"images": ws.save_capture(_report(report_id), clash_id, label, data)}
    except KeyError:
        raise HTTPException(404, "No such clash.")
    except PermissionError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/scenes/{scene_id}/detect/tests")
def detect_tests(scene_id: str):
    """The clash tests ORCA would run on the open models (docs/detection.md)."""
    return ws.detect_tests(_scene(scene_id))


@app.post("/api/scenes/{scene_id}/detect/stream")
def detect_stream(scene_id: str, body: DetectRequest, request: Request):
    """Find the clashes in the open models. Streams newline-delimited JSON: {"type": "phase"|"start"|"test"|
    "test_done", ...} while it works, then {"type": "done", report, coverage, diff, ...} or {"type": "error"}."""
    _scene(scene_id)
    if body.tests is not None:
        try:
            [detect.Test.from_dict(t) for t in body.tests]
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, f"Check the tests: {e}")
    refused = _take(detect_limit, request)
    if refused:
        raise HTTPException(429, refused)
    events: queue.Queue = queue.Queue()

    def work():
        try:
            events.put({"type": "done", **ws.detect(scene_id, body.tests, on_event=events.put)})
        except Exception as e:
            events.put({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        events.put(None)

    owner.spawn(work)

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event, default=str) + "\n"

    return _ndjson(stream())


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
        refused = _take(propose_limit, request)
        if refused:
            raise HTTPException(429, refused)
        _pattern_triage[key] = plans.triage_patterns(ws, pats)
    return _pattern_triage[key]


_pattern_triage: dict[tuple, dict] = {}
_triage_jobs: dict[str, triage.Job] = {}
_triage_lock = threading.Lock()


def _triage_key(report) -> str:
    """A sample report is the same files for every visitor (clash ids are positions), so its triage is shared."""
    return report.id if report.temporary else f"sample:{report.root}"


def _triage_facts(report_id: str, scene_id: str | None) -> dict[str, dict]:
    """Clashes the open model already settles: both sides resolve to one element (drawn purple in the viewer)."""
    if not scene_id or scene_id not in ws.scenes:
        return {}
    report = ws.report(report_id)
    with ws.lock:
        matches = ws.match(report_id, scene_id)
    out = {}
    for c in report.clashes:
        m = matches.get(c.id) or {}
        a, b = (m.get("show") or [None, None])
        a, b = a or m.get("a"), b or m.get("b")
        if a and a == b:
            out[c.id] = triage.same_element(c)
    return out


@app.get("/api/reports/{report_id}/triage")
def triage_state(report_id: str, scene_id: str | None = None):
    """The bulk triage of this report so far ({"results": {}} when it has not been run)."""
    job = _triage_jobs.get(_triage_key(ws.report(_report(report_id))))
    if job:
        job.learn(_triage_facts(report_id, scene_id))
    return job.state() if job else {"results": {}, "done": False, "started": False}


@app.post("/api/reports/{report_id}/triage/stream")
def triage_stream(report_id: str, request: Request, rerun: bool = False, scene_id: str | None = None):
    """Triage every clash in the report (open-weights model when configured). Streams newline-delimited JSON:
    start, one "clash" event per verdict, done. One run per report is shared by every visitor; starting one costs a
    proposal, following one already started is free. With `scene_id`, what the open model already settles (one
    element on both sides) is not asked of the model, and corrects a run that did ask."""
    report = ws.report(_report(report_id))
    try:
        job = _start_triage(report, scene_id, lambda: _take(propose_limit, request), rerun)
    except PermissionError as e:
        raise HTTPException(429, str(e))

    def stream():
        for event in job.follow():
            yield json.dumps(event, default=str) + "\n"

    return _ndjson(stream())


def _start_triage(report, scene_id: str | None, charge, rerun: bool = False) -> triage.Job:
    """The report's shared triage run: the one under way or done, else a new one (`charge` once: why not, or None)."""
    key = _triage_key(report)
    facts = _triage_facts(report.id, scene_id)
    with _triage_lock:
        job = _triage_jobs.get(key)
        if job is None or (rerun and job.done):
            refused = charge()
            if refused:
                raise PermissionError(refused)
            model, info = triage_model()
            job = triage.Job(report, model, info, int(os.environ.get("SIGHTLINE_TRIAGE_WORKERS", "8")))
            job.learn(facts)
            _triage_jobs[key] = job.start()
            while len(_triage_jobs) > 16:
                _triage_jobs.pop(next(iter(_triage_jobs)))
    job.learn(facts)
    return job


_title_jobs: dict[str, titles.Job] = {}
_title_lock = threading.Lock()


def _with_titles(report, found: dict[str, str]) -> None:
    """A shared run titles one copy of a sample report; every visitor's copy (same ids) gets its titles."""
    for c in report.clashes:
        if not c.title and c.id in found:
            c.title = found[c.id]


@app.get("/api/reports/{report_id}/titles")
def report_titles(report_id: str):
    report = ws.report(_report(report_id))
    job = _title_jobs.get(_triage_key(report))
    if job:
        _with_titles(report, job.titles)
    return {"titles": {c.id: c.title for c in report.clashes if c.title}, "running": bool(job and not job.done)}


@app.post("/api/reports/{report_id}/titles/stream")
def titles_stream(report_id: str, request: Request):
    """Title every clash in the report with Muse (titles.py). Streams newline-delimited JSON: start, a "titles" event
    per batch ({id: title}), done. One run per report is shared; following a run already started is free."""
    report = ws.report(_report(report_id))
    key = _triage_key(report)
    with _title_lock:
        job = _title_jobs.get(key)
        if job is not None:
            _with_titles(report, job.titles)
        # Start one when there is none, or when a finished one left clashes untitled (a failed batch): those only.
        if job is None or (job.done and any(not c.title for c in report.clashes)):
            refused = _take(title_limit, request)
            if refused:
                raise HTTPException(429, refused)
            model, info = triage_model()
            job = titles.Job(report, model, info)
            _title_jobs[key] = job.start()
            while len(_title_jobs) > 32:
                _title_jobs.pop(next(iter(_title_jobs)))

    def stream():
        for event in job.follow():
            if event.get("type") == "titles":
                _with_titles(report, event["items"])
            yield json.dumps(event, default=str) + "\n"

    return _ndjson(stream())


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
    refused = None if owner.no_caps() else propose_limit.take_many(who, max(n, 1))
    if refused:
        raise HTTPException(429, refused)
    events: queue.Queue = queue.Queue()

    def work():
        try:
            plan = (plans.build_root_cause(ws, scene_id, body.report_id, body.hub, body.fixed, events.put,
                                           charge=lambda k: None if owner.no_caps() else propose_limit.take_many(who, k)) if body.hub
                    else plans.build_batch(ws, scene_id, body.report_id, body.clash_ids, events.put))
            events.put({"type": "plan", **json.loads(plans.to_json(plan))})
        except Exception as e:
            events.put({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        events.put(None)

    owner.spawn(work)

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event, default=str) + "\n"

    return _ndjson(stream())


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
    return _chat


@app.post("/api/chat")
def chat_turn(body: ChatTurn, request: Request):
    """One chat message, answered by Muse Spark with tools over the open report and model. Newline-delimited JSON
    events (see chat.py): {"type": "session", "id"} first, then the agent's steps, then {"type": "done"}."""
    if not body.message.strip():
        raise HTTPException(422, "Say something.")
    refused = _take(chat_limit, request)
    if refused:
        raise HTTPException(429, refused)
    c = _chat_for(request)
    # Capture identity/bypass on this request, never on the shared Chat/session.
    who = client_id(request.headers, request.client.host if request.client else None)
    no_caps = owner.no_caps()
    allowed = lambda: None if no_caps else propose_limit.take(who)
    allowed_many = lambda n: None if no_caps else propose_limit.take_many(who, n)
    session = c.session(body.session_id)
    ctx = chat.Context(body.scene_id, body.report_id, body.clash_id, body.fixed)
    events = _RequestEvents(request)
    events.put({"type": "session", "id": session.id})

    def finish():
        events.put({"type": "done"})
        events.put(None)

    def work():
        try:
            c.turn(session, body.message[:4000], ctx, events.put, cancel=events.cancel,
                   propose_allowed=allowed, propose_allowed_many=allowed_many, before_publish=finish)
        except Exception as e:
            events.put({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        finish()  # idempotent after successful completion; also close failed/cancelled turns

    owner.spawn(work)

    return _ndjson(events.stream())


class DocumentRequest(BaseModel):
    scene_id: str | None = None
    scope: str = "combined"            # combined | team | model
    teams: dict[str, str] = {}         # model file name -> team, as the user confirmed it
    bcf: bool = True
    evidence: dict[str, dict] = {}     # clash id -> the session's fix (status, title, edit, pictures...)
    reviews: dict[str, list[dict]] = {}  # clash id -> [{team, name, decision, note, at}]
    marks: dict[str, str] = {}         # clash id -> "by_design" | "author"
    triage: dict[str, dict] = {}       # clash id -> the verdict the browser shows (survives a server restart or rerun)


_documents: dict[str, tuple[bytes, str, str]] = {}


@app.get("/api/reports/{report_id}/teams")
def report_teams(report_id: str, scene_id: str | None = None):
    """Each model in the report (and the open scene) with the team its content suggests; the user confirms."""
    scene = ws.scene(scene_id) if scene_id and scene_id in ws.scenes else None
    with ws.lock:
        return {"teams": document.TEAMS, "models": document.guess_teams(ws.report(_report(report_id)), scene)}


@app.post("/api/reports/{report_id}/document/stream")
def document_stream(report_id: str, body: DocumentRequest, request: Request):
    """A coordination report: PDF(s) combined, per team or per model, plus BCF. Needs the report's triage. Streams
    progress as newline-delimited JSON, then {"type": "ready", url, name}. Costs one proposal."""
    report = ws.report(_report(report_id))
    if body.scope not in ("combined", "team", "model"):
        raise HTTPException(422, "scope is combined, team or model.")
    # The verdicts the visitor sees (with their own "not a clash" marks applied), else the server's finished run. The
    # shared run can be gone (a restart) or running again (someone pressed Triage again) while the page still has one.
    job = _triage_jobs.get(_triage_key(report))
    verdicts = ({k: v for k, v in body.triage.items() if isinstance(v, dict) and v.get("verdict")} if body.triage
                else dict(job.results) if job is not None and job.done else {})
    if len(verdicts) < len(report.clashes) // 2:
        raise HTTPException(409, "Triage the report first: the report sorts clashes by its verdicts.")
    scene = ws.scene(body.scene_id) if body.scene_id and body.scene_id in ws.scenes else None
    refused = _take(propose_limit, request)
    if refused:
        raise HTTPException(429, refused)
    events: queue.Queue = queue.Queue()

    def work():
        try:
            doc = _build_document(report, verdicts, body.scene_id if scene is not None else None, body.scope, teams=body.teams, evidence=body.evidence,
                                  reviews=body.reviews, marks=body.marks, bcf=body.bcf, emit=events.put)
            events.put({"type": "ready", "url": doc["path"], "name": doc["name"], "bytes": doc["bytes"]})
        except Exception as e:
            events.put({"type": "error", "message": f"Could not build the report: {type(e).__name__}: {e}"})
        events.put(None)

    owner.spawn(work)

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event, default=str) + "\n"

    return _ndjson(stream())


def _build_document(report, verdicts: dict, scene_id: str | None, scope: str, *, teams: dict | None = None,
                    evidence: dict | None = None, reviews: dict | None = None, marks: dict | None = None,
                    bcf: bool = True, emit=None) -> dict:
    """Build a report and keep it for download: {path (the download route), name, bytes, file (a local copy)}."""
    scene = ws.scene(scene_id) if scene_id and scene_id in ws.scenes else None
    matches = ws.match(report.id, scene_id) if scene is not None else None
    data, name, media = document.generate(
        report, verdicts, ws.model, scope=scope, model_teams=teams or {}, matches=matches, scene=scene,
        evidence=evidence or {}, reviews=reviews or {}, marks=marks or {}, include_bcf=bcf, emit=emit or (lambda e: None))
    doc_id = uuid.uuid4().hex
    _documents[doc_id] = (data, name, media)
    while len(_documents) > 24:
        _documents.pop(next(iter(_documents)))
    local = EXPORTS / f"{doc_id}-{name}"
    local.write_bytes(data)
    return {"path": f"/api/documents/{doc_id}", "name": name, "bytes": len(data), "file": str(local)}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    if doc_id not in _documents:
        raise HTTPException(404, "That report has expired. Build it again.")
    data, name, media = _documents[doc_id]
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/transcribe")
async def transcribe_voice(request: Request, audio: UploadFile = File(...), report_id: str | None = Form(None)):
    """A spoken message to ORCA (Muse Voice Transcribe): a WAV clip in, its transcript out. The browser sends the
    transcript to the chat, so voice can do whatever the chat can. Biased toward BIM words and the open report's
    clash names."""
    data = await audio.read(MAX_VOICE_BYTES + 1)
    if len(data) > MAX_VOICE_BYTES:
        raise HTTPException(413, "That recording is too long: keep it under a minute.")
    try:
        with wave.open(io.BytesIO(data)) as w:
            fmt = (w.getnchannels(), w.getsampwidth(), w.getframerate())
    except (wave.Error, EOFError):
        raise HTTPException(422, "Send the recording as a WAV file.")
    if fmt[0] != 1 or fmt[1] != 2 or fmt[2] not in (16000, 24000):  # what Muse Voice Transcribe takes
        raise HTTPException(422, f"Send mono 16-bit WAV at 16 or 24 kHz (this is {fmt[0]} channel, {fmt[2]} Hz).")
    refused = _take(voice_limit, request)
    if refused:
        raise HTTPException(429, refused)
    words = list(VOICE_WORDS)
    if report_id and report_id in ws.reports:
        # What people say about a report's clashes: the elements' names (and Muse's titles), not their numbers.
        clashes = ws.report(report_id).clashes
        names = {e.name for c in clashes for e in (c.a, c.b) if e.name} | {c.title for c in clashes if c.title}
        words += sorted(names, key=lambda n: (len(n), n))[:40]
    try:
        return await run_in_threadpool(transcribe, data, words)
    except Exception as e:  # the key, the network or the service: say so rather than fail silently
        raise HTTPException(502, f"Transcription failed: {type(e).__name__}")

# ---------------------------------------------------------------------------------------------------------- agents
# "Connect an agent": a link (a secret token) lets an MCP client work on this visitor's session (agents.py), and the
# page follows what it does. The MCP server itself is mounted at /mcp below (mcp_server.py).

links = agents.Links()
ws.keep = links.kept  # what live links point at is evicted last
link_limit = ProposeLimit(int(os.environ.get("SIGHTLINE_LINKS_PER_HOUR", "0")),
                          int(os.environ.get("SIGHTLINE_LINKS_PER_DAY", "0")), noun="agent links")
agent_call_limit = ProposeLimit(int(os.environ.get("SIGHTLINE_AGENT_CALLS_PER_HOUR", "0")), 0, noun="agent calls")
MAX_CAPTURE_BYTES = 6_000_000


class LinkContext(BaseModel):
    scene_id: str | None = None
    report_id: str | None = None
    clash_id: str | None = None
    fixed: list[str] = []


def _link(token: str, touch: bool = True) -> agents.Link:
    """A live link: using it (a context update, an agent call) renews it; only reading its state does not."""
    link = links.get(token, touch=touch)
    if link is None:
        raise HTTPException(404, "This agent link has expired or was revoked.")
    return link


@app.post("/api/links")
def create_link(body: LinkContext, request: Request):
    """A new agent link for what this visitor has open. The token is shown once; only its hash is kept."""
    refused = _take(link_limit, request)
    if refused:
        raise HTTPException(429, refused)
    who = client_id(request.headers, request.client.host if request.client else None)
    token, link = links.create(who, owner.no_caps(), chat.Context(body.scene_id, body.report_id, body.clash_id,
                                                                  list(body.fixed)))
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return {"token": token, "mcp_url": f"{proto}://{host}/mcp", **link.public()}


@app.get("/api/links/{token}")
def link_state(token: str):
    return _link(token, touch=False).public()


@app.put("/api/links/{token}/context")
def link_context(token: str, body: LinkContext):
    """The page keeps the link's view of the session current: what is open, selected and fixed."""
    link = _link(token)
    link.ctx.scene_id, link.ctx.report_id, link.ctx.clash_id = body.scene_id, body.report_id, body.clash_id
    link.ctx.fixed = list(body.fixed)
    return link.public()


@app.get("/api/links/{token}/events")
async def link_events(token: str, request: Request):
    """What the agent does, for the page to follow (newline-delimited JSON): ui actions, agent calls, capture
    requests, a heartbeat every 15 s. Ends after a few minutes; the page reconnects."""
    link = _link(token)
    q = link.subscribe()

    async def stream():
        try:
            yield json.dumps({"type": "hello", **link.public()}) + "\n"
            idle = 0.0
            for _ in range(int(240 / 0.1)):  # under Modal's request limit; the page reconnects
                if await request.is_disconnected() or links.get(token, touch=False) is None:
                    break
                try:
                    event = q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.1)
                    idle += 0.1
                    if idle >= 15:
                        idle = 0.0
                        yield json.dumps({"type": "heartbeat"}) + "\n"
                    continue
                idle = 0.0
                yield json.dumps(event, default=str) + "\n"
        finally:
            link.unsubscribe(q)

    return _ndjson(stream())


@app.post("/api/links/{token}/captures/{capture_id}")
async def link_capture(token: str, capture_id: str, request: Request):
    """The page's answer to a capture request: a PNG of its view, or nothing (a clash's views went to the report)."""
    link = _link(token)
    data = await request.body()
    if len(data) > MAX_CAPTURE_BYTES:
        raise HTTPException(413, "That picture is too large.")
    if not link.deliver(capture_id, data or None):
        raise HTTPException(404, "Nobody is waiting for that picture any more.")
    return {"ok": True}


@app.delete("/api/links/{token}")
def revoke_link(token: str):
    return {"revoked": links.revoke(token)}


def mcp_hooks() -> mcp_server.Hooks:
    """What the MCP tools borrow from this server: links, the demo caps, triage and reports."""
    def charge(link: agents.Link, n: int) -> str | None:
        return None if link.owner else propose_limit.take_many(link.visitor, n)

    def start_triage(report_id: str, scene_id: str | None, link: agents.Link):
        return _start_triage(ws.report(report_id), scene_id, lambda: charge(link, 1))

    def build_document(report_id: str, scene_id: str | None, scope: str) -> dict:
        report = ws.report(report_id)
        job = _triage_jobs.get(_triage_key(report))
        verdicts = dict(job.results) if job is not None and job.done else {}
        if len(verdicts) < len(report.clashes) // 2:
            raise RuntimeError("Triage the report first (the triage tool): the report sorts clashes by its verdicts.")
        return _build_document(report, verdicts, scene_id, scope)

    return mcp_server.Hooks(
        links=links, charge=charge, allow_call=lambda link: agent_call_limit.take(link.id),
        start_triage=start_triage, triage_state=lambda rid, sid: triage_state(rid, sid),
        build_document=build_document, spawn=owner.spawn)


_mcp = mcp_server.build(lambda: ws, mcp_hooks())


def _mcp_transport():
    """The streamable-HTTP app for /mcp, with a new session manager (one per server start: it runs only once). One
    plain JSON response per call, no long-held stream: Modal cuts requests at ten minutes, and its edge buffers
    streams. Token-gated (`_McpGate`), so the transport's DNS-rebinding check (meant for localhost servers) is off."""
    return _mcp.streamable_http_app(stateless_http=True, json_response=True,
                                    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


class _McpGate:
    """/mcp for agents with a live link token: 401 otherwise. A `?key=` token becomes the Authorization header the
    tools read; responses go out uncompressed (Modal's edge)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        token = agents.token_from(headers, scope.get("query_string", b"").decode("latin-1"))
        if links.get(token, touch=False) is None:
            body = json.dumps({"error": "An ORCA agent link token is required: open ORCA, choose 'Connect an agent', "
                                        "and send it as 'Authorization: Bearer <token>'."}).encode()
            await send({"type": "http.response.start", "status": 401, "headers": [
                (b"content-type", b"application/json"), (b"www-authenticate", b'Bearer realm="orca"')]})
            await send({"type": "http.response.body", "body": body})
            return
        if "authorization" not in headers:
            scope = {**scope, "headers": [*scope.get("headers", []), (b"authorization", f"Bearer {token}".encode())]}

        async def send_identity(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), (b"content-encoding", b"identity")]}
            await send(message)
        await self.inner(scope, receive, send_identity)


_mcp_gate = _McpGate(None)
app.router.routes.insert(0, Route("/mcp", endpoint=_mcp_gate, methods=["GET", "POST", "DELETE"]))


@contextlib.asynccontextmanager
async def _lifespan(_app):
    _mcp_gate.inner = _mcp_transport()
    async with _mcp.session_manager.run():
        yield


app.router.lifespan_context = _lifespan

# Last, so /api routes win over static files.
if (WEB_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
