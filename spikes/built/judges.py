"""S0 for Show it built, step 4: which judge? Muse Spark (reasoning high) and Muse Wonder (low, medium), three runs
each on the same 31 pictures, scored against labels checked by eye on zoomed crops.

`python judges.py OUT ids [medium]` (or `lines`) judges the hard pictures again with a third image of the model
view. The ids picture is `s0.ids_picture` of the ids pass, saved as ids_picture.png in each pass folder.

Reads OUT/judge3.json (Spark: three verdicts and the pixel gate per picture) and OUT/wonder_judge.json (Wonder),
which `python judges.py OUT run [low,medium]` writes.

    cd server && uv run python ../spikes/built/judges.py OUT run low,medium
    cd server && uv run python ../spikes/built/judges.py OUT
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
import s0  # noqa: E402
from sightline.meta_client import _image_part, load_env  # noqa: E402

OUT = Path(sys.argv[1])
PRICE_IN, PRICE_OUT = 4 / 1e6, 20 / 1e6  # Muse Wonder preview, $ per token

# Restyles that looked faithful at thumbnail size and are not, by eye on zoomed crops (Oct 29):
LATER_BAD = {
    ("airpipe", "keep"): "the flat rectangular support column behind the cross-beam drawn round",
    ("airpipe", "keep2"): "the same column drawn round",
    ("airpipe", "keep_r"): "the block and stub under the slab, top right, dropped",
    ("duct", "keep"): "the tray's closed bend fitting drawn as an open channel",
    ("duct", "keep2"): "the same",
}
# ... and claims checked and found wrong: the cold-water views show two openings side by side in the girder web (the
# outline pass agrees), which Muse Wonder read as one wide slot in all 18 of its runs on them.


THIRD = {  # a third image to read the model view by: what it is, and the file in each pass folder
    "lines": (" Image 3 is the outline drawing of image 1, made from the model itself: use it to read image 1 exactly "
              "(how many openings, where edges and joints are, what is one object or two). It is the same view, not a "
              "third picture to compare.", "lines.png"),
    "ids": (" Image 3 is the same view as image 1 with each separate object of the model in its own flat colour, made "
            "from the model itself: use it to read image 1 exactly (how many objects and openings there are, where one "
            "object ends and the next begins). Its colours mean nothing else, and it is not a third picture to "
            "compare.", "ids_picture.png"),
}


def wonder_judge(look: Path, picture: Path, effort: str, client: httpx.Client, third: str | None = None) -> dict:
    """s0.judge's prompt and schema on Muse Wonder, with the time and the cost of the call. With `third` ("lines" or
    "ids"), that pass of the model view goes along as image 3, to read the model view by."""
    images = [_image_part(look), _image_part(picture)] + ([_image_part(look.parent / THIRD[third][1])] if third else [])
    payload = {"model": "muse-wonder-1.0", "reasoning_effort": effort,
               "messages": [{"role": "system", "content": s0.JUDGE_SYSTEM + (THIRD[third][0] if third else "")},
                            {"role": "user", "content": [{"type": "text", "text": "Image 1, image 2" +
                                                          (", then image 3." if third else ".")}, *images]}],
               "response_format": {"type": "json_schema",
                                   "json_schema": {"name": "reply", "schema": s0.JUDGE, "strict": True}}}
    t = time.time()
    err = ""
    for _ in range(3):
        try:
            r = client.post("https://api.meta.ai/v1/chat/completions", json=payload, timeout=400,
                            headers={"Authorization": f"Bearer {os.environ['META_API_KEY']}"})
            r.raise_for_status()
            body = r.json()
            out = json.loads(body["choices"][0]["message"]["content"])
            u = body.get("usage", {})
            return {**out, "_secs": round(time.time() - t, 1), "_usage": u,
                    "_usd": round(u.get("prompt_tokens", 0) * PRICE_IN + u.get("completion_tokens", 0) * PRICE_OUT, 4)}
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:200]
    return {"verdict": "error", "differences": [], "error": err, "_secs": round(time.time() - t, 1), "_usd": 0}


def run(efforts: list[str]) -> None:
    load_env()
    spark = json.load(open(OUT / "judge3.json"))
    jobs = [((r["case"], r["variant"], e, k)) for r in spark for e in efforts for k in range(3)]
    client = httpx.Client()
    d = OUT / "passes"

    def one(j):
        case, v, e, _ = j
        return [list(j), wonder_judge(d / f"{case}-R3/look.png", d / f"{case}-R3/muse-{v}-1024.png", e, client)]

    with ThreadPoolExecutor(10) as pool:
        json.dump(list(pool.map(one, jobs)), open(OUT / "wonder_judge.json", "w"))


def run_third(third: str, effort: str = "medium", runs: int = 2, everything: bool = False) -> None:
    """The pictures Wonder got wrong or that are hard (the cold-water views, the five found on zoom, the ladder's
    mesh guards) and two easy faithful ones, judged with a third image (`THIRD`) to read the model view by."""
    load_env()
    picks = [("cw", "keep"), ("cw", "keep2"), ("cw", "keep_r"), *LATER_BAD, ("ladder", "keep"), ("transom", "keep"),
             ("tray", "keep")]
    if everything:
        picks = [(r["case"], r["variant"]) for r in json.load(open(OUT / "judge3.json"))]
    client = httpx.Client()
    d = OUT / "passes"

    def one(j):
        case, v, k = j
        return [[case, v, effort, k], wonder_judge(d / f"{case}-R3/look.png", d / f"{case}-R3/muse-{v}-1024.png", effort,
                                                   client, third=third)]

    with ThreadPoolExecutor(10) as pool:
        res = list(pool.map(one, [(c, v, k) for c, v in picks for k in range(runs)]))
    json.dump(res, open(OUT / f"wonder_{third}{'_all' if everything else ''}.json", "w"))
    spark = {(r["case"], r["variant"]): r for r in json.load(open(OUT / "judge3.json"))}
    bad = {k for k, r in spark.items() if r["bad"]} | set(LATER_BAD)
    by: dict = {}
    for (case, v, e, _), r in res:
        by.setdefault((case, v), []).append(r)
    for k, rs in by.items():
        print(f"{k[0]:8} {k[1]:7} {'bad ' if k in bad else 'good'} {[r['verdict'] for r in rs]}",
              [f"{x['kind']} {x['size']}: {x['what']}"[:70] for x in rs[0].get("differences", []) if x["size"] != "small"][:2])
    secs = sorted(r["_secs"] for _, r in res)
    print(f"median {secs[len(secs) // 2]} s, ${sum(r['_usd'] for _, r in res) / len(res):.3f} a call")


def score() -> None:
    spark = {(r["case"], r["variant"]): r for r in json.load(open(OUT / "judge3.json"))}
    wonder: dict = {}
    calls = json.load(open(OUT / "wonder_judge.json"))
    for (case, v, e, _), r in calls:
        wonder.setdefault((case, v, e), []).append(r["verdict"])
    unf = lambda x: x in ("unfaithful", "error")  # noqa: E731
    bad = {k for k, r in spark.items() if r["bad"]} | set(LATER_BAD)
    judges = {
        "Spark high, 1 call": lambda k: unf(spark[k]["verdicts"][0]),
        "Spark high, any of 3": lambda k: any(map(unf, spark[k]["verdicts"])),
        "Wonder low, 1 call": lambda k: unf(wonder[(*k, "low")][0]),
        "Wonder low, any of 3": lambda k: any(map(unf, wonder[(*k, "low")])),
        "Wonder medium, 1 call": lambda k: unf(wonder[(*k, "medium")][0]),
        "Wonder medium, majority of 3": lambda k: sum(map(unf, wonder[(*k, "medium")])) >= 2,
        "Wonder medium, any of 3": lambda k: any(map(unf, wonder[(*k, "medium")])),
        "Wonder low 1 + Spark any of 3": lambda k: unf(wonder[(*k, "low")][0]) or any(map(unf, spark[k]["verdicts"])),
        "Wonder medium 1 + Spark any of 3": lambda k: unf(wonder[(*k, "medium")][0]) or any(map(unf, spark[k]["verdicts"])),
    }
    nb, ng = len(bad), len(spark) - len(bad)
    print(f"{len(spark)} pictures: {nb} bad ({len(LATER_BAD)} of them found on zoomed crops), {ng} faithful\n")
    print(f"{'pixel gate +':34} {'bad rejected':>12} {'faithful passed':>16}")
    for name, fails in judges.items():
        caught = sum(spark[k]["pixel_fail"] or fails(k) for k in bad)
        passed = sum(not (spark[k]["pixel_fail"] or fails(k)) for k in spark if k not in bad)
        print(f"{name:34} {caught:>9}/{nb} {passed:>13}/{ng}")
    for e in ("low", "medium"):
        rs = [r for (_, _, ee, _), r in calls if ee == e]
        if rs:
            secs = sorted(r["_secs"] for r in rs)
            print(f"\nWonder {e}: {len(rs)} calls, median {secs[len(secs) // 2]} s, max {secs[-1]} s, "
                  f"${sum(r['_usd'] for r in rs) / len(rs):.3f} a call")
    # Per call, averaged over every run (a fairer "1 call" than the first run alone).
    runs = {"Spark high": {k: r["verdicts"] for k, r in spark.items()}}
    for e in ("low", "medium"):
        runs[f"Wonder {e}"] = {k: wonder[(*k, e)] for k in spark if (*k, e) in wonder}
    for name, f in (("Wonder medium + outline", "wonder_lines_all.json"), ("Wonder medium + ids", "wonder_ids_all.json")):
        if (OUT / f).exists():
            got: dict = {}
            for (case, v, _, _), r in json.load(open(OUT / f)):
                got.setdefault((case, v), []).append(r["verdict"])
            runs[name] = got
    print(f"\n{'per call, pixel gate +':34} {'bad rejected':>12} {'faithful passed':>16}  runs")
    for name, got in runs.items():
        if len(got) < len(spark):
            continue
        rate = lambda k: 1.0 if spark[k]["pixel_fail"] else sum(map(unf, got[k])) / len(got[k])  # noqa: E731
        caught = sum(rate(k) for k in bad)
        passed = sum(1 - rate(k) for k in spark if k not in bad)
        print(f"{name:34} {caught:>9.1f}/{nb} {passed:>13.1f}/{ng}  {len(next(iter(got.values())))}")
    gen = {v: [k for k in spark if k[1] == v] for v in ("keep", "keep2", "keep_r")}
    print("\nfaithful restyles, by eye: images endpoint", sum(k not in bad for v in ("keep", "keep2") for k in gen[v]),
          "of", len(gen["keep"]) + len(gen["keep2"]),
          "| Responses with reasoning", sum(k not in bad for k in gen["keep_r"]), "of", len(gen["keep_r"]))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "run":
        run(sys.argv[3].split(",") if len(sys.argv) > 3 else ["low", "medium"])
    if len(sys.argv) > 2 and sys.argv[2] in THIRD:
        run_third(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "medium", everything="all" in sys.argv[4:])
    else:
        score()
