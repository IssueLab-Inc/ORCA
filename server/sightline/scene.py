"""Format-neutral scene over a loaded model. The IFC adapter is the only one today.

Elements are addressed by IFC GlobalId everywhere (browser, server, MCP), never by express id,
which is file-local and changes when the file is rewritten.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.system
import ifcopenshell.util.unit

# Things a coordinator normally keeps where they are. The agent may still propose moving them,
# but the domain pack tells it why it usually shouldn't; this flag only drives defaults in the UI.
FIXED_CLASSES = ("IfcBeam", "IfcColumn", "IfcSlab", "IfcWall", "IfcFooting", "IfcMember", "IfcPlate")


@dataclass
class Element:
    global_id: str
    ifc_class: str
    name: str | None
    storey: str | None
    fixed: bool
    connected: list[str] = field(default_factory=list)  # GlobalIds joined through ports


class IfcScene:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.model = ifcopenshell.open(str(self.path))
        # Project length unit → metres. Northbank-style models are often in millimetres.
        self.unit_scale = ifcopenshell.util.unit.calculate_unit_scale(self.model)

    def entity(self, global_id: str):
        return self.model.by_guid(global_id)

    def element(self, global_id: str) -> Element:
        e = self.entity(global_id)
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
            storey=getattr(container, "Name", None), fixed=e.is_a() in FIXED_CLASSES,
            connected=connected,
        )

    def products(self):
        """Every element with a body representation; the set the geometry check runs over."""
        return [p for p in self.model.by_type("IfcElement") if p.Representation is not None]

    def connected_run(self, global_id: str, stop_at=("IfcFlowFitting", "IfcDuctFitting", "IfcPipeFitting")) -> list[str]:
        """The element plus segments joined to it through ports, up to (not including) fittings.

        Moving a run instead of one segment keeps the system connected; the fittings at each end are
        where the proposal says offsets are needed.
        """
        seen, todo = {global_id}, [global_id]
        while todo:
            for other in self.element(todo.pop()).connected:
                if other not in seen and not self.entity(other).is_a() in stop_at:
                    seen.add(other)
                    todo.append(other)
        return sorted(seen)

    def placement(self, global_id: str) -> np.ndarray:
        """World placement of an element in METRES, whatever the project unit."""
        matrix = ifcopenshell.util.placement.get_local_placement(self.entity(global_id).ObjectPlacement).copy()
        matrix[:3, 3] *= self.unit_scale
        return matrix

    def translate(self, global_ids: list[str], delta_m: tuple[float, float, float]) -> dict[str, list[float]]:
        """Move elements by `delta_m` (metres, model axes, Z up). Returns GlobalId → new 4x4 world matrix,
        which is exactly what the browser applies to its preview meshes."""
        moved = {}
        for gid in global_ids:
            matrix = self.placement(gid).copy()
            matrix[:3, 3] += np.asarray(delta_m, dtype=float)
            ifcopenshell.api.run("geometry.edit_object_placement", self.model,
                                 product=self.entity(gid), matrix=matrix, is_si=True)
            moved[gid] = matrix.flatten().tolist()
        return moved

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        self.model.write(str(path))
        return path
