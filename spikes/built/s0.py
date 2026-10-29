"""S0 for Show it built (docs/show-it-built.md), step 3: Muse Image restyles ORCA's view of each fix, and the check
compares the picture with the model.

Reads the passes capture.cjs wrote (look, ids, normals, fix, legend.json) and the manifest from fixes.py.

    cd server && uv run python ../spikes/built/s0.py OUT_DIR [variant ...]

Variants: look (the view alone), lines (the view and its outline drawing), facts (both, plus what the objects are),
design (a known-bad prompt: "improve the design"), keep (lines with the second prompt: no cut wording, the background
kept), keep_r (keep through the Responses API, reasoning high). `keep:2` makes two pictures of each case.
"""
import base64
import io
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from sightline.meta_client import MetaChatModel, load_env  # noqa: E402

load_env()
OUT = Path(sys.argv[1])
VARIANTS = sys.argv[2:] or ["look", "lines", "facts"]
SIDE = 1024
TOL = 4  # pixels: an outline within this distance counts as kept
TILE_MAX = 0.45  # the worst tile's share of new edges (an added object); goods reached 0.42 (glazing), bad 0.45-0.91
F_MIN = 0.55  # edge F-score against ORCA's render; bad pictures of other scenes scored 0.12-0.37

STYLE = ("Restyle this 3D model view as a clean architectural presentation render. Keep the drawing exactly: the same "
         "camera and framing, every object in the same place with the same shape and size. Do not add, remove, move, "
         "bend or resize anything, and do not invent anything that is not shown. Change only how surfaces look: "
         "realistic materials, soft even studio light, gentle ambient occlusion, and a plain light background where "
         "the model ends. Where the model is cut (a section), show a clean cut. No people, no text, no labels.")
LINES = ("The second image is the outline drawing of the same view. Every line in it must stay exactly where it is in "
         "your picture: it is the model, and the model is the record.")
KEEP = ("Restyle this 3D model view as a clean architectural presentation render. Keep the drawing exactly: the same "
        "camera and framing, every object in the same place with the same shape and size, solid objects solid. Do not "
        "add, remove, move, bend, open up or resize anything, and do not invent anything that is not shown: no extra "
        "pipes, rods, hangers, cables, panels, ceilings or lights. Pale objects stay visible as objects. Change only how "
        "surfaces look: realistic materials for what each object is, soft even studio light, gentle ambient occlusion. "
        "Keep the background the same plain light blue-grey. No people, no text, no labels. The second image is the "
        "outline drawing of the same view: every line in it must stay exactly where it is in your picture.")
DESIGN = ("Improve this design: reroute whatever needs it so the services run neatly and nothing clashes, and render "
          "it as a realistic photo of the finished building.")


# ---------------------------------------------------------------- the passes

