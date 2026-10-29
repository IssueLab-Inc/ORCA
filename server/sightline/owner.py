"""The owner of a deployment: settings no visitor gets (reasoning effort, no demo caps).

The owner token is a long random secret in the environment (`SIGHTLINE_OWNER_TOKEN`, in the Modal secret), never in git,
chat or the browser's scripts. Unlocking sends it once; the server answers with a signed cookie that scripts cannot read
(HttpOnly, Secure, SameSite=Strict, /api only) and keeps it 30 days. The cookie is signed with a key made from the token,
so changing the token logs every browser out. With no token configured, nobody is the owner.

The owner's settings ride on each request in a header (`X-Sightline-Settings`, JSON), read only when the cookie checks
out, and reach the model calls through context variables. Work that leaves the request's thread (a stream's worker, a
pool of model calls) takes them along with `spawn` and `submit`.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import os
import threading
import time
from concurrent.futures import Executor, Future
from typing import Any, Callable

COOKIE = "sightline_owner"
HEADER = "x-sightline-settings"
DAYS = 30
EFFORTS = ("minimal", "low", "medium", "high")

_effort: contextvars.ContextVar[str | None] = contextvars.ContextVar("effort", default=None)
_triage_effort: contextvars.ContextVar[str | None] = contextvars.ContextVar("triage_effort", default=None)
_owner: contextvars.ContextVar[bool] = contextvars.ContextVar("owner", default=False)
_no_caps: contextvars.ContextVar[bool] = contextvars.ContextVar("no_caps", default=False)
_open_weights: contextvars.ContextVar[bool | None] = contextvars.ContextVar("open_weights", default=None)
_escalation: contextvars.ContextVar[str | None] = contextvars.ContextVar("escalation", default=None)
_escalation_effort: contextvars.ContextVar[str | None] = contextvars.ContextVar("escalation_effort", default=None)
ESCALATION = ("off", "button", "auto")


def _token() -> str:
    return os.environ.get("SIGHTLINE_OWNER_TOKEN", "")


def available() -> bool:
    return len(_token()) >= 24


def _key() -> bytes:
    return hashlib.sha256(b"sightline-owner-cookie:" + _token().encode()).digest()


def check_token(given: str) -> bool:
    return available() and hmac.compare_digest(given.encode(), _token().encode())


def cookie_value(now: float | None = None) -> str:
    expires = int((now or time.time()) + DAYS * 86400)
    sig = hmac.new(_key(), f"v1.{expires}".encode(), hashlib.sha256).hexdigest()
    return f"v1.{expires}.{sig}"


def cookie_ok(value: str | None, now: float | None = None) -> bool:
    if not value or not available():
        return False
    try:
        version, expires, sig = value.split(".")
    except ValueError:
        return False
    good = hmac.new(_key(), f"{version}.{expires}".encode(), hashlib.sha256).hexdigest()
    return version == "v1" and hmac.compare_digest(sig, good) and int(expires) > (now or time.time())


def settings(header: str | None) -> dict:
    """The owner's settings from the header, keeping only known values."""
    try:
        raw = json.loads(header or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k in ("effort", "triage_effort", "escalation_effort"):
        if raw.get(k) in EFFORTS:
            out[k] = raw[k]
    if raw.get("escalation") in ESCALATION:   # absent: follow the setting for everyone
        out["escalation"] = raw["escalation"]
    out["no_caps"] = raw.get("no_caps", True) is not False
    if isinstance(raw.get("open_weights"), bool):  # absent: follow the setting for everyone (settings.py)
        out["open_weights"] = raw["open_weights"]
    return out


def enter(is_owner: bool, header: str | None) -> list:
    """Set this request's context: whether it is the owner's, and the owner's settings. Returns tokens for `leave`."""
    s = settings(header) if is_owner else {}
    return [_owner.set(is_owner), _effort.set(s.get("effort")), _triage_effort.set(s.get("triage_effort")),
            _no_caps.set(is_owner and s.get("no_caps", True)), _open_weights.set(s.get("open_weights")),
            _escalation.set(s.get("escalation")), _escalation_effort.set(s.get("escalation_effort"))]


def leave(tokens: list) -> None:
    for var, tok in zip((_owner, _effort, _triage_effort, _no_caps, _open_weights, _escalation, _escalation_effort),
                        tokens):
        var.reset(tok)


def is_owner() -> bool:
    return _owner.get()


def no_caps() -> bool:
    return _no_caps.get()


def open_weights() -> bool | None:
    """The owner's own choice of the open-weights model for this request, else None (settings.open_weights decides)."""
    return _open_weights.get()


def escalation() -> str | None:
    """The owner's own choice of escalation for this request ("off", "button", "auto"), else None (settings)."""
    return _escalation.get()


def effort(role: str = "default") -> str | None:
    """The owner's reasoning effort for this request (`role` "triage" for the triage model, "escalation" for Muse
    Wonder), else None."""
    return {"triage": _triage_effort, "escalation": _escalation_effort}.get(role, _effort).get()


def spawn(fn: Callable[[], None]) -> threading.Thread:
    """Start a daemon thread that keeps this request's context (the owner's settings)."""
    t = threading.Thread(target=contextvars.copy_context().run, args=(fn,), daemon=True)
    t.start()
    return t


def submit(pool: Executor, fn: Callable, *args) -> Future:
    """`pool.submit`, keeping this request's context in the worker."""
    return pool.submit(contextvars.copy_context().run, fn, *args)
