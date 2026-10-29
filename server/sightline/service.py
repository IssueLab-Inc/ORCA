"""The operations ORCA offers, shared by the web API and the MCP server so they never drift."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from collections import Counter

import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.system
import numpy as np
from dataclasses import asdict
from pathlib import Path

from . import agent, detect, edits, reports, step, verify
from .meta_client import ChatModel, MetaChatModel
from .scene import IfcScene, step_source

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
# Each open scene holds its federated models in memory; a public server keeps only the most recent ones.
MAX_SCENES = int(os.environ.get("SIGHTLINE_MAX_SCENES", "0"))  # 0 = no limit
MAX_REPORTS = int(os.environ.get("SIGHTLINE_MAX_REPORTS", "0"))  # open clash reports kept, same rule
# Uploaded models and STEP conversions live here; a converted STEP is cached by its hash (`step-cache`).
MODELS = Path(tempfile.gettempdir()) / "sightline-models"
MODEL_SUFFIXES = {".ifc"} | step.SUFFIXES


# Clash tests the demo's sample reports leave out: site context, rooms and proxies are not coordination problems.
# Uploaded reports are kept whole. Comma-separated IFC classes; empty keeps everything.
SAMPLE_EXCLUDE = tuple(c.strip() for c in os.environ.get(
    "SIGHTLINE_SAMPLE_EXCLUDE", "IfcGeographicElement,IfcSpace,IfcBuildingElementProxy").split(",") if c.strip())


class Workspace:
    def __init__(self, samples: Path = SAMPLES, model: ChatModel | None = None, max_scenes: int = MAX_SCENES,
                 max_reports: int = MAX_REPORTS):
        self.samples = samples
        self.max_scenes = max_scenes
        self.max_reports = max_reports
        self.scenes: dict[str, IfcScene] = {}
        self.reports: dict[str, reports.Report] = {}
        self._matches: dict[tuple[str, str], dict] = {}
        self._runs: dict[str, dict] = {}  # scene id → what its last detection run found, for the next run's diff
        self._run_reports: dict[str, str] = {}  # scene id → its last detection report, whose views a rerun keeps
        # Scene id → {file index: {"step": original STEP, "manifest": converter manifest}} for models opened from STEP,
        # and the scene's own temporary folder (uploads, conversions), deleted when the scene is dropped.
        self.sources: dict[str, dict[int, dict]] = {}
        self._roots: dict[str, Path] = {}
        # Geometry trials edit the model and undo; anything touching a scene's geometry holds this.
        self.lock = threading.RLock()
        self._model = model

    @property
    def model(self) -> ChatModel:
        if self._model is None:
            self._model = MetaChatModel()
        return self._model

    def list_samples(self) -> list[str]:
        return sorted(p.name for p in self.samples.iterdir() if p.suffix.lower() in MODEL_SUFFIXES)

    def open(self, names: list[str], classify_with: ChatModel | None = None, on_event=lambda e: None) -> str:
        """Open one or more sample models that share coordinates (e.g. structure + MEP + architecture). IFC opens as
        is; STEP is converted first (`step.convert`, cached by its hash)."""
        paths = []
        for name in names:
            path = (self.samples / name).resolve()
            if path.parent != self.samples.resolve() or not path.exists():
                raise FileNotFoundError(name)
            paths.append(path)
        return self.open_paths(paths, classify_with=classify_with, on_event=on_event)

    def open_paths(self, paths: list[Path], root: Path | None = None, classify_with: ChatModel | None = None,
                   on_event=lambda e: None) -> str:
        """Open models from these paths (samples, or an upload kept in `root`, which is deleted with the scene)."""
        if not paths:
            raise FileNotFoundError("no models given")
        ifc_paths, sources = [], {}
        try:
            for i, path in enumerate(paths):
                if path.suffix.lower() in step.SUFFIXES:
                    if root is None:
                        MODELS.mkdir(parents=True, exist_ok=True)
                        root = Path(tempfile.mkdtemp(dir=MODELS))
                    ifc, manifest = step.convert(path, root / f"converted-{i}", classify_with, self.step_cache,
                                                 on_event)
                    ifc_paths.append(ifc)
                    sources[i] = {"step": path, "manifest": manifest}
                else:
                    ifc_paths.append(path)
            on_event({"type": "opening", "files": len(ifc_paths)})
            scene = IfcScene(ifc_paths)
            scene.bounds()  # pay the one-off triangulation now, not on the first check
        except BaseException:
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)
            raise
        scene_id = uuid.uuid4().hex[:12]
        self.scenes[scene_id] = scene
        self.sources[scene_id] = sources
        if root is not None:
            self._roots[scene_id] = root
        while self.max_scenes and len(self.scenes) > self.max_scenes:
            old = next(iter(self.scenes))  # oldest first (dicts keep insertion order)
            del self.scenes[old]
            self.sources.pop(old, None)
            if old in self._roots:
                shutil.rmtree(self._roots.pop(old), ignore_errors=True)
        return scene_id

    @property
    def step_cache(self) -> Path:
        """Converted STEP files by hash. `samples/step-cache` when it exists (the demo ships its conversion, so the
        first visitor after a restart does not wait for the part classes), else a temporary folder."""
        shipped = self.samples / "step-cache"
        return shipped if shipped.is_dir() else MODELS / "step-cache"

    def step_files(self, scene_id: str) -> dict[int, str]:
        """File index → the STEP file name it was converted from, for the models of this scene that came from STEP."""
        return {i: Path(src["step"]).name for i, src in self.sources.get(scene_id, {}).items()}

    def scene(self, scene_id: str) -> IfcScene:
        return self.scenes[scene_id]

    def describe(self, scene_id: str, global_id: str) -> dict:
        return asdict(self.scene(scene_id).element(global_id))

    def verify_move(self, scene_id: str, moved: list[str], delta_m: list[float], clearance_m: float = 0.025) -> dict:
        """Check a move without keeping it."""
        s = self.scene(scene_id)
        with self.lock:
            placements = s.translate(moved, tuple(delta_m))
            try:
                v = verify.check(s, moved, clearance_m=clearance_m)
            finally:
                s.translate(moved, tuple(-d for d in delta_m))
        return {**asdict(v), "placements": placements}

    def propose(self, scene_id: str, element_a: str, element_b: str, distance_m: float | None = None,
                images: list[str] | None = None, notes: str = "", report_id: str | None = None,
                clash_id: str | None = None, on_event=None) -> dict:
        """With a report clash, its Navisworks distance and images go to the model too (images are what let
        the model find openings and free space; spikes/README.md, spike 4)."""
        clash = self.clash_for(element_a, element_b, distance_m, images, notes, report_id, clash_id)
        return asdict(agent.resolve(self.scene(scene_id), clash, self.model, on_event=on_event, lock=self.lock,
                                    trials=on_event is not None))

    def clash_for(self, element_a: str, element_b: str, distance_m: float | None = None,
                  images: list[str] | None = None, notes: str = "", report_id: str | None = None,
                  clash_id: str | None = None) -> agent.Clash:
        pics = [Path(p) for p in images or []]
        if report_id and clash_id:
            c = self.report(report_id).clash(clash_id)
            pics = pics or [p for _, p in c.images]
            if distance_m is None:
                distance_m = c.distance_m
            source = (f"Found by ORCA's own detection: {c.test}, {c.name}." if self.report(report_id).origin == "sightline"
                      else f"From a Navisworks clash report: {c.test}, {c.name}.")
            seen = " Images are views of this clash." if pics else ""
            notes = "\n".join(filter(None, [notes, source + seen]))
        return agent.Clash(element_a, element_b, distance_m, pics, notes)

    def apply(self, scene_id: str, moved: list[str], delta_m: list[float]) -> dict:
        s = self.scene(scene_id)
        with self.lock:
            placements = s.translate(moved, tuple(delta_m))
            for g in moved:  # kept: export writes these files
                s.mark_edited(g)
            s.revision += 1
        return {"placements": placements, "files": sorted({s.index_of(g) for g in moved})}

    def check_offset(self, scene_id: str, element: str, other: str, split_m: list[float], dz_m: float,
                     clearance_m: float = 0.025) -> dict:
        """Try a local offset of `element` around `other` without keeping it (see edits.py)."""
        with self.lock:
            attempt, option = agent._try_offset(self.scene(scene_id), {"split_m": split_m, "dz_m": dz_m}, element, other,
                                                clearance_m)
        return {"passed": attempt.passed, "reason": attempt.reason,
                "min_clearance_m": option.min_clearance_m if option else None,
                "preview": option.preview if option else None}

    def apply_offset(self, scene_id: str, element: str, split_m: list[float], dz_m: float) -> dict:
        """Keep a local offset: the element is shortened and new pieces are added to its file."""
        s = self.scene(scene_id)
        with self.lock:
            off = edits.apply_offset(s, element, split_m[0], split_m[1], dz_m)
            s.mark_edited(element)
            s.revision += 1
        return {**asdict(off), "files": [s.index_of(element)]}

    def apply_trim(self, scene_id: str, element: str, end: str, by_m: float) -> dict:
        """Keep a trim: the element's end is cut back (see edits.apply_trim)."""
        s = self.scene(scene_id)
        with self.lock:
            t = edits.apply_trim(s, element, end, by_m)
            s.mark_edited(element)
            s.revision += 1
        return {**asdict(t), "pieces": [element], "files": [s.index_of(element)]}

    def file(self, scene_id: str, index: int, out_dir: Path) -> Path:
        """A model file as it is now: the original on disk, or the edited model written out."""
        with self.lock:
            s = self.scene(scene_id)
            if index not in s._edited:
                return s.paths[index]
            path = out_dir / f"{scene_id}-{index}-{s.paths[index].name}"
            s.models[index].write(str(path))
            return path

    def export(self, scene_id: str, out_dir: Path) -> list[Path]:
        """Write the edited files only; untouched discipline models are not rewritten. A model that came from STEP is
        also written back as STEP, each moved part translated in the original file (`step.export`)."""
        with self.lock:
            s = self.scene(scene_id)
            out = s.write_edited(out_dir)
            for i in sorted(s._edited):
                src = self.sources.get(scene_id, {}).get(i)
                if not src:
                    continue
                parts = json.loads(Path(src["manifest"]).read_text())["parts"]
                moves, replace, add = step_changes(s, i, parts)
                stem = Path(src["step"]).stem
                out.append(step.export(Path(src["step"]), parts, out_dir / f"{stem}.orca.step", moves, replace, add))
            return out

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
        return self._keep(reports.load(uuid.uuid4().hex[:12], root, list(root.glob("*.xml")), name,
                                       exclude=SAMPLE_EXCLUDE))

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
            "id": r.id, "title": r.title, "sources": r.sources, "origin": r.origin,
            "clashes": [{**{k: v for k, v in asdict(c).items() if k != "images"},
                         "images": [label for label, _ in c.images]} for c in r.clashes],
        }

    # ORCA detection (detect.py; design in docs/detection.md).

    def detect_tests(self, scene_id: str) -> dict:
        """The tests a run would use by default for the open models, and the ones offered but off."""
        scene = self.scene(scene_id)
        with self.lock:
            ix = detect._Index(scene)
            tests = detect.default_tests(scene, ix) + detect.presets(scene, ix)
            teams = {name: team for name, team in zip(ix.names, ix.teams)}
            per_file = Counter(ix.names[i] for i in ix.file.values())
        return {"tests": [asdict(t) for t in tests], "teams": teams, "elements": len(ix.entity), "file_elements": dict(per_file),
                "rules": detect.RULE_LABEL}

    def detect(self, scene_id: str, tests: list[dict] | None = None, on_event=None) -> dict:
        """Run ORCA's own clash detection and open the result as a clash report."""
        scene = self.scene(scene_id)
        chosen = None if tests is None else [detect.Test.from_dict(t) for t in tests]
        with self.lock:
            run = detect.run(scene, chosen, on_event=on_event, previous=self._runs.get(scene_id))
        self._runs[scene_id] = run.state
        self._carry(self.reports.get(self._run_reports.get(scene_id, "")), run.report)
        self._run_reports[scene_id] = run.report.id
        report = self._keep(run.report)
        return {"report": self.report_summary(report.id), "coverage": [asdict(c) for c in run.coverage],
                "diff": run.diff, "elements": run.elements, "seconds": run.seconds, "offset": run.offset}

    @staticmethod
    def _carry(old: reports.Report | None, new: reports.Report) -> None:
        """A clash keeps its id across runs, so its title and the views taken of it last time come with it."""
        if old is None:
            return
        titles = {c.id: c.title for c in old.clashes if c.title}
        before = {c.id: c.images for c in old.clashes if c.images}
        for c in new.clashes:
            c.title = c.title or titles.get(c.id)
            for label, path in before.get(c.id, []):
                if path.exists():
                    dest = new.root / "views" / path.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, dest)
                    c.images.append((label, dest))

    def save_capture(self, report_id: str, clash_id: str, label: str, png: bytes) -> list[str]:
        """A view of a detected clash taken in the browser (A, B or C). It joins the clash's images, so the fix agent,
        triage and the PDF see it as they see Navisworks views. Only detected reports take captures."""
        report = self.report(report_id)
        if report.origin != "sightline":
            raise PermissionError("Only clashes found by ORCA take captured views.")
        if label not in ("A", "B", "C"):
            raise ValueError("label must be A, B or C")
        clash = report.clash(clash_id)
        folder = report.root / "views"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{clash_id}-{label}.png"
        path.write_bytes(png)
        images = dict(clash.images)
        images[label] = path
        clash.images = sorted(images.items())
        return [k for k, _ in clash.images]

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

        def shown(gid: str | None) -> str | None:
            """What the viewer can draw for a matched element: a port has no body, so its pipe or valve."""
            if gid is None:
                return None
            e = scene.entity(gid)
            if e.is_a("IfcDistributionPort") or e.is_a("IfcPort"):
                owner = ifcopenshell.util.system.get_port_element(e)
                return owner.GlobalId if owner is not None else None
            return gid

        out = {}
        for c in self.report(report_id).clashes:
            (a, how_a), (b, how_b) = find(c.a), find(c.b)
            out[c.id] = {"a": a, "b": b, "how": [how_a, how_b], "show": [shown(a), shown(b)]}
        self._matches[key] = out
        return out

    def measure(self, report_id: str, clash_id: str, scene_id: str) -> dict:
        """ORCA's own measure of a report clash: the signed distance between the two matched elements.
        None when they do not overlap here, or when they are joined through ports (the check skips those)."""
        with self.lock:
            m = self.match(report_id, scene_id)[clash_id]
            if not (m["a"] and m["b"]):
                return {"matched": False, "physical": None, "distance_m": None}
            scene = self.scene(scene_id)
            physical = scene.bounds().keys()
            if m["a"] not in physical or m["b"] not in physical:
                return {"matched": True, "physical": False, "distance_m": None}
            if self.report(report_id).origin == "sightline":  # the same measure the run used, so the two agree
                return {"matched": True, "physical": True, "distance_m": detect.measure_pair(scene, m["a"], m["b"])}
            v = verify.check(scene, [m["a"]], clearance_m=0.0)
            hit = next((h for h in v.hits if h.other == m["b"]), None)
            return {"matched": True, "physical": True, "distance_m": hit.distance_m if hit else None}


