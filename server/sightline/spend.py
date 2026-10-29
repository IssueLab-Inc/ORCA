"""What the per-token models cost today, and the day's limit (docs/escalation.md).

Muse Wonder (escalations, Show it built's judges) bills every token; nothing else here does. Each priced call is
charged as it lands (`meta_client.MetaChatModel.on_cost`); a new piece of paid work asks `refused` first and holds
its estimate while it runs (`held`):

    SIGHTLINE_WONDER_MAX_USD_DAY   25 (default); 0 means no limit

Kept in memory per server (UTC day): a restart starts the day's count again. The owner's requests skip the limit as
they skip the demo caps (`refused(exempt=)`), and are still counted.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager

_lock = threading.Lock()
_day = ""
_spent = 0.0
_held = 0.0      # what paid work still running may cost (its estimate), until it ends


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def limit() -> float:
    try:
        return max(0.0, float(os.environ.get("SIGHTLINE_WONDER_MAX_USD_DAY", "25")))
    except ValueError:
        return 25.0


def charge(usd: float) -> None:
    """Add a call's cost to today's total."""
    global _day, _spent
    with _lock:
        if _day != _today():
            _day, _spent = _today(), 0.0
        _spent += max(0.0, float(usd))


def spent() -> float:
    with _lock:
        return _spent if _day == _today() else 0.0


@contextmanager
def held(estimate: float):
    """Count `estimate` against today's limit while paid work runs (its calls are charged as they land), so work
    started at the same moment cannot all pass `refused` on a nearly spent day."""
    global _held
    with _lock:
        _held += max(0.0, estimate)
    try:
        yield
    finally:
        with _lock:
            _held = max(0.0, _held - max(0.0, estimate))


def refused(estimate: float = 0.0, exempt: bool = False) -> str | None:
    """Why paid work may not start now (today's limit reached, counting what running work may still cost), or None.
    `exempt`: the owner's own work."""
    cap = limit()
    if exempt or cap <= 0:
        return None
    with _lock:
        pending = _held
    if spent() + pending + estimate > cap:
        return (f"Today's budget for Muse Wonder (${cap:.0f}) is used up; it resets at midnight UTC. "
                "Muse Spark's own proposals still work.")
    return None


def reset() -> None:
    """Start the count again (tests)."""
    global _day, _spent, _held
    with _lock:
        _day, _spent, _held = "", 0.0, 0.0
