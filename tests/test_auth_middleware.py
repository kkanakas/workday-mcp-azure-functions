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
