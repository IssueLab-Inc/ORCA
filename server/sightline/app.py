"""Web API for the browser app. Run: uv run uvicorn sightline.app:app --reload"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import io
import json
import os
import queue
import re
import shutil
import tempfile
import threading
import time
import uuid
import wave
import zlib
from dataclasses import asdict
from functools import partial
from typing import Callable
from http.cookies import CookieError, SimpleCookie
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import HTTPConnection
from starlette.routing import Route

from . import (agents, built, chat, checks, context_planner, demos, detect, document, domains, edits, escalation,
               faces, journal, manual, mcp_server, meta_client, owner, plans, property_edits, requirements, settings, spend,
               step, titles, triage, voice_live)
from .meta_client import escalation_info, labels as model_labels, transcribe, triage_model, triage_model_info
from .limits import ProposeLimit, client_id, env_float, env_int
from .service import MODEL_SUFFIXES, MODELS, StaleLayout, Workspace, project_name

# The repo's .env was read on the package's first import (sightline/__init__.py), before any module read a setting.
app = FastAPI(title="ORCA")


class _OwnerContext:
    """Each request knows whether it is the owner's (the signed cookie) and carries the owner's settings (owner.py)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.inner(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        jar = SimpleCookie()
        try:
            jar.load(headers.get(b"cookie", b"").decode("latin-1"))
        except CookieError:
            pass
        signed = jar[owner.COOKIE].value if owner.COOKIE in jar else None
        tokens = owner.enter(owner.cookie_ok(signed), headers.get(owner.HEADER.encode(), b"").decode("utf-8", "replace") or None)
        if scope["type"] == "websocket":  # live voice: only whether it is the owner (no caps) matters
            try:
                return await self.inner(scope, receive, send)
            finally:
                owner.leave(tokens)
        # Everyone's coordination requirements (requirements.py): an id the page registered. One this server does not
        # know (a restart) is refused, so the page registers its file again rather than run without it.
        rid = headers.get(requirements.HEADER.encode(), b"").decode("latin-1").strip() or None
        if rid and requirements.lookup(rid) is None and scope.get("path", "").startswith("/api/"):
            owner.leave(tokens)
            body = json.dumps({"detail": "requirements_unknown"}).encode()
            await send({"type": "http.response.start", "status": 409,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        token = requirements.enter(rid)
        try:
            await self.inner(scope, receive, send)
        finally:
            requirements.leave(token)
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
escalate_limit = ProposeLimit.escalate_from_env()
chat_limit = ProposeLimit.chat_from_env()
# Show it built (docs/show-it-built.md): pictures checked by Muse Wonder, a few cents each (SIGHTLINE_BUILT_PER_HOUR per
# visitor, _PER_DAY for everyone); a request costs up to two rounds of two pictures and two judges each.
built_limit = ProposeLimit(env_int("SIGHTLINE_BUILT_PER_HOUR", 0),
                           env_int("SIGHTLINE_BUILT_PER_DAY", 0), noun="built views")
unlock_limit = ProposeLimit(5, 50, noun="unlock attempts")  # wrong owner tokens, per visitor and for everyone
# Clash titles: one titling run per report (a few model calls for a whole report): SIGHTLINE_TITLES_PER_HOUR per visitor.
title_limit = ProposeLimit(env_int("SIGHTLINE_TITLES_PER_HOUR", 0),
                           env_int("SIGHTLINE_TITLES_PER_DAY", 0), noun="titling runs")
# Detection runs cost no model call but take the server's CPU for seconds: SIGHTLINE_DETECT_PER_HOUR per visitor.
detect_limit = ProposeLimit(env_int("SIGHTLINE_DETECT_PER_HOUR", 0),
                            env_int("SIGHTLINE_DETECT_PER_DAY", 0), noun="detection runs")
# The run that lists what a hand edit was kept with is not a detection run's charge, but it has a cap of its own, three
# times the detection cap, so keep, run, undo, keep again cannot be farmed for free runs.
edit_rerun_limit = ProposeLimit(3 * detect_limit.per_client_hour, 3 * detect_limit.per_day, noun="runs after hand edits")
voice_limit = ProposeLimit(env_int("SIGHTLINE_VOICE_PER_HOUR", 0),
                           env_int("SIGHTLINE_VOICE_PER_DAY", 0), noun="voice messages")
# Model uploads (IFC or STEP): each takes disk, memory and, for STEP, a conversion and one model call to name its parts.
model_upload_limit = ProposeLimit(env_int("SIGHTLINE_MODEL_UPLOADS_PER_HOUR", 0),
                                  env_int("SIGHTLINE_MODEL_UPLOADS_PER_DAY", 0), noun="model uploads")

# Coordination requirements (requirements.py): registering a file is cheap, a preview runs a detection.
requirements_limit = ProposeLimit(env_int("SIGHTLINE_REQUIREMENTS_PER_HOUR", 120),
                                  env_int("SIGHTLINE_REQUIREMENTS_PER_DAY", 0), noun="requirements files")
preview_limit = ProposeLimit(env_int("SIGHTLINE_PREVIEW_PER_HOUR", 60),
                             env_int("SIGHTLINE_PREVIEW_PER_DAY", 0), noun="requirement previews")

MAX_VOICE_BYTES = 3_000_000  # a minute of 16 kHz mono 16-bit PCM is 1.9 MB; the browser stops recording at 60 s
# Live voice (voice_live.py): hold to talk runs as long as a recording may; hands-free keeps the mic open longer.
VOICE_HOLD_MAX_S = env_float("SIGHTLINE_VOICE_HOLD_MAX_S", 60)
VOICE_HANDS_FREE_MAX_S = env_float("SIGHTLINE_VOICE_LIVE_MAX_S", 120)
# Words Muse Voice Transcribe should lean toward: what people say to ORCA about any model, then the domain's own
# (`domains.VOICE`) and the open models' and report's names (`_voice_words`).
VOICE_WORDS = ["ORCA", "Orca", "clash", "clashes", "offset", "trim", "reroute", "clearance", "IFC", "STEP", "BCF",
               "Navisworks", "triage", "root cause", "x-ray", "section box", "isolate", "requirements"]
# The built web app (`cd web && npm run build`), served from the same origin when present.
WEB_DIST = Path(os.environ.get("SIGHTLINE_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))


class Open(BaseModel):
    samples: list[str]


class Move(BaseModel):
    moved: list[str]
    delta_m: list[float]
    clearance_m: float | None = None   # None: the pair's (Workspace.clearance)
    obstacles: list[str] = []   # what the move must clear: what the moved elements stand on is then kept (verify.supports)


class Propose(BaseModel):
    element_a: str
    element_b: str
    distance_m: float | None = None
    notes: str = ""
    report_id: str | None = None  # a clash from an open report: its distance and images go to the model
    clash_id: str | None = None
    escalate: bool = False        # a second, longer try on Muse Wonder (docs/escalation.md), reading the last one


def escalation_refused(who: str, exempt: bool) -> tuple[int, str] | None:
    """Why this visitor may not make a second try now, as (HTTP status, words), or None: second tries switched off,
    the day's Muse Wonder budget spent, or the caps (a second try is one escalation and one proposal). `exempt`: the
    owner's own requests skip the caps and the budget."""
    if settings.escalation() == "off":
        return 403, "Second tries with Muse Wonder are switched off."
    why = spend.claim(escalation.ESTIMATE_USD, exempt)   # checked and held at once; the second try takes it over
    if why:
        return 429, why
    if exempt:
        return None
    why = ProposeLimit.take_all(who, escalate_limit, propose_limit)
    if why:
        spend.unclaim(escalation.ESTIMATE_USD)
        return 429, why
    return None


def _escalation_check(request: HTTPConnection) -> Callable[[], str | None]:
    """`escalation_refused` for this request, for work that decides later (automatic second tries, chat)."""
    who = client_id(request.headers, request.client.host if request.client else None)
    exempt = owner.no_caps()

    def check() -> str | None:
        r = escalation_refused(who, exempt)
        return r[1] if r else None
    return check


class Offset(BaseModel):
    element: str
    split_m: list[float]
    dz_m: float
    other: str | None = None   # the obstacle, for checking
    clearance_m: float | None = None   # None: the pair's (Workspace.clearance)


class PageFilter(BaseModel):
    """One of the user's filters, as the page shares it with chat and an agent link (docs/filters.md): what it finds,
    by name, for a check on it (detect_clashes)."""
    id: str = Field("", max_length=100)
    name: str = Field("", max_length=200)
    when: list[dict] = Field(default_factory=list, max_length=30)
    invert: bool = False
    on: bool = True
    origin: str | None = Field(None, max_length=20)
    # What it does (colour, byValue, hide, isolate) and, colouring by value, by what and the values ticked off: a
    # filter as a check's side takes what it acts on, and together the filters say what the page shows.
    action: str | None = Field(None, max_length=20)
    by: dict | None = None


class FilterView(BaseModel):
    """How the page's filters show together: the rest hidden (Hide the rest), and colours on (docs/filters.md)."""
    hide_rest: bool = False
    colours: bool = True


class ChatTurn(BaseModel):
    message: str
    session_id: str | None = None
    scene_id: str | None = None
    report_id: str | None = None
    clash_id: str | None = None
    fixed: list[str] = []
    filters: list[PageFilter] = Field(default_factory=list, max_length=100)
    filter_view: FilterView = Field(default_factory=FilterView)
    check: str | None = None   # the kept check the page's list shows (None: all of them)
    selected: dict | None = None   # what the user has selected: {element, face?, pick?} (the Edit tool's face)


class PlanRequest(BaseModel):
    report_id: str
    clash_ids: list[str] = []   # fix these together
    hub: str | None = None      # or: fix the root cause around this element
    fixed: list[str] = []


class PlanApply(BaseModel):
    options: list[dict]
    clash_ids: list[str | None] | None = None   # per option, the clash it was accepted for (the edit log ties them)


class OpenReport(BaseModel):
    sample: str


class DetectRequest(BaseModel):
    tests: list[dict] | None = None  # None: the default tests (GET /detect/tests); see detect.Test.from_dict
    check: str | None = None         # a kept check, by key: run it again with the tests it ran with
    all: bool = False                # run every kept check again, one after another (one detection run)
    after_edit: str | None = None    # the hand edit kept with clashes this run lists (its entry): that one run is free


# Uploaded clash reports: XML plus the images it links to, kept in a temp folder while the report is open.
UPLOADS = Path(tempfile.gettempdir()) / "sightline-reports"
UPLOAD_MAX_MB = env_int("SIGHTLINE_UPLOAD_MAX_MB", 200)
UPLOAD_MAX_FILES = env_int("SIGHTLINE_UPLOAD_MAX_FILES", 5000)
UPLOAD_TYPES = {".xml", ".png", ".jpg", ".jpeg"}
MODEL_UPLOAD_MAX_MB = env_int("SIGHTLINE_MODEL_UPLOAD_MAX_MB", UPLOAD_MAX_MB)
MODEL_UPLOAD_MAX_FILES = env_int("SIGHTLINE_MODEL_UPLOAD_MAX_FILES", 8)


def _gone(kind: str, ident: str) -> dict[str, str]:
    """The header on a 404 for a scene or report the server no longer holds (a restart, or let go to make room):
    `X-Sightline-Gone: scene:<id>`, so the page offers to open them again rather than show each call's error. Only an
    id the server could have made goes back in a header."""
    return {"X-Sightline-Gone": f"{kind}:{ident}"} if re.fullmatch(r"[0-9a-f]{1,32}", ident) else {}


def _scene(scene_id: str):
    if scene_id not in ws.scenes:
        raise HTTPException(404, "Model not loaded. Open it again.", headers=_gone("scene", scene_id))
    return scene_id


def _take(limit: ProposeLimit, request: HTTPConnection) -> str | None:
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
    """Which model this request's titles and triage would use (the owner's choice, else everyone's), for the copy, and
    how much a visitor may upload (the page checks before sending, and says so)."""
    return {"triage": triage_model_info(), "escalation": escalation_info(), "built_views": settings.built_views(),
            "labels": model_labels(), "triage_workers": env_int("SIGHTLINE_TRIAGE_WORKERS", triage.WORKERS),
            "model_upload_max_mb": MODEL_UPLOAD_MAX_MB, "model_upload_max_files": MODEL_UPLOAD_MAX_FILES}


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
    """The sample models, and the demos among them (`demos.listing`: their files, start label and tour)."""
    files = ws.list_samples()
    return {"files": files, "demos": demos.listing(files)}


def _classifier():
    """The model that names a STEP file's parts (the titles' and triage's model), or None without one."""
    try:
        return triage_model()[0]
    except Exception:
        return None


def _files_of(sid: str) -> dict:
    """What every way of opening or changing a scene's models answers with: its files in order, which came from STEP
    (by index), its revision and its layout (bumped when a model is added or removed: docs/add-and-remove-models.md)."""
    scene = ws.scene(sid)
    return {"id": sid, "files": list(ws.names.get(sid, [])), "step": ws.step_files(sid), "revision": scene.revision,
            "layout": scene.layout}


@app.post("/api/scenes")
def open_scene(body: Open):
    """Open sample models. A STEP sample is converted to IFC first (cached by its contents, so only the first
    opening pays for it)."""
    try:
        needs = any(Path(n).suffix.lower() in step.SUFFIXES for n in body.samples)
        sid = ws.open(body.samples, classify_with=_classifier() if needs else None)
        return _files_of(sid)
    except FileNotFoundError as e:
        raise HTTPException(404, f"No model called {e.args[0]}.")
    except step.StepError as e:
        raise HTTPException(400, str(e))


@app.post("/api/scenes/{scene_id}/models")
def add_sample_models(scene_id: str, body: Open):
    """Add sample models to an open scene (docs/add-and-remove-models.md): free, like opening samples. Everything kept
    stays; run the checks again to list the new clashes. 400 with why for STEP among building models or the reverse,
    a name already open or a set past the byte budget; 404 for a sample there is not."""
    _scene(scene_id)
    if not body.samples:
        raise HTTPException(400, "Choose a model to add.")
    try:
        needs = any(Path(n).suffix.lower() in step.SUFFIXES for n in body.samples)
        added = ws.add_samples(scene_id, body.samples, classify_with=_classifier() if needs else None)
        return {**_files_of(scene_id), "added": added}
    except FileNotFoundError as e:
        raise HTTPException(404, f"No model called {e.args[0]}.")
    except StaleLayout as e:
        raise HTTPException(409, str(e))
    except (ValueError, step.StepError) as e:
        raise HTTPException(400, str(e))
    except KeyError:
        _scene(scene_id)   # dropped meanwhile: the usual 404
        raise


@app.delete("/api/scenes/{scene_id}/models/{index}")
def remove_scene_model(scene_id: str, index: int, name: str):
    """Take a model out of an open scene: `name` is the file the page means at `index` (409 when the list has changed
    since: reload the files). Its clashes leave every kept check and the list, the edits kept in it stay in the log
    but can't be undone, an uploaded file is deleted. Answers the files, `removed` ({name, clashes, edits}), the
    report listing what is left (null when nothing is) and the checks."""
    _scene(scene_id)
    try:
        return {"id": scene_id, **ws.remove_model(scene_id, index, name)}
    except StaleLayout as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


class _TooBig(Exception):
    pass


UNPACK_STEP = 1 << 20   # bytes out of the gunzip per step: a small archive of zeros never inflates in one call


def _unpack(src, dest: Path, gz: bool, room: int) -> int:
    """Copy `src` (an uploaded part's file) to `dest`, gunzipping it when `gz`, writing at most `room` bytes
    (else _TooBig, as soon as it is past). A truncated archive is a zlib.error. Blocking: run it off the event loop."""
    written = 0
    unzip = zlib.decompressobj(16 + zlib.MAX_WBITS) if gz else None
    with dest.open("wb") as out:
        def put(data: bytes) -> None:
            nonlocal written
            written += len(data)
            if written > room:
                raise _TooBig
            out.write(data)
        while chunk := src.read(1 << 20):
            if unzip is None:
                put(chunk)
                continue
            while True:   # bounded steps until this chunk is used up and nothing is pending
                data = unzip.decompress(chunk, UNPACK_STEP)
                put(data)
                chunk = unzip.unconsumed_tail
                if unzip.eof or (not chunk and len(data) < UNPACK_STEP):
                    break
        if unzip is not None:
            put(unzip.flush())
            if not unzip.eof:
                raise zlib.error("the archive ends before its end")
    return written


async def _receive_models(request: Request, check: Callable[[list[str]], None] | None = None
                          ) -> tuple[Path, list[Path], list[str]]:
    """Check, receive and unpack an upload of model files: IFC or STEP, each as is or gzipped by the page (`.gz`, the
    name without it). Refused before the body is read when it has no length (411: a chunked body would be spooled
    whole before any check) or its length alone is over the cap; the cap (SIGHTLINE_MODEL_UPLOAD_MAX_MB, all files
    together) counts the unpacked size, checked in bounded steps off the event loop. `check` refuses by the names
    (an HTTPException) before the upload allowance is charged. Returns the folder (deleted with the scene, or here on
    failure), the paths and the names."""
    cap = MODEL_UPLOAD_MAX_MB << 20
    try:
        length = int(request.headers["content-length"])
    except (KeyError, ValueError):
        raise HTTPException(411, "Send the upload with its length (Content-Length).") from None
    if length > cap + (1 << 20):   # compressed or not, the body is never bigger than what it unpacks to (plus a form)
        raise HTTPException(413, f"Upload is over {MODEL_UPLOAD_MAX_MB} MB.")
    form = await request.form(max_files=MODEL_UPLOAD_MAX_FILES + 1)
    files = [v for v in form.getlist("files") if not isinstance(v, str)]
    if not files or len(files) > MODEL_UPLOAD_MAX_FILES:
        raise HTTPException(400, f"Choose 1 to {MODEL_UPLOAD_MAX_FILES} model files.")
    packed = [Path(f.filename or "").name for f in files]
    names = [n[:-3] if n.lower().endswith(".gz") else n for n in packed]
    bad = [n for n in names if Path(n).suffix.lower() not in MODEL_SUFFIXES]
    if bad:
        raise HTTPException(400, f"{bad[0]} is not an IFC or STEP file (.ifc, .step, .stp).")
    if len(set(names)) < len(names):
        raise HTTPException(400, "A file was given twice.")
    if check is not None:
        check(names)
    refused = _take(model_upload_limit, request)
    if refused:
        raise HTTPException(429, refused)
    MODELS.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(dir=MODELS))
    total, paths = 0, []
    try:
        for f, name, sent in zip(files, names, packed):
            dest = root / name
            await f.seek(0)
            total += await run_in_threadpool(_unpack, f.file, dest, sent != name, cap - total)
            paths.append(dest)
        return root, paths, names
    except _TooBig:
        shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(413, f"Upload is over {MODEL_UPLOAD_MAX_MB} MB.") from None
    except zlib.error:
        shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(400, "A compressed model file could not be unpacked.")
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


@app.post("/api/models/upload")
async def upload_models(request: Request):
    """Open your own models: IFC, or STEP (converted to IFC to check; Export gives the STEP back with the fixes).
    Files that share coordinates open together. Capped per visitor (SIGHTLINE_MODEL_UPLOADS_PER_HOUR/DAY) and in size
    (SIGHTLINE_MODEL_UPLOAD_MAX_MB for all files together, unpacked). `/upload/stream` does the same with progress."""
    root, paths, names = await _receive_models(request)
    try:
        needs = any(p.suffix.lower() in step.SUFFIXES for p in paths)
        classifier = _classifier() if needs else None
        sid = await run_in_threadpool(lambda: ws.open_paths(paths, root, classify_with=classifier))
        return _files_of(sid)
    except step.StepError as e:  # open_paths already removed the folder
        raise HTTPException(400, str(e))
    except Exception as e:  # not a model IfcOpenShell can read
        shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(400, f"Could not open the models: {type(e).__name__}: {e}")


@app.post("/api/models/upload/stream")
async def upload_models_stream(request: Request):
    """The same as /upload, answered as newline-delimited JSON once the files are in, so a big model's opening shows
    progress and never meets an idle timeout: {"type": "received", "bytes"}, the STEP conversion's events, {"type":
    "opening"}, {"type": "boxes", "done", "total"} (elements measured), {"type": "tick"} every 5 s, then {"type":
    "done", "id", "files", "step", "revision"} or {"type": "error", "status", "detail"}. Refusals before the files
    are in (size, count, type, allowance) are plain HTTP errors."""
    root, paths, names = await _receive_models(request)
    events: queue.Queue = queue.Queue()
    events.put({"type": "received", "bytes": sum(p.stat().st_size for p in paths)})

    def work():
        try:
            needs = any(p.suffix.lower() in step.SUFFIXES for p in paths)
            classifier = _classifier() if needs else None
            sid = ws.open_paths(paths, root, classify_with=classifier, on_event=events.put)
            events.put({"type": "done", **_files_of(sid)})
        except step.StepError as e:  # open_paths already removed the folder
            events.put({"type": "error", "status": 400, "detail": str(e)})
        except Exception as e:  # not a model IfcOpenShell can read
            shutil.rmtree(root, ignore_errors=True)
            events.put({"type": "error", "status": 400, "detail": f"Could not open the models: {type(e).__name__}: {e}"})
        events.put(None)

    owner.spawn(work)
    return _ndjson(_ticking(events))


def _ticking(events: queue.Queue):
    """A model stream's events as NDJSON until None, with a tick every 5 s: opening a big model can take minutes, and
    an idle connection would be timed out."""
    while True:
        try:
            event = events.get(timeout=5)
        except queue.Empty:
            yield json.dumps({"type": "tick"}) + "\n"
            continue
        if event is None:
            return
        yield json.dumps(event) + "\n"


@app.post("/api/scenes/{scene_id}/models/upload/stream")
async def add_uploaded_models_stream(scene_id: str, request: Request):
    """Add your own models to an open scene (docs/add-and-remove-models.md), answered as /api/models/upload/stream is:
    one model upload against the allowance, the same size cap and events, then {"type": "done", "id", "files", "step",
    "revision", "layout", "added"} or {"type": "error", "status", "detail"}. STEP among building models (or the
    reverse) and a name already open are refused (400) before anything is charged; past the byte budget, once the
    files are in, an error event."""
    _scene(scene_id)

    def check(names: list[str]) -> None:
        try:
            ws.check_adding(scene_id, [Path(n) for n in names])
        except KeyError:
            _scene(scene_id)
            raise
        except ValueError as e:
            raise HTTPException(400, str(e))

    root, paths, names = await _receive_models(request, check)
    events: queue.Queue = queue.Queue()
    events.put({"type": "received", "bytes": sum(p.stat().st_size for p in paths)})

    def work():
        try:
            needs = any(p.suffix.lower() in step.SUFFIXES for p in paths)
            classifier = _classifier() if needs else None
            added = ws.add_models(scene_id, paths, root, classify_with=classifier, on_event=events.put)
            events.put({"type": "done", **_files_of(scene_id), "added": added})
        except StaleLayout as e:   # add_models removed the folder
            events.put({"type": "error", "status": 409, "detail": str(e)})
        except (ValueError, step.StepError) as e:
            events.put({"type": "error", "status": 400, "detail": str(e)})
        except KeyError:
            events.put({"type": "error", "status": 404, "detail": "Model not loaded. Open it again."})
        except Exception as e:  # not a model IfcOpenShell can read
            events.put({"type": "error", "status": 400, "detail": f"Could not add the models: {type(e).__name__}: {e}"})
        events.put(None)   # add_models deletes the folder whenever it fails

    owner.spawn(work)
    return _ndjson(_ticking(events))


@app.get("/api/scenes/{scene_id}")
def scene_info(scene_id: str):
    """A scene the page had open (to resume after a reload or a closed tab): 404 once the server no longer holds it."""
    return ws.scene_info(_scene(scene_id))


EXPORTS_KEEP_S = env_int("SIGHTLINE_EXPORTS_KEEP_S", 3600)   # written models and exports older than this are deleted (a big model's export is big)


def _tidy_exports() -> None:
    cutoff = time.time() - EXPORTS_KEEP_S
    for p in EXPORTS.iterdir():
        try:
            if p.stat().st_mtime >= cutoff:
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        except OSError:
            continue


@app.get("/api/scenes/{scene_id}/files/{index}")
def scene_file(scene_id: str, index: int):
    _tidy_exports()
    paths = ws.scene(_scene(scene_id)).paths
    if not 0 <= index < len(paths):
        raise HTTPException(404, "No such file in this model set.")
    # Never cached: after an accepted edit the same URL serves the edited model.
    return FileResponse(ws.file(scene_id, index, EXPORTS), media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/scenes/{scene_id}/elements/{global_id}")
def element(scene_id: str, global_id: str):
    return ws.describe(_scene(scene_id), global_id)


@app.get("/api/scenes/{scene_id}/datums")
def scene_datums(scene_id: str):
    """Levels, grid axes and each element's storey (datums.read): the drawing views' levels, grids and plan defaults,
    and the viewer's level filter. Metres, IFC axes."""
    return ws.datums(_scene(scene_id))


@app.get("/api/scenes/{scene_id}/elements/{global_id}/properties")
def element_properties(scene_id: str, global_id: str, file: int | None = None):
    """Everything the model says about one object, for the Properties panel (properties.py). `file` (the model's
    index) picks the file when federated files repeat a GlobalId, as a breadcrumb's storey may."""
    try:
        return ws.properties(_scene(scene_id), global_id, file)
    except KeyError:
        raise HTTPException(404, "No such element in these models.")


class PropertyEdit(BaseModel):
    change: dict   # {kind: attribute|property|type|material|classification|container, ...} (property_edits.plan)


@app.get("/api/scenes/{scene_id}/elements/{global_id}/property-choices")
def element_property_choices(scene_id: str, global_id: str):
    """What an element's properties can be set to from its own model (property_edits.choices): its editable attributes
    and predefined types, the types of its kind, materials, storeys and spaces, classification references."""
    sid = _scene(scene_id)
    try:
        with ws.lock:
            return property_edits.choices(ws.scene(sid), global_id)
    except KeyError:
        raise HTTPException(404, "No such element in these models.")


@app.post("/api/scenes/{scene_id}/elements/{global_id}/properties")
def edit_element_property(scene_id: str, global_id: str, body: PropertyEdit):
    """Change one thing the model says about an element, not its shape (property_edits.edit): kept through the edit
    log; 422 with why when it cannot be made. Returns the entry and the element's properties now."""
    try:
        return property_edits.edit(ws, _scene(scene_id), global_id, body.change, source="you")
    except KeyError:
        raise HTTPException(404, "No such element in these models.")
    except edits.Unsupported as e:
        raise HTTPException(422, f"Cannot make this change: {e}")
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Not a change ORCA can make: {e}")


@app.get("/api/scenes/{scene_id}/facets")
def scene_facets(scene_id: str):
    """The filters' index (facets.py, docs/filters.md): each facet (file, class, storey, type, material, attributes,
    property and quantity sets, classifications, groups) with its values and, per value, the elements that have it."""
    return ws.facets(_scene(scene_id))


@app.get("/api/scenes/{scene_id}/classes")
def element_classes(scene_id: str):
    """Every physical element's IFC class and name (GlobalId → [class, name]): what a built view's cutaway may take
    away costs by class (Viewer.captureBuilt), and its caption says what was taken away by name."""
    return ws.classes(_scene(scene_id))


BUILT_PASS_MAX = 12_000_000   # characters per pass: a 2048 px PNG as a data URL, with room


class BuiltBody(BaseModel):
    look: str = Field(max_length=BUILT_PASS_MAX)      # PNG data URLs of one camera (Viewer.captureBuilt): true colours,
    ids: str = Field(max_length=BUILT_PASS_MAX)       # one flat colour per element (index + 1, 24 bits),
    normals: str = Field(max_length=BUILT_PASS_MAX)   # and view-space normals
    fix_kind: str = ""       # what kind of fix it shows (a trim is not drawn: too small at this scale)
    title: str = ""


@app.post("/api/scenes/{scene_id}/built/stream")
def built_stream(scene_id: str, body: BuiltBody, request: Request):
    """Show it built (docs/show-it-built.md): Muse Image restyles the page's view of a fix and the picture is checked
    against the model (built.make). NDJSON: drawing, gate, judging, judged, retry, then {"type": "result",
    status: "done" | "failed", ...} or {"type": "error"}. A picture already made for the same view costs nothing."""
    _scene(scene_id)
    if not settings.built_views():
        raise HTTPException(403, "Show it built is switched off.")
    if body.fix_kind in ("trim", "seat"):
        raise HTTPException(422, f"A {body.fix_kind} is too small to show at this scale: the model's own view shows it.")
    try:
        p = built.passes(body.look, body.ids, body.normals)
    except built.Refused as e:
        raise HTTPException(422, str(e))
    events = _RequestEvents(request)
    exempt = owner.no_caps()
    # Wonder's judges when the day's budget covers them; else the pictures with Muse Spark's lighter check.
    lighter = bool(spend.refused(built.ESTIMATE_USD, exempt))
    hit = built.cached(p.key)
    if hit is not None and hit.get("judge") == "Muse Spark" and not lighter:
        hit = None   # checked the lighter way when Wonder couldn't be paid for: check it properly now
    hold = built.PICTURES_USD if lighter else built.ESTIMATE_USD
    claimed = False
    if hit is None and not built.running(p.key):   # one being made now is shared, at no cost
        why = spend.claim(hold, exempt)           # checked and held at once; the work takes it over
        claimed = why is None
        why = why or _take(built_limit, request)
        if why:
            if claimed:
                spend.unclaim(hold)
            raise HTTPException(429, why)

    def work():
        try:
            if hit:
                events.put({"type": "result", **hit})
                return
            with spend.held(hold):
                out = (built.make(p, events.put, judge_model_fn=built.spark_judge_model, judges=built.SPARK_JUDGES,
                                  judged_by="Muse Spark") if lighter else built.make(p, events.put))
            events.put({"type": "result", **out})
        except Exception as e:  # the models or the check failed: tell the page rather than cut the stream
            events.put({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        finally:
            events.put(None)

    owner.spawn(work)
    return _ndjson(events.stream())


@app.get("/api/built/{name}")
def built_file(name: str):
    """A checked picture (`<key>.jpg`) or its outline (`<key>-lines.png`), by the name a result gave."""
    path = built.path_of(name)
    if path is None:
        raise HTTPException(404, "No such picture.")
    return FileResponse(path, media_type="image/jpeg" if name.endswith(".jpg") else "image/png",
                        headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/scenes/{scene_id}/connections")
def scene_connections(scene_id: str):
    """What is linked to what (joints, assemblies, hosted elements, what rests on what, contacts from the last check),
    for the viewer's connection highlight; cached until the scene changes."""
    return ws.connections(_scene(scene_id))


@app.post("/api/scenes/{scene_id}/verify")
def verify_move(scene_id: str, body: Move):
    return ws.verify_move(_scene(scene_id), body.moved, body.delta_m, body.clearance_m, body.obstacles)


def _refuse_escalation(request: HTTPConnection, scene_id: str, body: "Propose") -> None:
    """Refuse a second try that cannot be made (nothing may be edited: 409) before charging anything, then one that
    the switch, the budget or the caps refuse."""
    recommend = ws.fix_settings(scene_id, body.element_a, body.element_b).get("recommend")
    if recommend:
        raise HTTPException(409, f"Nothing may be edited here ({recommend}), so there is no second try to make.")
    r = escalation_refused(client_id(request.headers, request.client.host if request.client else None),
                           owner.no_caps())
    if r:
        raise HTTPException(*r)


@app.post("/api/scenes/{scene_id}/propose")
def propose(scene_id: str, body: Propose, request: Request):
    _scene(scene_id)
    if body.report_id:
        _report(body.report_id)
    if body.escalate:
        _refuse_escalation(request, _scene(scene_id), body)
        try:
            return ws.escalate(_scene(scene_id), body.element_a, body.element_b, body.distance_m, notes=body.notes,
                               report_id=body.report_id, clash_id=body.clash_id)
        except ValueError as e:
            raise HTTPException(409, str(e))
    refused = _take(propose_limit, request)
    if refused:
        raise HTTPException(429, refused)
    return ws.propose(_scene(scene_id), body.element_a, body.element_b, body.distance_m, notes=body.notes,
                      report_id=body.report_id, clash_id=body.clash_id, escalate_check=_escalation_check(request))


@app.post("/api/scenes/{scene_id}/propose/stream")
def propose_stream(scene_id: str, body: Propose, request: Request):
    """The same as /propose, as newline-delimited JSON events while it works: the agent's progress
    (see agent.resolve; a second try adds {"type": "escalating", "model", "first"} and names its model on every
    event), then {"type": "result", ...} or {"type": "error", "detail": ...}."""
    _scene(scene_id)
    if body.report_id:
        _report(body.report_id)
    if body.escalate:
        _refuse_escalation(request, _scene(scene_id), body)
    else:
        refused = _take(propose_limit, request)
        if refused:
            raise HTTPException(429, refused)
    check = _escalation_check(request)
    events: queue.Queue = queue.Queue()

    def work():
        try:
            run = ws.escalate if body.escalate else partial(ws.propose, escalate_check=check)
            result = run(scene_id, body.element_a, body.element_b, body.distance_m, notes=body.notes,
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


def _with_patch(scene_id: str, kept) -> dict:
    """Keep a fix (`kept()` returns the Workspace's reply, with "changed") and add what the page needs to update its
    model in place (`Workspace.patch`)."""
    with ws.lock:   # one request's edits between `before` and the patch, never another tab's
        before = ws.scene(scene_id).revision
        r = kept()
        return {**r, **ws.patch(scene_id, r.get("changed", []), before, removed=r.get("removed", []))}


def _keep(scene_id: str, options: list[dict], what: str, clash_ids: list[str | None] | None = None) -> dict:
    """Keep fixes through `plans.apply`, which tries each again first (as its proposal did, with the clearance and
    requirements of its clash) and keeps all or none, plus what the page needs to patch its model. A fix that no longer
    passes is a 409 with why; one that cannot be made a 422; one that is not a fix ORCA knows a 400."""
    try:
        return _with_patch(_scene(scene_id), lambda: plans.apply(ws, scene_id, options, clash_ids=clash_ids))
    except plans.NotVerified as e:
        raise HTTPException(409, str(e))
    except edits.Unsupported as e:
        raise HTTPException(422, f"Cannot apply {what}: {e}")
    except (ValueError, KeyError, TypeError, IndexError) as e:
        raise HTTPException(400, f"Not a fix ORCA can apply: {e}")


def _one(r: dict) -> dict:
    """One fix's reply: `pieces`, the first run's, as one fix of one run has always replied; `groups`, every run's (a
    combined fix)."""
    out = {**r, "pieces": r["pieces"][0], "groups": r["groups"][0]}
    if r.get("not_cut"):   # a penetration requested, not cut: the clash stays open until the host's team cuts it
        out.update(cut=False, blocked_by=r["not_cut"][0]["blocked_by"])
    return out


@app.post("/api/scenes/{scene_id}/apply")
def apply(scene_id: str, body: Move):
    """Keep a move of `moved` (its whole run) by `delta_m`, tried again first against `obstacles` (the clash's other
    element first). The clearance is the requirements' (25 mm without any), not the body's."""
    if not body.moved or not body.obstacles:
        raise HTTPException(422, "Say what moves (moved) and what it must clear (obstacles): a move is checked "
                                 "against its clash again before it is kept.")
    return _one(_keep(scene_id, [{"kind": "move", "title": "Move", "moved": body.moved, "delta_m": body.delta_m,
                                  "pair": [body.moved[0], body.obstacles[0]], "others": body.obstacles[1:]}],
                      "this move"))


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
        return _with_patch(scene_id, lambda: context_planner.accept(ws, scene_id, body.proposal_id,
                                                                     body.acknowledged_conditions))
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
    other: str | None = None   # the element it butts against: the trim is checked against it again before it is kept


@app.post("/api/scenes/{scene_id}/trim/apply")
def apply_trim(scene_id: str, body: TrimBody):
    if not body.other:
        raise HTTPException(422, "Say which element the trim butts against (other).")
    return _one(_keep(scene_id, [{"kind": "trim", "title": "Trim", "moved": [body.element], "delta_m": [0, 0, 0],
                                  "trim": {"end": body.end, "by_m": body.by_m}, "pair": [body.element, body.other]}],
                      "this trim"))


@app.post("/api/scenes/{scene_id}/offset/apply")
def apply_offset(scene_id: str, body: Offset):
    if not body.other:
        raise HTTPException(422, "Say which element the offset goes around (other).")
    return _one(_keep(scene_id, [{"kind": "offset", "title": "Offset", "moved": [body.element],
                                  "delta_m": [0, 0, body.dz_m], "split_m": body.split_m,
                                  "pair": [body.element, body.other]}], "this offset"))


class FixApply(BaseModel):
    option: dict
    clash_id: str | None = None   # the clash it was accepted for (the edit log ties them)


@app.post("/api/scenes/{scene_id}/fix/apply")
def fix_apply(scene_id: str, body: FixApply):
    """Keep one verified option of any kind (`plans.apply`, which every kind is registered with). The page's preview
    and before meshes are dropped: the fix is tried again on the server from its kind, its parameters and the clash it
    names (`pair`, and `others` for a plan's merged item), with the clearance and requirements of that clash, and what
    that trial makes is kept; one that no longer passes is a 409. A kind whose keeping depends on the requirements
    decides that in its `plans.KEEP` entry, never from what the page sends."""
    o = {k: v for k, v in body.option.items() if k not in ("preview", "before")}
    if not isinstance(o.get("moved"), list) or not o["moved"]:
        raise HTTPException(400, "The fix names no element.")
    return _one(_keep(scene_id, [o], "this fix", [body.clash_id]))


class FacePick(BaseModel):
    element: str
    point: list[float]
    normal: list[float]


class EditBody(BaseModel):
    op: dict
    key: str | None = None             # the check's: refused (409) when the model changed since
    accept_clashes: int = 0            # how many new clashes the person accepted ("Keep with N clashes")
    accept_joints: int = 0             # how many joints it may leave open ("Keep with N open joints")
    clash_id: str | None = None        # the clash on screen when it was made: the log ties the edit to it
    pair: list[str] | None = None      # that clash's two elements


@app.post("/api/scenes/{scene_id}/edit/face")
def edit_face(scene_id: str, body: FacePick):
    """The face of an element under a pick (faces.resolve): its kind, its name in words, what it allows."""
    s = ws.scene(_scene(scene_id))
    try:
        with ws.lock:
            face = faces.resolve(s, body.element, body.point, body.normal)
            return {**face.to_dict(), "label": manual.label(s, body.element),
                    "choices": manual.choices_for(s, body.element, face)}
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))


@app.get("/api/scenes/{scene_id}/elements/{global_id}/faces")
def element_faces(scene_id: str, global_id: str):
    """Every face of an element there is to edit, named (faces.faces): what Muse and a person can point at."""
    s = ws.scene(_scene(scene_id))
    try:
        with ws.lock:
            return {"element": global_id, "faces": [f.to_dict() for f in faces.faces(s, global_id)]}
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))


@app.post("/api/scenes/{scene_id}/edit/check")
def edit_check(scene_id: str, body: EditBody):
    """Try a hand edit without keeping it (manual.check): what it clears, what it would hit, the nearest gap, its
    warnings, and the preview meshes. A refusal comes back as `blocked` with why, not as an error."""
    return manual.check(ws, _scene(scene_id), body.op)


@app.post("/api/scenes/{scene_id}/edit/apply")
def edit_apply(scene_id: str, body: EditBody):
    """Keep a hand edit (manual.apply): checked again here first; 409 when the requirements refuse it, the model
    changed since its check, or it would make more clashes than `accept_clashes` or leave more joints open than
    `accept_joints`. Logged, then the patch."""
    try:
        return _with_patch(_scene(scene_id), lambda: manual.apply(ws, scene_id, body.op, key=body.key,
                                                                  accept_clashes=body.accept_clashes,
                                                                  accept_joints=body.accept_joints,
                                                                  clash_id=body.clash_id, pair=body.pair))
    except manual.NotKept as e:
        raise HTTPException(409, str(e))
    except edits.Unsupported as e:
        raise HTTPException(422, f"Cannot make this edit: {e}")
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, f"Not an edit ORCA can make: {e}")


class EditStep(BaseModel):
    entry: str | None = None   # the entry the page means: refused (409) when it is not the one next in line


@app.get("/api/scenes/{scene_id}/edits")
def edits_log(scene_id: str, format: str = "json"):
    """The scene's edit log (journal.py): every kept edit, by whom, for which clash, oldest first, with whether undo
    and redo can go now. `?format=csv` gives it as a spreadsheet."""
    _scene(scene_id)
    if format == "csv":
        return Response(ws.edits_csv(scene_id), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="orca-edits.csv"'})
    return ws.journal(scene_id).summary()


def _step(scene_id: str, go) -> dict:
    try:
        return _with_patch(_scene(scene_id), go)
    except journal.Fenced as e:
        raise HTTPException(409, f"Cannot do that: {e}.")


class EditPicture(BaseModel):
    png: str   # a data:image/ URL the page took of the edit, kept (at most journal.PICTURE_MAX_BYTES)


@app.post("/api/scenes/{scene_id}/edits/{entry_id}/picture")
def edits_picture(scene_id: str, entry_id: str, body: EditPicture):
    """A picture of a kept edit, taken by the page right after it (the server draws nothing): the report shows it
    as "After the edits" on its clash's page."""
    _scene(scene_id)
    try:
        ws.journal(scene_id).attach_picture(entry_id, body.png)
    except KeyError:
        raise HTTPException(404, f"No edit {entry_id} in this scene's log.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/scenes/{scene_id}/edits/undo")
def edits_undo(scene_id: str, body: EditStep):
    """Undo the newest kept edit: an agent fix, a plan, a wider fix or a hand edit. 409 when another edit came after
    it outside the log, or `entry` is not the newest."""
    return _step(scene_id, lambda: ws.undo_edit(scene_id, body.entry))


@app.post("/api/scenes/{scene_id}/edits/redo")
def edits_redo(scene_id: str, body: EditStep):
    return _step(scene_id, lambda: ws.redo_edit(scene_id, body.entry))


@app.get("/api/scenes/{scene_id}/export")
def export(scene_id: str):
    """The edited file. With edits in several discipline files (or a STEP model's STEP and IFC), they come back as one
    zip named for the project, `<project>-orca.zip` ("Northbank-orca.zip"), else `orca-export.zip`."""
    _tidy_exports()
    out = EXPORTS / scene_id
    out.mkdir(exist_ok=True)
    paths = ws.export(_scene(scene_id), out)
    if not paths:
        raise HTTPException(409, "Nothing has been changed yet. Accept a fix first.")
    if len(paths) == 1:
        return FileResponse(paths[0], filename=paths[0].name, media_type="application/octet-stream")
    archive = shutil.make_archive(str(EXPORTS / f"{scene_id}-orca"), "zip", out)
    return FileResponse(archive, filename=export_zip_name(ws.names.get(scene_id, [])), media_type="application/zip")


def export_zip_name(files: list[str]) -> str:
    """The download name of a multi-file export: the project's name (`service.project_name`), safe in a file name."""
    project = re.sub(r"[^A-Za-z0-9._ -]+", "-", project_name(files) or "").strip(" .-")
    return f"{project}-orca.zip" if project else "orca-export.zip"


def _report(report_id: str):
    if report_id not in ws.reports:
        raise HTTPException(404, "Clash report not loaded. Open it again.", headers=_gone("report", report_id))
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
    if body.check is not None:
        register = ws.checks.get(scene_id)
        if register is None or body.check not in register.checks:
            raise HTTPException(404, "That check is no longer kept: run it from the Filters panel again.")
    # Run all again is one detection run too. Once, after a hand edit kept with clashes, it is not charged as one: the
    # person accepted those clashes, and the list must show them (docs/manual-edits.md). It has its own, larger cap.
    after_edit = ws.journal(scene_id).free_rerun(body.after_edit)
    refused = _take(edit_rerun_limit if after_edit else detect_limit, request)
    if refused:
        raise HTTPException(429, refused)
    events: queue.Queue = queue.Queue()

    def work():
        try:
            if body.all:
                out = ws.detect_all(scene_id, on_event=events.put)
            else:
                out = ws.detect(scene_id, body.tests, on_event=events.put, check=body.check)
            events.put({"type": "done", **out})
        except Exception as e:
            events.put({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        events.put(None)

    owner.spawn(work)

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event, default=str) + "\n"

    return _ndjson(stream())


@app.get("/api/scenes/{scene_id}/checks")
def scene_checks(scene_id: str):
    """The scene's kept checks (docs/detection.md, "Kept checks") and the report listing their clashes, made again
    with a new id if the server let it go (no detection run is spent)."""
    return ws.checks_info(_scene(scene_id))


@app.delete("/api/scenes/{scene_id}/checks/{key}")
def remove_scene_check(scene_id: str, key: str):
    """Drop a check on filters: its clashes leave the list unless another check found them too. Returns the report
    listing what is left (null when nothing is) and the checks still kept."""
    try:
        return ws.remove_check(_scene(scene_id), key)
    except KeyError:
        raise HTTPException(404, "No such check.")
    except ValueError as e:
        raise HTTPException(409, str(e))


# ------------------------------------------------------------------------------------------------- requirements

class RequirementsDraft(BaseModel):
    level: int = 3
    strictness: str = "balanced"
    name: str = "Coordination requirements"


@app.get("/api/requirements/scale")
def requirements_scale():
    """The design levels and strictness steps, and what each sets (docs/requirements.md)."""
    return requirements.scale()


def _requirements_out(doc) -> dict:
    return {"id": requirements.doc_id(doc), "doc": doc.to_dict(), "params": asdict(requirements.resolve(doc)),
            "label": requirements.label(doc), "model_key": requirements.model_key(doc)}


@app.post("/api/requirements")
async def register_requirements(request: Request):
    """Register a requirements file (the body): returns its id, to send as X-Sightline-Requirements, the file as
    ORCA reads it, and the numbers its level and strictness resolve to."""
    raw = await request.body()
    if len(raw) > requirements.MAX_BYTES:
        raise HTTPException(413, f"A requirements file is at most {requirements.MAX_BYTES // 1024} KB.")
    try:
        doc = requirements.parse(json.loads(raw or b"{}"))
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    if requirements.lookup(requirements.doc_id(doc)) is None:
        refused = _take(requirements_limit, request)
        if refused:
            raise HTTPException(429, refused)
    requirements.register(doc)
    return _requirements_out(doc)


@app.get("/api/scenes/{scene_id}/requirements/default")
def requirements_default(scene_id: str):
    """A starting point: a demo's own requirements (`demos.py`), else one from the open models (L3 Coordinated,
    balanced: what ORCA checks without requirements, in the models' domain), and what the models contain."""
    scene = ws.scene(_scene(scene_id))
    # Read-only (classes, teams, systems), so it does not wait for a preview or a fix trial holding the lock.
    doc = demos.requirements_for(ws.names.get(scene_id) or []) or requirements.default_doc(scene)
    inv = requirements.inventory(scene, requirements.domain_of(scene, doc))
    return {**_requirements_out(doc), "inventory": inv}


@app.post("/api/scenes/{scene_id}/requirements/suggest")
def requirements_suggest(scene_id: str, body: RequirementsDraft, request: Request):
    """Muse Spark drafts requirements for the open models at a level and strictness. One model call: counts as one
    proposal."""
    scene = ws.scene(_scene(scene_id))
    refused = _take(propose_limit, request)
    if refused:
        raise HTTPException(429, refused)
    inv = requirements.inventory(scene)
    try:
        doc, summary = requirements.suggest(ws.model, inv, body.level, body.strictness, body.name)
    except Exception as e:
        raise HTTPException(502, f"Muse Spark could not draft requirements: {type(e).__name__}: {e}")
    doc.domain = doc.domain or inv["domain"]   # the draft keeps the models' domain unless it says otherwise
    return {**_requirements_out(doc), "summary": summary, "inventory": inv}


_previews: dict[tuple, dict] = {}


@app.post("/api/scenes/{scene_id}/requirements/preview")
async def requirements_preview(scene_id: str, request: Request):
    """How many clashes a requirements file (the body) would find in the open models, and how many ORCA's defaults
    find, without opening a report. Runs the detection (seconds); repeated files are answered from a cache."""
    _scene(scene_id)
    raw = await request.body()
    if len(raw) > requirements.MAX_BYTES:
        raise HTTPException(413, "Too large.")
    try:
        doc = requirements.parse(json.loads(raw or b"{}"))
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))

    def count(tests) -> dict:
        key = (scene_id, json.dumps([asdict(t) for t in tests] if tests is not None else None, sort_keys=True, default=str))
        if key not in _previews:
            scene = ws.scene(scene_id)
            with ws.lock:
                run = detect.run(scene, tests)
            _previews[key] = {"clashes": len(run.report.clashes), "seconds": run.seconds,
                              "tests": [{"name": c.name, "kind": c.kind, "clashes": c.clashes} for c in run.coverage]}
            while len(_previews) > 64:
                _previews.pop(next(iter(_previews)))
        return _previews[key]

    tests = requirements.compile_tests(doc, ws.scene(scene_id))
    cached = all(k in _previews for k in [(scene_id, json.dumps([asdict(t) for t in tests], sort_keys=True, default=str)),
                                          (scene_id, json.dumps(None))])
    if not cached:
        refused = _take(preview_limit, request)
        if refused:
            raise HTTPException(429, refused)
    found = await run_in_threadpool(count, tests)
    baseline = await run_in_threadpool(count, None)
    return {**found, "baseline": baseline["clashes"], "params": asdict(requirements.resolve(doc))}


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
    """Ask Muse Spark what each pattern is (one call for all). Counts as one proposal, once: the reading is shared with
    the chat and MCP (`plans.read_patterns`)."""
    pats = plans.patterns(ws, _scene(scene_id), _report(report_id), body.fixed)
    verdicts, refused = plans.read_patterns(ws, scene_id, report_id, pats, lambda: _take(propose_limit, request))
    if refused:
        raise HTTPException(429, refused)
    return verdicts


_triage_jobs: dict[str, triage.Job] = {}
_triage_lock = threading.Lock()


def _triage_key(report, doc=None) -> str:
    """A sample report is the same files for every visitor (clash ids are positions), so its triage is shared. Under
    coordination requirements, a run is shared only with the same prompt (`model_key`) and the same rules. The list of
    ORCA's checks is one run per scene, which follows its clashes from list to list (docs/detection.md, "Kept checks")."""
    if report.origin == "sightline" and report.scene_id is not None:
        base = f"scene:{report.scene_id}"
    else:
        base = report.id if report.temporary else f"sample:{report.root}"
    return base if doc is None else f"{base}|{requirements.model_key(doc)}|{requirements.rules_key(doc)}"


def _title_key(report) -> str:
    """One titling run per report, and one per scene for ORCA's lists of checks (as triage): a new list follows the
    run under way instead of titling the same clashes again."""
    if report.origin == "sightline" and report.scene_id is not None:
        return f"scene:{report.scene_id}"
    return _triage_key(report)


def _kept_titles(report) -> None:
    """A list of ORCA's checks takes every title the scene's checks keep (a run over an earlier list landed them)."""
    register = _register_of(report)
    if register is not None:
        with register.lock:
            found = dict(register.titles)
        _with_titles(report, found)


def _triage_donor(report, doc) -> triage.Job | None:
    """A finished run of this report under the same triage prompt, whose model readings a run under other rules can
    keep (adding a rule from Insights must not re-ask the model about everything)."""
    base = _triage_key(report)
    prefix = base if doc is None else f"{base}|{requirements.model_key(doc)}|"
    for key, job in reversed(list(_triage_jobs.items())):
        # Never a stopped run: what it left unread would then be read free under the new rules.
        if job.done and not job.error and not job.stopped and (key.startswith(prefix) if doc is not None else key == base):
            return job
    return None


def _ruled(doc, clash, verdict: dict | None) -> dict:
    """A reading shown under requirements it was not read under: a by-design rule now in force settles it (keeping the
    model's reading); a requirement verdict whose rule is gone is shown as not yet read."""
    rule = requirements.settle(doc, clash)
    if rule:
        out = {**rule, "source": "rule"}
        if verdict and verdict.get("source") == "model" and verdict.get("understanding"):
            out["model_reading"] = f"{verdict.get('verdict', '').replace('_', ' ')}: {verdict['understanding']}"
        return out
    if verdict and verdict.get("basis") == "requirement":
        return {"verdict": "unknown", "source": "rule", "error": "Its requirements rule is gone: triage again to read it."}
    return verdict or {"verdict": "unknown", "source": "rule"}


def _triage_latest(report) -> triage.Job | None:
    """The latest run of this report under any requirements: shown, marked stale, until one under these is started."""
    base = _triage_key(report)
    for key, job in reversed(list(_triage_jobs.items())):
        if key == base or key.startswith(base + "|"):
            return job
    return None


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


def _register_of(report):
    """The scene's kept checks behind a list of ORCA's checks (checks.py), or None for an import or a run on its own."""
    return ws.checks.get(report.scene_id) if report.origin == "sightline" and report.scene_id else None


def _model_key(doc) -> str:
    return requirements.model_key(doc) if doc is not None else ""


def _same_in(job: triage.Job, report) -> set[str]:
    """The clashes of `report` that are the same, unchanged, in the run's own report (`checks.same_clash`): what a run
    over an earlier list of the same checks may say of them."""
    if job.report is report:
        return {c.id for c in report.clashes}
    return {c.id for c in report.clashes if (o := job._by_id.get(c.id)) is not None and checks.same_clash(o, c)}


def _for_report(job: triage.Job, report) -> dict:
    """A run's state for this report: a run over an earlier list of the same checks tells only the clashes listed here
    that are unchanged (same pair, depth within 1 mm), and counts them. A run queued behind another shows that one's
    readings until its own land."""
    state = job.state()
    same = _same_in(job, report)
    results = {c.id: state["results"][c.id] for c in report.clashes if c.id in state["results"] and c.id in same}
    if job.after is not None and not job.done:
        results = {**_for_report(job.after, report)["results"], **results}
    unread = sum(1 for c in report.clashes if c.id not in results or results[c.id].get("error"))  # a failed read too
    return {**state, "results": results, "summary": triage.summary(results), "total": len(report.clashes),
            "unread": unread, "scope": job.scope}


def _unread(report, doc, facts: dict, carried: dict, scope: str | None, rerun: bool) -> set[str]:
    """The clashes in scope (a kept check's, or all) that triage would ask the model about: not settled by a rule or
    the open model, nor (unless read again) by a reading that still holds."""
    out = set()
    for c in report.clashes:
        if scope is not None and scope not in c.checks:
            continue
        if triage.settled_by(c, doc, facts)[0]:   # the same test triage_report makes, so the charge matches the run
            continue
        if c.id in carried and not rerun:
            continue
        out.add(c.id)
    return out


def _visitor(request) -> str | None:
    """Who is asking (`limits.client_id`, as for the caps), or None without a request (an MCP tool's own call)."""
    return client_id(request.headers, request.client.host if request.client else None) if request is not None else None


@app.get("/api/reports/{report_id}/triage")
def triage_state(report_id: str, scene_id: str | None = None, request: Request = None):
    """The bulk triage of this report so far ({"results": {}} when it has not been run). Under requirements that only
    change rules since a finished run, a run under them starts at once from its readings (no model call for those,
    no charge); under a different prompt, the last run is returned marked "stale" until one is started. A list of
    ORCA's checks gets the readings that still hold for its clashes at once, free (docs/detection.md, "Kept checks"),
    with `unread`: how many the model has not read. `can_stop`: whether this visitor may stop the run under way
    (whoever started it, or the owner)."""
    who = _visitor(request)
    state, job = _triage_state(report_id, scene_id, who)
    return {**state, "can_stop": job is not None and not job.done and job.may_stop(who, owner.is_owner())}


def _triage_state(report_id: str, scene_id: str | None, who: str | None) -> tuple[dict, triage.Job | None]:
    """`triage_state`'s answer, and the run it describes (None when there is none)."""
    report = ws.report(_report(report_id))
    doc = requirements.current()
    register = _register_of(report)
    scene_id = scene_id or (report.scene_id if register is not None else None)
    job = _triage_jobs.get(_triage_key(report, doc))
    if register is not None:
        if job is None or (job.done and job.report is not report):
            if register.carried(report, _model_key(doc)):
                job = _start_triage(report, scene_id, lambda: None, ask=False, who=who)   # nothing new is read: free
        if job is not None:
            job.learn(_triage_facts(report_id, scene_id))
            return _for_report(job, report), job
    elif job is None and doc is not None and _triage_donor(report, doc) is not None:
        job = _start_triage(report, scene_id, lambda: None, who=who)
    if job:
        job.learn(_triage_facts(report_id, scene_id))
        return job.state(), job
    latest = _triage_latest(report)
    if latest is not None:
        state = _for_report(latest, report) if register is not None else latest.state()
        if doc is not None:  # its readings, with the rules in force now (no model call): a rule added applies at once
            state["results"] = {c.id: _ruled(doc, c, state["results"].get(c.id)) for c in report.clashes
                                if c.id in state["results"] or requirements.settle(doc, c)}
            state["summary"] = triage.summary(state["results"])
        return {**state, "stale": True}, latest
    return {"results": {}, "done": False, "started": False,
            **({"unread": len(report.clashes)} if register is not None else {})}, None


@app.post("/api/reports/{report_id}/triage/stream")
def triage_stream(report_id: str, request: Request, rerun: bool = False, scene_id: str | None = None,
                  scope: str | None = None):
    """Triage every clash in the report (open-weights model when configured). Streams newline-delimited JSON:
    start, one "clash" event per verdict, done. One run per report is shared by every visitor; starting one costs a
    proposal, following one already started is free. With `scene_id`, what the open model already settles (one
    element on both sides) is not asked of the model, and corrects a run that did ask. A list of ORCA's checks asks
    only about the clashes no reading holds for, in `scope` (a kept check's key) or all, and costs nothing when there
    are none. Its `start` event says `can_stop`: whether this visitor may stop the run (whoever started it, or the
    owner)."""
    report = ws.report(_report(report_id))
    who = _visitor(request)
    try:
        job = _start_triage(report, scene_id, lambda: _take(propose_limit, request), rerun, scope, who=who)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    mine = job.may_stop(who, owner.is_owner())   # here: the owner is known in the request, not in the stream
    # Following a run over an earlier list of the same checks: only what it says of clashes unchanged here, and its
    # start says so (`following`), with this list's count.
    other = job.report is not report
    same = _same_in(job, report) if other else None

    def stream():
        for event in job.follow():
            if event.get("type") == "start":
                event = {**event, "can_stop": mine}
            if other:
                if event.get("type") == "start":
                    event = {**event, "total": len(report.clashes), "following": job.report.id}
                elif event.get("type") in ("clash", "reasoning") and event.get("id") not in same:
                    continue
            yield json.dumps(event, default=str) + "\n"

    return _ndjson(stream())


@app.post("/api/reports/{report_id}/triage/stop")
def triage_stop(report_id: str, request: Request):
    """Stop the report's triage under way, and a run it waits behind that this visitor also started. The run is
    shared, so only whoever started it (or the owner) may stop it: 403 for anyone else following it. What the model
    has read stays; triaging again asks only about the rest. Free. {"stopped": false} when nothing was running."""
    report = ws.report(_report(report_id))
    who, boss = _visitor(request), owner.is_owner()
    job = _triage_jobs.get(_triage_key(report, requirements.current()))
    if job is None or job.done:
        job = _triage_latest(report)
    if job is not None and not job.done and not job.may_stop(who, boss):
        raise HTTPException(403, "Only whoever started this triage can stop it: it is shared with everyone following it.")
    stopped = False
    while job is not None and not job.done and job.may_stop(who, boss):
        stopped = job.stop() or stopped
        job = job.after
    return {"stopped": stopped}


def _keep_job(jobs: dict, key: str, job, cap: int) -> None:
    """A job under its key, last in line: a key used again (a scene's run) moves to the end, so the cap drops the
    oldest other jobs first, never the one just started."""
    jobs.pop(key, None)
    jobs[key] = job
    while len(jobs) > cap:
        jobs.pop(next(iter(jobs)))


def _unfinished(job: triage.Job) -> bool:
    """A finished run that left clashes unread: stopped, or a read that failed (a run over a report reads them all)."""
    return job.stopped or any(c.id not in job.results or job.results[c.id].get("error") for c in job.report.clashes)


def _kept_readings(job: triage.Job) -> dict[str, dict]:
    """What a run started after an unfinished one keeps of it: every model reading that did not fail."""
    return {k: v for k, v in job.results.items() if v.get("source") == "model" and not v.get("error")}


def _reading(job: triage.Job, report) -> set[str]:
    """The clashes of `report` a run under way will still read itself: those it asks about, unchanged here."""
    asking = job.only if job.only is not None else set(job._by_id)
    return (asking - set(job.results)) & _same_in(job, report)


def _start_triage(report, scene_id: str | None, charge, rerun: bool = False, scope: str | None = None,
                  ask: bool = True, who: str | None = None) -> triage.Job:
    """The report's shared triage run: the one under way or done, else a new one (`charge` once: why not, or None).
    For a list of ORCA's checks, one run per scene: a reading the model made follows its clash to every later list
    while the clash is unchanged, so a new run asks only about the rest, in `scope` (charged only when it asks).
    `ask` False: only carry what holds and what the rules settle, asking the model nothing. `who`: the visitor
    asking, the starter of a run this starts (who may stop it)."""
    doc = requirements.current()
    register = _register_of(report)
    if register is not None:
        scene_id = scene_id or report.scene_id
    key = _triage_key(report, doc)
    facts = _triage_facts(report.id, scene_id)
    teams = _report_teams(report, scene_id)  # before the triage lock: it takes the workspace's
    with _triage_lock:
        job = _triage_jobs.get(key)
        if register is not None:
            mk = _model_key(doc)
            carried = register.carried(report, mk)
            unread = _unread(report, doc, facts, carried, scope, rerun) if ask else set()
            running = job is not None and not job.done
            if running and not rerun and not (unread - _reading(job, report)):
                job.learn(facts)
                return job   # the run under way reads all of it (or nothing is asked): follow it, free
            if not running and job is not None and job.report is report and not rerun and not unread:
                job.learn(facts)
                return job
            refused = charge() if unread else None   # carrying readings over is free
            if refused:
                raise PermissionError(refused)
            model, info = triage_model()
            if doc is not None:
                info = {**info, "requirements": ws.requirements_info(doc)}
            in_scope = {c.id for c in report.clashes if scope is None or scope in c.checks}
            seed = {k: v for k, v in carried.items() if not (rerun and k in in_scope)}
            prepare = None
            if running:   # queued behind the run under way: what to read is worked out when it ends
                before = job

                def prepare():
                    now = register.carried(report, mk)
                    fresh = {k for k, v in before.results.items() if v.get("source") == "model" and not v.get("error")}
                    left = _unread(report, doc, facts, now, scope, rerun) - (fresh if rerun else set())
                    return {k: v for k, v in now.items() if k not in left}, left
            job = triage.Job(report, model, info, env_int("SIGHTLINE_TRIAGE_WORKERS", triage.WORKERS),
                             requirements=doc, seed=seed if not running else None, domain=domains.of(ws, scene_id), teams=teams,
                             only=unread, scope=scope, on_reading=lambda c, v: register.keep_reading(mk, c, v),
                             prior_audit=job.audit if job is not None and not running else None,
                             after=job if running else None, prepare=prepare, starter=who)
            job.learn(facts)
            _keep_job(_triage_jobs, key, job.start(), 16)
            return job
        if job is None or (job.done and (rerun or _unfinished(job))):
            # A run that stopped or failed some reads goes on from its readings: only the rest is asked (charged once).
            resume = None if job is None or rerun else _kept_readings(job)
            donor = None if rerun or resume is not None else _triage_donor(report, doc) if doc is not None else None
            refused = None if donor is not None else charge()  # carrying readings over to new rules is free
            if refused:
                raise PermissionError(refused)
            model, info = triage_model()
            if doc is not None:
                info = {**info, "requirements": ws.requirements_info(doc)}
            seed = resume if resume is not None else donor.results if donor is not None else None
            job = triage.Job(report, model, info, env_int("SIGHTLINE_TRIAGE_WORKERS", triage.WORKERS),
                             requirements=doc, seed=seed, domain=domains.of(ws, scene_id), teams=teams,
                             starter=who)
            job.learn(facts)
            _keep_job(_triage_jobs, key, job.start(), 16)
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
    _kept_titles(report)
    job = _title_jobs.get(_title_key(report))
    if job:
        _with_titles(report, job.titles)
    return {"titles": {c.id: c.title for c in report.clashes if c.title}, "running": bool(job and not job.done)}


def _report_teams(report, scene_id: str | None) -> list[str]:
    """The teams ORCA guesses for the report's models (`document.guess_teams`): the names triage's "responsible" uses;
    the report translates them to the names the user types."""
    scene = ws.scene(scene_id) if scene_id and scene_id in ws.scenes else None
    with ws.lock:
        models = document.guess_teams(report, scene, domains.of(ws, scene_id if scene is not None else None))
    return list(dict.fromkeys(m["guess"] for m in models))


@app.post("/api/reports/{report_id}/titles/stream")
def titles_stream(report_id: str, request: Request, scene_id: str | None = None):
    """Title every clash in the report with Muse (titles.py). Streams newline-delimited JSON: start, a "titles" event
    per batch ({id: title}), done. One run per report is shared; following a run already started is free."""
    report = ws.report(_report(report_id))
    key = _title_key(report)
    register = _register_of(report)
    with _title_lock:
        _kept_titles(report)
        job = _title_jobs.get(key)
        if job is not None:
            _with_titles(report, job.titles)
        # Start one when there is none, or when a finished one left clashes untitled (a failed batch): those only.
        if job is None or (job.done and any(not c.title for c in report.clashes)):
            refused = _take(title_limit, request)
            if refused:
                raise HTTPException(429, refused)
            model, info = triage_model()
            job = titles.Job(report, model, info, domains.of(ws, scene_id if scene_id in ws.scenes else None),
                             on_titles=register.keep_titles if register is not None else None)
            _keep_job(_title_jobs, key, job.start(), 32)

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
    """Keep a plan's fixes, all or none: each tried again alone and all together first (plans.apply)."""
    return _keep(scene_id, body.options, "the plan", body.clash_ids)


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
    escalate_allowed = _escalation_check(request)
    detect_allowed = lambda: None if no_caps else detect_limit.take(who)
    session = c.session(body.session_id)
    ctx = chat.Context(body.scene_id, body.report_id, body.clash_id, body.fixed, [f.model_dump() for f in body.filters],
                       body.filter_view.model_dump(), body.check, body.selected)
    events = _RequestEvents(request)
    events.put({"type": "session", "id": session.id})

    def finish():
        events.put({"type": "done"})
        events.put(None)

    def work():
        try:
            c.turn(session, body.message[:4000], ctx, events.put, cancel=events.cancel,
                   propose_allowed=allowed, propose_allowed_many=allowed_many, escalate_allowed=escalate_allowed,
                   detect_allowed=detect_allowed, before_publish=finish)
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
    check: str | None = None           # one kept check's clashes only (its key; None: every clash in the report)


_documents: dict[str, tuple[bytes, str, str]] = {}


def _narrowed(report, check: str | None):
    """The report as one kept check's clashes, titled as that check's run (KeyError: the report holds no such check)."""
    if check is None:
        return report
    kept = next((c for c in report.checks if c["key"] == check), None)
    if kept is None:
        raise KeyError(check)
    return dataclasses.replace(report, title=kept["title"],
                               clashes=[dataclasses.replace(c, test=c.checks[check]) for c in report.clashes if check in c.checks])


@app.get("/api/reports/{report_id}/teams")
def report_teams(report_id: str, scene_id: str | None = None):
    """Each model in the report (and the open scene) with the team its content suggests; the user confirms."""
    scene = ws.scene(scene_id) if scene_id and scene_id in ws.scenes else None
    with ws.lock:
        models = document.guess_teams(ws.report(_report(report_id)), scene, domains.of(ws, scene_id if scene is not None else None))
    # The guesses are suggestions only: the dialog takes any team name typed for a model.
    return {"teams": list(dict.fromkeys(m["guess"] for m in models)), "models": models}


@app.post("/api/reports/{report_id}/document/stream")
def document_stream(report_id: str, body: DocumentRequest, request: Request):
    """A coordination report: PDF(s) combined, per team or per model, plus BCF. Needs the report's triage. Streams
    progress as newline-delimited JSON, then {"type": "ready", url, name}. Costs one proposal."""
    report = ws.report(_report(report_id))
    if body.scope not in ("combined", "team", "model"):
        raise HTTPException(422, "scope is combined, team or model.")
    try:
        whole, report = report, _narrowed(report, body.check)
    except KeyError:
        raise HTTPException(404, "That check is not in this report.")
    # The verdicts the visitor sees (with their own "not a clash" marks applied), else the server's finished run. The
    # shared run can be gone (a restart) or running again (someone pressed Triage again) while the page still has one.
    job = _triage_jobs.get(_triage_key(whole, requirements.current())) or _triage_latest(whole)
    ids = {c.id for c in report.clashes}
    verdicts = ({k: v for k, v in body.triage.items() if isinstance(v, dict) and v.get("verdict")} if body.triage
                else {k: v for k, v in job.results.items() if k in ids} if job is not None and job.done else {})
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
                                  reviews=body.reviews, marks=body.marks, bcf=body.bcf, emit=events.put,
                                  triage_info=job.info if job is not None else None)
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
                    bcf: bool = True, emit=None, triage_info: dict | None = None) -> dict:
    """Build a report and keep it for download: {path (the download route), name, bytes, file (a local copy)}.
    `triage_info`: the triage run's model, which the PDF names (none: the one triage would run on now)."""
    scene = ws.scene(scene_id) if scene_id and scene_id in ws.scenes else None
    matches = ws.match(report.id, scene_id) if scene is not None else None
    data, name, media = document.generate(
        report, verdicts, ws.model, scope=scope, model_teams=teams or {}, matches=matches, scene=scene,
        evidence=evidence or {}, reviews=reviews or {}, marks=marks or {}, include_bcf=bcf, emit=emit or (lambda e: None),
        triage_info=triage_info, domain=domains.of(ws, scene_id if scene is not None else None),
        journal=ws.journals.get(scene_id) if scene is not None else None)
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
async def transcribe_voice(request: Request, audio: UploadFile = File(...), report_id: str | None = Form(None),
                           scene_id: str | None = Form(None)):
    """A spoken message to ORCA (Muse Voice Transcribe): a WAV clip in, its transcript out. The browser sends the
    transcript to the chat, so voice can do whatever the chat can. Biased toward coordination words, the domain's and
    the open models' and report's names (`_voice_words`)."""
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
    try:
        return await run_in_threadpool(lambda: transcribe(data, _voice_words(report_id, scene_id)))
    except Exception as e:  # the key, the network or the service: say so rather than fail silently
        raise HTTPException(502, f"Transcription failed: {type(e).__name__}")


def _voice_words(report_id: str | None, scene_id: str | None = None) -> list[str]:
    """Words Muse Voice Transcribe should lean toward: coordination words, the domain's, the open models' levels and
    systems, and what people call the open report's clashes."""
    scene_id = scene_id if scene_id in ws.scenes else None
    domain = domains.of(ws, scene_id)
    words = [*VOICE_WORDS, *domains.VOICE[domain], *([meta_client.model_label(meta_client.model_id("proposal"))])]
    if scene_id:
        inv = requirements.inventory(ws.scene(scene_id), requirements.domain_of(ws.scene(scene_id)))
        words += [*list(inv["storeys"])[:12], *list(inv["systems"])[:12]]
    if report_id and report_id in ws.reports:
        # What people say about a report's clashes: the elements' names (and Muse's titles), not their numbers.
        clashes = ws.report(report_id).clashes
        names = {e.name for c in clashes for e in (c.a, c.b) if e.name} | {c.title for c in clashes if c.title}
        words += sorted(names, key=lambda n: (len(n), n))[:40]
    return words


@app.websocket("/api/voice/live")
async def voice_live_socket(socket: WebSocket):
    """Talk to ORCA live (voice_live.py): the words come back as they are said. The first frame says how
    (`{mode: "hold" | "hands_free", report_id, scene_id}`); one session is one voice message against the caps, hands-free too."""
    if not voice_live.same_origin(socket.headers):
        await socket.close(code=1008)  # before accepting: the browser sees a refused handshake
        return
    await socket.accept()
    try:
        first = await asyncio.wait_for(socket.receive_json(), 10)
    except Exception:
        await socket.close(code=1008)
        return
    first = first if isinstance(first, dict) else {}
    hands_free = first.get("mode") == "hands_free"
    refused = _take(voice_limit, socket)
    if refused:
        await socket.send_json({"type": "error", "detail": refused})
        await socket.close(code=1000)
        return
    report_id = first.get("report_id") if isinstance(first.get("report_id"), str) else None
    scene_id = first.get("scene_id") if isinstance(first.get("scene_id"), str) else None
    words = await run_in_threadpool(_voice_words, report_id, scene_id)
    await voice_live.relay(socket, voice_live.MODES["hands_free" if hands_free else "hold"], words,
                           VOICE_HANDS_FREE_MAX_S if hands_free else VOICE_HOLD_MAX_S)

# ---------------------------------------------------------------------------------------------------------- agents
# "Connect an agent": a link (a secret token) lets an MCP client work on this visitor's session (agents.py), and the
# page follows what it does. The MCP server itself is mounted at /mcp below (mcp_server.py).

links = agents.Links()
ws.keep = links.kept  # what live links point at is evicted last
link_limit = ProposeLimit(env_int("SIGHTLINE_LINKS_PER_HOUR", 0),
                          env_int("SIGHTLINE_LINKS_PER_DAY", 0), noun="agent links")
agent_call_limit = ProposeLimit(env_int("SIGHTLINE_AGENT_CALLS_PER_HOUR", 0), 0, noun="agent calls")
MAX_CAPTURE_BYTES = 6_000_000


class LinkContext(BaseModel):
    scene_id: str | None = None
    report_id: str | None = None
    clash_id: str | None = None
    fixed: list[str] = []
    filters: list[PageFilter] = Field(default_factory=list, max_length=100)
    filter_view: FilterView = Field(default_factory=FilterView)
    check: str | None = None   # the kept check the page's list shows (None: all of them)


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
                                                                  list(body.fixed), [f.model_dump() for f in body.filters],
                                                                  body.filter_view.model_dump(), body.check))
    link.requirements = requirements.current_id()
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
    link.ctx.filters = [f.model_dump() for f in body.filters]
    link.ctx.filter_view = body.filter_view.model_dump()
    link.ctx.check = body.check
    link.requirements = requirements.current_id()  # the page sends its requirements with every call, this one too
    return link.public()


