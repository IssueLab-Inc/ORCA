"""Show it built (docs/show-it-built.md): Muse Image restyles ORCA's own view of a verified fix as a clean
presentation render, and the picture is checked against the model before anyone sees it.

The page renders the fix four ways from one camera (`Viewer.captureBuilt`: a cutaway it picks so the fix shows): the
look (true colours), the ids (one flat colour per element) and the normals. From those the server draws the outline
(`model_lines`), asks Muse Image for two restyles at once (the look and its outline, `PROMPT`), and checks each:

1. the pixel gate (instant): the picture's edges against the look's at a coarse scale (texture drops out), and no
   tile full of new edges where the model has none (an added object): `gate`;
2. two Muse Wonder judges in parallel, given the look, the picture and the ids pass in flat colours to read the
   model view by (`ids_picture`); either one calling it unfaithful fails the picture: `judge`.

The first picture that passes is kept; with none, one more pair with what the judges found in the prompt. Measured
in S0 (spikes/built/, 31 pictures): 17/19 bad pictures rejected, 10/12 faithful passed.

Kept in a cache by a hash of the look, the outline and the prompt's version, so a report, a replay or a second click
reuses it. Muse Image costs $0.01 a picture and Muse Wonder bills its tokens: both charge the day's budget (spend.py).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx
import numpy as np
from PIL import Image, ImageFilter

from . import owner, spend
from .meta_client import MetaChatModel, load_env

PROMPT_VERSION = "1"
CACHE = Path(os.environ.get("SIGHTLINE_BUILT_CACHE", Path(tempfile.gettempdir()) / "sightline-built"))
SIDE = 1024
F_MIN = 0.55        # edge F-score against ORCA's render; S0: faithful 0.65-0.95, other scenes 0.12-0.37
TILE_MAX = 0.45     # the worst of 8 x 8 tiles' share of new edges; S0: faithful at most 0.34
PICTURES = 2        # restyles drawn at once per round
JUDGES = 2          # Muse Wonder judges per picture that passes the gate; either "unfaithful" fails it
ROUNDS = 2          # a second pair, told what the judges found, when the first has no faithful picture
IMAGE_USD = 0.01    # Muse Image, a flat price per picture returned
ESTIMATE_USD = 0.62  # at most, two rounds: four pictures and eight Muse Wonder judgements (held while it runs)
PICTURES_USD = PICTURES * ROUNDS * IMAGE_USD   # the pictures alone, when the judges are the lighter Muse Spark
SPARK_JUDGES = 3    # without Wonder (the day's budget spent): three Muse Spark judges, any of them can fail a picture

PROMPT = ("Restyle this 3D model view as a clean architectural presentation render. Keep the drawing exactly: the "
          "same camera and framing, every object in the same place with the same shape and size, solid objects "
          "solid. Do not add, remove, move, bend, open up or resize anything, and do not invent anything that is not "
          "shown: no extra pipes, rods, hangers, cables, panels, ceilings or lights. Pale objects stay visible as "
          "objects. Change only how surfaces look: realistic materials for what each object is, soft even studio "
          "light, gentle ambient occlusion. Keep the background the same plain light blue-grey. No people, no text, "
          "no labels. The second image is the outline drawing of the same view: every line in it must stay exactly "
          "where it is in your picture.")

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
    "unfaithful (any medium or large one). Be strict: a reader will treat image 2 as the model. "
    "Image 3 is the same view as image 1 with each separate object of the model in its own flat colour, made from the "
    "model itself: use it to read image 1 exactly (how many objects and openings there are, where one object ends and the "
    "next begins). Its colours mean nothing else, and it is not a third picture to compare.")


class Refused(ValueError):
    """Passes that cannot be used (not PNGs, the wrong size), with why."""


# ------------------------------------------------------------------------------------------------- the passes

@dataclass
class Passes:
    look: bytes            # PNG, as the page rendered it
    look_img: np.ndarray   # RGB
    ids: np.ndarray        # one int per pixel: the element drawn there (0: nothing)
    lines: np.ndarray      # bool: the model's outlines

    @property
    def key(self) -> str:
        """What makes two requests the same picture: the look, the outline and the prompt's version."""
        h = hashlib.sha256(self.look)
        h.update(np.packbits(self.lines).tobytes())
        h.update(PROMPT_VERSION.encode())
        return h.hexdigest()[:32]


def _decode(data: str | bytes, what: str) -> np.ndarray:
    try:
        raw = data if isinstance(data, bytes) else base64.b64decode(data.split(",", 1)[-1])
        img = Image.open(io.BytesIO(raw))   # reads the header only: the size is checked before any pixel is
    except Exception as e:  # noqa: BLE001 - anything PIL cannot read
        raise Refused(f"the {what} pass is not a picture: {e}") from e
    if img.size[0] != img.size[1] or not 256 <= img.size[0] <= 2048:
        raise Refused(f"the {what} pass must be square, 256 to 2048 px (got {img.size[0]} x {img.size[1]})")
    try:
        img.load()
    except Exception as e:  # noqa: BLE001
        raise Refused(f"the {what} pass is not a picture: {e}") from e
    return np.asarray(img.convert("RGB"))


