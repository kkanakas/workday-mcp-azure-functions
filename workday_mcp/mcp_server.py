# workday_mcp/mcp_server.py
from __future__ import annotations

import os
from urllib.parse import urlsplit

import anyio.to_thread
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
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

        if self.dev_skip_auth:
            # In dev-skip mode, EntraAuthMiddleware.dispatch never touches
            # self.validator/self.obo_resolver, so avoid eagerly building
            # them: MSAL's ConfidentialClientApplication performs a live
            # network call to validate the tenant authority at construction
            # time (regardless of validate_authority/instance_discovery
            # flags), which would require a real Entra tenant to be
            # reachable just to boot the server locally.
            self.validator = None
            self.obo_resolver = None
        else:
            self.validator = EntraTokenValidator(tenant_id=tenant_id, audience=api_audience)
            msal_app = build_msal_confidential_app(tenant_id, client_id, client_secret)
            self.obo_resolver = GraphOboResolver(msal_app)


# Loopback Host/Origin values the MCP SDK allows by default; kept so local
# `func start` / health probes keep working alongside the deployed host.
_LOOPBACK_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
_LOOPBACK_ORIGINS = ("http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*")


def resolve_allowed_hosts(resource_url: str) -> list[str]:
    """Host header values the MCP transport should accept.

    The SDK's DNS-rebinding protection only allows loopback hosts by default,
    which makes every request to a real Azure Functions hostname return HTTP
    421. MCP_ALLOWED_HOSTS (comma-separated) overrides; otherwise the host of
    MCP_RESOURCE_URL is used.
    """
    configured = [host.strip() for host in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if host.strip()]
    if not configured:
        netloc = urlsplit(resource_url).netloc
        configured = [netloc] if netloc else []

    hosts: list[str] = []
    for host in configured:
        candidates = [host]
        if ":" not in host:
            # Also accept the same host with any explicit port (e.g. :443).
            candidates.append(f"{host}:*")
        for candidate in candidates:
            if candidate not in hosts:
                hosts.append(candidate)

    for loopback in _LOOPBACK_HOSTS:
        if loopback not in hosts:
            hosts.append(loopback)
    return hosts


def build_transport_security(resource_url: str) -> TransportSecuritySettings:
    """DNS-rebinding protection kept ON, but with the real host allowed."""
    hosts = resolve_allowed_hosts(resource_url)
    origins: list[str] = []
    for host in hosts:
        for origin in (f"https://{host}", f"http://{host}"):
            if origin not in origins:
                origins.append(origin)
    for origin in _LOOPBACK_ORIGINS:
        if origin not in origins:
            origins.append(origin)

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def build_workday_client() -> WorkdayClient:
    return WorkdayClient(
        tenant_base_url=os.environ["WORKDAY_TENANT_BASE_URL"],
        token_url=os.environ["WORKDAY_TOKEN_URL"],
        client_id=os.environ["WORKDAY_CLIENT_ID"],
        client_secret=os.environ["WORKDAY_CLIENT_SECRET"],
    )


PROTECTED_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"


def protected_resource_metadata_url(resource_url: str) -> str:
    """Absolute URL of the metadata document, derived from resource_url's origin.

    `resource_url` identifies the protected resource and may carry a path (e.g.
    `https://host/mcp`), but the metadata route lives at the app root, so only
    the scheme+host are reused.
    """
    parts = urlsplit(resource_url)
    return f"{parts.scheme}://{parts.netloc}{PROTECTED_RESOURCE_METADATA_PATH}"


class EntraAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_context: AuthContext):
        super().__init__(app)
        self._auth = auth_context

    async def dispatch(self, request: Request, call_next):
        if request.url.path == PROTECTED_RESOURCE_METADATA_PATH:
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

        # Both calls do blocking network I/O (JWKS fetch; MSAL + httpx call to
        # Graph), so they must not run inline on the ASGI event loop.
        try:
            await anyio.to_thread.run_sync(self._auth.validator.validate, raw_token)
        except TokenValidationError as exc:
            return self._unauthorized(str(exc))

        try:
            resolved = await anyio.to_thread.run_sync(self._auth.obo_resolver.resolve, raw_token)
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
            headers={"WWW-Authenticate": f'Bearer resource_metadata="{self.resource_metadata_url}"'},
        )

    @property
    def resource_metadata_url(self) -> str:
        """Where the protected-resource metadata document is actually served.

        The route is registered at the app root, not under the resource URL's
        path (e.g. `/mcp`), so advertise the origin of resource_url only.
        """
        return protected_resource_metadata_url(self._auth.resource_url)


def build_mcp_app(auth_context: AuthContext | None = None, workday_client: WorkdayClient | None = None):
    auth_context = auth_context or AuthContext()
    client = workday_client or build_workday_client()

    mcp = MCPServer("workday-mcp")

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

    @mcp.custom_route(PROTECTED_RESOURCE_METADATA_PATH, methods=["GET"])
    async def protected_resource_metadata(request):
        return JSONResponse(
            build_protected_resource_metadata(
                resource_url=auth_context.resource_url,
                tenant_id=auth_context.tenant_id,
                scope=auth_context.scope,
            )
        )

    # Without explicit transport_security the SDK auto-enables DNS-rebinding
    # protection with a loopback-only Host allow-list, which 421s every request
    # to a real Azure Functions hostname.
    app = mcp.streamable_http_app(transport_security=build_transport_security(auth_context.resource_url))
    app.add_middleware(EntraAuthMiddleware, auth_context=auth_context)
    return app
