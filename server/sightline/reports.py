"""Navisworks clash reports (XML) as ORCA reads them: tests, clashes, the two elements and their images.

Reads the Navisworks XML report format (`exchange/batchtest/clashtests/clashtest/clashresults/clashresult`).
Two flavours of element properties are understood:
- grouped smart tags, "<node> / <category> / <property>" (e.g. "Supply air main / Element / GlobalId"), as written by
  the three-view export of IssueLab's demo package; the clashed element is the first group with a non-spatial IFC class;
- the standard export's flat tags ("Item Name", "Item Type", an IFC GUID property), with the selection-tree path.

Images come from each result's `href`, relative to its XML file. When the image sits next to the other views of the
three-view set (A-transparent / B-context / C-alternate), all three are attached.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element as XmlElement

import defusedxml.ElementTree as ET

from . import demos

SPATIAL = {"IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey"}
THREE_VIEW = [("A", "A-transparent.png"), ("B", "B-context.png"), ("C", "C-alternate.png")]
GUID = re.compile(r"^[0-9A-Za-z_$]{22}$")


@dataclass
class ReportElement:
    global_id: str | None
    ifc_class: str | None
    name: str
    level: str | None
    file: str | None          # the model file at the top of the selection tree
    system: str | None = None
    description: str | None = None
    part_of: str | None = None  # parent element, when the clashed item is a sub-object such as a port


@dataclass
class ReportClash:
    id: str                   # stable while the report is open (detected clashes: stable across runs too)
    name: str                 # what it is, plainly: "Cold water main L02 DN54 × Transfer plate girder" (see plain_name)
    guid: str | None
    test: str
    test_type: str | None
    tolerance_m: float | None
    status: str | None
    distance_m: float | None  # Navisworks' signed distance: negative = penetration
    point: list[float] | None
    grid: str | None
    a: ReportElement
    b: ReportElement
    images: list[tuple[str, Path]] = field(default_factory=list)  # (label, file) on the server
    source: str = ""          # the XML file it came from ("sightline" for a clash ORCA found)
    number: int = 0           # #N, unique across the whole report (not per test); people say "#39"
    title: str | None = None  # a short title written by Muse from the clash's facts, when there is one
    ref: str | None = None    # the source tool's own label (Navisworks "Clash39", repeated in every test)
    # A clash ORCA found: the kept checks that found it, check key → its test there (checks.py); empty for an import.
    checks: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """How people and the models refer to it: "#39 Cold-water main clips the girder's bottom flange"."""
        return f"#{self.number} {self.title or self.name}"


def plain_name(a: ReportElement, b: ReportElement) -> str:
    """A name anyone can read, from the two elements, before Muse has titled the clash."""
    def short(e: ReportElement) -> str:
        n = (e.name or e.ifc_class or "element").strip()
        return f"{e.part_of} ({n})" if e.part_of and e.ifc_class and e.ifc_class.endswith("Port") else n
    return f"{short(a)} × {short(b)}"


@dataclass
class Report:
    id: str
    title: str
    root: Path
    sources: list[str]
    clashes: list[ReportClash]
    temporary: bool = False   # uploaded: the folder is deleted when the report is closed
    origin: str = "navisworks"  # "sightline" when ORCA detected the clashes itself (detect.py)
    requirements_id: str | None = None  # a detected run: the requirements it ran under (None: the defaults)
    # ORCA's checks (checks.Register.union): the scene they checked, which union this is (a later one has a higher
    # serial) and the checks it holds, as summaries. None, 0 and [] for an import or a run on its own.
    scene_id: str | None = None
    serial: int = 0
    checks: list[dict] = field(default_factory=list)

    def clash(self, clash_id: str) -> ReportClash:
        """By id, or by number as people say it ("#39" or "39")."""
        for c in self.clashes:
            if c.id == clash_id:
                return c
        number = str(clash_id).strip().lstrip("#")
        if number.isdigit():
            for c in self.clashes:
                if c.number == int(number):
                    return c
        raise KeyError(clash_id)


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _element(obj: XmlElement) -> ReportElement:
    groups: dict[str, dict[str, str]] = {}
    flat: dict[str, str] = {}
    for tag in obj.findall("smarttags/smarttag"):
        key, value = tag.findtext("name") or "", tag.findtext("value") or ""
        parts = key.rsplit(" / ", 2)  # node names can contain " / " themselves, so split from the right
        if len(parts) == 3:
            groups.setdefault(parts[0], {})[f"{parts[1]} / {parts[2]}"] = value
        else:
            flat.setdefault(key, value)
    attrs = {a.findtext("name") or "": a.findtext("value") or "" for a in obj.findall("objectattribute")}
    path = [n.text for n in obj.findall("pathlink/node") if n.text]
    file = path[0] if path else None

    found = [(g, t) for g, t in groups.items() if g and t.get("Element / IfcClass")
             and t["Element / IfcClass"] not in SPATIAL]
    if found:
        name, tags = found[0]
        storey = next((g for g, t in groups.items() if t.get("Element / IfcClass") == "IfcBuildingStorey"), None)
        return ReportElement(
            global_id=tags.get("Element / GlobalId") or tags.get("Element / IfcGUID") or None,
            ifc_class=tags["Element / IfcClass"], name=name,
            level=tags.get(f"{demos.SMART_TAG_SET} / Level") or storey, file=file,
            system=tags.get(f"{demos.SMART_TAG_SET} / System") or None,
            description=tags.get("Element / Description") or None,
            part_of=found[1][0] if len(found) > 1 else None,
        )

    # Standard export: flat properties plus the selection-tree path.
    gid = next((v for k, v in flat.items() if re.search(r"global\s*id|ifc\s*guid", k, re.I) and GUID.match(v)), None)
    if gid is None:
        gid = next((v for v in [*attrs.values(), *flat.values()] if GUID.match(v)), None)
    ifc_class = next((v for k, v in flat.items() if re.search(r"ifc\s*(class|entity)", k, re.I)), None) \
        or next((n for n in reversed(path) if n.startswith("Ifc") and n not in SPATIAL), None) \
        or flat.get("Item Type")
    level = obj.findtext("layer") or next((n for n in path if re.match(r"(level|storey|floor)\b", n, re.I)), None) \
        or flat.get("Item Layer")
    name = flat.get("Item Name") or attrs.get("Name") or (path[-1] if path else "") or "(unnamed)"
    return ReportElement(global_id=gid, ifc_class=ifc_class, name=name, level=level, file=file)


def _images(root: Path, xml_dir: Path, href: str | None) -> list[tuple[str, Path]]:
    if not href:
        return []
    path = (xml_dir / href.replace("\\", "/")).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return []
    views = [(label, path.parent / name) for label, name in THREE_VIEW]
    if path.name in dict(THREE_VIEW).values() and all(p.is_file() for _, p in views):
        return views
    return [("Navisworks", path)]


def read_xml(root: Path, xml: Path) -> list[ReportClash]:
    """Every clash result in one XML file, with images resolved inside `root`."""
    doc = ET.parse(xml).getroot()
    clashes = []
    for test in doc.iter("clashtest"):
        for res in test.iter("clashresult"):
            objs = res.findall("clashobjects/clashobject")
            if len(objs) != 2:
                continue
            pos = res.find("clashpoint/pos3f")
            a, b = _element(objs[0]), _element(objs[1])
            clashes.append(ReportClash(
                id=f"c{len(clashes) + 1:04d}",
                name=plain_name(a, b), ref=res.get("name") or None,
                guid=res.get("guid"),
                test=test.get("name") or "(unnamed test)",
                test_type=test.get("test_type"),
                tolerance_m=_float(test.get("tolerance")),
                status=res.get("status") or res.findtext("resultstatus"),
                distance_m=_float(res.get("distance")),
                point=[_float(pos.get(k)) for k in "xyz"] if pos is not None else None,
                grid=res.findtext("gridlocation") or None,
                a=a, b=b,
                images=_images(root, xml.parent, res.get("href")),
                source=str(xml.relative_to(root)) if xml.is_relative_to(root) else xml.name,
            ))
    return clashes


def load(report_id: str, root: Path, xmls: list[Path], title: str, temporary: bool = False,
         exclude: tuple[str, ...] = ()) -> Report:
    """Read several XML files as one report. The same result exported twice (a combined file and a per-test
    file, say) is kept once, preferring the copy whose image links resolve.

    `exclude` drops every clash test that involves one of these IFC classes (named in the test, or on either side of
    any of its results): the demo leaves out site context, rooms and proxies, which are not coordination problems."""
    read = [c for xml in sorted(xmls) for c in read_xml(root, xml)]
    if exclude:
        def involves(text: str | None) -> bool:
            return any(re.search(rf"\b{re.escape(cls)}\b", text or "", re.IGNORECASE) for cls in exclude)
        dropped = {c.test for c in read if involves(c.test) or involves(c.a.ifc_class) or involves(c.b.ifc_class)}
        read = [c for c in read if c.test not in dropped]
    seen: dict[tuple[str, str], int] = {}
    clashes: list[ReportClash] = []
    for c in read:
        key = (c.test, c.guid or f"{c.ref}@{c.point}")
        if key in seen:
            i = seen[key]
            if len(c.images) > len(clashes[i].images):
                c.id, c.number = clashes[i].id, clashes[i].number
                clashes[i] = c
            continue
        seen[key] = len(clashes)
        c.id = f"c{len(clashes) + 1:04d}"
        c.number = len(clashes) + 1  # #N across the whole report: Navisworks' "Clash39" repeats in every test
        clashes.append(c)
    if not clashes:
        raise ValueError("No clash results found in the XML. Export a clash report from Navisworks as XML.")
    return Report(report_id, title, root, [str(x.relative_to(root)) for x in sorted(xmls)], clashes, temporary)
