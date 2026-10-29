"""Format-neutral scene over loaded models. The IFC adapter is the only one today.

A scene is federated: one or more IFC files that share coordinates (architecture, structure, MEP…),
because real clashes are between disciplines and so between files.

Elements are addressed by IFC GlobalId everywhere (browser, server, MCP), never by express id,
which is file-local and changes when the file is rewritten.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import os

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.api
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.system
import ifcopenshell.util.unit

# The pset a part converted from STEP carries (step.py): its group, label and source file. Older conversions, and their
# caches, called it Sightline_STEP.
STEP_PSET = "ORCA_STEP"
STEP_PSETS = (STEP_PSET, "Sightline_STEP")


def step_source(entity) -> dict:
    """Where a part converted from STEP came from (Group, Label, Source), or {} for any other element."""
    for name in STEP_PSETS:
        found = ifcopenshell.util.element.get_pset(entity, name)
        if found:
            return found
    return {}

# Things a coordinator normally keeps where they are. The agent may still propose moving them,
# but the domain pack tells it why it usually shouldn't; this flag only drives defaults in the UI.
FIXED_CLASSES = ("IfcBeam", "IfcColumn", "IfcSlab", "IfcWall", "IfcFooting", "IfcMember", "IfcPlate")

# Not physical: openings are voids already cut from their host, virtual elements have no material.
NOT_PHYSICAL = ("IfcFeatureElement", "IfcVirtualElement")


def is_provision(e) -> bool:
    """A provision for void: the space a service asks to be opened through a wall or slab, drawn in the service's own
    model (IFC4 PredefinedType PROVISIONFORVOID; IFC2X3 has only the ObjectType)."""
    return bool(e.is_a("IfcBuildingElementProxy") and (
        getattr(e, "PredefinedType", None) == "PROVISIONFORVOID"
        or (getattr(e, "ObjectType", None) or "").replace(" ", "").lower() == "provisionforvoid"))


def not_physical(e) -> bool:
    """Not a thing that can clash: an opening, a virtual element, a provision for void."""
    return any(e.is_a(c) for c in NOT_PHYSICAL) or is_provision(e)

FITTINGS = ("IfcFlowFitting", "IfcDuctFitting", "IfcPipeFitting", "IfcCableCarrierFitting")


@dataclass
class Element:
    global_id: str
    ifc_class: str
    name: str | None
    tag: str | None
    storey: str | None
    source: str               # file name the element lives in
    fixed: bool
    connected: list[str] = field(default_factory=list)  # GlobalIds joined through ports


class IfcScene:
    def __init__(self, paths: str | Path | list[str | Path]):
        self.paths = [Path(p) for p in (paths if isinstance(paths, list) else [paths])]
        self.models = [ifcopenshell.open(str(p)) for p in self.paths]
        # Project length unit → metres, per file. Authoring-tool exports are often in millimetres.
        self.unit_scales = [ifcopenshell.util.unit.calculate_unit_scale(m) for m in self.models]
        self._edited: set[int] = set()
        self._bounds: dict[str, np.ndarray] | None = None
        self.revision = 0

    def snapshot(self) -> IfcScene:
        """Clone current in-memory IFC state, including edits not yet exported."""
        clone = object.__new__(IfcScene)
        clone.paths = list(self.paths)
        clone.models = [ifcopenshell.file.from_string(m.to_string()) for m in self.models]
        clone.unit_scales = list(self.unit_scales)
        clone._edited = set(self._edited)
        clone._bounds = None if self._bounds is None else {g: b.copy() for g, b in self._bounds.items()}
        clone.revision = self.revision
        return clone

    # Single-file conveniences (tests, spikes).
    @property
    def path(self) -> Path:
        return self.paths[0]

    @property
    def model(self):
        return self.models[0]

    @property
    def unit_scale(self) -> float:
        return self.unit_scales[0]

    def index_of(self, global_id: str) -> int:
        for i, m in enumerate(self.models):
            try:
                m.by_guid(global_id)
                return i
            except RuntimeError:
                continue
        raise KeyError(f"No element with GlobalId {global_id} in {[p.name for p in self.paths]}")

    def entity(self, global_id: str):
        return self.models[self.index_of(global_id)].by_guid(global_id)

    def element(self, global_id: str) -> Element:
        i = self.index_of(global_id)
        e = self.models[i].by_guid(global_id)
        container = ifcopenshell.util.element.get_container(e)
        connected = []
        for port in ifcopenshell.util.system.get_ports(e):
            other = ifcopenshell.util.system.get_connected_port(port)
            if other is not None:
                owner = ifcopenshell.util.system.get_port_element(other)
                if owner is not None:
                    connected.append(owner.GlobalId)
        return Element(
            global_id=e.GlobalId, ifc_class=e.is_a(), name=getattr(e, "Name", None),
            tag=getattr(e, "Tag", None), storey=getattr(container, "Name", None),
            source=self.paths[i].name, fixed=e.is_a() in FIXED_CLASSES, connected=connected,
        )

    def products(self):
        """Every physical element with a body, across all files; the set the geometry check runs over."""
        return [p for m in self.models for p in m.by_type("IfcElement")
                if p.Representation is not None and not not_physical(p)]

    def bounds(self) -> dict[str, np.ndarray]:
        """GlobalId → [[min x, y, z], [max x, y, z]] in metres at current positions.

        Triangulating the whole federation takes seconds, so it happens once; moves shift the cached boxes.
        The geometry check uses these to test only the neighbourhood of what moved.
        """
        if self._bounds is None:
            settings = ifcopenshell.geom.settings()
            settings.set("use-world-coords", True)
            self._bounds = {}
            by_file: dict[int, list] = {}
            for p in self.products():
                by_file.setdefault(self.index_of(p.GlobalId), []).append(p)
            for i, include in by_file.items():
                it = ifcopenshell.geom.iterator(settings, self.models[i], os.cpu_count() or 1, include=include)
                if not it.initialize():
                    continue
                while True:
                    shape = it.get()
                    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
                    if len(verts):
                        self._bounds[shape.guid] = np.array([verts.min(axis=0), verts.max(axis=0)])
                    if not it.next():
                        break
        return self._bounds

    def refresh_bounds(self, global_ids: list[str]) -> None:
        """Recompute the cached boxes of elements whose shape changed or that were just created."""
        if self._bounds is None:
            return
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        for gid in global_ids:
            if not_physical(self.entity(gid)):   # never a box for what cannot clash: detection reads boxes as physical
                continue
            verts = np.asarray(ifcopenshell.geom.create_shape(settings, self.entity(gid)).geometry.verts,
                               dtype=float).reshape(-1, 3)
            self._bounds[gid] = np.array([verts.min(axis=0), verts.max(axis=0)])

    def mark_edited(self, global_id: str) -> None:
        """Record that the file holding this element changed, so export writes it."""
        self._edited.add(self.index_of(global_id))

    def near(self, global_ids: list[str], margin_m: float) -> set[str]:
        """Elements whose box comes within `margin_m` of the boxes of `global_ids`."""
        b = self.bounds()
        boxes = [b[g] for g in global_ids if g in b]
        if not boxes:
            return set(b)
        lo = np.min([x[0] for x in boxes], axis=0) - margin_m
        hi = np.max([x[1] for x in boxes], axis=0) + margin_m
        return {g for g, x in b.items() if np.all(x[0] <= hi) and np.all(x[1] >= lo)}

    def connected_run(self, global_id: str, stop_at=FITTINGS) -> list[str]:
        """The element plus segments joined to it through ports, up to (not including) fittings.

        Moving a run instead of one segment keeps the system connected; the fittings at each end are
        where the proposal says offsets are needed.
        """
        seen, todo = {global_id}, [global_id]
        while todo:
            for other in self.element(todo.pop()).connected:
                if other not in seen and not any(self.entity(other).is_a(c) for c in stop_at):
                    seen.add(other)
                    todo.append(other)
        if len(seen) == 1:
            seen = set(self.step_run(global_id))
        return sorted(seen)

    def step_run(self, global_id: str, touch_m: float = 0.001) -> list[str]:
        """For a part converted from STEP (no ports): the parts of the same STEP group that touch it, transitively
        (boxes within `touch_m`). A cable ladder's runs and bends move together; fence posts, which touch nothing in
        their own group, move alone. Anything else: just the element."""
        group = self.step_group(global_id)
        if group is None:
            return [global_id]
        b = self.bounds()
        i = self.index_of(global_id)
        members = [e.GlobalId for e in self.models[i].by_type("IfcElement")
                   if e.GlobalId in b and self.step_group(e.GlobalId) == group]
        seen, todo = {global_id}, [global_id]
        while todo:
            box = b.get(todo.pop())
            if box is None:
                continue
            for other in members:
                if other not in seen and np.all(b[other][0] <= box[1] + touch_m) and np.all(b[other][1] >= box[0] - touch_m):
                    seen.add(other)
                    todo.append(other)
        return sorted(seen)

    def step_group(self, global_id: str) -> str | None:
        """The STEP assembly group a converted part came from (pset ORCA_STEP), else None."""
        entity = self.entity(global_id)
        group = step_source(entity).get("Group") if entity is not None else None
        return group if isinstance(group, str) and group else None

    def placement(self, global_id: str) -> np.ndarray:
        """World placement of an element in METRES, whatever the project unit."""
        i = self.index_of(global_id)
        matrix = ifcopenshell.util.placement.get_local_placement(
            self.models[i].by_guid(global_id).ObjectPlacement).copy()
        matrix[:3, 3] *= self.unit_scales[i]
        return matrix

    def translate(self, global_ids: list[str], delta_m: tuple[float, float, float]) -> dict[str, list[float]]:
        """Move elements by `delta_m` (metres, model axes, Z up). Returns GlobalId → new 4x4 world matrix,
        which is exactly what the browser applies to its preview meshes. Trials move and move back with this, so it
        does not mark the file edited: whoever keeps a move calls `mark_edited`."""
        moved = {}
        for gid in global_ids:
            i = self.index_of(gid)
            matrix = self.placement(gid)
            matrix[:3, 3] += np.asarray(delta_m, dtype=float)
            ifcopenshell.api.run("geometry.edit_object_placement", self.models[i],
                                 product=self.models[i].by_guid(gid), matrix=matrix, is_si=True)
            if self._bounds is not None and gid in self._bounds:
                self._bounds[gid] = self._bounds[gid] + np.asarray(delta_m, dtype=float)
            moved[gid] = matrix.flatten().tolist()
        return moved

    def write(self, path: str | Path) -> Path:
        """Write the first (or only) file."""
        path = Path(path)
        self.model.write(str(path))
        return path

    def write_edited(self, out_dir: Path, suffix: str = ".orca") -> list[Path]:
        """Write every file that has edits, as <name><suffix>.ifc. Untouched files are not rewritten."""
        out = []
        for i in sorted(self._edited):
            path = out_dir / f"{self.paths[i].stem}{suffix}.ifc"
            self.models[i].write(str(path))
            out.append(path)
        return out
