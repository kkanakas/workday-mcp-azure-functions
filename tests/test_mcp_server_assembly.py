# tests/test_mcp_server_assembly.py
import pytest
from starlette.testclient import TestClient

from workday_mcp.mcp_server import (
    AuthContext,
    build_mcp_app,
    protected_resource_metadata_url,
    resolve_allowed_hosts,
)
from workday_mcp.workday.client import WorkdayClient

DEPLOYED_HOST = "wd-func.azurewebsites.net"
DEPLOYED_RESOURCE_URL = f"https://{DEPLOYED_HOST}/mcp"

INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0"},
    },
}
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class FakeWorkdayClient(WorkdayClient):
    def __init__(self):
        pass  # bypass real __init__; not exercised by this smoke test


def _dev_env(monkeypatch, resource_url=DEPLOYED_RESOURCE_URL, allowed_hosts=None):
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-abc")
    monkeypatch.setenv("ENTRA_API_AUDIENCE", "66666666-7777-8888-9999-000000000000")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "66666666-7777-8888-9999-000000000000")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("DEV_SKIP_AUTH", "true")
    monkeypatch.setenv("MCP_RESOURCE_URL", resource_url)
    if allowed_hosts is None:
        monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    else:
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", allowed_hosts)
    return AuthContext()


def test_protected_resource_metadata_is_publicly_reachable(monkeypatch):
    auth_context = _dev_env(monkeypatch, resource_url="http://localhost:7071/mcp")
    app = build_mcp_app(auth_context=auth_context, workday_client=FakeWorkdayClient())
    client = TestClient(app, base_url="http://localhost:7071")

    response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == auth_context.resource_url
    assert body["authorization_servers"] == ["https://login.microsoftonline.com/tenant-abc/v2.0"]


def test_metadata_resource_field_keeps_the_full_resource_identifier(monkeypatch):
    """resource_url (with its /mcp path) is the resource identifier; only the
    location the document is *served* from drops the path."""
    auth_context = _dev_env(monkeypatch)
    app = build_mcp_app(auth_context=auth_context, workday_client=FakeWorkdayClient())
    client = TestClient(app, base_url=f"https://{DEPLOYED_HOST}")

    body = client.get("/.well-known/oauth-protected-resource").json()

    assert body["resource"] == DEPLOYED_RESOURCE_URL


def test_advertised_metadata_url_is_actually_reachable(monkeypatch):
    """End-to-end (I1): take the URL from the real 401's WWW-Authenticate header
    and fetch it; it must return the metadata document, not a 404."""
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-abc")
    monkeypatch.setenv("ENTRA_API_AUDIENCE", "66666666-7777-8888-9999-000000000000")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "66666666-7777-8888-9999-000000000000")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("DEV_SKIP_AUTH", "false")
    monkeypatch.setenv("MCP_RESOURCE_URL", DEPLOYED_RESOURCE_URL)
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)

    class UnauthenticatedAuthContext(AuthContext):
        """Real resource_url/tenant/scope wiring, but no live Entra/MSAL setup:
        a request with no Authorization header 401s before either is touched."""

        def __init__(self):
            import os

            self.dev_skip_auth = False
            self.resource_url = os.environ["MCP_RESOURCE_URL"]
            self.tenant_id = os.environ["ENTRA_TENANT_ID"]
            self.scope = f"api://{os.environ['ENTRA_API_AUDIENCE']}/access_as_user"
            self.validator = None
            self.obo_resolver = None

    app = build_mcp_app(auth_context=UnauthenticatedAuthContext(), workday_client=FakeWorkdayClient())
    client = TestClient(app, base_url=f"https://{DEPLOYED_HOST}")

    unauthorized = client.post("/mcp", json=INITIALIZE_REQUEST, headers=MCP_HEADERS)
    assert unauthorized.status_code == 401

    advertised = unauthorized.headers["WWW-Authenticate"].split('resource_metadata="', 1)[1].rstrip('"')
    assert advertised == f"https://{DEPLOYED_HOST}/.well-known/oauth-protected-resource"

    # Fetch exactly the advertised URL as a real request.
    metadata = client.get(advertised)
    assert metadata.status_code == 200, f"advertised metadata URL {advertised} is not reachable"
    assert metadata.json()["resource"] == DEPLOYED_RESOURCE_URL


def test_mcp_endpoint_accepts_the_deployed_host(monkeypatch):
    """C3: a real Azure Functions Host header must not be rejected with 421."""
    auth_context = _dev_env(monkeypatch)
    app = build_mcp_app(auth_context=auth_context, workday_client=FakeWorkdayClient())

    with TestClient(app, base_url=f"https://{DEPLOYED_HOST}") as client:
        response = client.post("/mcp", json=INITIALIZE_REQUEST, headers=MCP_HEADERS)

    assert response.status_code != 421, f"deployed host rejected: {response.text}"
    assert response.status_code == 200


def test_mcp_endpoint_still_rejects_an_unknown_host(monkeypatch):
    """C3: DNS-rebinding protection stays ON - it is configured, not disabled."""
    auth_context = _dev_env(monkeypatch)
    app = build_mcp_app(auth_context=auth_context, workday_client=FakeWorkdayClient())

    with TestClient(app, base_url="https://attacker.example.com") as client:
        response = client.post("/mcp", json=INITIALIZE_REQUEST, headers=MCP_HEADERS)

    assert response.status_code == 421


def test_mcp_allowed_hosts_env_var_overrides_the_derived_host(monkeypatch):
    auth_context = _dev_env(monkeypatch, allowed_hosts="apim-gateway.azure-api.net")

    # A session manager can only be run once, so build a fresh app per client.
    allowed_app = build_mcp_app(auth_context=auth_context, workday_client=FakeWorkdayClient())
    with TestClient(allowed_app, base_url="https://apim-gateway.azure-api.net") as client:
        allowed = client.post("/mcp", json=INITIALIZE_REQUEST, headers=MCP_HEADERS)
    assert allowed.status_code == 200

    rejected_app = build_mcp_app(auth_context=auth_context, workday_client=FakeWorkdayClient())
    with TestClient(rejected_app, base_url=f"https://{DEPLOYED_HOST}") as client:
        rejected = client.post("/mcp", json=INITIALIZE_REQUEST, headers=MCP_HEADERS)
    assert rejected.status_code == 421


@pytest.mark.parametrize(
    "resource_url,expected",
    [
        ("https://wd-func.azurewebsites.net/mcp", "https://wd-func.azurewebsites.net/.well-known/oauth-protected-resource"),
        ("http://localhost:7071/mcp", "http://localhost:7071/.well-known/oauth-protected-resource"),
        ("https://host/nested/path", "https://host/.well-known/oauth-protected-resource"),
    ],
)
def test_protected_resource_metadata_url_drops_the_resource_path(resource_url, expected):
    assert protected_resource_metadata_url(resource_url) == expected


def test_resolve_allowed_hosts_defaults_to_the_resource_host_plus_loopback(monkeypatch):
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    hosts = resolve_allowed_hosts(DEPLOYED_RESOURCE_URL)
    assert DEPLOYED_HOST in hosts
    assert f"{DEPLOYED_HOST}:*" in hosts  # tolerate an explicit :443
    assert "localhost:*" in hosts
    assert "attacker.example.com" not in hosts


def test_resolve_allowed_hosts_reads_the_env_var(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "a.example.com, b.example.com:8443 ")
    hosts = resolve_allowed_hosts(DEPLOYED_RESOURCE_URL)
    assert "a.example.com" in hosts
    assert "b.example.com:8443" in hosts
    assert DEPLOYED_HOST not in hosts
