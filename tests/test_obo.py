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
