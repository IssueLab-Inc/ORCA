"""The public demo on Modal: one container serves the built web app and the API from one origin.

    cd web && npm ci && npm run build && cd ..
    modal secret create sightline-meta META_API_KEY=...      # once
    modal deploy deploy/modal_app.py

The demo models are the *.ifc files in samples/ at deploy time (not in git; see samples/README.md).

One container, always: open scenes (and their edits) live in that process's memory, and so do the proposal
limits. A second container would answer "Model not loaded" to half the requests.
"""
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = "/app"

image = (
    modal.Image.debian_slim(python_version="3.13")
    .uv_sync(str(ROOT / "server"))
    .env({
        "SIGHTLINE_PROPOSE_PER_HOUR": "5",     # per visitor; every proposal is a paid Muse Spark call
        "SIGHTLINE_PROPOSE_PER_DAY": "200",    # for everyone
        "SIGHTLINE_TRUST_FORWARDED": "1",      # Modal's proxy sets X-Forwarded-For
        "SIGHTLINE_MAX_SCENES": "8",           # open model sets kept in memory
    })
    .add_local_dir(ROOT / "server" / "sightline", f"{APP_DIR}/server/sightline", ignore=["__pycache__"])
    .add_local_dir(ROOT / "web" / "dist", f"{APP_DIR}/web/dist")
    .add_local_dir(ROOT / "samples", f"{APP_DIR}/samples", ignore=lambda p: p.suffix.lower() != ".ifc")
)

app = modal.App("clashwise-sightline")


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("sightline-meta")],
    cpu=2,
    memory=4096,
    max_containers=1,
    scaledown_window=20 * 60,
    timeout=10 * 60,  # a proposal with retries can take a few minutes
)
@modal.concurrent(max_inputs=32)
@modal.asgi_app()
def web():
    import sys

    sys.path.insert(0, f"{APP_DIR}/server")
    from sightline.app import app as fastapi_app

    return fastapi_app