def png(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def id_map(img: np.ndarray) -> np.ndarray:
    return img[..., 0].astype(np.int64) | (img[..., 1].astype(np.int64) << 8) | (img[..., 2].astype(np.int64) << 16)


def model_lines(ids: np.ndarray, normals: np.ndarray, crease_deg: float = 25) -> np.ndarray:
    """The outline drawing: where the element changes (silhouettes, element against element) and creases (normals
    turning by more than `crease_deg`)."""
    out = np.zeros(ids.shape, bool)
    n = normals.astype(np.float32) / 127.5 - 1
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    cos = np.cos(np.radians(crease_deg))
    for dy, dx in ((0, 1), (1, 0)):
        a, b = ids[: ids.shape[0] - dy, : ids.shape[1] - dx], ids[dy:, dx:]
        na, nb = n[: n.shape[0] - dy, : n.shape[1] - dx], n[dy:, dx:]
        e = (a != b) | ((a > 0) & ((na * nb).sum(-1) < cos))
        out[: out.shape[0] - dy, : out.shape[1] - dx] |= e
    return out


def ids_picture(ids: np.ndarray) -> Image.Image:
    """The ids pass as a picture a reader can use: each element its own flat colour (hues spread by the golden
    ratio, so neighbours differ), the background white."""
    keys, inv = np.unique(ids, return_inverse=True)
    hue = (np.arange(len(keys)) * 0.618034) % 1.0
    sat = 0.55 + 0.4 * ((np.arange(len(keys)) * 0.381966) % 1.0)
    val = 0.6 + 0.35 * ((np.arange(len(keys)) * 0.7548777) % 1.0)
    hsv = np.stack([hue, sat, val], -1)
    i = np.floor(hsv[:, 0] * 6).astype(int) % 6
    f = hsv[:, 0] * 6 - np.floor(hsv[:, 0] * 6)
    v, s_ = hsv[:, 2], hsv[:, 1]
    p_, q, t = v * (1 - s_), v * (1 - f * s_), v * (1 - (1 - f) * s_)
    rgb = np.choose(i[:, None], [np.stack(c, -1) for c in
                                 ((v, t, p_), (q, v, p_), (p_, v, t), (p_, q, v), (t, p_, v), (v, p_, q))])
    rgb[keys == 0] = 1.0
    return Image.fromarray((rgb[inv.reshape(ids.shape)] * 255).astype(np.uint8))


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(r):
        grow = out.copy()
        grow[1:] |= out[:-1]; grow[:-1] |= out[1:]; grow[:, 1:] |= out[:, :-1]; grow[:, :-1] |= out[:, 1:]
        out = grow
    return out


def picture_edges(img: np.ndarray) -> np.ndarray:
    """Edges of a picture: gradient of the slightly blurred grey image, above a quarter of its 99th percentile."""
    g = img.astype(np.float32).mean(-1)
    k = np.ones(3) / 3
    g = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 1, g)
    g = np.apply_along_axis(lambda c: np.convolve(c, k, "same"), 0, g)
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]; gy[1:-1] = g[2:] - g[:-2]
    mag = np.hypot(gx, gy)
    return mag > 0.25 * np.percentile(mag, 99)


# ---------------------------------------------------------------- the check

def check(picture: np.ndarray, p: dict) -> dict:
    """Scores (0 to 1) of a picture against the model's view: whole frame, each large element, the fix, and what is
    new (picture edges far from any model line)."""
    lines, ids, fix = p["lines"], p["ids"], p["fix"]
    edges = picture_edges(picture)
    near_lines, near_edges = dilate(lines, TOL), dilate(edges, TOL)
    recall = (lines & near_edges).sum() / max(lines.sum(), 1)
    precision = (edges & near_lines).sum() / max(edges.sum(), 1)
    f = 2 * recall * precision / max(recall + precision, 1e-9)
    # each element covering at least 1% of the frame keeps its outline
    per = {}
    for k, n in zip(*np.unique(ids, return_counts=True)):
        if k == 0 or n < 0.01 * ids.size:
            continue
        own = lines & dilate(ids == k, 1)
        if own.sum() > 50:
            per[p["legend"].get(str(k), str(k))] = round(float((own & near_edges).sum() / own.sum()), 3)
    fix_zone = dilate(fix, 6)
    fix_lines = lines & fix_zone
    fix_recall = (fix_lines & near_edges).sum() / max(fix_lines.sum(), 1)
    new = (edges & ~dilate(lines, 3 * TOL)).sum() / max(edges.sum(), 1)
    return {"f": round(float(f), 3), "recall": round(float(recall), 3), "precision": round(float(precision), 3),
            "fix": round(float(fix_recall), 3), "new": round(float(new), 3),
            "elements_min": round(min(per.values()), 3) if per else None,
            "elements_median": round(float(np.median(list(per.values()))), 3) if per else None, "elements": per}


JUDGE = {
    "type": "object", "additionalProperties": False, "required": ["model_view_objects", "differences", "verdict"],
    "properties": {
        "model_view_objects": {"type": "array", "items": {"type": "string"}},
        "differences": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["kind", "what", "where", "size"],
            "properties": {"kind": {"type": "string", "enum": ["added", "removed", "moved", "reshaped", "resized"]},
                           "what": {"type": "string"}, "where": {"type": "string"},
                           "size": {"type": "string", "enum": ["small", "medium", "large"]}}}},
        "verdict": {"type": "string", "enum": ["faithful", "minor_differences", "unfaithful"]},
    },
}
JUDGE_SYSTEM = (
    "You audit a restyled picture against the 3D model view it was made from, for a design coordination report. "
    "Image 1 is the model view: the truth. Image 2 must show exactly the same objects, in the same places, with the same "
    "shapes and sizes; only surface appearance (colour, material, texture, light, background) may differ. "
    "First list every object you can see in image 1. Then go over image 2 region by region (top left, top, top right, "
    "left, centre, right, bottom left, bottom, bottom right) and record every difference that is not surface appearance: "
    "an object added (including ceilings, lights, grilles, hangers, rods, cables, pipes, panels, fences, doors, furniture, "
    "people, labels), removed, moved, reshaped or resized. Size: small (a detail), medium (a part of an object, or a small "
    "object), large (a whole object or more). verdict: faithful (no differences), minor_differences (only small ones), "
    "unfaithful (any medium or large one). Be strict: a reader will treat image 2 as the model.")


