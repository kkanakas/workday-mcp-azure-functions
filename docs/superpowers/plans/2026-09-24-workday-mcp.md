# workday-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python MCP server on Azure Functions that authenticates via OAuth 2.0/Entra ID, performs an OBO exchange against Microsoft Graph to resolve caller identity, calls Workday's REST API via a client-credentials (ISU) grant, and is fronted by Azure API Management — with Bicep infra and an Entra ID app-registration script.

**Architecture:** A `workday_mcp` Python package (auth, workday client, MCP tools, server assembly) wraps the official `mcp` SDK's `FastMCP` streamable-HTTP ASGI app with a Starlette auth middleware, mounted into Azure Functions' Python v2 model via `func.AsgiFunctionApp`. Bicep provisions Storage, Key Vault, the Function App, and APIM with a `validate-jwt` policy.

**Tech Stack:** Python 3.11, `azure-functions`, `mcp` (FastMCP), `starlette`, `httpx`, `PyJWT`, `msal`, Bicep, Azure CLI, pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-workday-mcp-design.md`

## Global Constraints

- Python 3.11 target runtime (Azure Functions Python worker).
- No plaintext secrets in app settings — Entra client secret and Workday client ID/secret are Key Vault references (`@Microsoft.KeyVault(...)`) only.
- Tools resolve the caller's identity only from the OBO-resolved token (`get_current_identity()`), never from a caller-supplied "act as" parameter (spec §6).
- No live network calls in automated tests — mock `httpx`, `msal`, and JWKS lookups.
- `DEV_SKIP_AUTH` bypasses auth for local dev only; it must default to `false` and never be set `true` in deployed app settings.
- MCP transport is the `mcp` SDK's `FastMCP` streamable-HTTP ASGI app, embedded in Azure Functions' Python v2 model via `func.AsgiFunctionApp` (spec §9).
- **Layout refinement from the spec:** the spec's illustrative tree nests the package under `src/workday_mcp/`. This plan places the `workday_mcp` package and `function_app.py` at the **repository root** instead (no `src/` indirection), because Azure Functions' Python v2 model and Oryx build expect `function_app.py` at the app root with no extra `PYTHONPATH`/entry-point configuration. Internal package structure (`auth/`, `workday/`, `tools/`) is unchanged from the spec.

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Create: `conftest.py`
- Create: `host.json`
- Create: `local.settings.json.example`
- Create: `.funcignore`
- Create: `workday_mcp/__init__.py`
- Create: `workday_mcp/auth/__init__.py`
- Create: `workday_mcp/workday/__init__.py`
- Create: `workday_mcp/tools/__init__.py`

**Interfaces:**
- Produces: an importable `workday_mcp` package (empty modules) and a working `pytest`/`pip install` environment that all later tasks build on.

- [ ] **Step 1: Create package directories and empty `__init__.py` files**

```bash
mkdir -p workday_mcp/auth workday_mcp/workday workday_mcp/tools tests
touch workday_mcp/__init__.py workday_mcp/auth/__init__.py workday_mcp/workday/__init__.py workday_mcp/tools/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
azure-functions>=1.21.0
mcp>=1.2.0
starlette>=0.38.0
httpx>=0.27.0
PyJWT[crypto]>=2.9.0
msal>=1.31.0
```

- [ ] **Step 3: Write `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.3.0
cryptography>=43.0.0
```

- [ ] **Step 4: Write `pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 5: Write `conftest.py`** (anchors pytest's rootdir so `workday_mcp` is importable from `tests/`)

```python
# Intentionally empty: presence of this file anchors pytest's rootdir
# insertion so the top-level `workday_mcp` package is importable from tests/.
```

- [ ] **Step 6: Write `host.json`**

```json
{
  "version": "2.0",
  "logging": {
    "applicationInsights": {
      "samplingSettings": {
        "isEnabled": true,
        "excludedTypes": "Request"
      }
    }
  },
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
```

- [ ] **Step 7: Write `local.settings.json.example`**

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "ENTRA_TENANT_ID": "<entra-tenant-id>",
    "ENTRA_API_AUDIENCE": "api://workday-mcp",
    "ENTRA_API_SCOPE": "api://workday-mcp/access_as_user",
    "ENTRA_CLIENT_ID": "<workday-mcp-api-app-client-id>",
    "ENTRA_CLIENT_SECRET": "<workday-mcp-api-app-client-secret>",
    "MCP_RESOURCE_URL": "http://localhost:7071/mcp",
    "WORKDAY_TENANT_BASE_URL": "https://<workday-host>/ccx/api/v1/<workday-tenant>",
    "WORKDAY_TOKEN_URL": "https://<workday-host>/ccx/oauth2/<workday-tenant>/token",
    "WORKDAY_CLIENT_ID": "<workday-isu-client-id>",
    "WORKDAY_CLIENT_SECRET": "<workday-isu-client-secret>",
    "DEV_SKIP_AUTH": "true"
  }
}
```

- [ ] **Step 8: Write `.funcignore`**

```
.venv/
venv/
.git/
.github/
tests/
docs/
infra/
scripts/
*.md
.pytest_cache/
__pycache__/
requirements-dev.txt
local.settings.json
```

- [ ] **Step 9: Create venv and install dependencies**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

- [ ] **Step 10: Verify the package imports and pytest collects cleanly**

Run: `python -c "import workday_mcp" && pytest --collect-only`
Expected: no errors, `0 tests collected` is fine at this point.

- [ ] **Step 11: Commit**

```bash
git add requirements.txt requirements-dev.txt pyproject.toml conftest.py host.json local.settings.json.example .funcignore workday_mcp/
git commit -m "Scaffold Python project and Azure Functions config"
```

---

### Task 2: Request-scoped identity context

**Files:**
- Create: `workday_mcp/auth/identity_context.py`
- Test: `tests/test_identity_context.py`

**Interfaces:**
- Produces: `RequestIdentity(upn: str, display_name: str, object_id: str)`, `set_current_identity(identity) -> contextvars.Token`, `reset_current_identity(token) -> None`, `get_current_identity() -> RequestIdentity`, `NoIdentityError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_identity_context.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_identity_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'workday_mcp.auth.identity_context'`

- [ ] **Step 3: Write the implementation**

```python
# workday_mcp/auth/identity_context.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_identity_context.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add workday_mcp/auth/identity_context.py tests/test_identity_context.py
git commit -m "Add request-scoped identity context"
```

---

### Task 3: Entra ID bearer token validator

**Files:**
- Create: `workday_mcp/auth/jwt_validator.py`
- Test: `tests/test_jwt_validator.py`

**Interfaces:**
- Produces: `EntraTokenValidator(tenant_id: str, audience: str, jwks_client=None)` with `.validate(token: str) -> ValidatedToken` (`ValidatedToken(raw: str, claims: dict)`), `TokenValidationError`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_jwt_validator.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_jwt_validator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'workday_mcp.auth.jwt_validator'`

- [ ] **Step 3: Write the implementation**

```python
# workday_mcp/auth/jwt_validator.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_jwt_validator.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add workday_mcp/auth/jwt_validator.py tests/test_jwt_validator.py
git commit -m "Add Entra ID bearer token validator"
```

---

### Task 4: OBO identity resolution via Microsoft Graph

