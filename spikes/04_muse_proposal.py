"""Spike 4: does Muse Spark return a usable structured proposal for one clash?

    # META_API_KEY in .env or the environment; base URL and model default to https://api.meta.ai/v1 and muse-spark-1.3-contributor
    cd server
    uv run python ../spikes/04_muse_proposal.py A.png B.png C.png \
        --a "IfcFlowTerminal 'Fan coil unit', Level 03" --b "IfcBeam 'Open-web joist', Level 03" --distance-mm -94.8

Run it 3 times on the same clash: the proposals should agree on the direction of the fix.
Pass: valid JSON every time, sensible moves, and an "understanding" you would sign off.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from sightline.meta_client import MetaChatModel  # noqa: E402

PACK = Path(__file__).resolve().parents[1] / "server/sightline/domain_packs/construction.md"

p = argparse.ArgumentParser()
p.add_argument("images", nargs="*", type=Path)
p.add_argument("--a", required=True, help="element A (red): class, name, level")
p.add_argument("--b", required=True, help="element B (green): class, name, level")
p.add_argument("--distance-mm", type=float)
p.add_argument("--notes", default="")
p.add_argument("--runs", type=int, default=1)
args = p.parse_args()

text = f"Element A (red): {args.a}\nElement B (green): {args.b}\n"
if args.distance_mm is not None:
    text += f"Reported signed distance: {args.distance_mm} mm (negative = overlap)\n"
if args.notes:
    text += f"Notes: {args.notes}\n"

model = MetaChatModel()
for i in range(args.runs):
    t = time.perf_counter()
    reply = model.complete_json(PACK.read_text(), text, args.images)
    print(f"--- run {i + 1} · {time.perf_counter() - t:.1f} s · model {model.model}")
    print(json.dumps(reply, indent=2))
