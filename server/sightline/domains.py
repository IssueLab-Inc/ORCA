"""Which domain a scene is in, what stays in place there by default, and the prompts in that domain's voice.

ORCA works on buildings (IFC, Northbank) and machines (a cell opened from STEP, the palletising cell). The requirements
file says which (`requirements.Doc.domain`); without one, a scene whose every model came from STEP is a machine and
anything else a building (`requirements.domain_of`). The fix agent reads a whole pack per domain
(`domain_packs/construction.md`, `domain_packs/machines.md`); the prompts shared by both say who ORCA is through a
`{role}` placeholder, filled here.
"""
from __future__ import annotations

from pathlib import Path

PACKS = Path(__file__).parent / "domain_packs"
CONSTRUCTION = "construction"
MACHINES = "machines"
DOMAINS = (CONSTRUCTION, MACHINES)
NAMES = {CONSTRUCTION: "Building", MACHINES: "Machine"}
# What stays in place (a fix never moves it to make room, nor a run that holds it) when the requirements do not list
# it: these classes and their subclasses (IFC2X3's IfcWallStandardCase is a wall). A requirements file replaces the
# list (`Doc.stays`) and adds every group it allows no edits.
_FRAME = ("IfcBeam", "IfcColumn", "IfcSlab", "IfcWall", "IfcFooting", "IfcPile", "IfcMember", "IfcPlate")
STAYS = {CONSTRUCTION: _FRAME, MACHINES: _FRAME}
# Who reviews a seat (one element cut to bear on another, agent._try_seat): how it bears is the frame's designer's.
SEAT_REVIEW = {CONSTRUCTION: "structure", MACHINES: "structure"}
ROLES = {
    CONSTRUCTION: "a senior BIM coordinator",
    MACHINES: "a senior mechanical integration engineer on a machine and automation cell",
}
# Where the clash titles are read out (titles.md).
MEETINGS = {
    CONSTRUCTION: "a BIM coordination meeting",
    MACHINES: "a machine cell design review",
}

# Words people say about each domain's models, for voice (app._voice_words).
VOICE = {
    CONSTRUCTION: ["duct", "ductwork", "supply air", "cable tray", "pipe", "girder", "beam", "column", "slab", "wall",
                   "mullion", "transom", "curtain wall", "web opening", "MEP", "structure", "architecture", "level"],
    MACHINES: ["conveyor", "robot", "guarding", "fence", "post", "rail", "frame", "pallet", "air line", "pneumatics",
               "cable ladder", "cable chain", "gland plate", "control cabinet", "pedestal", "maintenance access"],
}
# Examples a prompt shows, per domain (`{examples}`): each domain's own kind of element, and none of them a demo's
# answer.
EXAMPLES = {
    "titles": {
        CONSTRUCTION: """- `#12: A IfcPipeSegment 'Cold water main L02 DN54' (Level 02, Domestic cold water); B IfcBeam 'Transfer plate girder
  1000 deep - grid 3' (Level 02); test 'MEP vs Structure' (hard); overlap 77 mm` →
  "Cold-water main clips the transfer girder at grid 3, level 02"
- `#40: A IfcMember 'Transom T4' (Level 01); B IfcMember 'Mullion M2' (Level 01); test 'Architecture (within)' (hard);
  overlap 30 mm` → "Transom T4 runs 30 mm into mullion M2"
- `#7: A IfcColumn 'Column C1 copy 1'; B IfcColumn 'Column C1 copy 2'; test 'Duplicates (all models)' (duplicate);
  overlap 300 mm` → "Column C1 is modelled twice\"""",
        MACHINES: """- `#12: A IfcPipeSegment 'Air line AL-9 DN25' (Compressed air); B IfcMember 'Conveyor CV-12 side rail'; test
  'Services vs Frame and structure' (hard); overlap 40 mm` → "Air line AL-9 clips the conveyor CV-12 side rail"
- `#40: A IfcMember 'Fence top rail N2'; B IfcMember 'Fence post N3'; test 'Frame and structure (within)' (hard);
  overlap 30 mm` → "Fence top rail N2 runs 30 mm into post N3"
- `#7: A IfcColumn 'Pedestal P1 copy 1'; B IfcColumn 'Pedestal P1 copy 2'; test 'Duplicates (all models)' (duplicate);
  overlap 300 mm` → "Pedestal P1 is modelled twice\"""",
    },
}


def infer(ws, scene_id: str | None) -> str:
    """"machines" for a scene whose every model was opened from STEP (`Workspace.sources`), else "construction"
    (IFC, a mix of IFC and STEP, or no scene). `ws` is the Workspace; a stand-in without scenes reads as construction."""
    names = (getattr(ws, "names", None) or {}).get(scene_id) if scene_id else None
    sources = (getattr(ws, "sources", None) or {}).get(scene_id) or {}
    return MACHINES if names and len(sources) == len(names) else CONSTRUCTION


def of(ws, scene_id: str | None) -> str:
    """The scene's domain: what its effective requirements say (`Workspace.requirements_for`: the user's file, else
    the demo's), else `infer`."""
    effective = getattr(ws, "requirements_for", None)
    if effective is not None and scene_id and scene_id in (getattr(ws, "scenes", None) or {}):
        doc = effective(scene_id)
        if doc is not None and doc.domain in DOMAINS:
            return doc.domain
    return infer(ws, scene_id)


def fill(text: str, domain: str = CONSTRUCTION, **fields: str) -> str:
    """`text` with ORCA's role and meeting for `domain` in place of `{role}` and `{meeting}`, and each of `fields`
    (say `teams`) in place of its `{name}`; an empty field drops its " ({name})" or "{name}". Plain replacement: the
    prompts' JSON examples keep their braces."""
    known = {"role": ROLES.get(domain, ROLES[CONSTRUCTION]), "meeting": MEETINGS.get(domain, MEETINGS[CONSTRUCTION]),
             "teams": "", "examples": "", **fields}
    for key, value in known.items():
        if not value:
            text = text.replace(f" ({{{key}}})", "")
        text = text.replace(f"{{{key}}}", value)
    return text


def prompt(name: str, domain: str = CONSTRUCTION, **fields: str) -> str:
    """`domain_packs/<name>.md`, filled for `domain` (`fill`), with that domain's `{examples}` (`EXAMPLES`)."""
    examples = EXAMPLES.get(name, {})
    fields = {"examples": examples.get(domain, examples.get(CONSTRUCTION, "")), **fields}
    return fill((PACKS / f"{name}.md").read_text(), domain, **fields)
