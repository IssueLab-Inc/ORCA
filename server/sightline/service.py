"""The operations Sightline offers, shared by the web API and the MCP server so they never drift."""
from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path

from . import agent, verify
from .meta_client import ChatModel, MetaChatModel
from .scene import IfcScene

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


class Workspace:
    def __init__(self, samples: Path = SAMPLES, model: ChatModel | None = None):
        self.samples = samples
        self.scenes: dict[str, IfcScene] = {}
        self._model = model

    @property
    def model(self) -> ChatModel:
        if self._model is None:
            self._model = MetaChatModel()
        return self._model

    def list_samples(self) -> list[str]:
        return sorted(p.name for p in self.samples.glob("*.ifc"))

    def open(self, names: list[str]) -> str:
        """Open one or more IFC files that share coordinates (e.g. structure + MEP + architecture)."""
        paths = []
        for name in names:
            path = (self.samples / name).resolve()
            if path.parent != self.samples.resolve() or not path.exists():
                raise FileNotFoundError(name)
            paths.append(path)
        if not paths:
            raise FileNotFoundError("no models given")
        scene = IfcScene(paths)
        scene.bounds()  # pay the one-off triangulation now, not on the first check
        scene_id = uuid.uuid4().hex[:12]
        self.scenes[scene_id] = scene
        return scene_id

    def scene(self, scene_id: str) -> IfcScene:
        return self.scenes[scene_id]

    def describe(self, scene_id: str, global_id: str) -> dict:
        return asdict(self.scene(scene_id).element(global_id))

    def verify_move(self, scene_id: str, moved: list[str], delta_m: list[float], clearance_m: float = 0.025) -> dict:
        """Check a move without keeping it."""
        s = self.scene(scene_id)
        placements = s.translate(moved, tuple(delta_m))
        try:
            v = verify.check(s, moved, clearance_m=clearance_m)
        finally:
            s.translate(moved, tuple(-d for d in delta_m))
        return {**asdict(v), "placements": placements}

    def propose(self, scene_id: str, element_a: str, element_b: str, distance_m: float | None = None,
                images: list[str] | None = None, notes: str = "") -> dict:
        clash = agent.Clash(element_a, element_b, distance_m, [Path(p) for p in images or []], notes)
        return asdict(agent.resolve(self.scene(scene_id), clash, self.model))

    def apply(self, scene_id: str, moved: list[str], delta_m: list[float]) -> dict:
        return self.scene(scene_id).translate(moved, tuple(delta_m))

    def export(self, scene_id: str, out_dir: Path) -> list[Path]:
        """Write the edited files only; untouched discipline models are not rewritten."""
        return self.scene(scene_id).write_edited(out_dir)
