"""Spend limits for a public deployment. Every "Propose fixes" is a paid Muse Spark call on our key.

Off unless configured, so local runs and tests are unaffected:

    SIGHTLINE_PROPOSE_PER_HOUR   proposals per visitor per rolling hour (0 = no limit)
    SIGHTLINE_PROPOSE_PER_DAY    proposals for everyone per rolling day (0 = no limit)
    SIGHTLINE_TRUST_FORWARDED    1 behind a proxy that sets X-Forwarded-For (Modal does)

State is in memory, which is only correct with a single server process; the Modal app pins one container
for the same reason (scenes are in memory too).
"""
from __future__ import annotations

import os
import time
from collections import deque

HOUR = 3600
DAY = 24 * HOUR


class ProposeLimit:
    def __init__(self, per_client_hour: int = 0, per_day: int = 0, clock=time.monotonic):
        self.per_client_hour = per_client_hour
        self.per_day = per_day
        self.clock = clock
        self._clients: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()

    @classmethod
    def from_env(cls) -> "ProposeLimit":
        return cls(int(os.environ.get("SIGHTLINE_PROPOSE_PER_HOUR", "0")),
                   int(os.environ.get("SIGHTLINE_PROPOSE_PER_DAY", "0")))

    @staticmethod
    def _trim(q: deque[float], since: float) -> deque[float]:
        while q and q[0] <= since:
            q.popleft()
        return q

    def take(self, client: str) -> str | None:
        """Count one proposal for `client`, or return why it is refused (nothing is counted then)."""
        now = self.clock()
        mine = self._trim(self._clients.setdefault(client, deque()), now - HOUR)
        everyone = self._trim(self._all, now - DAY)
        if self.per_day and len(everyone) >= self.per_day:
            return "The demo has used today's proposals. Try again tomorrow, or run Sightline locally with your own key."
        if self.per_client_hour and len(mine) >= self.per_client_hour:
            return f"You've used {self.per_client_hour} proposals this hour. Try again later, or use Check this move."
        mine.append(now)
        everyone.append(now)
        return None


def client_id(headers, peer: str | None) -> str:
    if os.environ.get("SIGHTLINE_TRUST_FORWARDED") == "1":
        forwarded = headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer or "unknown"
