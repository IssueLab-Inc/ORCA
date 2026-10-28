"""The public demo on Modal: one container serves the built web app and the API from one origin.

    cd web && npm ci && npm run build && cd ..
    modal secret create sightline-meta META_API_KEY=...      # once
    modal deploy deploy/modal_app.py

The demo models are the *.ifc files in samples/ at deploy time, and the sample clash reports are in samples/reports/
(not in git; see samples/README.md).

One container, always: open scenes (and their edits) live in that process's memory, and so do the proposal
limits. A second container would answer "Model not loaded" to half the requests.
"""
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = "/app"

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("libpango-1.0-0", "libpangoft2-1.0-0", "libharfbuzz0b", "libharfbuzz-subset0", "fonts-dejavu-core")  # WeasyPrint (PDF reports)
    .uv_sync(str(ROOT / "server"))
    .env({
        "SIGHTLINE_PROPOSE_PER_HOUR": "20",    # per visitor; every proposal is a paid Muse Spark call, a plan costs
        "SIGHTLINE_PROPOSE_PER_DAY": "300",    # one per clash pair; for everyone
        "SIGHTLINE_TRUST_FORWARDED": "1",      # Modal's proxy sets X-Forwarded-For
        "SIGHTLINE_MAX_SCENES": "8",           # open model sets kept in memory
        "SIGHTLINE_MAX_REPORTS": "8",          # open clash reports (uploads are deleted when dropped)
        "SIGHTLINE_UPLOAD_MAX_MB": "150",
        "SIGHTLINE_CHAT_PER_HOUR": "40",       # chat messages per visitor; each is one or more Muse Spark calls
        "SIGHTLINE_CHAT_PER_DAY": "1500",
        "SIGHTLINE_VOICE_PER_HOUR": "60",      # spoken messages per visitor (Muse Voice Transcribe, $0.18 an audio hour)
        "SIGHTLINE_VOICE_PER_DAY": "2000",
        "SIGHTLINE_OPEN_WEIGHTS": "0",         # titles and triage on Muse Spark unless the owner switches the open-weights
                                               # model on (owner settings; kept in the "sightline-settings" Modal Dict)
    })
    .add_local_dir(ROOT / "server" / "sightline", f"{APP_DIR}/server/sightline", ignore=["__pycache__"])
    .add_local_dir(ROOT / "web" / "dist", f"{APP_DIR}/web/dist")
    .add_local_dir(ROOT / "samples", f"{APP_DIR}/samples",  # models, and sample clash reports with their images
                   ignore=lambda p: p.suffix.lower() not in {".ifc", ".xml", ".png", ".jpg", ".jpeg"})
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