def judge(model: MetaChatModel, look: Path, picture: Path, tries: int = 2) -> dict:
    """Muse Spark (reasoning high) lists what image 2 adds, drops or reshapes; unfaithful fails the picture."""
    for i in range(tries):
        try:
            return model.complete_json(JUDGE_SYSTEM, "Image 1 then image 2.", [look, picture], JUDGE)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:200]
    return {"verdict": "error", "differences": [], "error": err}


def coarse_edges(img: np.ndarray, side: int = 256, blur: float = 1.6, q: float = 0.3) -> np.ndarray:
    """Edges at a coarse scale, so surface texture (concrete, galvanising) mostly drops out."""
    from PIL import ImageFilter
    im = Image.fromarray(img).convert("L").resize((side, side), Image.LANCZOS).filter(ImageFilter.GaussianBlur(blur))
    g = np.asarray(im, np.float32)
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]; gy[1:-1] = g[2:] - g[:-2]
    mag = np.hypot(gx, gy)
    return mag > q * np.percentile(mag, 99)


def tiles(picture: np.ndarray, look: np.ndarray, lines: np.ndarray, n: int = 8) -> tuple[float, float]:
    """(edge F-score against ORCA's own render, the worst of n x n tiles' share of new edges): an added object shows
    as a tile full of edges where neither the render nor the model's outlines have any."""
    pe, le = coarse_edges(picture), coarse_edges(look)
    ls = np.asarray(Image.fromarray((lines * 255).astype(np.uint8)).resize(pe.shape[::-1], Image.BOX)) > 40
    near_l, near_p = dilate(le, 2), dilate(pe, 2)
    r = (le & near_p).sum() / max(le.sum(), 1); p_ = (pe & near_l).sum() / max(pe.sum(), 1)
    f = 2 * r * p_ / max(r + p_, 1e-9)
    new = dilate(pe & ~dilate(le | ls, 3), 1)
    h = new.shape[0] // n
    worst = max(new[i * h:(i + 1) * h, j * h:(j + 1) * h].mean() for i in range(n) for j in range(n))
    return round(float(f), 3), round(float(worst), 3)


# ---------------------------------------------------------------- Muse Image

def data_url(path_or_img) -> str:
    if isinstance(path_or_img, Path):
        raw = path_or_img.read_bytes()
    else:
        buf = io.BytesIO(); path_or_img.save(buf, "PNG"); raw = buf.getvalue()
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def muse_image(prompt: str, images: list, responses: bool = False) -> tuple[Image.Image, float]:
    headers = {"Authorization": f"Bearer {os.environ['META_API_KEY']}"}
    t = time.time()
    if responses:
        content = [{"type": "input_text", "text": prompt}] + [{"type": "input_image", "image_url": data_url(i)} for i in images]
        body = {"model": "muse-image-1.0", "input": [{"role": "user", "content": content}], "store": False,
                "tools": [{"type": "image_generation", "reasoning_strength": "high", "output_format": "png",
                           "enable_web_search": False, "enable_image_search": False}]}
        r = httpx.post("https://api.meta.ai/v1/responses", json=body, headers=headers, timeout=400)
        r.raise_for_status()
        b64 = next(o["result"] for o in r.json()["output"] if o.get("type") == "image_generation_call" and o.get("result"))
    else:
        body = {"model": "muse-image-1.0", "prompt": prompt, "output_format": "png", "size": "1024x1024",
                "images": [{"image_url": data_url(i)} for i in images]}
        r = httpx.post("https://api.meta.ai/v1/images/edits", json=body, headers=headers, timeout=400)
        r.raise_for_status()
        b64 = r.json()["data"][0]["b64_json"]
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    return img, time.time() - t


# ---------------------------------------------------------------- facts

