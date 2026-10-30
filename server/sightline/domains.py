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
# Where the clash titles are read out (titles.md).
MEETINGS = {
    CONSTRUCTION: "a BIM coordination meeting",
    MACHINES: "a machine cell design review",
}


def of(ws, scene_id: str | None) -> str:
    """"machines" for a scene whose every model was opened from STEP (`Workspace.sources`), else "construction"
    (IFC, a mix of IFC and STEP, or no scene). `ws` is the Workspace; a stand-in without scenes reads as construction."""
    names = (getattr(ws, "names", None) or {}).get(scene_id) if scene_id else None
    sources = (getattr(ws, "sources", None) or {}).get(scene_id) or {}
    return MACHINES if names and len(sources) == len(names) else CONSTRUCTION


def fill(text: str, domain: str = CONSTRUCTION, **fields: str) -> str:
    """`text` with ORCA's role and meeting for `domain` in place of `{role}` and `{meeting}`, and each of `fields`
    (say `teams`) in place of its `{name}`; an empty field drops its " ({name})" or "{name}". Plain replacement: the
    prompts' JSON examples keep their braces."""
    known = {"role": ROLES.get(domain, ROLES[CONSTRUCTION]), "meeting": MEETINGS.get(domain, MEETINGS[CONSTRUCTION]),
             "teams": "", **fields}
    for key, value in known.items():
        if not value:
            text = text.replace(f" ({{{key}}})", "")
        text = text.replace(f"{{{key}}}", value)
    return text


def prompt(name: str, domain: str = CONSTRUCTION, **fields: str) -> str:
    """`domain_packs/<name>.md`, filled for `domain` (`fill`)."""
    return fill((PACKS / f"{name}.md").read_text(), domain, **fields)
