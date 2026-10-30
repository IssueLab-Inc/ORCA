"""Spend limits for a public deployment. Every "Propose fixes" is a paid Muse Spark call on our key.

Off unless configured, so local runs and tests are unaffected:

    SIGHTLINE_PROPOSE_PER_HOUR   proposals per visitor per rolling hour (0 = no limit)
    SIGHTLINE_PROPOSE_PER_DAY    proposals for everyone per rolling day (0 = no limit)
    SIGHTLINE_TRUST_FORWARDED    N proxies in front that each append to X-Forwarded-For (0 = none; Modal needs none)

State is in memory, which is only correct with a single server process; the Modal app pins one container
for the same reason (scenes are in memory too).

Every number setting is read with `env_int` / `env_float`: unset or empty (`SIGHTLINE_PROPOSE_PER_HOUR=` in .env)
is its default, so a blanked cap is off (or its own default), never a server that stops at import.
"""
from __future__ import annotations

import os
import time
from collections import deque

HOUR = 3600
DAY = 24 * HOUR


def env_int(name: str, default: int) -> int:
    """A whole number from the environment; unset or empty is `default`. Anything else not a number raises."""
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def env_float(name: str, default: float) -> float:
    """A number from the environment; unset or empty is `default`. Anything else not a number raises."""
    value = os.environ.get(name, "").strip()
    return float(value) if value else default


class ProposeLimit:
    def __init__(self, per_client_hour: int = 0, per_day: int = 0, clock=time.monotonic, noun: str = "proposals"):
        self.per_client_hour = per_client_hour
        self.per_day = per_day
        self.noun = noun
        self.clock = clock
        self._clients: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()

    @classmethod
    def from_env(cls) -> "ProposeLimit":
        return cls(env_int("SIGHTLINE_PROPOSE_PER_HOUR", 0),
                   env_int("SIGHTLINE_PROPOSE_PER_DAY", 0))

    @classmethod
    def escalate_from_env(cls) -> "ProposeLimit":
        """Second tries on Muse Wonder (docs/escalation.md): SIGHTLINE_ESCALATE_PER_HOUR per visitor,
        SIGHTLINE_ESCALATE_PER_DAY for everyone. Each also takes one proposal."""
        return cls(env_int("SIGHTLINE_ESCALATE_PER_HOUR", 0),
                   env_int("SIGHTLINE_ESCALATE_PER_DAY", 0), noun="second tries with Muse Wonder")

    @classmethod
    def chat_from_env(cls) -> "ProposeLimit":
        """Chat messages: SIGHTLINE_CHAT_PER_HOUR per visitor, SIGHTLINE_CHAT_PER_DAY for everyone."""
        return cls(env_int("SIGHTLINE_CHAT_PER_HOUR", 0),
                   env_int("SIGHTLINE_CHAT_PER_DAY", 0), noun="chat messages")

    @staticmethod
    def _trim(q: deque[float], since: float) -> deque[float]:
        while q and q[0] <= since:
            q.popleft()
        return q

    def take_many(self, client: str, n: int) -> str | None:
        """Count `n` at once, or none of them: a plan of several fixes is refused whole, not half-run."""
        now = self.clock()
        mine = self._trim(self._clients.setdefault(client, deque()), now - HOUR)
        everyone = self._trim(self._all, now - DAY)
        if self.per_day and len(everyone) + n > self.per_day:
            return f"The demo has too few {self.noun} left today for {n} more. Try fewer, or run ORCA locally."
        if self.per_client_hour and len(mine) + n > self.per_client_hour:
            left = max(self.per_client_hour - len(mine), 0)
            return f"That needs {n} {self.noun}; you have {left} left this hour. Pick fewer clashes or try later."
        mine.extend([now] * n)
        everyone.extend([now] * n)
        return None

    def refusal(self, client: str) -> str | None:
        """Why one more for `client` would be refused now, or None; nothing is counted."""
        now = self.clock()
        mine = self._trim(self._clients.setdefault(client, deque()), now - HOUR)
        everyone = self._trim(self._all, now - DAY)
        if self.per_day and len(everyone) >= self.per_day:
            return f"The demo has used today's {self.noun}. Try again tomorrow, or run ORCA locally with your own key."
        if self.per_client_hour and len(mine) >= self.per_client_hour:
            return f"You've used {self.per_client_hour} {self.noun} this hour. Try again later."
        return None

    def take(self, client: str) -> str | None:
        """Count one proposal for `client`, or return why it is refused (nothing is counted then)."""
        why = self.refusal(client)
        if why:
            return why
        now = self.clock()
        self._clients[client].append(now)
        self._all.append(now)
        return None

    @staticmethod
    def take_all(client: str, *limits: "ProposeLimit") -> str | None:
        """One of each, or none: the first refusal, with nothing counted on any of them."""
        for limit in limits:
            why = limit.refusal(client)
            if why:
                return why
        for limit in limits:
            limit.take(client)
        return None


def trusted_hops() -> int:
    try:
        return max(int(os.environ.get("SIGHTLINE_TRUST_FORWARDED") or 0), 0)
    except ValueError:
        return 0


def client_id(headers, peer: str | None) -> str:
    """Who a visitor is, for their caps: the socket's peer address, or behind `trusted_hops()` proxies that each append
    the address they saw to X-Forwarded-For, the entry the outermost of them wrote (that many from the right). Never
    the left end: a client writes what it likes there, and a proxy that appends keeps it. A header with fewer entries
    than trusted proxies was not written by them, so it is ignored.

    Modal's edge strips any X-Forwarded-For a client sends, adds none, and hands the app the visitor's own address as
    the peer, HTTP and WebSocket alike (measured Oct 30 from outside and from inside Modal), so the deploy trusts none."""
    hops = trusted_hops()
    if hops:
        lines = headers.getlist("x-forwarded-for") if hasattr(headers, "getlist") else [headers.get("x-forwarded-for", "")]
        entries = [a.strip() for line in lines for a in (line or "").split(",") if a.strip()]
        if len(entries) >= hops:
            return entries[-hops]
    return peer or "unknown"
