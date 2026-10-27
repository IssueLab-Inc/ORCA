"""The operations Sightline offers, shared by the web API and the MCP server so they never drift."""
from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

from . import agent, edits, reports, verify
from .meta_client import ChatModel, MetaChatModel
from .scene import IfcScene

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
# Each open scene holds its federated models in memory; a public server keeps only the most recent ones.
MAX_SCENES = int(os.environ.get("SIGHTLINE_MAX_SCENES", "0"))  # 0 = no limit
MAX_REPORTS = int(os.environ.get("SIGHTLINE_MAX_REPORTS", "0"))  # open clash reports kept, same rule


class Workspace:
    def __init__(self, samples: Path = SAMPLES, model: ChatModel | None = None, max_scenes: int = MAX_SCENES,
                 max_reports: int = MAX_REPORTS):
        self.samples = samples
        self.max_scenes = max_scenes
        self.max_reports = max_reports
        self.scenes: dict[str, IfcScene] = {}
        self.reports: dict[str, reports.Report] = {}
        self._matches: dict[tuple[str, str], dict] = {}
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
        while self.max_scenes and len(self.scenes) > self.max_scenes:
            del self.scenes[next(iter(self.scenes))]  # oldest first (dicts keep insertion order)
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
                images: list[str] | None = None, notes: str = "", report_id: str | None = None,
                clash_id: str | None = None) -> dict:
        """With a report clash, its Navisworks distance and images go to the model too (images are what let
        the model find openings and free space; spikes/README.md, spike 4)."""
        pics = [Path(p) for p in images or []]
        if report_id and clash_id:
            c = self.report(report_id).clash(clash_id)
            pics = pics or [p for _, p in c.images]
            if distance_m is None:
                distance_m = c.distance_m
            notes = "\n".join(filter(None, [notes, f"From a Navisworks clash report: {c.test}, {c.name}. "
                                                    "Images are Navisworks views of this clash."]))
        clash = agent.Clash(element_a, element_b, distance_m, pics, notes)
        return asdict(agent.resolve(self.scene(scene_id), clash, self.model))

    def apply(self, scene_id: str, moved: list[str], delta_m: list[float]) -> dict:
        s = self.scene(scene_id)
        placements = s.translate(moved, tuple(delta_m))
        return {"placements": placements, "files": sorted({s.index_of(g) for g in moved})}

    def check_offset(self, scene_id: str, element: str, other: str, split_m: list[float], dz_m: float,
                     clearance_m: float = 0.025) -> dict:
        """Try a local offset of `element` around `other` without keeping it (see edits.py)."""
        attempt, option = agent._try_offset(self.scene(scene_id), {"split_m": split_m, "dz_m": dz_m}, element, other,
                                            clearance_m)
        return {"passed": attempt.passed, "reason": attempt.reason,
                "min_clearance_m": option.min_clearance_m if option else None,
                "preview": option.preview if option else None}

    def apply_offset(self, scene_id: str, element: str, split_m: list[float], dz_m: float) -> dict:
        """Keep a local offset: the element is shortened and new pieces are added to its file."""
        s = self.scene(scene_id)
        off = edits.apply_offset(s, element, split_m[0], split_m[1], dz_m)
        s.mark_edited(element)
        return {**asdict(off), "files": [s.index_of(element)]}

    def file(self, scene_id: str, index: int, out_dir: Path) -> Path:
        """A model file as it is now: the original on disk, or the edited model written out."""
        s = self.scene(scene_id)
        if index not in s._edited:
            return s.paths[index]
        path = out_dir / f"{scene_id}-{index}-{s.paths[index].name}"
        s.models[index].write(str(path))
        return path

    def export(self, scene_id: str, out_dir: Path) -> list[Path]:
        """Write the edited files only; untouched discipline models are not rewritten."""
        return self.scene(scene_id).write_edited(out_dir)

    # Clash reports (Navisworks XML).

    @property
    def report_samples_dir(self) -> Path:
        return self.samples / "reports"

    def list_report_samples(self) -> list[str]:
        """Folders under samples/reports/ with an XML report at their top level."""
        root = self.report_samples_dir
        return sorted(d.name for d in root.iterdir() if d.is_dir() and any(d.glob("*.xml"))) if root.is_dir() else []

    def open_report_sample(self, name: str) -> reports.Report:
        root = (self.report_samples_dir / name).resolve()
        if root.parent != self.report_samples_dir.resolve() or not root.is_dir():
            raise FileNotFoundError(name)
        return self._keep(reports.load(uuid.uuid4().hex[:12], root, list(root.glob("*.xml")), name))

    def open_report_folder(self, root: Path, title: str) -> reports.Report:
        """An uploaded folder: every XML in it, at any depth. The folder is deleted when the report is dropped."""
        try:
            report = reports.load(uuid.uuid4().hex[:12], root, list(root.rglob("*.xml")), title, temporary=True)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return self._keep(report)

    def _keep(self, report: reports.Report) -> reports.Report:
        self.reports[report.id] = report
        while self.max_reports and len(self.reports) > self.max_reports:
            old = self.reports.pop(next(iter(self.reports)))
            if old.temporary:
                shutil.rmtree(old.root, ignore_errors=True)
        return report

    def report(self, report_id: str) -> reports.Report:
        return self.reports[report_id]

    def report_summary(self, report_id: str) -> dict:
        r = self.report(report_id)
        return {
            "id": r.id, "title": r.title, "sources": r.sources,
            "clashes": [{**{k: v for k, v in asdict(c).items() if k != "images"},
                         "images": [label for label, _ in c.images]} for c in r.clashes],
        }

    def report_image(self, report_id: str, clash_id: str, index: int) -> Path:
        return self.report(report_id).clash(clash_id).images[index][1]

    def match(self, report_id: str, scene_id: str) -> dict[str, dict]:
        """Which model element each clash side is: by GlobalId, else by a unique IFC class + name.
        Covers every product (spaces and ports too), not only the physical ones the geometry check uses."""
        key = (report_id, scene_id)
        if key in self._matches:
            return self._matches[key]
        scene = self.scene(scene_id)
        by_name: dict[tuple[str, str], list[str]] = {}
        known: set[str] = set()
        for model in scene.models:
            for p in model.by_type("IfcProduct"):
                known.add(p.GlobalId)
                by_name.setdefault((p.is_a(), p.Name or ""), []).append(p.GlobalId)

        def find(e: reports.ReportElement) -> tuple[str | None, str | None]:
            if e.global_id and e.global_id in known:
                return e.global_id, "globalid"
            hits = by_name.get((e.ifc_class or "", e.name), [])
            return (hits[0], "name") if len(hits) == 1 else (None, None)

        out = {}
        for c in self.report(report_id).clashes:
            (a, how_a), (b, how_b) = find(c.a), find(c.b)
            out[c.id] = {"a": a, "b": b, "how": [how_a, how_b]}
        self._matches[key] = out
        return out

    def measure(self, report_id: str, clash_id: str, scene_id: str) -> dict:
        """Sightline's own measure of a report clash: the signed distance between the two matched elements.
        None when they do not overlap here, or when they are joined through ports (the check skips those)."""
        m = self.match(report_id, scene_id)[clash_id]
        if not (m["a"] and m["b"]):
            return {"matched": False, "physical": None, "distance_m": None}
        scene = self.scene(scene_id)
        physical = scene.bounds().keys()
        if m["a"] not in physical or m["b"] not in physical:
            return {"matched": True, "physical": False, "distance_m": None}
        v = verify.check(scene, [m["a"]], clearance_m=0.0)
        hit = next((h for h in v.hits if h.other == m["b"]), None)
        return {"matched": True, "physical": True, "distance_m": hit.distance_m if hit else None}