**Files:**
- Create: `workday_mcp/auth/obo.py`
- Test: `tests/test_obo.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `build_msal_confidential_app(tenant_id, client_id, client_secret) -> msal.ConfidentialClientApplication`, `GraphOboResolver(msal_app, http_client=None)` with `.resolve(user_access_token: str) -> ResolvedIdentity` (`ResolvedIdentity(upn, display_name, object_id)`), `OboExchangeError`. `ResolvedIdentity`'s fields are consumed by Task 8 to build a `RequestIdentity` (Task 2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_obo.py
import httpx
import pytest

from workday_mcp.auth.obo import GraphOboResolver, OboExchangeError, ResolvedIdentity


class FakeMsalApp:
    def __init__(self, result):
        self._result = result
        self.last_call = None

    def acquire_token_on_behalf_of(self, user_assertion, scopes):
        self.last_call = (user_assertion, scopes)
        return self._result


def make_http_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_resolve_returns_identity_on_success():
    msal_app = FakeMsalApp({"access_token": "graph-token-123"})

    def handler(request):
        assert request.headers["Authorization"] == "Bearer graph-token-123"
        return httpx.Response(200, json={
            "userPrincipalName": "alice@example.com",
            "displayName": "Alice Smith",
            "id": "obj-1",
        })

    resolver = GraphOboResolver(msal_app, http_client=make_http_client(handler))
    identity = resolver.resolve("user-assertion-token")

    assert identity == ResolvedIdentity(upn="alice@example.com", display_name="Alice Smith", object_id="obj-1")
    assert msal_app.last_call == ("user-assertion-token", ["https://graph.microsoft.com/User.Read"])


def test_resolve_raises_when_msal_fails():
    msal_app = FakeMsalApp({"error": "invalid_grant", "error_description": "bad assertion"})
    resolver = GraphOboResolver(msal_app, http_client=make_http_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(OboExchangeError, match="bad assertion"):
        resolver.resolve("bad-token")


def test_resolve_raises_when_graph_call_fails():
    msal_app = FakeMsalApp({"access_token": "graph-token-123"})
    resolver = GraphOboResolver(msal_app, http_client=make_http_client(lambda r: httpx.Response(403, text="Forbidden")))

    with pytest.raises(OboExchangeError, match="403"):
        resolver.resolve("user-assertion-token")


def test_resolve_raises_when_upn_missing():
    msal_app = FakeMsalApp({"access_token": "graph-token-123"})
    resolver = GraphOboResolver(
        msal_app,
        http_client=make_http_client(lambda r: httpx.Response(200, json={"displayName": "No UPN"})),
    )

    with pytest.raises(OboExchangeError, match="userPrincipalName"):
        resolver.resolve("user-assertion-token")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_obo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'workday_mcp.auth.obo'`

- [ ] **Step 3: Write the implementation**

```python
# workday_mcp/auth/obo.py
from __future__ import annotations

from dataclasses import dataclass

import httpx
import msal


class OboExchangeError(Exception):
    pass


@dataclass(frozen=True)
class ResolvedIdentity:
    upn: str
    display_name: str
    object_id: str


class GraphOboResolver:
    GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"
    GRAPH_SCOPE = ["https://graph.microsoft.com/User.Read"]

    def __init__(self, msal_app, http_client: httpx.Client | None = None):
        self._msal_app = msal_app
        self._http_client = http_client or httpx.Client(timeout=10.0)

    def resolve(self, user_access_token: str) -> ResolvedIdentity:
        result = self._msal_app.acquire_token_on_behalf_of(
            user_assertion=user_access_token,
            scopes=self.GRAPH_SCOPE,
        )
        if "access_token" not in result:
            raise OboExchangeError(result.get("error_description", "OBO token exchange failed"))

        graph_token = result["access_token"]
        response = self._http_client.get(
            self.GRAPH_ME_URL,
            headers={"Authorization": f"Bearer {graph_token}"},
        )
        if response.status_code != 200:
            raise OboExchangeError(f"Graph /me call failed: {response.status_code} {response.text}")

        data = response.json()
        upn = data.get("userPrincipalName") or data.get("mail")
        if not upn:
            raise OboExchangeError("Graph /me response missing userPrincipalName/mail")

        return ResolvedIdentity(
            upn=upn,
            display_name=data.get("displayName", ""),
            object_id=data.get("id", ""),
        )


def build_msal_confidential_app(tenant_id: str, client_id: str, client_secret: str) -> msal.ConfidentialClientApplication:
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_obo.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add workday_mcp/auth/obo.py tests/test_obo.py
git commit -m "Add OBO identity resolution via Microsoft Graph"
```

---

### Task 5: OAuth protected-resource metadata

**Files:**
- Create: `workday_mcp/auth/protected_resource_metadata.py`
- Test: `tests/test_protected_resource_metadata.py`

**Interfaces:**
- Produces: `build_protected_resource_metadata(resource_url: str, tenant_id: str, scope: str) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_protected_resource_metadata.py
from workday_mcp.auth.protected_resource_metadata import build_protected_resource_metadata


def test_build_protected_resource_metadata():
    metadata = build_protected_resource_metadata(
        resource_url="https://workday-mcp.example.com/mcp",
        tenant_id="tenant-abc",
        scope="api://workday-mcp/access_as_user",
    )

    assert metadata["resource"] == "https://workday-mcp.example.com/mcp"
    assert metadata["authorization_servers"] == ["https://login.microsoftonline.com/tenant-abc/v2.0"]
    assert metadata["scopes_supported"] == ["api://workday-mcp/access_as_user"]
    assert metadata["bearer_methods_supported"] == ["header"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_protected_resource_metadata.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# workday_mcp/auth/protected_resource_metadata.py
from __future__ import annotations


def build_protected_resource_metadata(resource_url: str, tenant_id: str, scope: str) -> dict:
    return {
        "resource": resource_url,
        "authorization_servers": [f"https://login.microsoftonline.com/{tenant_id}/v2.0"],
        "scopes_supported": [scope],
        "bearer_methods_supported": ["header"],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_protected_resource_metadata.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add workday_mcp/auth/protected_resource_metadata.py tests/test_protected_resource_metadata.py
git commit -m "Add OAuth protected-resource metadata endpoint payload"
```

---

### Task 6: Workday REST client

**Files:**
- Create: `workday_mcp/workday/models.py`
- Create: `workday_mcp/workday/client.py`
- Test: `tests/test_workday_client.py`

**Interfaces:**
- Produces: `Worker(worker_id, display_name, email, job_title="", organization="")`, `TimeOffEntry(date, hours, type)`, `OrganizationInfo(organization_id, name, manager_worker_id="", member_worker_ids=[])`; `WorkdayClient(tenant_base_url, token_url, client_id, client_secret, http_client=None, clock=time.time)` with `.get_worker(upn) -> Worker`, `.search_workers(query, limit=20) -> list[Worker]`, `.get_worker_time_off(worker_id) -> list[TimeOffEntry]`, `.get_organization(worker_id) -> OrganizationInfo`; `WorkdayApiError`. Consumed by Task 7 (tools).

- [ ] **Step 1: Write `workday_mcp/workday/models.py`**

