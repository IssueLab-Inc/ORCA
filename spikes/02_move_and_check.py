"""Spikes 2 and 3: move one element of a real model, write it, reload it, and time the geometry check.

    cd server
    uv run python ../spikes/02_move_and_check.py ../samples/Northbank-MEP.ifc <GlobalId> --dz -0.25

Without a GlobalId it lists the first duct, pipe and cable-tray segments to pick from.
Pass: the edited file reopens with the element moved, and one check takes a few seconds at most.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from sightline.scene import IfcScene  # noqa: E402
from sightline import verify  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("ifc", type=Path)
p.add_argument("global_id", nargs="?")
p.add_argument("--dx", type=float, default=0.0)
p.add_argument("--dy", type=float, default=0.0)
p.add_argument("--dz", type=float, default=-0.25)
args = p.parse_args()

t = time.perf_counter()
scene = IfcScene(args.ifc)
print(f"Opened {args.ifc.name} in {time.perf_counter() - t:.1f} s · unit scale {scene.unit_scale} · "
      f"{len(scene.products())} elements with geometry")

if not args.global_id:
    for cls in ("IfcDuctSegment", "IfcPipeSegment", "IfcCableCarrierSegment"):
        for e in scene.model.by_type(cls)[:5]:
            print(f"  {cls:24} {e.GlobalId}  {e.Name}")
    sys.exit(0)

gid = args.global_id
print("Element:", scene.element(gid))
print("Connected run:", scene.connected_run(gid))

t = time.perf_counter()
before = verify.check(scene, [gid])
print(f"Check before move: {time.perf_counter() - t:.1f} s · passed={before.passed} · hits={before.hits[:5]}")

scene.translate([gid], (args.dx, args.dy, args.dz))
t = time.perf_counter()
after = verify.check(scene, [gid])
print(f"Check after move:  {time.perf_counter() - t:.1f} s · passed={after.passed} · "
      f"min clearance={after.min_clearance_m} · hits={after.hits[:5]}")

out = scene.write(args.ifc.with_suffix(".spike.ifc"))
again = IfcScene(out)
print("Reloaded placement (m):", again.placement(gid)[:3, 3], "→", out)
