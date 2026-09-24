from __future__ import annotations

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient


class TokenValidationError(Exception):
    pass


@dataclass(frozen=True)
class ValidatedToken:
    raw: str
    claims: dict


class EntraTokenValidator:
    def __init__(self, tenant_id: str, audience: str, jwks_client: PyJWKClient | None = None):
        self.tenant_id = tenant_id
        self.audience = audience
        self.issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        jwks_uri = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        self._jwks_client = jwks_client or PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)

    def validate(self, token: str) -> ValidatedToken:
        if not token:
            raise TokenValidationError("missing bearer token")
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenValidationError(str(exc)) from exc
        return ValidatedToken(raw=token, claims=claims)