```python
# workday_mcp/workday/models.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Worker:
    worker_id: str
    display_name: str
    email: str
    job_title: str = ""
    organization: str = ""


@dataclass(frozen=True)
class TimeOffEntry:
    date: str
    hours: float
    type: str


@dataclass(frozen=True)
class OrganizationInfo:
    organization_id: str
    name: str
    manager_worker_id: str = ""
    member_worker_ids: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_workday_client.py
import httpx
import pytest

from workday_mcp.workday.client import WorkdayApiError, WorkdayClient


def make_client(handler, clock=lambda: 1_000_000.0):
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return WorkdayClient(
        tenant_base_url="https://wd.example.com/api/v1/acme",
        token_url="https://wd.example.com/oauth2/token",
        client_id="isu-client",
        client_secret="isu-secret",
        http_client=http_client,
        clock=clock,
    )


def test_get_worker_returns_worker_and_caches_token():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer tok-1"
        return httpx.Response(200, json={"data": [{"id": "w-1", "descriptor": "Alice Smith", "jobTitle": "Engineer"}]})

    client = make_client(handler)
    worker = client.get_worker("alice@example.com")
    worker2 = client.get_worker("alice@example.com")

    assert worker.worker_id == "w-1"
    assert worker.display_name == "Alice Smith"
    assert worker.email == "alice@example.com"
    assert worker2.worker_id == "w-1"
    assert calls.count("/oauth2/token") == 1


def test_token_refreshed_after_expiry():
    time_box = {"now": 1_000_000.0}
    token_calls = {"count": 0}

    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            token_calls["count"] += 1
            return httpx.Response(200, json={"access_token": f"tok-{token_calls['count']}", "expires_in": 60})
        return httpx.Response(200, json={"data": [{"id": "w-1", "descriptor": "Alice"}]})

    client = make_client(handler, clock=lambda: time_box["now"])
    client.get_worker("alice@example.com")
    time_box["now"] += 120
    client.get_worker("alice@example.com")

    assert token_calls["count"] == 2


def test_get_worker_raises_when_not_found():
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(200, json={"data": []})

    client = make_client(handler)
    with pytest.raises(WorkdayApiError, match="No worker found"):
        client.get_worker("nobody@example.com")


def test_search_workers_returns_list():
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(200, json={"data": [
            {"id": "w-1", "descriptor": "Alice", "email": "alice@example.com"},
            {"id": "w-2", "descriptor": "Bob", "email": "bob@example.com"},
        ]})

    client = make_client(handler)
    workers = client.search_workers("a")

    assert [w.worker_id for w in workers] == ["w-1", "w-2"]


def test_get_worker_time_off_returns_entries():
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(200, json={"data": [{"date": "2026-01-05", "hours": 8, "type": "Vacation"}]})

    client = make_client(handler)
    entries = client.get_worker_time_off("w-1")

    assert entries[0].type == "Vacation"
    assert entries[0].hours == 8


def test_get_organization_returns_info():
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(200, json={"id": "org-1", "name": "Engineering", "managerId": "w-9", "memberIds": ["w-1", "w-2"]})

    client = make_client(handler)
    org = client.get_organization("w-1")

    assert org.name == "Engineering"
    assert org.member_worker_ids == ["w-1", "w-2"]


def test_token_request_failure_raises():
    def handler(request):
        return httpx.Response(401, text="unauthorized")

    client = make_client(handler)
    with pytest.raises(WorkdayApiError, match="401"):
        client.get_worker("alice@example.com")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_workday_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'workday_mcp.workday.client'`

- [ ] **Step 4: Write the implementation**

```python
# workday_mcp/workday/client.py
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from .models import OrganizationInfo, TimeOffEntry, Worker


class WorkdayApiError(Exception):
    pass


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float


class WorkdayClient:
    def __init__(
        self,
        tenant_base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        http_client: httpx.Client | None = None,
        clock=time.time,
    ):
        self._tenant_base_url = tenant_base_url.rstrip("/")
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._http_client = http_client or httpx.Client(timeout=15.0)
        self._clock = clock
        self._cached_token: _CachedToken | None = None

    def _get_access_token(self) -> str:
        if self._cached_token and self._cached_token.expires_at > self._clock() + 30:
            return self._cached_token.access_token

        response = self._http_client.post(
            self._token_url,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
        )
        if response.status_code != 200:
            raise WorkdayApiError(f"Workday token request failed: {response.status_code} {response.text}")

        payload = response.json()
        access_token = payload["access_token"]
        expires_in = payload.get("expires_in", 3600)
        self._cached_token = _CachedToken(access_token=access_token, expires_at=self._clock() + expires_in)
        return access_token

    def _get(self, path: str, params: dict | None = None) -> dict:
        token = self._get_access_token()
        response = self._http_client.get(
            f"{self._tenant_base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            raise WorkdayApiError(f"Workday API call failed: {response.status_code} {response.text}")
        return response.json()

    def get_worker(self, upn: str) -> Worker:
        data = self._get("/workers", params={"search": upn})
        entries = data.get("data", [])
        if not entries:
            raise WorkdayApiError(f"No worker found for {upn}")
        entry = entries[0]
        return Worker(
            worker_id=entry["id"],
            display_name=entry.get("descriptor", ""),
            email=upn,
            job_title=entry.get("jobTitle", ""),
            organization=entry.get("organization", ""),
        )

    def search_workers(self, query: str, limit: int = 20) -> list[Worker]:
        data = self._get("/workers", params={"search": query, "limit": limit})
        return [
            Worker(
                worker_id=entry["id"],
                display_name=entry.get("descriptor", ""),
                email=entry.get("email", ""),
                job_title=entry.get("jobTitle", ""),
                organization=entry.get("organization", ""),
            )
            for entry in data.get("data", [])
        ]

    def get_worker_time_off(self, worker_id: str) -> list[TimeOffEntry]:
        data = self._get(f"/workers/{worker_id}/timeOffEntries")
        return [
            TimeOffEntry(date=entry["date"], hours=entry["hours"], type=entry.get("type", ""))
            for entry in data.get("data", [])
        ]

    def get_organization(self, worker_id: str) -> OrganizationInfo:
        data = self._get(f"/workers/{worker_id}/organization")
        return OrganizationInfo(
            organization_id=data["id"],
            name=data.get("name", ""),
            manager_worker_id=data.get("managerId", ""),
            member_worker_ids=data.get("memberIds", []),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_workday_client.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add workday_mcp/workday/ tests/test_workday_client.py
git commit -m "Add Workday REST client with ISU client-credentials token caching"
```

---

### Task 7: MCP tools

