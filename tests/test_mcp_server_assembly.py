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
