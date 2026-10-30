"""Which domain a scene is in, and the prompts in that domain's voice.

ORCA works on buildings (IFC, Northbank) and machines (a cell opened from STEP, the palletising cell). The fix agent
reads a whole pack per domain (`domain_packs/construction.md`, `domain_packs/machines.md`); the prompts shared by
both (chat, triage, report, report summary, patterns, root cause) say who ORCA is through a `{role}` placeholder,
filled here. A building's prompts come out exactly as they were written before machines had a voice of their own.
"""
from __future__ import annotations

from pathlib import Path

PACKS = Path(__file__).parent / "domain_packs"
CONSTRUCTION = "construction"
MACHINES = "machines"
ROLES = {
    CONSTRUCTION: "a senior BIM coordinator",
    MACHINES: "a senior mechanical integration engineer on a machine and automation cell",
}


def of(ws, scene_id: str | None) -> str:
    """"machines" for a scene whose every model was opened from STEP (`Workspace.sources`), else "construction"
    (IFC, a mix of IFC and STEP, or no scene). `ws` is the Workspace; a stand-in without scenes reads as construction."""
    names = (getattr(ws, "names", None) or {}).get(scene_id) if scene_id else None
    sources = (getattr(ws, "sources", None) or {}).get(scene_id) or {}
    return MACHINES if names and len(sources) == len(names) else CONSTRUCTION


def prompt(name: str, domain: str = CONSTRUCTION) -> str:
    """`domain_packs/<name>.md` with ORCA's role for `domain` in place of `{role}` (plain replacement: the prompts'
    JSON examples keep their braces)."""
    return (PACKS / f"{name}.md").read_text().replace("{role}", ROLES.get(domain, ROLES[CONSTRUCTION]))