**Files:**
- Create: `workday_mcp/tools/get_worker.py`
- Create: `workday_mcp/tools/search_workers.py`
- Create: `workday_mcp/tools/get_worker_time_off.py`
- Create: `workday_mcp/tools/get_organization.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `get_current_identity()` (Task 2), `WorkdayClient` and its models (Task 6).
- Produces: `get_worker(client) -> dict`, `search_workers(client, query, limit=20) -> list[dict]`, `get_worker_time_off(client) -> list[dict]`, `get_organization(client) -> dict`. Consumed by Task 8 to register as MCP tools.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tools.py
import pytest

from workday_mcp.auth.identity_context import RequestIdentity, reset_current_identity, set_current_identity
from workday_mcp.tools.get_organization import get_organization
from workday_mcp.tools.get_worker import get_worker
from workday_mcp.tools.get_worker_time_off import get_worker_time_off
from workday_mcp.tools.search_workers import search_workers
from workday_mcp.workday.models import OrganizationInfo, TimeOffEntry, Worker


class FakeWorkdayClient:
    def __init__(self):
        self.worker = Worker(worker_id="w-1", display_name="Alice", email="alice@example.com", job_title="Engineer", organization="Eng")
        self.time_off = [TimeOffEntry(date="2026-01-05", hours=8, type="Vacation")]
        self.org = OrganizationInfo(organization_id="org-1", name="Engineering", manager_worker_id="w-9", member_worker_ids=["w-1"])
        self.search_results = [self.worker]
        self.last_worker_id_lookup = None

    def get_worker(self, upn):
        assert upn == "alice@example.com"
        return self.worker

    def get_worker_time_off(self, worker_id):
        self.last_worker_id_lookup = worker_id
        return self.time_off

    def get_organization(self, worker_id):
        self.last_worker_id_lookup = worker_id
        return self.org

    def search_workers(self, query, limit=20):
        assert query == "ali"
        return self.search_results


@pytest.fixture
def identity_ctx():
    identity = RequestIdentity(upn="alice@example.com", display_name="Alice", object_id="obj-1")
    token = set_current_identity(identity)
    yield identity
    reset_current_identity(token)


def test_get_worker_returns_caller_profile(identity_ctx):
    client = FakeWorkdayClient()
    result = get_worker(client)
    assert result["worker_id"] == "w-1"
    assert result["email"] == "alice@example.com"


def test_get_worker_time_off_scopes_to_caller(identity_ctx):
    client = FakeWorkdayClient()
    result = get_worker_time_off(client)
    assert result == [{"date": "2026-01-05", "hours": 8, "type": "Vacation"}]
    assert client.last_worker_id_lookup == "w-1"


def test_get_organization_scopes_to_caller(identity_ctx):
    client = FakeWorkdayClient()
    result = get_organization(client)
    assert result["name"] == "Engineering"
    assert client.last_worker_id_lookup == "w-1"


def test_search_workers_returns_list(identity_ctx):
    client = FakeWorkdayClient()
    result = search_workers(client, "ali")
    assert result[0]["worker_id"] == "w-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'workday_mcp.tools.get_worker'`

- [ ] **Step 3: Write the implementations**

```python
# workday_mcp/tools/get_worker.py
from __future__ import annotations

from workday_mcp.auth.identity_context import get_current_identity
from workday_mcp.workday.models import Worker


def _worker_to_dict(worker: Worker) -> dict:
    return {
        "worker_id": worker.worker_id,
        "display_name": worker.display_name,
        "email": worker.email,
        "job_title": worker.job_title,
        "organization": worker.organization,
    }


def get_worker(client) -> dict:
    identity = get_current_identity()
    worker = client.get_worker(identity.upn)
    return _worker_to_dict(worker)
```

```python
# workday_mcp/tools/search_workers.py
from __future__ import annotations


def search_workers(client, query: str, limit: int = 20) -> list[dict]:
    workers = client.search_workers(query, limit=limit)
    return [
        {
            "worker_id": w.worker_id,
            "display_name": w.display_name,
            "email": w.email,
            "job_title": w.job_title,
            "organization": w.organization,
        }
        for w in workers
    ]
```

```python
# workday_mcp/tools/get_worker_time_off.py
from __future__ import annotations

from workday_mcp.auth.identity_context import get_current_identity


def get_worker_time_off(client) -> list[dict]:
    identity = get_current_identity()
    worker = client.get_worker(identity.upn)
    entries = client.get_worker_time_off(worker.worker_id)
    return [{"date": e.date, "hours": e.hours, "type": e.type} for e in entries]
```

```python
# workday_mcp/tools/get_organization.py
from __future__ import annotations

from workday_mcp.auth.identity_context import get_current_identity


def get_organization(client) -> dict:
    identity = get_current_identity()
    worker = client.get_worker(identity.upn)
    org = client.get_organization(worker.worker_id)
    return {
        "organization_id": org.organization_id,
        "name": org.name,
        "manager_worker_id": org.manager_worker_id,
        "member_worker_ids": org.member_worker_ids,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tools.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add workday_mcp/tools/ tests/test_tools.py
git commit -m "Add MCP tool functions for Workday worker/time-off/org reads"
```

---

### Task 8: MCP server assembly and Entra auth middleware

**Files:**
- Create: `workday_mcp/mcp_server.py`
- Test: `tests/test_auth_middleware.py`
- Test: `tests/test_mcp_server_assembly.py`

**Interfaces:**
- Consumes: `RequestIdentity`/`set_current_identity`/`reset_current_identity` (Task 2), `EntraTokenValidator`/`TokenValidationError` (Task 3), `GraphOboResolver`/`OboExchangeError`/`build_msal_confidential_app` (Task 4), `build_protected_resource_metadata` (Task 5), `WorkdayClient` (Task 6), the four tool functions (Task 7).
- Produces: `AuthContext` (reads `ENTRA_TENANT_ID`, `ENTRA_API_AUDIENCE`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `DEV_SKIP_AUTH`, `MCP_RESOURCE_URL`, `ENTRA_API_SCOPE` from env), `build_workday_client()`, `EntraAuthMiddleware`, `build_mcp_app(auth_context=None, workday_client=None) -> Starlette` (ASGI app). Consumed by Task 9.

**Note:** this task uses `mcp.server.fastmcp.FastMCP`'s `.tool()`, `.custom_route()`, and `.streamable_http_app()`. Before Step 3, run `python -c "from mcp.server.fastmcp import FastMCP; help(FastMCP)"` in the venv and confirm these three members exist on the installed `mcp` version from `requirements.txt`; if a name differs, adjust Step 3 to match the installed API before proceeding (its behavior — tool registration, a custom HTTP route, and an ASGI app — must stay the same).

- [ ] **Step 1: Write the failing middleware tests**

```python
# tests/test_auth_middleware.py
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from workday_mcp.auth.identity_context import get_current_identity
from workday_mcp.auth.jwt_validator import TokenValidationError
from workday_mcp.auth.obo import OboExchangeError
from workday_mcp.mcp_server import EntraAuthMiddleware


class FakeAuthContext:
    def __init__(self, validate_result=None, validate_error=None, resolve_result=None, resolve_error=None, dev_skip_auth=False):
        self._validate_result = validate_result
        self._validate_error = validate_error
        self._resolve_result = resolve_result
        self._resolve_error = resolve_error
        self.dev_skip_auth = dev_skip_auth
        self.resource_url = "http://localhost:7071/mcp"
        self.validator = self
        self.obo_resolver = self

    def validate(self, token):
        if self._validate_error:
            raise self._validate_error
        return self._validate_result

    def resolve(self, token):
        if self._resolve_error:
            raise self._resolve_error
        return self._resolve_result


class FakeResolved:
    def __init__(self, upn, display_name, object_id):
        self.upn = upn
        self.display_name = display_name
        self.object_id = object_id


def make_app(auth_context):
    async def echo_identity(request):
        identity = get_current_identity()
        return PlainTextResponse(identity.upn)

    app = Starlette(routes=[Route("/echo", echo_identity)])
    app.add_middleware(EntraAuthMiddleware, auth_context=auth_context)
    return app


def test_missing_bearer_token_returns_401():
    client = TestClient(make_app(FakeAuthContext()))
    response = client.get("/echo")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_invalid_token_returns_401():
    auth_context = FakeAuthContext(validate_error=TokenValidationError("bad signature"))
    client = TestClient(make_app(auth_context))
    response = client.get("/echo", headers={"Authorization": "Bearer bad-token"})
    assert response.status_code == 401
    assert "bad signature" in response.json()["detail"]


def test_obo_failure_returns_401():
    auth_context = FakeAuthContext(validate_result=object(), resolve_error=OboExchangeError("obo boom"))
    client = TestClient(make_app(auth_context))
    response = client.get("/echo", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 401
    assert "obo boom" in response.json()["detail"]


def test_valid_token_sets_identity_and_calls_downstream():
    resolved = FakeResolved(upn="alice@example.com", display_name="Alice", object_id="obj-1")
    auth_context = FakeAuthContext(validate_result=object(), resolve_result=resolved)
    client = TestClient(make_app(auth_context))
    response = client.get("/echo", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    assert response.text == "alice@example.com"


def test_dev_skip_auth_bypasses_validation():
    client = TestClient(make_app(FakeAuthContext(dev_skip_auth=True)))
    response = client.get("/echo")
    assert response.status_code == 200
    assert response.text == "dev-user@example.com"


def test_well_known_path_is_not_gated():
    async def metadata(request):
        return PlainTextResponse("public")

    app = Starlette(routes=[Route("/.well-known/oauth-protected-resource", metadata)])
    app.add_middleware(EntraAuthMiddleware, auth_context=FakeAuthContext())
    client = TestClient(app)
    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth_middleware.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'workday_mcp.mcp_server'`

