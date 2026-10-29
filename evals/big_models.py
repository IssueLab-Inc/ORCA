"""How big a model ORCA can take: synthetic IFC4 files of a given size, opened the way an upload is (server: open,
boxes, detection; browser: upload, parse, draw), with time and memory. Results go in evals/README.md.

    cd server
    uv run python ../evals/big_models.py make --mb 150 --out /tmp/big-150.ifc
    uv run python ../evals/big_models.py server /tmp/big-150.ifc          # open + boxes + detection, peak RSS
    node ../evals/big_models_browser.cjs http://localhost:8000 /tmp/big-150.ifc   # upload, parse, draw, JS heap

The mix is what makes a model's size: a third of the elements are tessellated (fittings, furniture: 100-600
triangles each), the rest extrusions (ducts, pipes, beams, walls), and every element carries a property set of eight
values, as authoring tools export them. Elements sit on a 0.5 m grid in storeys of 3 m, with one planted overlap in 50,
so detection has something to find and nothing explodes.
"""
from __future__ import annotations

import argparse
import math
import os
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

GRID, PITCH, STOREY_H = 400, 0.5, 3.0
CLASSES = ("IfcDuctSegment", "IfcPipeSegment", "IfcBeam", "IfcWall", "IfcMember", "IfcCableCarrierSegment")
MESHES = ("IfcDuctFitting", "IfcFurniture")


def _guid(k: int) -> str:
    import ifcopenshell.guid
    return ifcopenshell.guid.compress(f"{k:032x}")


