import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from workday_mcp.auth.jwt_validator import EntraTokenValidator, TokenValidationError


class FakeSigningKey:
    def __init__(self, key):
        self.key = key


class FakeJWKSClient:
    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return FakeSigningKey(self._public_key)


@pytest.fixture
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def make_token(private_key, tenant_id, audience, overrides=None):
    now = int(time.time())
    claims = {
        "aud": audience,
        "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        "iat": now,
        "exp": now + 3600,
        "sub": "user-123",
        "preferred_username": "alice@example.com",
    }
    if overrides:
        claims.update(overrides)
    return pyjwt.encode(claims, private_key, algorithm="RS256")


def test_validate_accepts_well_formed_token(rsa_keypair):
    private_key, public_key = rsa_keypair
    tenant_id = "tenant-abc"
    audience = "api://workday-mcp"
    token = make_token(private_key, tenant_id, audience)

    validator = EntraTokenValidator(tenant_id, audience, jwks_client=FakeJWKSClient(public_key))
    result = validator.validate(token)

    assert result.claims["preferred_username"] == "alice@example.com"


def test_validate_rejects_wrong_audience(rsa_keypair):
    private_key, public_key = rsa_keypair
    tenant_id = "tenant-abc"
    token = make_token(private_key, tenant_id, "api://someone-else")

    validator = EntraTokenValidator(tenant_id, "api://workday-mcp", jwks_client=FakeJWKSClient(public_key))
    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_validate_rejects_expired_token(rsa_keypair):
    private_key, public_key = rsa_keypair
    tenant_id = "tenant-abc"
    audience = "api://workday-mcp"
    now = int(time.time())
    token = make_token(private_key, tenant_id, audience, overrides={"exp": now - 10, "iat": now - 3600})

    validator = EntraTokenValidator(tenant_id, audience, jwks_client=FakeJWKSClient(public_key))
    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_validate_rejects_missing_token():
    validator = EntraTokenValidator("tenant-abc", "api://workday-mcp", jwks_client=FakeJWKSClient(None))
    with pytest.raises(TokenValidationError):
        validator.validate("")
