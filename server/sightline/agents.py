"""Agents connected over MCP: pairing links, the channel to the browser, and long jobs.

A visitor who clicks "Connect an agent" gets a link: a secret token tied to what they have open (scene, report,
selected clash, fixed clashes). An agent that presents the token (MCP over HTTP, `mcp_server.py`) works on that
session, and the browser follows along:
- the page keeps the link's context current (`Link.context`), so the agent sees what the person sees;
- the page listens on the link's event stream and carries out what the agent asks of the viewer (show a clash, change
  the view, open models, reload an applied fix), as it does for the chat's "ui" events;
- the agent can ask the page for a picture (`Link.capture`): the current view, or a clash's A/B/C views.

Tokens are capabilities: whoever holds one can act on that session until it expires or is revoked. Only a hash is
kept. Links live in memory, like the scenes they point at: a restart ends them.
"""
from __future__ import annotations

import hashlib
import queue
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .chat import Context

TTL = 12 * 3600          # a link lives this long after its last use...
MAX_AGE = 24 * 3600      # ...but never longer than this
MAX_LINKS = 200
EVENTS_PER_SUBSCRIBER = 200
JOBS_PER_LINK = 16


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Job:
    """Work an agent started that may outlast one tool call (a proposal, a plan, a report)."""
    id: str
    kind: str
    started: float = field(default_factory=time.time)
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: str | None = None

    def state(self) -> dict:
        if not self.done.is_set():
            return {"job_id": self.id, "kind": self.kind, "status": "running",
                    "seconds": round(time.time() - self.started, 1),
                    "note": "Still working. Call get_job with this job_id to wait for the result."}
        if self.error:
            return {"job_id": self.id, "kind": self.kind, "status": "failed", "error": self.error}
        return {"job_id": self.id, "kind": self.kind, "status": "done", "result": self.result}


@dataclass
class Link:
    id: str                       # public, for logs and the page; never the secret
    key: str                      # sha256 of the token
    visitor: str                  # who created it: MCP calls are charged to them
    owner: bool                   # created by the site's owner: no demo caps
    created: float
    expires: float
    ctx: Context = field(default_factory=Context)
    last_call: dict | None = None
    calls: int = 0
    proposals: dict[str, dict] = field(default_factory=dict)   # clash id -> the last proposal's result
    applied: dict[str, str] = field(default_factory=dict)      # clash id -> the fix the agent applied (its title)
    plans: dict[str, Any] = field(default_factory=dict)        # plan id -> plans.Plan
    jobs: dict[str, Job] = field(default_factory=dict)
    _subscribers: list[queue.Queue] = field(default_factory=list, repr=False)
    _captures: dict[str, tuple[threading.Event, list]] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------------ the browser

    @property
    def browser(self) -> bool:
        """A page is listening (the person has ORCA open with this link)."""
        return bool(self._subscribers)

    def publish(self, event: dict) -> None:
        """Send an event to every page following this link. A page that stops reading loses old events, never the
        agent's time."""
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=EVENTS_PER_SUBSCRIBER)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def capture(self, what: str, wait_s: float = 15.0, **details) -> list | None:
        """Ask the page for pictures ("view": what the viewer shows now; "clash": a clash's A/B/C views, which the
        page saves on the report). Returns what the page sent (PNG bytes for a view, [] for a clash), or None when no
        page answered in time."""
        if not self.browser:
            return None
        rid = uuid.uuid4().hex[:12]
        got: list = []
        ready = threading.Event()
        with self._lock:
            self._captures[rid] = (ready, got)
        try:
            self.publish({"type": "capture_request", "id": rid, "what": what, **details})
            return got if ready.wait(wait_s) else None
        finally:
            with self._lock:
                self._captures.pop(rid, None)

    def deliver(self, rid: str, data: bytes | None) -> bool:
        with self._lock:
            pending = self._captures.get(rid)
        if pending is None:
            return False
        ready, got = pending
        if data:
            got.append(data)
        ready.set()
        return True

    # ------------------------------------------------------------------ jobs

    def start(self, kind: str, work: Callable[[], Any], spawn: Callable[[Callable[[], None]], Any] | None = None) -> Job:
        job = Job(uuid.uuid4().hex[:10], kind)

        def run():
            try:
                job.result = work()
            except Exception as e:  # tell the agent rather than lose the job
                job.error = f"{type(e).__name__}: {e}"
            finally:
                job.done.set()

        with self._lock:
            self.jobs[job.id] = job
            while len(self.jobs) > JOBS_PER_LINK:
                oldest = next(iter(self.jobs))
                if not self.jobs[oldest].done.is_set():
                    break
                self.jobs.pop(oldest)
        (spawn or (lambda f: threading.Thread(target=f, daemon=True).start()))(run)
        return job

    def wait(self, job: Job, wait_s: float) -> dict:
        job.done.wait(max(0.0, min(wait_s, 55.0)))
        return job.state()

    def public(self) -> dict:
        return {"id": self.id, "expires_at": self.expires, "max_expires_at": self.created + MAX_AGE,
                "server_time": time.time(), "calls": self.calls, "last_call": self.last_call,
                "browser": self.browser, "context": {"scene_id": self.ctx.scene_id, "report_id": self.ctx.report_id,
                                                     "clash_id": self.ctx.clash_id, "fixed": len(self.ctx.fixed)},
                "applied": self.applied}


class Links:
    """Every live link, by the hash of its token."""

    def __init__(self):
        self._links: dict[str, Link] = {}
        self._lock = threading.Lock()

    def create(self, visitor: str, owner: bool, ctx: Context | None = None) -> tuple[str, Link]:
        token = "orca_" + secrets.token_urlsafe(32)
        now = time.time()
        link = Link(uuid.uuid4().hex[:8], _hash(token), visitor, owner, now, now + TTL, ctx or Context())
        with self._lock:
            self._sweep(now)
            self._links[link.key] = link
            while len(self._links) > MAX_LINKS:
                self._links.pop(next(iter(self._links)))
        return token, link

    def get(self, token: str | None, touch: bool = True) -> Link | None:
        if not token:
            return None
        now = time.time()
        with self._lock:
            link = self._links.get(_hash(token))
            if link is None:
                return None
            if now > link.expires:
                self._links.pop(link.key, None)
                return None
            if touch:
                link.expires = min(link.created + MAX_AGE, max(link.expires, now + TTL))
        return link

    def revoke(self, token: str) -> bool:
        with self._lock:
            link = self._links.pop(_hash(token), None)
        if link is not None:
            link.publish({"type": "revoked"})
        return link is not None

    def kept(self) -> set[str]:
        """The scenes and reports live links point at: the server evicts them last."""
        now = time.time()
        with self._lock:
            live = [l for l in self._links.values() if now <= l.expires]
        return {x for l in live for x in (l.ctx.scene_id, l.ctx.report_id) if x}

    def _sweep(self, now: float) -> None:
        for key in [k for k, l in self._links.items() if now > l.expires]:
            self._links.pop(key, None)

    def __len__(self) -> int:
        return len(self._links)


def token_from(headers, query: str = "") -> str | None:
    """The link token an agent presents: `Authorization: Bearer <token>`, or `?key=<token>` for clients that cannot
    set headers."""
    auth = (headers.get("authorization") or "") if headers is not None else ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    for part in query.split("&"):
        if part.startswith("key="):
            return part[4:] or None
    return None