- [ ] **Step 3: Write `workday_mcp/mcp_server.py`**

```python
# workday_mcp/mcp_server.py
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from workday_mcp.auth.identity_context import RequestIdentity, reset_current_identity, set_current_identity
from workday_mcp.auth.jwt_validator import EntraTokenValidator, TokenValidationError
from workday_mcp.auth.obo import GraphOboResolver, OboExchangeError, build_msal_confidential_app
from workday_mcp.auth.protected_resource_metadata import build_protected_resource_metadata
from workday_mcp.tools.get_organization import get_organization
from workday_mcp.tools.get_worker import get_worker
from workday_mcp.tools.get_worker_time_off import get_worker_time_off
from workday_mcp.tools.search_workers import search_workers
from workday_mcp.workday.client import WorkdayClient


class AuthContext:
    def __init__(self):
        tenant_id = os.environ["ENTRA_TENANT_ID"]
        api_audience = os.environ["ENTRA_API_AUDIENCE"]
        client_id = os.environ["ENTRA_CLIENT_ID"]
        client_secret = os.environ["ENTRA_CLIENT_SECRET"]

        self.dev_skip_auth = os.environ.get("DEV_SKIP_AUTH", "false").lower() == "true"
        self.resource_url = os.environ.get("MCP_RESOURCE_URL", "http://localhost:7071/mcp")
        self.scope = os.environ.get("ENTRA_API_SCOPE", f"{api_audience}/access_as_user")
        self.tenant_id = tenant_id

        self.validator = EntraTokenValidator(tenant_id=tenant_id, audience=api_audience)
        msal_app = build_msal_confidential_app(tenant_id, client_id, client_secret)
        self.obo_resolver = GraphOboResolver(msal_app)


def build_workday_client() -> WorkdayClient:
    return WorkdayClient(
        tenant_base_url=os.environ["WORKDAY_TENANT_BASE_URL"],
        token_url=os.environ["WORKDAY_TOKEN_URL"],
        client_id=os.environ["WORKDAY_CLIENT_ID"],
        client_secret=os.environ["WORKDAY_CLIENT_SECRET"],
    )


class EntraAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_context: AuthContext):
        super().__init__(app)
        self._auth = auth_context

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/.well-known/oauth-protected-resource":
            return await call_next(request)

        if self._auth.dev_skip_auth:
            identity = RequestIdentity(upn="dev-user@example.com", display_name="Dev User", object_id="dev-obj")
            token = set_current_identity(identity)
            try:
                return await call_next(request)
            finally:
                reset_current_identity(token)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return self._unauthorized("missing bearer token")
        raw_token = header.split(" ", 1)[1]

        try:
            self._auth.validator.validate(raw_token)
        except TokenValidationError as exc:
            return self._unauthorized(str(exc))

        try:
            resolved = self._auth.obo_resolver.resolve(raw_token)
        except OboExchangeError as exc:
            return self._unauthorized(f"identity resolution failed: {exc}")

        identity = RequestIdentity(upn=resolved.upn, display_name=resolved.display_name, object_id=resolved.object_id)
        token = set_current_identity(identity)
        try:
            return await call_next(request)
        finally:
            reset_current_identity(token)

    def _unauthorized(self, detail: str) -> Response:
        return JSONResponse(
            {"error": "unauthorized", "detail": detail},
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="'
                    f'{self._auth.resource_url.rstrip("/")}/.well-known/oauth-protected-resource"'
                )
            },
        )


def build_mcp_app(auth_context: AuthContext | None = None, workday_client: WorkdayClient | None = None):
    auth_context = auth_context or AuthContext()
    client = workday_client or build_workday_client()

    mcp = FastMCP("workday-mcp")

    @mcp.tool()
    def get_worker_tool() -> dict:
        """Return the caller's own Workday worker profile."""
        return get_worker(client)

    @mcp.tool()
    def search_workers_tool(query: str, limit: int = 20) -> list[dict]:
        """Search the Workday worker directory by name or other free-text query."""
        return search_workers(client, query, limit=limit)

    @mcp.tool()
    def get_worker_time_off_tool() -> list[dict]:
        """Return the caller's own time-off/absence entries."""
        return get_worker_time_off(client)

    @mcp.tool()
    def get_organization_tool() -> dict:
        """Return the caller's own organization/team structure."""
        return get_organization(client)

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def protected_resource_metadata(request):
        return JSONResponse(
            build_protected_resource_metadata(
                resource_url=auth_context.resource_url,
                tenant_id=auth_context.tenant_id,
                scope=auth_context.scope,
            )
        )

    app = mcp.streamable_http_app()
    app.add_middleware(EntraAuthMiddleware, auth_context=auth_context)
    return app
```

- [ ] **Step 4: Run middleware tests to verify they pass**

Run: `pytest tests/test_auth_middleware.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Write the failing assembly smoke test**

```python
# tests/test_mcp_server_assembly.py
from starlette.testclient import TestClient

from workday_mcp.mcp_server import AuthContext, build_mcp_app
from workday_mcp.workday.client import WorkdayClient


class FakeWorkdayClient(WorkdayClient):
    def __init__(self):
        pass  # bypass real __init__; not exercised by this smoke test


def test_protected_resource_metadata_is_publicly_reachable(monkeypatch):
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-abc")
    monkeypatch.setenv("ENTRA_API_AUDIENCE", "api://workday-mcp")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "client-id")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("DEV_SKIP_AUTH", "true")

    auth_context = AuthContext()
    app = build_mcp_app(auth_context=auth_context, workday_client=FakeWorkdayClient())
    client = TestClient(app)

    response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == auth_context.resource_url
    assert body["authorization_servers"] == ["https://login.microsoftonline.com/tenant-abc/v2.0"]
