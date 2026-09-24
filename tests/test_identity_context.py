import pytest

from workday_mcp.auth.identity_context import (
    NoIdentityError,
    RequestIdentity,
    get_current_identity,
    reset_current_identity,
    set_current_identity,
)


def test_get_current_identity_raises_when_unset():
    with pytest.raises(NoIdentityError):
        get_current_identity()


def test_set_and_get_current_identity_roundtrip():
    identity = RequestIdentity(upn="alice@example.com", display_name="Alice", object_id="obj-1")
    token = set_current_identity(identity)
    try:
        assert get_current_identity() == identity
    finally:
        reset_current_identity(token)

    with pytest.raises(NoIdentityError):
        get_current_identity()