def passes(look: str | bytes, ids: str | bytes, normals: str | bytes) -> Passes:
    """The page's three passes (data URLs or bytes) → what the restyle and the check use."""
    look_img, ids_img, normals_img = _decode(look, "look"), _decode(ids, "ids"), _decode(normals, "normals")
    if not (look_img.shape == ids_img.shape == normals_img.shape):
        raise Refused("the passes must be the same size")
    id_map = ids_img[..., 0].astype(np.int64) | (ids_img[..., 1].astype(np.int64) << 8) | (ids_img[..., 2].astype(np.int64) << 16)
    buf = io.BytesIO()
    Image.fromarray(look_img).save(buf, "PNG")
    return Passes(buf.getvalue(), look_img, id_map, model_lines(id_map, normals_img))


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
        out[: out.shape[0] - dy, : out.shape[1] - dx] |= (a != b) | ((a > 0) & ((na * nb).sum(-1) < cos))
    return out


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(r):
        grow = out.copy()
        grow[1:] |= out[:-1]; grow[:-1] |= out[1:]; grow[:, 1:] |= out[:, :-1]; grow[:, :-1] |= out[:, 1:]
        out = grow
    return out


def png(img: np.ndarray | Image.Image) -> bytes:
    buf = io.BytesIO()
    (img if isinstance(img, Image.Image) else Image.fromarray(img)).save(buf, "PNG")
    return buf.getvalue()


def lines_picture(lines: np.ndarray) -> bytes:
    """The outline, black on white, a pixel thicker so it reads (what Muse Image is told to keep)."""
    return png(np.where(dilate(lines, 1), 0, 255).astype(np.uint8))


def ids_picture(ids: np.ndarray) -> bytes:
    """The ids pass as a picture a reader can use: each element its own flat colour (hues spread by the golden
    ratio, so neighbours differ), the background white."""
    keys, inv = np.unique(ids, return_inverse=True)
    k = np.arange(len(keys))
    h, s, v = (k * 0.618034) % 1.0, 0.55 + 0.4 * ((k * 0.381966) % 1.0), 0.6 + 0.35 * ((k * 0.7548777) % 1.0)
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    rgb = np.choose(i[:, None], [np.stack(c, -1) for c in
                                 ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))])
    rgb[keys == 0] = 1.0
    return png((rgb[inv.reshape(ids.shape)] * 255).astype(np.uint8))


# ------------------------------------------------------------------------------------------------- the gate

def coarse_edges(img: np.ndarray, side: int = 256, blur: float = 1.6, q: float = 0.3) -> np.ndarray:
    """Edges at a coarse scale, so surface texture (concrete, galvanising) mostly drops out."""
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert("L").resize((side, side), Image.LANCZOS) \
        .filter(ImageFilter.GaussianBlur(blur))
    g = np.asarray(im, np.float32)
    gx, gy = np.zeros_like(g), np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1] = g[2:] - g[:-2]
    mag = np.hypot(gx, gy)
    return mag > q * max(float(np.percentile(mag, 99)), 1e-6)


def gate(picture: np.ndarray, p: Passes, n: int = 8) -> dict:
    """The pixel gate: {f, tile, passed}. `f`: the picture's coarse edges against the look's (F-score, 2 px at 256);
    `tile`: the worst of n x n tiles' share of edges near neither the look's nor the model's outlines."""
    pe, le = coarse_edges(picture), coarse_edges(p.look_img)
    ls = np.asarray(Image.fromarray((p.lines * 255).astype(np.uint8)).resize(pe.shape[::-1], Image.BOX)) > 40
    near_l, near_p = dilate(le, 2), dilate(pe, 2)
    recall = (le & near_p).sum() / max(le.sum(), 1)
    precision = (pe & near_l).sum() / max(pe.sum(), 1)
    f = float(2 * recall * precision / max(recall + precision, 1e-9))
    new = dilate(pe & ~dilate(le | ls, 3), 1)
    h = new.shape[0] // n
    tile = float(max(new[i * h:(i + 1) * h, j * h:(j + 1) * h].mean() for i in range(n) for j in range(n)))
    return {"f": round(f, 3), "tile": round(tile, 3), "passed": f >= F_MIN and tile <= TILE_MAX}


# ------------------------------------------------------------------------------------------------- the models

