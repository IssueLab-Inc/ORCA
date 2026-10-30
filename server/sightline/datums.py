"""Levels, grids and each element's storey, for the viewer's drawing views and its visibility filters (docs/views.md,
"Datums from the server").

Read with IfcOpenShell from the scene's own files, in metres, IFC axes (Z up). When none of them has an `IfcGrid` and
the scene came from the samples folder, the grid is read from `<prefix>-Grids.ifc` there (Northbank's grid lives in its
own file, which the demo does not open): for its grid only, never added to the scene, the check or export.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit

from .scene import IfcScene


def levels(scene: IfcScene) -> list[dict]:
    """Every storey of every file, merged by name and elevation (to the millimetre), lowest first. A storey's elevation
    is its placement's world z (the `Elevation` attribute is optional and sometimes relative); `height_m` is the gap to
    the next level, None for the top one."""
    seen: dict[tuple[str, float], dict] = {}
    for model, scale in zip(scene.models, scene.unit_scales):
        for st in model.by_type("IfcBuildingStorey"):
            z = _elevation(st, scale)
            if z is None:
                continue
            name = st.Name or st.LongName or f"Storey {st.id()}"
            seen.setdefault((name, round(z, 3)), {"name": name, "elevation_m": round(z, 6)})
    out = sorted(seen.values(), key=lambda lv: (lv["elevation_m"], lv["name"]))
    for i, lv in enumerate(out):
        nxt = next((o["elevation_m"] for o in out[i + 1:] if o["elevation_m"] > lv["elevation_m"] + 1e-6), None)
        lv["height_m"] = None if nxt is None else round(nxt - lv["elevation_m"], 6)
    return out


def _elevation(storey, scale: float) -> float | None:
    if storey.ObjectPlacement is not None:
        try:
            return float(ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)[2][3]) * scale
        except Exception:   # an unreadable placement: fall back on the attribute
            pass
    return float(storey.Elevation) * scale if storey.Elevation is not None else None


def grids(models: list[tuple[ifcopenshell.file, float]]) -> list[dict]:
    """Every grid axis drawn as a polyline (U, V and W axes), through its grid's placement: tag, grid name, start and
    end in world metres."""
    out = []
    for model, scale in models:
        for grid in model.by_type("IfcGrid"):
            m = (ifcopenshell.util.placement.get_local_placement(grid.ObjectPlacement)
                 if grid.ObjectPlacement is not None else None)
            for axis in [*(grid.UAxes or ()), *(grid.VAxes or ()), *(getattr(grid, "WAxes", None) or ())]:
                pts = _polyline(axis.AxisCurve)
                if len(pts) < 2:
                    continue
                world = [_place(m, p, scale) for p in (pts[0], pts[-1])]
                out.append({"tag": axis.AxisTag or "", "grid": grid.Name or "Grid", "start": world[0], "end": world[1]})
    return out


def _polyline(curve) -> list[list[float]]:
    if curve is None:
        return []
    if curve.is_a("IfcPolyline"):
        return [list(p.Coordinates) for p in curve.Points]
    if curve.is_a("IfcIndexedPolyCurve"):
        return [list(c) for c in curve.Points.CoordList]
    if curve.is_a("IfcTrimmedCurve") and curve.BasisCurve.is_a("IfcLine"):
        trims = [t for t in (curve.Trim1, curve.Trim2)]
        pts = [next((list(v.Coordinates) for v in t if hasattr(v, "Coordinates")), None) for t in trims]
        return [p for p in pts if p is not None]
    return []


def _place(m, p: list[float], scale: float) -> list[float]:
    x, y, z = (list(p) + [0.0, 0.0])[:3]
    if m is not None:
        x, y, z = (float(m[r][0] * x + m[r][1] * y + m[r][2] * z + m[r][3]) for r in range(3))
    return [round(x * scale, 6), round(y * scale, 6), round(z * scale, 6)]


def storeys(scene: IfcScene) -> dict[str, str]:
    """GlobalId → the name of the storey each physical element stands in (through spaces and assemblies)."""
    out = {}
    for model in scene.models:
        for e in model.by_type("IfcElement"):
            st = ifcopenshell.util.element.get_container(e, ifc_class="IfcBuildingStorey")
            if st is not None:
                out[e.GlobalId] = st.Name or st.LongName or f"Storey {st.id()}"
    return out


def sibling_grids(names: list[str], samples: Path) -> Path | None:
    """`<prefix>-Grids.ifc` in the samples folder for files named `<prefix>-…` (Northbank-Structure.ifc → Northbank),
    when it is not one of them."""
    prefixes = {n.split("-", 1)[0] for n in names if "-" in n}
    if len(prefixes) != 1:
        return None
    path = samples / f"{prefixes.pop()}-Grids.ifc"
    return path if path.exists() and path.name not in names else None


@lru_cache(maxsize=8)
def _grids_of(path: str, mtime: float) -> tuple:
    model = ifcopenshell.open(path)
    return tuple(tuple(sorted(a.items())) for a in grids([(model, ifcopenshell.util.unit.calculate_unit_scale(model))]))


def read(scene: IfcScene, names: list[str], samples: Path | None) -> dict:
    """Levels, grids and storeys for a scene opened from `names` (sample files when `samples` is given)."""
    found = grids(list(zip(scene.models, scene.unit_scales)))
    source = None
    if found:
        source = next((n for n, m in zip(names, scene.models) if m.by_type("IfcGrid")), None)
    elif samples is not None and (path := sibling_grids(names, samples)) is not None:
        found = [dict(a) for a in _grids_of(str(path), path.stat().st_mtime)]
        source = path.name
    return {"levels": levels(scene), "grids": found, "storeys": storeys(scene), "sources": {"grids": source}}