@app.get("/api/links/{token}/events")
async def link_events(token: str, request: Request):
    """What the agent does, for the page to follow (newline-delimited JSON): ui actions, agent calls, capture
    requests, a heartbeat every 15 s. Ends after a few minutes; the page reconnects."""
    link = _link(token)
    q = link.subscribe()

    async def stream():
        try:
            yield json.dumps({"type": "hello", "stream": q.stream_id, **link.public()}) + "\n"
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
                if event.get("type") == "bye":  # the page said it is closing
                    break
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


@app.post("/api/links/{token}/leave/{stream_id}")
def link_leave(token: str, stream_id: str):
    """The page is closing (a beacon from `pagehide`): it no longer counts as a browser following this link."""
    return {"left": _link(token, touch=False).leave(stream_id)}


@app.delete("/api/links/{token}")
def revoke_link(token: str):
    return {"revoked": links.revoke(token)}


def mcp_hooks() -> mcp_server.Hooks:
    """What the MCP tools borrow from this server: links, the demo caps (proposals, second tries, detection runs, all
    charged to the link's creator), triage and reports."""
    def charge(link: agents.Link, n: int) -> str | None:
        return None if link.owner else propose_limit.take_many(link.visitor, n)

    def escalate(link: agents.Link) -> str | None:
        r = escalation_refused(link.visitor, link.owner)
        return r[1] if r else None

    def detect_run(link: agents.Link) -> str | None:
        return None if link.owner else detect_limit.take(link.visitor)

    def start_triage(report_id: str, scene_id: str | None, link: agents.Link):
        # Started by an agent: the link's creator is the starter, who may stop it from their page.
        return _start_triage(ws.report(report_id), scene_id, lambda: charge(link, 1), who=link.visitor)

    def build_document(report_id: str, scene_id: str | None, scope: str, check: str | None = None) -> dict:
        whole = ws.report(report_id)
        report = _narrowed(whole, check)
        job = _triage_jobs.get(_triage_key(whole, requirements.current())) or _triage_latest(whole)
        ids = {c.id for c in report.clashes}
        verdicts = {k: v for k, v in job.results.items() if k in ids} if job is not None and job.done else {}
        if len(verdicts) < len(report.clashes) // 2:
            raise RuntimeError("Triage the report first (the triage tool): the report sorts clashes by its verdicts.")
        return _build_document(report, verdicts, scene_id, scope, triage_info=job.info if job is not None else None)

    return mcp_server.Hooks(
        links=links, charge=charge, escalate=escalate, detect=detect_run,
        allow_call=lambda link: agent_call_limit.take(link.id),
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
