"""Settings for everyone: what visitors' requests use, set by the owner (owner.py) and kept across restarts.

- `open_weights`: whether clash titles and triage run on the open-weights model (Muse Spark Open on Baseten) when its
  key is configured. Off, they run on Muse Spark. It costs per hour on the host, so it is off unless switched on.
- `effort` / `triage_effort`: the reasoning effort for Muse Spark (proposals, chat) and for the triage model.

None means "the environment's default" (`defaults()`). The owner's own settings, sent with their requests, win over
these for the owner (owner.py); these win over the environment for everyone else.

Stored in a Modal Dict on the deployment (it survives restarts and redeploys), else in a JSON file. A store that cannot
be read or written is logged and the value in memory is used: a setting never fails a request.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

EFFORTS = ("minimal", "low", "medium", "high")
DICT_NAME = "sightline-settings"
KEY = "settings"


@dataclass
class Settings:
    open_weights: bool | None = None
    effort: str | None = None
    triage_effort: str | None = None


_lock = threading.Lock()
_current: Settings | None = None


def _file() -> Path:
    return Path(os.environ.get("SIGHTLINE_SETTINGS_FILE", Path(__file__).resolve().parents[1] / ".sightline-settings.json"))


def _modal_dict():
    """The deployment's Modal Dict, when running in a Modal container."""
    if not os.environ.get("MODAL_TASK_ID"):
        return None
    import modal
    return modal.Dict.from_name(DICT_NAME, create_if_missing=True)


def _clean(raw: object) -> Settings:
    raw = raw if isinstance(raw, dict) else {}
    ow = raw.get("open_weights")
    return Settings(open_weights=ow if isinstance(ow, bool) else None,
                    effort=raw.get("effort") if raw.get("effort") in EFFORTS else None,
                    triage_effort=raw.get("triage_effort") if raw.get("triage_effort") in EFFORTS else None)


def _load() -> Settings:
    try:
        d = _modal_dict()
        if d is not None:
            return _clean(d.get(KEY, {}))
        f = _file()
        return _clean(json.loads(f.read_text())) if f.exists() else Settings()
    except Exception as e:  # the defaults are better than a failed request
        log.warning("settings: could not read the store (%s: %s); using defaults", type(e).__name__, e)
        return Settings()


def _save(s: Settings) -> None:
    try:
        d = _modal_dict()
        if d is not None:
            d[KEY] = asdict(s)
        else:
            _file().write_text(json.dumps(asdict(s), indent=2))
    except Exception as e:
        log.warning("settings: could not write the store (%s: %s); kept in memory", type(e).__name__, e)


def current() -> Settings:
    global _current
    with _lock:
        if _current is None:
            _current = _load()
        return _current


def update(changes: dict) -> Settings:
    """Change some settings (a key set to None goes back to the default). Raises ValueError on an unknown value."""
    global _current
    for k, v in changes.items():
        if k not in ("open_weights", "effort", "triage_effort"):
            raise ValueError(f"unknown setting {k!r}")
        if k == "open_weights" and v is not None and not isinstance(v, bool):
            raise ValueError("open_weights is true, false or null")
        if k != "open_weights" and v is not None and v not in EFFORTS:
            raise ValueError(f"{k} is one of {', '.join(EFFORTS)}, or null")
    s = current()
    with _lock:
        _current = Settings(**{**asdict(s), **changes})
        _save(_current)
        return _current


def reset_cache() -> None:
    """Read the store again on next use (tests)."""
    global _current
    with _lock:
        _current = None


def defaults() -> dict:
    """What the environment gives when a setting is not set."""
    return {"open_weights": os.environ.get("SIGHTLINE_OPEN_WEIGHTS", "0") == "1",
            "effort": os.environ.get("META_REASONING_EFFORT", "low") or None,
            "triage_effort": os.environ.get("TRIAGE_REASONING_EFFORT") or None}


def effort_for(role: str) -> str | None:
    """The effort set for everyone for a model role ("triage" or anything else), else None."""
    s = current()
    return s.triage_effort if role == "triage" else s.effort


def open_weights() -> bool:
    """Whether this request uses the open-weights model: the owner's own choice, else everyone's, else the default."""
    from . import owner
    mine = owner.open_weights()
    if mine is not None:
        return mine
    s = current()
    return s.open_weights if s.open_weights is not None else defaults()["open_weights"]
