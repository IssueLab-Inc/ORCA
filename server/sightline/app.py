"""Web API for the browser app. Run: uv run uvicorn sightline.app:app --reload"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .service import Workspace

app = FastAPI(title="ClashWise Sightline")
ws = Workspace()
EXPORTS = Path(tempfile.gettempdir()) / "sightline-exports"
EXPORTS.mkdir(exist_ok=True)


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
    return FileResponse(paths[index], media_type="application/octet-stream")


@app.get("/api/scenes/{scene_id}/elements/{global_id}")
def element(scene_id: str, global_id: str):
    return ws.describe(_scene(scene_id), global_id)


@app.post("/api/scenes/{scene_id}/verify")
def verify_move(scene_id: str, body: Move):
    return ws.verify_move(_scene(scene_id), body.moved, body.delta_m, body.clearance_m)


@app.post("/api/scenes/{scene_id}/propose")
def propose(scene_id: str, body: Propose):
    return ws.propose(_scene(scene_id), body.element_a, body.element_b, body.distance_m, notes=body.notes)


@app.post("/api/scenes/{scene_id}/apply")
def apply(scene_id: str, body: Move):
    return ws.apply(_scene(scene_id), body.moved, body.delta_m)


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
