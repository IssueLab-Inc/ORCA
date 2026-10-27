"""Sightline as an MCP server: the same operations the web app uses, for agents such as ClashWise Wise.

Run over stdio:  uv run python -m sightline.mcp_server
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .service import Workspace

mcp = MCPServer("clashwise-sightline", title="ClashWise Sightline")
ws = Workspace()


@mcp.tool()
def list_models() -> list[str]:
    """List the IFC models Sightline can open."""
    return ws.list_samples()


@mcp.tool()
def open_model(names: list[str]) -> str:
    """Open one or more IFC files that share coordinates (e.g. structure + MEP) and return a scene id."""
    return ws.open(names)


@mcp.tool()
def describe_element(scene_id: str, global_id: str) -> dict:
    """Class, name, level, whether it is normally fixed, and what it connects to."""
    return ws.describe(scene_id, global_id)


@mcp.tool()
def verify_move(scene_id: str, moved: list[str], delta_m: list[float], clearance_m: float = 0.025) -> dict:
    """Check a move (metres, Z up) against the whole model without keeping it."""
    return ws.verify_move(scene_id, moved, delta_m, clearance_m)


@mcp.tool()
def propose_solutions(scene_id: str, element_a: str, element_b: str, distance_m: float | None = None,
                      images: list[str] | None = None, notes: str = "") -> dict:
    """Understand a clash and return up to three verified fixes, plus every attempt that failed."""
    return ws.propose(scene_id, element_a, element_b, distance_m, images, notes)


@mcp.tool()
def apply_solution(scene_id: str, moved: list[str], delta_m: list[float]) -> dict:
    """Apply an accepted fix to the open model."""
    return ws.apply(scene_id, moved, delta_m)


@mcp.tool()
def export_model(scene_id: str) -> list[str]:
    """Write the edited IFC files (only those with changes) and return their paths."""
    return [str(p) for p in ws.export(scene_id, Path(tempfile.gettempdir()))]


if __name__ == "__main__":
    mcp.run()
