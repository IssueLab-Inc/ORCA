"""The repo's .env reaches every setting, including those modules read at import; real environment variables win, and
an empty number is the same as an unset one.

Each case starts a fresh interpreter on a copy of the package with its own .env two folders above it (where
`meta_client.ENV_FILE` looks), so neither the developer's .env nor the modules this process has imported play a part.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from sightline.limits import env_float, env_int

PKG = Path(__file__).resolve().parents[1] / "sightline"

# What the server read, after importing it the way uvicorn and Modal do (`sightline.app`).
PROBE = """
import json
import sightline.app as app
from sightline import built, context_planner, scene, service, step
print(json.dumps({
    "package": app.__file__,
    "SIGHTLINE_MAX_SCENES": service.MAX_SCENES,
    "SIGHTLINE_SCENE_BUDGET_MB": service.SCENE_BUDGET_MB,
    "SIGHTLINE_MAX_REPORTS": service.MAX_REPORTS,
    "SIGHTLINE_SAMPLE_EXCLUDE": list(service.SAMPLE_EXCLUDE),
    "SIGHTLINE_STEP_MAX_PARTS": step.MAX_PARTS,
    "SIGHTLINE_STEP_MAX_TRIANGLES": step.MAX_TRIANGLES,
    "SIGHTLINE_BIG_MODEL_MB": scene.BIG_MODEL_BYTES >> 20,
    "SIGHTLINE_WIDER_FIX_MAX_MB": context_planner.WIDER_MAX_MB,
    "SIGHTLINE_BUILT_CACHE": str(built.CACHE),
    "SIGHTLINE_PROPOSE_PER_HOUR": app.propose_limit.per_client_hour,
    "SIGHTLINE_PROPOSE_PER_DAY": app.propose_limit.per_day,
    "SIGHTLINE_CHAT_PER_HOUR": app.chat_limit.per_client_hour,
    "SIGHTLINE_DETECT_PER_HOUR": app.detect_limit.per_client_hour,
    "SIGHTLINE_REQUIREMENTS_PER_HOUR": app.requirements_limit.per_client_hour,
    "SIGHTLINE_PREVIEW_PER_HOUR": app.preview_limit.per_client_hour,
    "SIGHTLINE_AGENT_CALLS_PER_HOUR": app.agent_call_limit.per_client_hour,
    "SIGHTLINE_UPLOAD_MAX_MB": app.UPLOAD_MAX_MB,
    "SIGHTLINE_MODEL_UPLOAD_MAX_MB": app.MODEL_UPLOAD_MAX_MB,
    "SIGHTLINE_VOICE_LIVE_MAX_S": app.VOICE_HANDS_FREE_MAX_S,
    "SIGHTLINE_CONTEXT_TRIALS": context_planner.Limits.from_env().trials,
}))
"""
NAMES = [line.split('"')[1] for line in PROBE.splitlines() if line.strip().startswith('"SIGHTLINE_')]


def start(tmp: Path, dotenv: dict[str, str], real: dict[str, str] | None = None) -> dict:
    """Import the server from a copy of the package beside `dotenv`, with `real` as the only real settings."""
    server = tmp / "server"
    shutil.copytree(PKG, server / "sightline", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp / ".env").write_text("".join(f"{k}={v}\n" for k, v in dotenv.items()), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in NAMES}  # this process may hold the developer's .env
    env.update(real or {}, PYTHONPATH=str(server))
    done = subprocess.run([sys.executable, "-c", PROBE], cwd=server, env=env, capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, f"the server did not start:\n{done.stderr[-3000:]}"
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert Path(seen["package"]).resolve().is_relative_to(server.resolve()), "imported the real package, not the copy"
    return seen


def test_dotenv_reaches_settings_read_at_import_and_real_variables_win(tmp_path):
    cache = str(tmp_path / "built")
    seen = start(tmp_path, {
        "SIGHTLINE_MAX_SCENES": "7", "SIGHTLINE_SCENE_BUDGET_MB": "123", "SIGHTLINE_MAX_REPORTS": "5",
        "SIGHTLINE_SAMPLE_EXCLUDE": "IfcSpace", "SIGHTLINE_STEP_MAX_PARTS": "11", "SIGHTLINE_STEP_MAX_TRIANGLES": "22",
        "SIGHTLINE_BIG_MODEL_MB": "3", "SIGHTLINE_WIDER_FIX_MAX_MB": "9", "SIGHTLINE_BUILT_CACHE": cache,
        "SIGHTLINE_PROPOSE_PER_HOUR": "4", "SIGHTLINE_PREVIEW_PER_HOUR": "6",
    }, real={"SIGHTLINE_MAX_REPORTS": "2", "SIGHTLINE_PROPOSE_PER_DAY": "40"})
    assert seen["SIGHTLINE_MAX_SCENES"] == 7 and seen["SIGHTLINE_SCENE_BUDGET_MB"] == 123
    assert seen["SIGHTLINE_SAMPLE_EXCLUDE"] == ["IfcSpace"]
    assert seen["SIGHTLINE_STEP_MAX_PARTS"] == 11 and seen["SIGHTLINE_STEP_MAX_TRIANGLES"] == 22
    assert seen["SIGHTLINE_BIG_MODEL_MB"] == 3 and seen["SIGHTLINE_WIDER_FIX_MAX_MB"] == 9
    assert seen["SIGHTLINE_BUILT_CACHE"] == cache
    assert seen["SIGHTLINE_PROPOSE_PER_HOUR"] == 4 and seen["SIGHTLINE_PREVIEW_PER_HOUR"] == 6
    assert seen["SIGHTLINE_MAX_REPORTS"] == 2, "a real environment variable wins over .env"
    assert seen["SIGHTLINE_PROPOSE_PER_DAY"] == 40


def test_empty_numbers_in_dotenv_take_their_defaults(tmp_path):
    seen = start(tmp_path, {name: "" for name in NAMES if name != "SIGHTLINE_SAMPLE_EXCLUDE"})
    assert seen["SIGHTLINE_MAX_SCENES"] == seen["SIGHTLINE_SCENE_BUDGET_MB"] == seen["SIGHTLINE_MAX_REPORTS"] == 0
    assert seen["SIGHTLINE_STEP_MAX_PARTS"] == 20000 and seen["SIGHTLINE_STEP_MAX_TRIANGLES"] == 5000000
    assert seen["SIGHTLINE_BIG_MODEL_MB"] == 50 and seen["SIGHTLINE_WIDER_FIX_MAX_MB"] == 100
    assert seen["SIGHTLINE_BUILT_CACHE"] == str(Path(tempfile.gettempdir()) / "sightline-built")
    # Caps: empty is no limit where that is the default, and the default where a cap has one of its own.
    assert seen["SIGHTLINE_PROPOSE_PER_HOUR"] == seen["SIGHTLINE_PROPOSE_PER_DAY"] == 0
    assert seen["SIGHTLINE_CHAT_PER_HOUR"] == seen["SIGHTLINE_DETECT_PER_HOUR"] == 0
    assert seen["SIGHTLINE_AGENT_CALLS_PER_HOUR"] == 0
    assert seen["SIGHTLINE_REQUIREMENTS_PER_HOUR"] == 120 and seen["SIGHTLINE_PREVIEW_PER_HOUR"] == 60
    assert seen["SIGHTLINE_UPLOAD_MAX_MB"] == seen["SIGHTLINE_MODEL_UPLOAD_MAX_MB"] == 200
    assert seen["SIGHTLINE_VOICE_LIVE_MAX_S"] == 120 and seen["SIGHTLINE_CONTEXT_TRIALS"] == 12


def test_numbers_from_the_environment(monkeypatch):
    monkeypatch.delenv("ORCA_TEST_NUMBER", raising=False)
    assert env_int("ORCA_TEST_NUMBER", 3) == 3 and env_float("ORCA_TEST_NUMBER", 1.5) == 1.5
    for blank in ("", "  "):
        monkeypatch.setenv("ORCA_TEST_NUMBER", blank)
        assert env_int("ORCA_TEST_NUMBER", 3) == 3 and env_float("ORCA_TEST_NUMBER", 1.5) == 1.5
    monkeypatch.setenv("ORCA_TEST_NUMBER", " 0 ")
    assert env_int("ORCA_TEST_NUMBER", 3) == 0 and env_float("ORCA_TEST_NUMBER", 1.5) == 0.0
    monkeypatch.setenv("ORCA_TEST_NUMBER", "twenty")
    with pytest.raises(ValueError):  # a value that is not a number still stops the server, loudly
        env_int("ORCA_TEST_NUMBER", 3)
