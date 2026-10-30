"""Settings for everyone: what visitors' requests use, set by the owner (owner.py) and kept across restarts.

- `open_weights`: whether clash titles and triage run on the open-weights model (Muse Spark Open on Baseten) when its
  key is configured. Off, they run on Muse Spark. It costs per hour on the host, so it is off unless switched on.
- `effort` / `triage_effort`: the reasoning effort for Muse Spark (proposals, chat) and for the triage model.
- `escalation`: whether a clash Muse Spark could not fix (or fixed with a resize or an opening) may be handed to Muse
  Wonder for a second try: "off", "button" (offered, the default) or "auto" (a failed proposal goes on to Muse Wonder
  at once). `escalation_effort`: Muse Wonder's reasoning effort (medium by default). Docs: docs/escalation.md.
- `built_views`: whether "Show it built" is offered (Muse Image restyling ORCA's view of a fix, checked by Muse Wonder;
  docs/show-it-built.md) and drawn for every accepted fix's report page. It costs per picture, so it is off unless
  switched on.

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
ESCALATION = ("off", "button", "auto")
DICT_NAME = "sightline-settings"
KEY = "settings"


@dataclass
class Settings:
    open_weights: bool | None = None
    effort: str | None = None
    triage_effort: str | None = None
    escalation: str | None = None
    escalation_effort: str | None = None
    built_views: bool | None = None


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
                    triage_effort=raw.get("triage_effort") if raw.get("triage_effort") in EFFORTS else None,
                    escalation=raw.get("escalation") if raw.get("escalation") in ESCALATION else None,
                    escalation_effort=raw.get("escalation_effort") if raw.get("escalation_effort") in EFFORTS else None,
                    built_views=raw.get("built_views") if isinstance(raw.get("built_views"), bool) else None)


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
        if k not in ("open_weights", "effort", "triage_effort", "escalation", "escalation_effort", "built_views"):
            raise ValueError(f"unknown setting {k!r}")
        if k in ("open_weights", "built_views") and v is not None and not isinstance(v, bool):
            raise ValueError(f"{k} is true, false or null")
        if k == "escalation" and v is not None and v not in ESCALATION:
            raise ValueError(f"escalation is one of {', '.join(ESCALATION)}, or null")
        if k not in ("open_weights", "escalation", "built_views") and v is not None and v not in EFFORTS:
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
    mode = os.environ.get("SIGHTLINE_ESCALATION", "button")
    return {"open_weights": os.environ.get("SIGHTLINE_OPEN_WEIGHTS", "0") == "1",
            "effort": os.environ.get("META_REASONING_EFFORT", "low") or None,
            "triage_effort": os.environ.get("TRIAGE_REASONING_EFFORT") or None,
            "escalation": mode if mode in ESCALATION else "button",
            "escalation_effort": os.environ.get("META_ESCALATION_EFFORT", "medium") or None,
            "built_views": os.environ.get("SIGHTLINE_BUILT_VIEWS", "0") == "1"}


def effort_for(role: str) -> str | None:
    """The effort set for everyone for a model role ("triage", "escalation" or anything else), else None."""
    s = current()
    return {"triage": s.triage_effort, "escalation": s.escalation_effort}.get(role, s.effort)


def built_views() -> bool:
    """Whether this request gets Show it built: the owner's own choice, else everyone's, else the default (off)."""
    from . import owner
    mine = owner.built_views()
    if mine is not None:
        return mine
    s = current()
    return s.built_views if s.built_views is not None else defaults()["built_views"]


def escalation() -> str:
    """Whether this request may hand a clash to Muse Wonder: the owner's own choice, else everyone's, else the
    default ("button")."""
    from . import owner
    mine = owner.escalation()
    if mine is not None:
        return mine
    s = current()
    return s.escalation if s.escalation is not None else defaults()["escalation"]


def open_weights() -> bool:
    """Whether this request uses the open-weights model: the owner's own choice, else everyone's, else the default."""
    from . import owner
    mine = owner.open_weights()
    if mine is not None:
        return mine
    s = current()
    return s.open_weights if s.open_weights is not None else defaults()["open_weights"]
