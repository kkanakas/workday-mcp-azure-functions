# tests/test_auth_middleware.py
import threading

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from workday_mcp.auth.identity_context import get_current_identity
from workday_mcp.auth.jwt_validator import TokenValidationError
from workday_mcp.auth.obo import OboExchangeError
from workday_mcp.mcp_server import EntraAuthMiddleware


class FakeAuthContext:
    def __init__(
        self,
        validate_result=None,
        validate_error=None,
        resolve_result=None,
        resolve_error=None,
        dev_skip_auth=False,
        resource_url="http://localhost:7071/mcp",
    ):
        self._validate_result = validate_result
        self._validate_error = validate_error
        self._resolve_result = resolve_result
        self._resolve_error = resolve_error
        self.dev_skip_auth = dev_skip_auth
        self.resource_url = resource_url
        self.validator = self
        self.obo_resolver = self
        self.validate_thread = None
        self.resolve_thread = None

    def validate(self, token):
        self.validate_thread = threading.current_thread()
        if self._validate_error:
            raise self._validate_error
        return self._validate_result

    def resolve(self, token):
        self.resolve_thread = threading.current_thread()
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

    async def echo_event_loop_thread(request):
        return PlainTextResponse(str(threading.get_ident()))

    app = Starlette(
        routes=[
            Route("/echo", echo_identity),
            Route("/loop-thread", echo_event_loop_thread),
        ]
    )
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


def test_blocking_auth_calls_run_off_the_event_loop():
    """validate()/resolve() do blocking network I/O, so they must not run inline
    on the ASGI event loop thread (I4)."""
    resolved = FakeResolved(upn="alice@example.com", display_name="Alice", object_id="obj-1")
    auth_context = FakeAuthContext(validate_result=object(), resolve_result=resolved)
    client = TestClient(make_app(auth_context))

    response = client.get("/loop-thread", headers={"Authorization": "Bearer good-token"})

    assert response.status_code == 200
    event_loop_thread_id = int(response.text)
    assert auth_context.validate_thread is not None
    assert auth_context.resolve_thread is not None
    assert auth_context.validate_thread.ident != event_loop_thread_id
    assert auth_context.resolve_thread.ident != event_loop_thread_id


def test_exceptions_from_the_worker_thread_still_map_to_401():
    """Exceptions raised inside anyio.to_thread.run_sync must propagate to the
    await site so the existing except clauses keep working."""
    validate_ctx = FakeAuthContext(validate_error=TokenValidationError("thread-side validate boom"))
    validate_response = TestClient(make_app(validate_ctx)).get(
        "/echo", headers={"Authorization": "Bearer t"}
    )
    assert validate_response.status_code == 401
    assert "thread-side validate boom" in validate_response.json()["detail"]
    assert validate_ctx.validate_thread.ident != threading.main_thread().ident

    resolve_ctx = FakeAuthContext(validate_result=object(), resolve_error=OboExchangeError("thread-side obo boom"))
    resolve_response = TestClient(make_app(resolve_ctx)).get("/echo", headers={"Authorization": "Bearer t"})
    assert resolve_response.status_code == 401
    assert "thread-side obo boom" in resolve_response.json()["detail"]


def test_advertised_resource_metadata_url_uses_the_resource_origin_not_its_path():
    """The metadata route lives at the app root, so the advertised URL must not
    carry the resource URL's /mcp path (I1)."""
    auth_context = FakeAuthContext(resource_url="https://wd-func.azurewebsites.net/mcp")
    client = TestClient(make_app(auth_context), base_url="https://wd-func.azurewebsites.net")

    response = client.get("/echo")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == (
        'Bearer resource_metadata="https://wd-func.azurewebsites.net/.well-known/oauth-protected-resource"'
    )
    assert "/mcp/.well-known" not in response.headers["WWW-Authenticate"]


def test_well_known_path_is_not_gated():
    async def metadata(request):
        return PlainTextResponse("public")

    app = Starlette(routes=[Route("/.well-known/oauth-protected-resource", metadata)])
    app.add_middleware(EntraAuthMiddleware, auth_context=FakeAuthContext())
    client = TestClient(app)
    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
