from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestIdentity:
    upn: str
    display_name: str
    object_id: str


_current_identity: "contextvars.ContextVar[RequestIdentity | None]" = contextvars.ContextVar(
    "workday_mcp_current_identity", default=None
)


class NoIdentityError(Exception):
    pass


def set_current_identity(identity: RequestIdentity) -> contextvars.Token:
    return _current_identity.set(identity)


def reset_current_identity(token: contextvars.Token) -> None:
    _current_identity.reset(token)


def get_current_identity() -> RequestIdentity:
    identity = _current_identity.get()
    if identity is None:
        raise NoIdentityError("no resolved identity in request context")
    return identity