```

- [ ] **Step 6: Run the assembly test to verify it passes**

Run: `pytest tests/test_mcp_server_assembly.py -v`
Expected: PASS (1 passed). If `.custom_route`/`.streamable_http_app` differ from the installed `mcp` version, fix Step 3 per the note above the tests and re-run until green.

- [ ] **Step 7: Commit**

```bash
git add workday_mcp/mcp_server.py tests/test_auth_middleware.py tests/test_mcp_server_assembly.py
git commit -m "Assemble FastMCP app with Entra auth + OBO middleware"
```

---

### Task 9: Azure Functions entry point

**Files:**
- Create: `function_app.py`
- Test: `tests/test_function_app.py`

**Interfaces:**
- Consumes: `build_mcp_app` (Task 8).
- Produces: module-level `app: func.AsgiFunctionApp`, the Azure Functions runtime's entry point.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_function_app.py
import importlib

import azure.functions as func


def test_function_app_exposes_asgi_function_app(monkeypatch):
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-abc")
    monkeypatch.setenv("ENTRA_API_AUDIENCE", "api://workday-mcp")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "client-id")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("WORKDAY_TENANT_BASE_URL", "https://wd.example.com/api/v1/acme")
    monkeypatch.setenv("WORKDAY_TOKEN_URL", "https://wd.example.com/oauth2/token")
    monkeypatch.setenv("WORKDAY_CLIENT_ID", "isu-client")
    monkeypatch.setenv("WORKDAY_CLIENT_SECRET", "isu-secret")
    monkeypatch.setenv("DEV_SKIP_AUTH", "true")

    import function_app as function_app_module
    importlib.reload(function_app_module)

    assert isinstance(function_app_module.app, func.AsgiFunctionApp)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_function_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'function_app'`

- [ ] **Step 3: Write `function_app.py`**

```python
# function_app.py
import azure.functions as func

from workday_mcp.mcp_server import build_mcp_app

asgi_app = build_mcp_app()

app = func.AsgiFunctionApp(app=asgi_app, http_auth_level=func.AuthLevel.FUNCTION)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_function_app.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Smoke-test locally with Azure Functions Core Tools**

```bash
cp local.settings.json.example local.settings.json
func start
```

Expected: the host starts without error and logs an HTTP route for the function; `curl http://localhost:7071/.well-known/oauth-protected-resource` (with `DEV_SKIP_AUTH=true` in `local.settings.json`) returns the metadata JSON. Stop the host (Ctrl+C) when confirmed.

- [ ] **Step 6: Commit**

```bash
git add function_app.py tests/test_function_app.py
git commit -m "Add Azure Functions entry point wrapping the FastMCP ASGI app"
```

---

### Task 10: Bicep — Storage and Key Vault modules

**Files:**
- Create: `infra/modules/storage.bicep`
- Create: `infra/modules/key-vault.bicep`