def make(mb: float, out: Path) -> dict:
    """Write a synthetic IFC4 of about `mb` megabytes. Returns {"elements", "bytes", "seconds"}."""
    t0 = time.perf_counter()
    target = int(mb * 1_000_000)
    lines: list[str] = []
    n = [0]

    def e(text: str) -> int:
        n[0] += 1
        lines.append(f"#{n[0]}={text};\n")
        return n[0]

    head = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [ReferenceView]'),'2;1');\n"
            f"FILE_NAME('{out.name}','2026-10-29T00:00:00',('ORCA'),('IssueLab'),'ORCA big-model eval','ORCA','');\n"
            "FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n")
    person = e("IFCPERSON($,'Eval',$,$,$,$,$,$)")
    org = e("IFCORGANIZATION($,'IssueLab',$,$,$)")
    po = e(f"IFCPERSONANDORGANIZATION(#{person},#{org},$)")
    app = e(f"IFCAPPLICATION(#{org},'1','ORCA eval','ORCA')")
    oh = e(f"IFCOWNERHISTORY(#{po},#{app},$,.ADDED.,$,$,$,0)")
    origin = e("IFCCARTESIANPOINT((0.,0.,0.))")
    world = e(f"IFCAXIS2PLACEMENT3D(#{origin},$,$)")
    ctx = e(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#{world},$)")
    body = e(f"IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#{ctx},$,.MODEL_VIEW.,$)")
    unit = e("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
    units = e(f"IFCUNITASSIGNMENT((#{unit}))")
    project = e(f"IFCPROJECT('{_guid(10**9)}',#{oh},'Big model',$,$,$,$,(#{ctx}),#{units})")
    site_place = e(f"IFCLOCALPLACEMENT($,#{world})")
    building = e(f"IFCBUILDING('{_guid(10**9 + 1)}',#{oh},'Building',$,$,#{site_place},$,$,.ELEMENT.,$,$,$)")
    e(f"IFCRELAGGREGATES('{_guid(10**9 + 2)}',#{oh},$,$,#{project},(#{building}))")
    up, x_dir = e("IFCDIRECTION((0.,0.,1.))"), e("IFCDIRECTION((1.,0.,0.))")
    along_y = e("IFCDIRECTION((0.,1.,0.))")
    profile_pos = e(f"IFCAXIS2PLACEMENT2D(#{e('IFCCARTESIANPOINT((0.,0.))')},$)")
    profiles = [e(f"IFCRECTANGLEPROFILEDEF(.AREA.,$,#{profile_pos},0.3,0.2)"),
                e(f"IFCCIRCLEPROFILEDEF(.AREA.,$,#{profile_pos},0.08)"),
                e(f"IFCRECTANGLEPROFILEDEF(.AREA.,$,#{profile_pos},0.2,0.3)")]
    storeys, contained = [], {}
    k = 0
    size = len(head)
    while size < target:
        level = k // (GRID * GRID)
        if level >= len(storeys):
            sp = e(f"IFCLOCALPLACEMENT(#{site_place},#{e(f'IFCAXIS2PLACEMENT3D(#{e(f"IFCCARTESIANPOINT((0.,0.,{level * STOREY_H:.1f}))")},$,$)')})")
            st = e(f"IFCBUILDINGSTOREY('{_guid(10**9 + 10 + level)}',#{oh},'Level {level:02d}',$,$,#{sp},$,$,.ELEMENT.,{level * STOREY_H:.1f})")
            storeys.append((st, sp))
            contained[st] = []
        st, sp = storeys[level]
        start = len(lines)
        gx, gy = k % GRID, (k // GRID) % GRID
        x, y, z = gx * PITCH, gy * PITCH, 0.5 + (k % 7) * 0.3
        if k % 50 == 49:      # a planted overlap: into its neighbour's place
            x -= PITCH * 0.6
        place = e(f"IFCLOCALPLACEMENT(#{sp},#{e(f'IFCAXIS2PLACEMENT3D(#{e(f"IFCCARTESIANPOINT(({x:.3f},{y:.3f},{z:.3f}))")},$,$)')})")
        if k % 3 == 2:        # tessellated: a fitting or a piece of furniture
            cls = MESHES[k % 2]
            seg = 8 + (k % 5) * 4
            ring = 6 + (k % 4) * 2
            pts = []
            for i in range(seg + 1):
                a = i / seg * math.pi / 2
                for j in range(ring):
                    b = j / ring * 2 * math.pi
                    r = 0.25 + 0.06 * math.cos(b)
                    pts.append(f"({r * math.cos(a):.4f},{r * math.sin(a):.4f},{0.06 * math.sin(b):.4f})")
            faces = []
            for i in range(seg):
                for j in range(ring):
                    p, q = i * ring + j + 1, i * ring + (j + 1) % ring + 1
                    faces.append(f"({p},{q},{q + ring})")
                    faces.append(f"({p},{q + ring},{p + ring})")
            pl = e(f"IFCCARTESIANPOINTLIST3D(({','.join(pts)}),$)")
            item = e(f"IFCTRIANGULATEDFACESET(#{pl},$,.T.,({','.join(faces)}),$)")
            rep = e(f"IFCSHAPEREPRESENTATION(#{body},'Body','Tessellation',(#{item}))")
        else:
            cls = CLASSES[k % len(CLASSES)]
            pos = e(f"IFCAXIS2PLACEMENT3D(#{origin},#{x_dir if k % 2 else along_y},#{up if k % 2 else x_dir})")
            item = e(f"IFCEXTRUDEDAREASOLID(#{profiles[k % 3]},#{pos},#{up},{0.3 + (k % 4) * 0.02:.2f})")
            rep = e(f"IFCSHAPEREPRESENTATION(#{body},'Body','SweptSolid',(#{item}))")
        shape = e(f"IFCPRODUCTDEFINITIONSHAPE($,$,(#{rep}))")
        el = e(f"{cls.upper()}('{_guid(k)}',#{oh},'{cls[3:]} {k}','Synthetic element for the big-model eval',$,#{place},#{shape},'T{k}',$)")
        props = [e(f"IFCPROPERTYSINGLEVALUE('{name}',$,{value},$)") for name, value in (
            ("Reference", f"IFCIDENTIFIER('R-{k:07d}')"), ("Status", "IFCLABEL('New')"),
            ("System", f"IFCLABEL('System {k % 40}')"), ("Manufacturer", "IFCLABEL('Example Ltd')"),
            ("Length", f"IFCLENGTHMEASURE({0.3 + (k % 4) * 0.02:.2f})"), ("Weight", f"IFCMASSMEASURE({(k % 97) * 0.7:.1f})"),
            ("FireRating", "IFCLABEL('EI 60')"), ("Comment", f"IFCTEXT('Element {k} on level {level:02d}')"))]
        pset = e(f"IFCPROPERTYSET('{_guid(2 * 10**9 + k)}',#{oh},'Pset_Synthetic',$,({','.join(f'#{p}' for p in props)}))")
        e(f"IFCRELDEFINESBYPROPERTIES('{_guid(3 * 10**9 + k)}',#{oh},$,$,(#{el}),#{pset})")
        contained[st].append(el)
        size += sum(len(s) for s in lines[start:])
        k += 1
    for i, (st, _) in enumerate(storeys):
        e(f"IFCRELAGGREGATES('{_guid(4 * 10**9 + i)}',#{oh},$,$,#{building},(#{st}))")
        e(f"IFCRELCONTAINEDINSPATIALSTRUCTURE('{_guid(5 * 10**9 + i)}',#{oh},$,$,({','.join(f'#{x}' for x in contained[st])}),#{st})")
    with out.open("w") as f:
        f.write(head)
        f.writelines(lines)
        f.write("ENDSEC;\nEND-ISO-10303-21;\n")
    return {"elements": k, "bytes": out.stat().st_size, "seconds": round(time.perf_counter() - t0, 1)}


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def server(path: Path, detect_too: bool = True) -> dict:
    """Open and box the model as an upload does, then detect; seconds and peak RSS after each."""
    from sightline import detect
    from sightline.scene import IfcScene
    out = {"file_mb": round(path.stat().st_size / 1e6, 1), "rss_start_mb": round(rss_mb())}
    t0 = time.perf_counter()
    scene = IfcScene([path])
    out["open_s"], out["rss_open_mb"] = round(time.perf_counter() - t0, 1), round(rss_mb())
    t1 = time.perf_counter()
    boxes = scene.bounds()
    out["bounds_s"], out["rss_bounds_mb"], out["elements"] = round(time.perf_counter() - t1, 1), round(rss_mb()), len(boxes)
    if detect_too:
        t2 = time.perf_counter()
        run = detect.run(scene)
        out["detect_s"], out["clashes"], out["rss_detect_mb"] = (round(time.perf_counter() - t2, 1),
                                                                 len(run.report.clashes), round(rss_mb()))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--mb", type=float, required=True)
    m.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("server")
    s.add_argument("path", type=Path)
    s.add_argument("--no-detect", action="store_true")
    args = ap.parse_args()
    if args.cmd == "make":
        print(make(args.mb, args.out))
    else:
        print(server(args.path, not args.no_detect), f"cpus {len(os.sched_getaffinity(0))}")


if __name__ == "__main__":
    main()
