"""Who is asking: one identity per request, for caps, a triage run's starter and an agent link's creator.

Today a visitor is an address (`limits.client_id`: the socket's peer, or behind trusted proxies the entry the outermost
one wrote). With accounts (docs/accounts.md) a signed-in person will be their user id, wherever they connect from. The
middleware in app.py (`_OwnerContext`) sets the identity for every HTTP request and WebSocket; `who` reads it.

The identity is a context variable, so it reaches what a request starts with `owner.spawn` and `owner.submit` (a
stream's worker, a pool of model calls), as the owner's settings do.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass

from starlette.datastructures import Headers

from .limits import client_id


@dataclass(frozen=True)
class Identity:
    address: str               # limits.client_id: the peer, or what the outermost trusted proxy appended
    user_id: str | None = None  # the signed-in person (docs/accounts.md); None until accounts exist

    @property
    def key(self) -> str:
        """What caps and runs are counted under: `u:<user id>` for a signed-in person, else the address."""
        return f"u:{self.user_id}" if self.user_id else self.address


_current: contextvars.ContextVar[Identity | None] = contextvars.ContextVar("identity", default=None)


def _peer(client) -> str | None:
    """The peer's host from a connection's `client` (an Address) or an ASGI scope's (a pair), else None."""
    if not client:
        return None
    return client.host if hasattr(client, "host") else client[0]


def of_scope(scope) -> Identity:
    """The identity of an ASGI connection (HTTP or WebSocket), from its headers and peer."""
    return Identity(client_id(Headers(scope=scope), _peer(scope.get("client"))))


def of(conn) -> Identity:
    """The identity of a request or socket (starlette's HTTPConnection), exactly as `limits.client_id` reads it."""
    return Identity(client_id(conn.headers, _peer(conn.client)))


def enter(identity: Identity | None) -> contextvars.Token:
    return _current.set(identity)


def leave(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> Identity | None:
    """This request's identity, or None outside one (a test calling a function directly, the stdio MCP server)."""
    return _current.get()


def who(conn=None) -> str | None:
    """Who is asking, as caps and runs count them: this request's identity (`Identity.key`), else one read from `conn`
    as `limits.client_id` does, else None (no request at all)."""
    mine = current()
    if mine is not None:
        return mine.key
    return of(conn).key if conn is not None else None
