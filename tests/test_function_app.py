import importlib
import json
from pathlib import Path

import azure.functions as func

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def test_host_json_clears_the_default_api_route_prefix():
    """C4: AsgiFunctionApp forwards the full request path into the ASGI app, and
    the Starlette routes have no /api prefix, so the default routePrefix ("api")
    would make every request 404 in a real deployment."""
    host_config = json.loads((REPO_ROOT / "host.json").read_text())
    assert host_config["extensions"]["http"]["routePrefix"] == ""


def test_starlette_routes_have_no_api_prefix():
    """The counterpart to the host.json assertion above: the app really does
    serve its routes at the root, so an "api" prefix could not match."""
    from workday_mcp.mcp_server import PROTECTED_RESOURCE_METADATA_PATH

    assert PROTECTED_RESOURCE_METADATA_PATH == "/.well-known/oauth-protected-resource"
    assert not PROTECTED_RESOURCE_METADATA_PATH.startswith("/api/")
