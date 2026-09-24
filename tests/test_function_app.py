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
