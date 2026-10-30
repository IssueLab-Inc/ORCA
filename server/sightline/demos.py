"""The demo projects, in one place: which sample files make each demo, what the start page calls it, its default
coordination requirements, and what the demo models' generator wrote that only the demos need (their property set and
their Navisworks smart tags). Nothing outside this module (and the tour, the landing and the evals) names a demo.

The demo files are IssueLab's own generated models (`docs/architecture/19-demo-data.md`), copied into `samples/`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .requirements import Doc

HERE = Path(__file__).parent / "demos"


@dataclass(frozen=True)
class Demo:
    id: str
    name: str                    # the start page's name for it
    label: str                   # the start button's words
    kind: str                    # "construction" or "machines"
    files: tuple[str, ...]       # opened together by default
    context: tuple[str, ...] = ()   # in the set, not opened by default (grids, a later revision)
    tour: str | None = None      # the guided tour that goes with it (web/src/Tour.tsx)
    requirements: str | None = None   # its default requirements file in `demos/`
    extra: dict = field(default_factory=dict)


DEMOS: tuple[Demo, ...] = (
    Demo(id="northbank", name="Northbank", label="Open the Northbank demo", kind="construction",
         files=("Northbank-Architecture.ifc", "Northbank-MEP.ifc", "Northbank-Site.ifc", "Northbank-Structure.ifc"),
         context=("Northbank-Grids.ifc", "Northbank-MEP-Rev04.ifc"), tour="northbank",
         requirements="northbank.json"),
    Demo(id="cell", name="PC-03 palletising cell", label="Open the machine cell", kind="machines",
         files=("PC-03-Palletising-Cell-RevA.step",), context=("PC-03-Palletising-Cell-RevB.step",), tour="cell",
         requirements="palletising-cell.json"),
)

# The demo models' generator writes one property set per element, and a note on the clash host; the panel shows the
# set by a plain name and hides the note (properties.py). Navisworks smart tags of the demo package (reports.py).
PSET_NAMES = {"ClashWise_Demo": "Model data"}
HIDDEN_PROPERTIES = {"ClashRole"}
SMART_TAG_SET = "ClashWise_Demo"


def _key(name: str) -> str:
    return name.lower()


def find(files: list[str]) -> Demo | None:
    """The demo these opened files belong to: all of them in its set (files and context), case aside."""
    if not files:
        return None
    names = {_key(Path(f).name) for f in files}
    for d in DEMOS:
        if names <= {_key(f) for f in (*d.files, *d.context)}:
            return d
    return None


@lru_cache(maxsize=None)
def _load(file: str) -> "Doc":
    from . import requirements
    return requirements.parse(json.loads((HERE / file).read_text()))


def requirements_for(files: list[str]) -> "Doc | None":
    """A demo's default requirements when these files are a demo set; None for anything else."""
    demo = find(files)
    return _load(demo.requirements) if demo and demo.requirements else None


def listing(samples: list[str]) -> list[dict]:
    """The demos whose default files are all among the samples, for the start page."""
    have = {_key(s): s for s in samples}
    out = []
    for d in DEMOS:
        files = [have[_key(f)] for f in d.files if _key(f) in have]
        if len(files) == len(d.files):
            out.append({"id": d.id, "name": d.name, "label": d.label, "kind": d.kind, "files": files,
                        "context": [have[_key(f)] for f in d.context if _key(f) in have], "tour": d.tour})
    return out