def _spec(scene: IfcScene, element) -> dict:
    """An element's body for `step.export`, in metres and world axes: its extrusion when it is one, else its mesh."""
    try:
        _, _, item, origin, d, px, _ = edits._frames(scene, element)
        k = scene.unit_scales[scene.index_of(element.GlobalId)]
        area = item.SweptArea
        if area.is_a("IfcCircleProfileDef"):
            profile = ("circle", area.Radius * k)
        elif area.is_a("IfcRectangleProfileDef"):
            profile = ("rect", area.XDim * k, area.YDim * k)
        else:
            raise edits.Unsupported(area.is_a())
        return {"kind": "prism", "profile": profile, "start": (np.asarray(origin) * k).tolist(),
                "axis": np.asarray(d).tolist(), "xdir": np.asarray(px).tolist(), "depth": item.Depth * k}
    except edits.Unsupported:
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        geom = ifcopenshell.geom.create_shape(settings, element).geometry
        return {"kind": "mesh", "verts": np.asarray(geom.verts, float).reshape(-1, 3).tolist(),
                "faces": np.asarray(geom.faces, int).reshape(-1, 3).tolist()}


def step_changes(scene: IfcScene, index: int, parts: dict) -> tuple[dict, dict, list]:
    """What changed in a model converted from STEP, for `step.export`: moved parts (placement against the manifest's
    origin), parts whose extrusion changed (an offset's first piece, a trimmed member) and new parts (the rest of an
    offset), each new part tied to the STEP part it came from through its `ORCA_STEP` label."""
    model = scene.models[index]
    moves, replace, add = {}, {}, []
    for gid, info in parts.items():
        try:
            element = model.by_guid(gid)
        except RuntimeError:
            continue
        delta = np.asarray(scene.placement(gid)[:3, 3]) - np.asarray(info["origin"])
        prism = info.get("prism")
        if prism:
            now = _spec(scene, element)
            moved_start = np.asarray(prism["start"]) + delta
            if now["kind"] != "prism" or abs(now["depth"] - prism["depth"]) > 1e-6 \
                    or np.linalg.norm(np.asarray(now["start"]) - moved_start) > 1e-6:
                replace[gid] = now
                continue
        if np.any(np.abs(delta) > 1e-6):
            moves[gid] = delta.tolist()
    known = set(parts)
    for element in model.by_type("IfcElement"):
        if element.GlobalId in known or element.Representation is None or element.is_a("IfcFeatureElement"):
            continue
        source = step_source(element)
        if source.get("Label"):
            add.append({"name": element.Name or element.is_a()[3:], "label": source["Label"],
                        "spec": _spec(scene, element)})
    return moves, replace, add