def restyle(look: bytes, lines: bytes, extra: str = "", timeout_s: float = 300) -> bytes:
    """One picture from Muse Image (Responses, reasoning high: S0's most faithful setting). Charges $0.01."""
    load_env()
    base = os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
    url = lambda b: "data:image/png;base64," + base64.b64encode(b).decode()  # noqa: E731
    body = {"model": os.environ.get("META_IMAGE_MODEL", "muse-image-1.0"), "store": False,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": PROMPT + extra},
                                                   {"type": "input_image", "image_url": url(look)},
                                                   {"type": "input_image", "image_url": url(lines)}]}],
            "tools": [{"type": "image_generation", "reasoning_strength": "high", "output_format": "png",
                       "enable_web_search": False, "enable_image_search": False}]}
    r = httpx.post(f"{base}/responses", json=body, timeout=timeout_s,
                   headers={"Authorization": f"Bearer {os.environ['META_API_KEY']}"})
    r.raise_for_status()
    found = next((o["result"] for o in r.json().get("output", [])
                  if o.get("type") == "image_generation_call" and o.get("result")), None)
    if not found:
        raise RuntimeError("Muse Image returned no picture")
    spend.charge(IMAGE_USD)
    return base64.b64decode(found)


def judge_model() -> MetaChatModel:
    """Muse Wonder at medium effort (S0's judge), its tokens charged to the day's budget."""
    load_env()
    model = MetaChatModel(model=os.environ.get("META_ESCALATION_MODEL", "muse-wonder-1.0"), timeout_s=240,
                          reasoning_effort="medium")
    model.role = "judge"   # neither the owner's nor everyone's effort for Muse Spark or a second try
    model.on_cost = spend.charge
    return model


def spark_judge_model() -> MetaChatModel:
    """The lighter check, when the day's Muse Wonder budget is spent: Muse Spark (contributor tier, not billed per
    token), three judges where Wonder has two. S0: it passed shape changes Wonder caught, so the picture says so."""
    load_env()
    model = MetaChatModel(timeout_s=240, reasoning_effort="medium")
    model.role = "judge"
    return model


def judge(model, look: bytes, picture: bytes, ids: bytes) -> dict:
    """One judge's verdict: {verdict, differences, ...}; an error counts as unfaithful (`unfaithful`)."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name, data in (("look", look), ("picture", picture), ("ids", ids)):
            path = Path(tmp) / f"{name}.png"
            path.write_bytes(data)
            paths.append(path)
        try:
            return model.complete_json(JUDGE_SYSTEM, "Image 1, image 2, then image 3.", paths, JUDGE)
        except Exception as e:  # noqa: BLE001 - a judge that fails cannot pass a picture
            return {"verdict": "error", "differences": [], "error": f"{type(e).__name__}: {e}"[:200]}


def unfaithful(verdict: dict) -> bool:
    return verdict.get("verdict") not in ("faithful", "minor_differences")


def big_differences(verdicts: list[dict]) -> list[str]:
    seen, out = set(), []
    for v in verdicts:
        for d in v.get("differences", []):
            if d.get("size") in ("medium", "large"):
                line = f"{d.get('kind', 'changed')}: {d.get('what', '?')} ({d.get('where', '?')})"
                if line.lower() not in seen:
                    seen.add(line.lower())
                    out.append(line)
    return out[:6]


# ------------------------------------------------------------------------------------------------- one request

def cached(key: str) -> dict | None:
    meta = CACHE / f"{key}.json"
    if meta.exists() and (CACHE / f"{key}.jpg").exists():
        try:
            return {**json.loads(meta.read_text()), "cached": True}
        except (OSError, json.JSONDecodeError):
            return None
    return None


def path_of(name: str) -> Path | None:
    """A cached file by its public name (`<key>.jpg` or `<key>-lines.png`), or None."""
    if not re.fullmatch(r"[0-9a-f]{32}(\.jpg|-lines\.png)", name):
        return None
    path = CACHE / name
    return path if path.exists() else None


_running: dict[str, "Future"] = {}   # pictures being made now, by key: a second ask waits for the first
_running_lock = threading.Lock()


def running(key: str) -> bool:
    """Whether this picture is being made now (a request for it then waits and costs nothing)."""
    with _running_lock:
        return key in _running


def make(p: Passes, on_event: Callable[[dict], None] = lambda e: None, **kw) -> dict:
    """`_make` once per key at a time: a request for a picture already being made waits for that one's result."""
    with _running_lock:
        mine = p.key not in _running
        fut = _running.setdefault(p.key, Future())
    if not mine:
        on_event({"type": "drawing", "round": 1, "pictures": PICTURES, "shared": True})
        return fut.result()
    try:
        out = _make(p, on_event, **kw)
        fut.set_result(out)
        return out
    except BaseException as e:
        fut.set_exception(e)
        raise
    finally:
        with _running_lock:
            _running.pop(p.key, None)


