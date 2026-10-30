"""S0 for Show it built (docs/show-it-built.md), step 1: real ORCA fixes to picture.

Opens Northbank and the palletising cell on a running server, asks Muse Spark for a fix on each case (the same
/propose the app uses), accepts the best verified option and writes a manifest the capture page reads: per case,
the scene, the fix (kind, moved, edit, preview meshes for framing) and the pair it resolved.

    cd server && uv run python ../spikes/built/fixes.py OUT_DIR [--base http://localhost:8000]
"""
import json
import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "http://localhost:8000"
OUT = Path(sys.argv[1])
NORTHBANK = ["Northbank-Architecture.ifc", "Northbank-MEP.ifc", "Northbank-Structure.ifc"]
CELL = ["PC-03-Palletising-Cell-RevA.step"]
GIRDER = "1eVHoPtl1IhAbbhivqVqb0"
CASES = [  # (name, files, element to fix, the element it clashes with, how the element is named when only a name is known)
    ("duct", NORTHBANK, "2AbvqKF25LGeR0M34N_jld", GIRDER),
    ("tray", NORTHBANK, "3tQ7zxxRDMefPXL6hbHmO2", GIRDER),
    ("cw", NORTHBANK, "1RHD_I4ibLDuUhW1LBAckc", GIRDER),
    ("transom", NORTHBANK, "3FZ5_g0pXGx9qRfB9Lw5Mw", "2AgFm_5w1SU9p7tLtV6sDp"),
    ("ladder", CELL, "name:CT-301 run 2 along the west fence", "name:Fence post W5"),
    ("airpipe", CELL, "name:PL-301 compressed air DN25 segment 2", "name:CV-301 side rail north"),
]


def by_name(c: httpx.Client, sid: str, name: str) -> str:
    """A cell part's GlobalId from its name, through a clash check of the open models (the parts are named)."""
    for line in c.post(f"{BASE}/api/scenes/{sid}/detect/stream", json={}, timeout=300).iter_lines():
        e = json.loads(line)
        if e.get("type") == "done":
            for clash in e["report"]["clashes"]:
                for side in ("a", "b"):
                    if (clash.get(side) or {}).get("name") == name:
                        return clash[side]["global_id"]
    raise SystemExit(f"no part called {name!r}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    c = httpx.Client(timeout=600)
    scenes: dict[tuple, str] = {}
    cases = []
    for name, files, target, other in CASES:
        key = tuple(files)
        if key not in scenes:
            scenes[key] = c.post(f"{BASE}/api/scenes", json={"samples": files}).raise_for_status().json()["id"]
        sid = scenes[key]
        target = by_name(c, sid, target[5:]) if target.startswith("name:") else target
        other = by_name(c, sid, other[5:]) if other.startswith("name:") else other
        t = time.time()
        r = c.post(f"{BASE}/api/scenes/{sid}/propose", json={"element_a": target, "element_b": other})
        if r.status_code != 200:
            print(name, "propose failed", r.status_code, r.text[:300])
            continue
        result = r.json()
        options = result.get("options") or []
        print(f"{name}: {len(options)} verified option(s) in {time.time() - t:.0f} s;",
              [f"{o['kind']} {o['title']}" for o in options])
        if not options:
            continue
        o = options[0]
        if o["kind"] == "offset":
            c.post(f"{BASE}/api/scenes/{sid}/offset/apply",
                   json={"element": o["moved"][0], "split_m": o["split_m"], "dz_m": o["delta_m"][2]}).raise_for_status()
        elif o["kind"] == "trim":
            c.post(f"{BASE}/api/scenes/{sid}/trim/apply", json={"element": o["moved"][0], **o["trim"]}).raise_for_status()
        else:
            c.post(f"{BASE}/api/scenes/{sid}/apply", json={"moved": o["moved"], "delta_m": o["delta_m"]}).raise_for_status()
        cases.append({"name": name, "scene": sid, "files": files, "target": target, "other": other,
                      "kind": o["kind"], "title": o["title"], "moved": o["moved"], "delta_m": o["delta_m"],
                      "split_m": o.get("split_m"), "trim": o.get("trim"), "rationale": o.get("rationale", ""),
                      "preview": o.get("preview") or [], "before": o.get("before") or []})
    (OUT / "manifest.json").write_text(json.dumps({"base": BASE, "cases": cases}))
    print("wrote", OUT / "manifest.json", [x["name"] for x in cases])


if __name__ == "__main__":
    main()