**Interfaces:**
- Produces (storage.bicep): outputs `storageAccountId`, `storageAccountName`.
- Produces (key-vault.bicep): outputs `keyVaultName`; consumes `functionAppPrincipalId` (from Task 11's function-app.bicep output) to grant the `Key Vault Secrets User` role.

- [ ] **Step 1: Write `infra/modules/storage.bicep`**

```bicep
@description('Name of the storage account (must be globally unique, lowercase, 3-24 chars).')
param storageAccountName string

@description('Azure region for the storage account.')
param location string = resourceGroup().location

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

output storageAccountId string = storageAccount.id
output storageAccountName string = storageAccount.name
```

- [ ] **Step 2: Write `infra/modules/key-vault.bicep`**

```bicep
@description('Name of the Key Vault.')
param keyVaultName string

@description('Azure region.')
param location string = resourceGroup().location

@description('Tenant ID for the Key Vault.')
param tenantId string

@description('Principal ID of the Function App managed identity to grant secret access to.')
param functionAppPrincipalId string

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
  }
}

resource secretsUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, functionAppPrincipalId, 'KeyVaultSecretsUser')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
    principalId: functionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output keyVaultName string = keyVault.name
```

- [ ] **Step 3: Validate both modules compile**

Run: `az bicep build --file infra/modules/storage.bicep && az bicep build --file infra/modules/key-vault.bicep`
Expected: no errors; each produces a sibling `.json` ARM template. Delete the generated `.json` files afterward (they're build output, not source).

- [ ] **Step 4: Commit**

```bash
git add infra/modules/storage.bicep infra/modules/key-vault.bicep
git commit -m "Add Bicep modules for Storage and Key Vault"
```

---

### Task 11: Bicep — Function App, APIM, and main composition

**Files:**
- Create: `infra/modules/function-app.bicep`
- Create: `infra/modules/apim.bicep`
- Create: `infra/main.bicep`

**Interfaces:**
- Consumes: `storage.bicep` output `storageAccountName` (Task 10), `key-vault.bicep` (Task 10, invoked after function-app.bicep to close the dependency loop — see Step 3).
- Produces (function-app.bicep): outputs `functionAppPrincipalId`, `functionAppHostName`, `functionAppName`.
- Produces (apim.bicep): the APIM instance and API definition with a `validate-jwt` policy.
- Produces (main.bicep): the top-level deployable template, outputs `functionAppName`, `functionAppHostName`, `keyVaultName`.

- [ ] **Step 1: Write `infra/modules/function-app.bicep`**

```bicep
@description('Name of the Function App.')
param functionAppName string

@description('Azure region.')
param location string = resourceGroup().location

@description('Storage account name used by the Functions runtime.')
param storageAccountName string

@description('Key Vault URI for Key Vault reference app settings.')
param keyVaultUri string

@description('Application Insights connection string.')
param appInsightsConnectionString string

@description('Entra ID tenant ID.')
param entraTenantId string

@description('Entra ID API app (workday-mcp-api) client ID / audience.')
param entraApiAudience string

@description('Entra ID API app scope, e.g. api://workday-mcp/access_as_user.')
param entraApiScope string

@description('Public resource URL of the deployed MCP endpoint.')
param mcpResourceUrl string

@description('Workday tenant REST API base URL.')
param workdayTenantBaseUrl string

@description('Workday OAuth2 token URL.')
param workdayTokenUrl string

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

resource hostingPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${functionAppName}-plan'
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: hostingPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'ENTRA_TENANT_ID', value: entraTenantId }
        { name: 'ENTRA_API_AUDIENCE', value: entraApiAudience }
        { name: 'ENTRA_API_SCOPE', value: entraApiScope }
        { name: 'ENTRA_CLIENT_ID', value: entraApiAudience }
        { name: 'ENTRA_CLIENT_SECRET', value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/entra-client-secret/)' }
        { name: 'MCP_RESOURCE_URL', value: mcpResourceUrl }
        { name: 'WORKDAY_TENANT_BASE_URL', value: workdayTenantBaseUrl }
        { name: 'WORKDAY_TOKEN_URL', value: workdayTokenUrl }
        { name: 'WORKDAY_CLIENT_ID', value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/workday-client-id/)' }
        { name: 'WORKDAY_CLIENT_SECRET', value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/workday-client-secret/)' }
        { name: 'DEV_SKIP_AUTH', value: 'false' }
      ]
    }
  }
}

output functionAppPrincipalId string = functionApp.identity.principalId
output functionAppHostName string = functionApp.properties.defaultHostName
output functionAppName string = functionApp.name
```

- [ ] **Step 2: Write `infra/modules/apim.bicep`**

```bicep
@description('Name of the API Management instance.')
param apimName string

@description('Azure region.')
param location string = resourceGroup().location

@description('Publisher email for APIM.')
param publisherEmail string

@description('Publisher name for APIM.')
param publisherName string

@description('Backend Function App host name.')
param functionAppHostName string

@description('Function App host key, so calls must go through APIM to reach the Function.')
@secure()
param functionAppHostKey string

@description('Entra ID tenant ID, for the validate-jwt policy.')
param entraTenantId string

@description('Entra ID API audience (client ID of the workday-mcp-api app).')
param entraApiAudience string

resource apim 'Microsoft.ApiManagement/service@2023-05-01-preview' = {
  name: apimName
  location: location
  sku: {
    name: 'Developer'
    capacity: 1
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' = {
  parent: apim
  name: 'workday-mcp'
  properties: {
    displayName: 'Workday MCP Server'
    path: 'workday-mcp'
    protocols: ['https']
    serviceUrl: 'https://${functionAppHostName}'
    subscriptionRequired: false
  }
}

resource wildcardOperation 'Microsoft.ApiManagement/service/apis/operations@2023-05-01-preview' = {
  parent: api
  name: 'proxy-all'
  properties: {
    displayName: 'Proxy all MCP traffic'
    method: '*'
    urlTemplate: '/*'
  }
}

resource apiPolicy 'Microsoft.ApiManagement/service/apis/policies@2023-05-01-preview' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'xml'
    value: '''
<policies>
  <inbound>
    <base />
    <choose>
      <when condition="@(context.Request.Url.Path.EndsWith("/.well-known/oauth-protected-resource"))">
      </when>
      <otherwise>
        <validate-jwt header-name="Authorization" failed-validation-httpcode="401" require-expiration-time="true" require-signed-tokens="true">
          <openid-config url="https://login.microsoftonline.com/${entraTenantId}/v2.0/.well-known/openid-configuration" />
          <audiences>
            <audience>${entraApiAudience}</audience>
          </audiences>
          <issuers>
            <issuer>https://login.microsoftonline.com/${entraTenantId}/v2.0</issuer>
          </issuers>
        </validate-jwt>
      </otherwise>
    </choose>
    <set-header name="x-functions-key" exists-action="override">
      <value>${functionAppHostKey}</value>
    </set-header>
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
'''
  }
}

output apimGatewayUrl string = apim.properties.gatewayUrl
```

- [ ] **Step 3: Write `infra/main.bicep`**, breaking the Function App / Key Vault circular dependency by computing `keyVaultUri` from the deterministic vault name rather than from the Key Vault module's output (Key Vault needs the Function App's principal ID; the Function App only needs the URI string, not the vault resource itself):

```bicep
@description('Base name used to derive resource names.')
param baseName string = 'workday-mcp'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Entra ID tenant ID.')
param entraTenantId string

@description('Entra ID API app (workday-mcp-api) client ID / audience.')
param entraApiAudience string

@description('Entra ID API app scope, e.g. api://workday-mcp/access_as_user.')
param entraApiScope string

@description('Public resource URL of the deployed MCP endpoint.')
param mcpResourceUrl string

@description('Workday tenant REST API base URL.')
param workdayTenantBaseUrl string

@description('Workday OAuth2 token URL.')
param workdayTokenUrl string

@description('APIM publisher email.')
param apimPublisherEmail string

@description('APIM publisher name.')
param apimPublisherName string

@description('Function App host key. Empty on first deploy; fetch with `az functionapp keys list` after the Function App exists, then redeploy passing it so APIM can call the Function.')
@secure()
param functionAppHostKey string = ''

var storageAccountName = toLower(replace('${baseName}stg${uniqueString(resourceGroup().id)}', '-', ''))
var keyVaultName = '${baseName}-kv-${uniqueString(resourceGroup().id)}'
var keyVaultUri = 'https://${keyVaultName}.vault.azure.net/'
var functionAppName = '${baseName}-func-${uniqueString(resourceGroup().id)}'
var apimName = '${baseName}-apim-${uniqueString(resourceGroup().id)}'
var appInsightsName = '${baseName}-appi'

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storageDeploy'
  params: {
    storageAccountName: storageAccountName
    location: location
  }
}

module functionApp 'modules/function-app.bicep' = {
  name: 'functionAppDeploy'
  params: {
    functionAppName: functionAppName
    location: location
    storageAccountName: storage.outputs.storageAccountName
    keyVaultUri: keyVaultUri
    appInsightsConnectionString: appInsights.properties.ConnectionString
    entraTenantId: entraTenantId
    entraApiAudience: entraApiAudience
    entraApiScope: entraApiScope
    mcpResourceUrl: mcpResourceUrl
    workdayTenantBaseUrl: workdayTenantBaseUrl
    workdayTokenUrl: workdayTokenUrl
  }
}

module keyVault 'modules/key-vault.bicep' = {
  name: 'keyVaultDeploy'
  params: {
    keyVaultName: keyVaultName
    location: location
    tenantId: entraTenantId
    functionAppPrincipalId: functionApp.outputs.functionAppPrincipalId
  }
}

module apim 'modules/apim.bicep' = {
  name: 'apimDeploy'
  params: {
    apimName: apimName
    location: location
    publisherEmail: apimPublisherEmail
    publisherName: apimPublisherName
    functionAppHostName: functionApp.outputs.functionAppHostName
    functionAppHostKey: functionAppHostKey
    entraTenantId: entraTenantId
    entraApiAudience: entraApiAudience
  }
}

output functionAppName string = functionApp.outputs.functionAppName
output functionAppHostName string = functionApp.outputs.functionAppHostName
output keyVaultName string = keyVaultName
```

- [ ] **Step 4: Validate the full template compiles**

Run: `az bicep build --file infra/main.bicep`
Expected: no errors (this also resolves and type-checks the module files). Delete the generated `.json` build output afterward.

- [ ] **Step 5: Commit**

```bash
git add infra/modules/function-app.bicep infra/modules/apim.bicep infra/main.bicep
git commit -m "Add Bicep for Function App, APIM validate-jwt policy, and main composition"
```

---

### Task 12: Entra ID app registration script

**Files:**
- Create: `scripts/register-entra-apps.sh`

**Interfaces:**
- Produces: a standalone `az cli` script, no Python interfaces (not imported by application code).

- [ ] **Step 1: Write `scripts/register-entra-apps.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Creates the Entra ID app registration for the workday-mcp API, exposes the
# access_as_user scope, and adds the delegated Microsoft Graph User.Read
# permission needed for the OBO identity-resolution step. Optionally also
# creates a client app registration pre-authorized for that scope.
#
# Requires: az cli, logged in (`az login`) with Application Administrator
# or Global Administrator rights.
#
# Usage:
#   ./scripts/register-entra-apps.sh <api-app-display-name> [client-app-display-name]
#
# Example:
#   ./scripts/register-entra-apps.sh workday-mcp-api workday-mcp-client

API_APP_NAME="${1:?Usage: $0 <api-app-display-name> [client-app-display-name]}"
CLIENT_APP_NAME="${2:-}"

GRAPH_USER_READ_SCOPE_ID="e1fe6dd8-ba31-4d61-89e7-88639da4683d" # Microsoft Graph User.Read
GRAPH_RESOURCE_APP_ID="00000003-0000-0000-c000-000000000000"   # Microsoft Graph

echo "Creating API app registration: ${API_APP_NAME}"
API_APP_ID=$(az ad app create \
  --display-name "${API_APP_NAME}" \
  --sign-in-audience AzureADMyOrg \
  --query appId -o tsv)

echo "API app created: appId=${API_APP_ID}"

az ad app update --id "${API_APP_ID}" --identifier-uris "api://${API_APP_ID}"

SCOPE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")

az ad app update --id "${API_APP_ID}" --set api="{
  \"oauth2PermissionScopes\": [
    {
      \"id\": \"${SCOPE_ID}\",
      \"adminConsentDescription\": \"Allow the app to call workday-mcp on behalf of the signed-in user.\",
      \"adminConsentDisplayName\": \"Access workday-mcp as the signed-in user\",
      \"userConsentDescription\": \"Allow the app to access workday-mcp on your behalf.\",
      \"userConsentDisplayName\": \"Access workday-mcp\",
      \"value\": \"access_as_user\",
      \"type\": \"User\",
      \"isEnabled\": true
    }
  ]
}"

echo "Exposed scope api://${API_APP_ID}/access_as_user"

echo "Adding delegated Microsoft Graph User.Read permission"
az ad app permission add \
  --id "${API_APP_ID}" \
  --api "${GRAPH_RESOURCE_APP_ID}" \
  --api-permissions "${GRAPH_USER_READ_SCOPE_ID}=Scope"

echo "Creating client secret (used as the confidential client for the OBO flow)"
CLIENT_SECRET=$(az ad app credential reset \
  --id "${API_APP_ID}" \
  --display-name "workday-mcp-obo-secret" \
  --years 1 \
  --query password -o tsv)

echo ""
echo "=== API app registration complete ==="
echo "ENTRA_CLIENT_ID (=ENTRA_API_AUDIENCE): ${API_APP_ID}"
echo "ENTRA_API_SCOPE: api://${API_APP_ID}/access_as_user"
echo "ENTRA_CLIENT_SECRET: ${CLIENT_SECRET}"
echo ""
echo "NOTE: a tenant admin must still grant admin consent for User.Read:"
echo "  az ad app permission admin-consent --id ${API_APP_ID}"
echo ""

if [[ -n "${CLIENT_APP_NAME}" ]]; then
  echo "Creating client app registration: ${CLIENT_APP_NAME}"
  CLIENT_APP_ID=$(az ad app create \
    --display-name "${CLIENT_APP_NAME}" \
    --sign-in-audience AzureADMyOrg \
    --query appId -o tsv)

  az ad app permission add \
    --id "${CLIENT_APP_ID}" \
    --api "${API_APP_ID}" \
    --api-permissions "${SCOPE_ID}=Scope"

  echo "=== Client app registration complete ==="
  echo "CLIENT_APP_ID: ${CLIENT_APP_ID}"
  echo ""
  echo "NOTE: a tenant admin must still grant admin consent for the client's access to workday-mcp:"
  echo "  az ad app permission admin-consent --id ${CLIENT_APP_ID}"
fi
```

- [ ] **Step 2: Make it executable and syntax-check it**

```bash
chmod +x scripts/register-entra-apps.sh
bash -n scripts/register-entra-apps.sh
command -v shellcheck >/dev/null && shellcheck scripts/register-entra-apps.sh || echo "shellcheck not installed, skipping lint"
```

Expected: `bash -n` produces no output (valid syntax); `shellcheck` (if installed) reports no errors.

- [ ] **Step 3: Commit**

```bash
git add scripts/register-entra-apps.sh
git commit -m "Add Entra ID app registration script"
```

---

### Task 13: README and final wiring

**Files:**
- Create: `README.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Write `README.md`**

```markdown
# workday-mcp

A Python MCP (Model Context Protocol) server, hosted on Azure Functions, that
exposes read-only Workday HR tools to MCP clients. Inbound calls are
authenticated with OAuth 2.0 / Microsoft Entra ID and fronted by Azure API
Management; the server uses the OAuth On-Behalf-Of (OBO) flow against
Microsoft Graph to resolve the caller's verified identity, then calls
Workday's REST API using Workday's own client-credentials (Integration
System User) grant, scoped to that identity.

See [docs/superpowers/specs/2026-09-24-workday-mcp-design.md](docs/superpowers/specs/2026-09-24-workday-mcp-design.md)
for the full design.

## Tools

- `get_worker_tool` — the caller's own Workday worker profile.
- `search_workers_tool` — free-text search of the Workday worker directory.
- `get_worker_time_off_tool` — the caller's own time-off/absence entries.
- `get_organization_tool` — the caller's own organization/team structure.

## Prerequisites

- Python 3.11
- [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local)
- Azure CLI, logged in (`az login`)
- A Workday tenant with permission to create an Integration System User (ISU)
  and an OAuth 2.0 API Client

## 1. Workday-side setup (manual)

1. In Workday, create an Integration System User (ISU) with the minimum
   security group access needed for worker profile, time-off, and
   organization reads.
2. Register an OAuth 2.0 API Client in Workday, bound to that ISU, using the
   client-credentials grant.
3. Record: the Workday REST API base URL for your tenant, the OAuth2 token
   URL, and the client ID/secret for the API client.

## 2. Entra ID app registrations

\`\`\`bash
./scripts/register-entra-apps.sh workday-mcp-api workday-mcp-client
\`\`\`

This creates the `workday-mcp-api` app registration (exposes the
`access_as_user` scope, requests delegated `User.Read` on Microsoft Graph for
the OBO step, and creates a client secret), and optionally a client app
registration pre-authorized for that scope. A tenant admin must grant admin
consent using the `az ad app permission admin-consent` commands printed by
the script.

## 3. Local development

\`\`\`bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp local.settings.json.example local.settings.json
# fill in local.settings.json with the values from steps 1-2
func start
\`\`\`

With `DEV_SKIP_AUTH=true` in `local.settings.json`, requests are treated as
an authenticated dev user without a real Entra ID token, so tools can be
exercised locally without a live OAuth flow.

## 4. Tests

\`\`\`bash
pytest
\`\`\`

All tests run offline — Graph and Workday HTTP calls are mocked.

## 5. Deploy infrastructure

\`\`\`bash
az deployment group create \\
  --resource-group <your-resource-group> \\
  --template-file infra/main.bicep \\
  --parameters entraTenantId=<tenant-id> \\
               entraApiAudience=<workday-mcp-api-app-id> \\
               entraApiScope=api://<workday-mcp-api-app-id>/access_as_user \\
               mcpResourceUrl=https://<function-app-host>/mcp \\
               workdayTenantBaseUrl=<workday-rest-base-url> \\
               workdayTokenUrl=<workday-oauth2-token-url> \\
               apimPublisherEmail=<you@example.com> \\
               apimPublisherName="<Your Org>"
\`\`\`

APIM's policy needs the deployed Function App's host key to call it directly.
After the first deploy, fetch it and redeploy so APIM can present it:

\`\`\`bash
FUNCTION_KEY=$(az functionapp keys list \\
  --resource-group <your-resource-group> \\
  --name <function-app-name> \\
  --query functionKeys.default -o tsv)

az deployment group create \\
  --resource-group <your-resource-group> \\
  --template-file infra/main.bicep \\
  --parameters @<same params as above> functionAppHostKey="${FUNCTION_KEY}"
\`\`\`

Store the Entra client secret and Workday client ID/secret in the deployed
Key Vault under the secret names referenced by
`infra/modules/function-app.bicep` (`entra-client-secret`,
`workday-client-id`, `workday-client-secret`):

\`\`\`bash
az keyvault secret set --vault-name <kv-name> --name entra-client-secret --value "<...>"
az keyvault secret set --vault-name <kv-name> --name workday-client-id --value "<...>"
az keyvault secret set --vault-name <kv-name> --name workday-client-secret --value "<...>"
\`\`\`

## 6. Deploy application code

\`\`\`bash
func azure functionapp publish <function-app-name>
\`\`\`
```

- [ ] **Step 2: Run the full test suite one final time**

Run: `pytest -v`
Expected: all tests from Tasks 2-9 pass (24 tests).

- [ ] **Step 3: Commit and push to GitHub**

```bash
git add README.md
git commit -m "Add README with setup, deploy, and testing instructions"
gh repo create workday-mcp --private --source=. --push
```

Expected: `gh repo create` reports the new private repository URL and pushes `main`.