def _make(p: Passes, on_event: Callable[[dict], None] = lambda e: None, *, restyle_fn=restyle,
         judge_model_fn=judge_model, rounds: int = ROUNDS, judges: int = JUDGES, judged_by: str = "Muse Wonder") -> dict:
    """A checked restyle of the passes: {status: "done", key, image_url, lines_url, gate, verdicts, judge, ...} or
    {status: "failed", why, tried}. Events while it works: drawing {round, pictures}, gate {round, picture, f, tile,
    passed}, judging {round, picture}, judged {round, picture, verdicts}, retry {why}. `lighter`: Muse Spark's three
    judges instead of Wonder's two (`spark_judge_model`)."""
    key = p.key
    hit = cached(key)
    if hit and (judged_by == "Muse Spark" or hit.get("judge", "Muse Wonder") == judged_by):
        return hit   # a picture checked the lighter way is checked again when Wonder can be
    started = time.perf_counter()
    lines_png = lines_picture(p.lines)
    ids_png = ids_picture(p.ids)
    extra = ""
    tried = 0
    found: list[str] = []
    errors: list[str] = []   # Muse Image itself failing (not the check): said as such
    pool = ThreadPoolExecutor(PICTURES * judges)
    try:
        for rnd in range(1, rounds + 1):
            on_event({"type": "drawing", "round": rnd, "pictures": PICTURES})
            drawn = [owner.submit(pool, restyle_fn, p.look, lines_png, extra) for _ in range(PICTURES)]
            pictures: list[tuple[int, bytes, np.ndarray, dict]] = []
            for i, fut in enumerate(drawn, 1):
                try:
                    raw = fut.result()
                except Exception as e:  # noqa: BLE001 - one picture failing leaves the other
                    errors.append(str(e)[:120])
                    on_event({"type": "gate", "round": rnd, "picture": i, "passed": False, "error": str(e)[:200]})
                    continue
                try:
                    img = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB").resize(p.look_img.shape[1::-1], Image.LANCZOS))
                except Exception as e:  # noqa: BLE001 - a reply that is not a picture: the other may be
                    errors.append(str(e)[:120])
                    on_event({"type": "gate", "round": rnd, "picture": i, "passed": False, "error": str(e)[:200]})
                    continue
                tried += 1
                g = gate(img, p)
                on_event({"type": "gate", "round": rnd, "picture": i, **g})
                if g["passed"]:
                    pictures.append((i, png(img), img, g))
            judged = []
            for i, data, img, g in pictures:
                on_event({"type": "judging", "round": rnd, "picture": i})
                calls = [owner.submit(pool, judge, judge_model_fn(), p.look, data, ids_png) for _ in range(judges)]
                judged.append((i, data, img, g, calls))
            for i, data, img, g, calls in judged:
                verdicts = [fut.result() for fut in calls]
                on_event({"type": "judged", "round": rnd, "picture": i,
                          "verdicts": [v.get("verdict") for v in verdicts]})
                found += big_differences(verdicts)
                if not any(unfaithful(v) for v in verdicts):
                    return _keep(key, img, lines_png, g, verdicts, tried, time.perf_counter() - started, judged_by)
            if rnd < rounds:
                why = "; ".join(found) if found else "the pictures strayed from the model's outlines"
                on_event({"type": "retry", "why": why})
                extra = (" A first attempt was rejected because it did not keep to the model: " + why +
                         ". Keep exactly what the model view shows.")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    why = ("Muse Image couldn't keep to the model here: " + "; ".join(found[:3]) if found
           else f"Muse Image didn't return a picture ({errors[0]})." if not tried and errors
           else "Muse Image couldn't keep to the model here.")
    return {"status": "failed", "tried": tried, "seconds": round(time.perf_counter() - started, 1), "why": why}


def _write(path: Path, data: bytes) -> None:
    """Write a cache file whole: a reader never sees half of it."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _keep(key: str, img: np.ndarray, lines_png: bytes, g: dict, verdicts: list[dict], tried: int, seconds: float,
          judged_by: str = "Muse Wonder") -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "JPEG", quality=88)
    _write(CACHE / f"{key}.jpg", buf.getvalue())
    _write(CACHE / f"{key}-lines.png", lines_png)
    out = {"status": "done", "key": key, "image_url": f"/api/built/{key}.jpg", "lines_url": f"/api/built/{key}-lines.png",
           "gate": g, "verdicts": [{"verdict": v.get("verdict"), "differences": v.get("differences", [])} for v in verdicts],
           "tried": tried, "seconds": round(seconds, 1), "judge": judged_by}
    _write(CACHE / f"{key}.json", json.dumps(out).encode())   # last: `cached` reads it as the sign all is there
    return out