def facts(case: dict, p: dict, base: str, limit: int = 10) -> list[str]:
    """What the largest objects in the view are, from the server (class, name, storey)."""
    ids = p["ids"]
    keys, counts = np.unique(ids[ids > 0], return_counts=True)
    out = []
    for k, n in sorted(zip(keys, counts), key=lambda x: -x[1])[:limit]:
        gid = p["legend"].get(str(int(k)))
        if not gid:
            continue
        e = json.load(urllib.request.urlopen(f"{base}/api/scenes/{case['scene']}/elements/{gid}"))
        out.append(f"{e.get('name') or e['ifc_class']} ({e['ifc_class'][3:]}, {100 * n / ids.size:.0f}% of the view)")
    return out


def main():
    manifest = json.loads((OUT / "manifest.json").read_text())
    base = manifest["base"]
    spark = MetaChatModel(reasoning_effort="high")
    rows = []
    jobs = []
    for case in manifest["cases"]:
        for pdir in sorted((OUT / "passes").glob(f"{case['name']}-R*")):
            leg = json.loads((pdir / "legend.json").read_text())
            p = {"ids": id_map(png(pdir / "ids.png")), "fix": png(pdir / "fix.png")[..., 0] > 128,
                 "legend": {str(k): v for k, v in leg["legend"].items()}}
            p["lines"] = model_lines(p["ids"], png(pdir / "normals.png"))
            Image.fromarray(np.where(dilate(p["lines"], 1), 0, 255).astype(np.uint8)).save(pdir / "lines.png")
            for v in VARIANTS:
                name, _, n = v.partition(":")
                for k in range(int(n or 1)):
                    jobs.append((case, pdir, p, name if k == 0 else f"{name}{k + 1}"))

    def run(job):
        case, pdir, p, v = job
        kind = v.rstrip("0123456789")
        look, lines_png = pdir / "look.png", pdir / "lines.png"
        prompt, images = STYLE, [look]
        if kind in ("lines", "facts"):
            prompt, images = STYLE + " " + LINES, [look, lines_png]
        if kind == "facts":
            setting = ("a machine cell" if case["files"][0].lower().endswith((".step", ".stp")) else
                       "a building's ceiling void and structure")
            prompt += (f" It shows {setting}. What the objects are, largest first: " + "; ".join(facts(case, p, base))
                       + ". Give each its real material.")
        if kind == "design":
            prompt = DESIGN
        if kind in ("keep", "keep_r"):
            prompt, images = KEEP, [look, lines_png]
        out = pdir / f"muse-{v}.png"
        try:
            if out.exists():
                img, secs = Image.open(out).convert("RGB"), 0.0
            else:
                img, secs = muse_image(prompt, images, responses=kind.endswith("_r"))
                img.save(out)
        except Exception as e:  # noqa: BLE001
            return {"case": case["name"], "pass": pdir.name, "variant": v, "error": f"{type(e).__name__}: {e}"[:300]}
        pic = np.asarray(img.resize((SIDE, SIDE), Image.LANCZOS))
        Image.fromarray(pic).save(pdir / f"muse-{v}-1024.png")
        scores = check(pic, p)
        f_look, tile = tiles(pic, png(look), p["lines"])
        verdict = judge(spark, look, pdir / f"muse-{v}-1024.png")
        big = [d for d in verdict.get("differences", []) if d["size"] != "small"]
        ok = verdict.get("verdict") in ("faithful", "minor_differences") and tile <= TILE_MAX and f_look >= F_MIN
        return {"case": case["name"], "pass": pdir.name, "variant": v, "seconds": round(secs, 1),
                "size": list(img.size), **{k: v2 for k, v2 in scores.items() if k != "elements"},
                "f_look": f_look, "tile": tile, "verdict": verdict.get("verdict"), "big": big, "ok": ok,
                "elements": scores["elements"], "judge": verdict}

    with ThreadPoolExecutor(4) as pool:
        for row in pool.map(run, jobs):
            rows.append(row)
            short = {k: row.get(k) for k in ("case", "variant", "seconds", "f_look", "tile", "verdict", "ok", "error")}
            print(json.dumps(short), [f"{d['kind']} {d['size']}: {d['what']}"[:80] for d in row.get("big", [])][:3])
    with (OUT / "results.jsonl").open("a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
