# workday-mcp Design Spec

Date: 2026-09-24
Status: Approved for planning

## 1. Purpose

Build a Python MCP (Model Context Protocol) server, hosted on Azure Functions,
that exposes a small set of Workday HR read tools to MCP clients. The server:

- Registers as an API behind Azure API Management (APIM).
- Authenticates inbound calls using OAuth 2.0 / Microsoft Entra ID.
- Uses the OAuth On-Behalf-Of (OBO) flow to resolve the caller's verified
  identity via Microsoft Graph.
- Calls Workday's own REST API using Workday's independently-configured
  OAuth 2.0 client-credentials grant (Integration System User), scoped
  per-request by the identity resolved via OBO.

## 2. Key Architectural Decision: Two Separate OAuth Relationships

Workday does not accept Microsoft Entra ID access tokens. It issues its own
OAuth 2.0 clients, typically bound to an Integration System User (ISU) using
the client-credentials grant. This means there is no single token handoff
from "user signs into Entra ID" all the way through to "Workday authorizes
the call" — that would only be possible if Workday were explicitly federated
to accept externally-issued tokens, which is not being assumed here.

Instead, this design uses two distinct, independently-configured OAuth
relationships:

1. **Inbound (Entra ID)** — authenticates and authorizes the call to the MCP
   server itself. The bearer token's audience is the `workday-mcp-api` Entra
   ID app registration. This is where OAuth/Entra ID auth and OBO apply.
2. **Outbound to Workday (Workday-native)** — the Function calls Workday's
   REST API using a client-credentials token obtained from Workday's own
   OAuth server, using an Integration System User. This is a service-level
   credential, not a per-user delegated token.

The OBO flow exchanges the inbound Entra ID user token for a Microsoft Graph
token (`User.Read` scope) to reliably resolve the caller's UPN/email from a
trusted source (rather than trusting unsigned claims in the raw token). That
resolved identity is then passed to Workday as a request parameter, so
Workday-side results are scoped to that specific worker even though the
Workday call itself is authenticated as the ISU.

## 3. Request Flow

```
MCP Client
   │  Authorization: Bearer <Entra ID access token>, aud=api://workday-mcp
   ▼
Azure API Management
   │  policy: validate-jwt (issuer, audience, signature via Entra ID OIDC metadata)
   │  policy: inject Function host key for backend
   ▼
Azure Function App (Python, FastMCP over ASGI, streamable HTTP transport)
   │  1. Re-validate bearer JWT (PyJWT + cached JWKS) — defense in depth
   │  2. MSAL ConfidentialClientApplication.acquire_token_on_behalf_of(
   │       user_token, scopes=["User.Read"]) → Graph token
   │  3. Call Graph /me with that token → resolve UPN/email
   │  4. Acquire (cached) Workday client-credentials token (ISU)
   │  5. Call Workday REST API, scoped by resolved UPN/email
   │  6. Return MCP tool result
   ▼
Workday REST API
```

## 4. Entra ID App Registrations

1. `workday-mcp-api` — the resource app registration.
   - Exposes API scope `access_as_user` (Application ID URI `api://workday-mcp`).
   - Has a client secret (stored in Key Vault) so it can act as a confidential
     client for the OBO flow.
   - Requires delegated Graph permission `User.Read`, with admin consent granted.
2. MCP client registration — whatever app registration the calling MCP client
   uses to acquire tokens for the `access_as_user` scope. A helper script is
   provided to create one if you don't already have a client registration to
   reuse; otherwise point your existing client at this API's scope.

Entra ID app registrations are an identity-plane resource, not part of ARM/
Bicep — they are created via an `az ad app` / `az cli` script
(`scripts/register-entra-apps.sh`), not the Bicep templates.

## 5. Workday-Side Setup (manual, outside Azure)

Documented in `README.md`, not automated (outside Azure's control plane):

1. Create an Integration System User (ISU) in Workday with the minimum
   security group access needed for the read operations the tools perform.
2. Register an OAuth 2.0 API Client in Workday configured for the
   client-credentials grant, bound to that ISU.
3. Record the Workday tenant's REST API base URL, client ID, and client
   secret — these go into Key Vault (see §7), referenced by the Function App.

## 6. MCP Tools (initial set)

Implemented under `src/workday_mcp/tools/`, each a thin wrapper that calls
`workday/client.py`:

- `get_worker` — fetch a single worker's profile by ID or resolved identity.
- `search_workers` — search workers by name/criteria.
- `get_worker_time_off` — fetch a worker's time-off/absence records.
- `get_organization` — fetch org/team structure for a worker or org ID.

Each tool receives the OBO-resolved UPN/email from the request context and
uses it to scope the Workday query. Tools do not accept a caller-supplied
"act as this worker" override — the identity comes only from the validated
token, to avoid privilege-escalation via a spoofed parameter.

## 7. Infrastructure (Bicep)

`infra/main.bicep` composing modules:

- **Storage account** — required by Azure Functions runtime.
- **Function App** (Python, Linux, Consumption or Flex Consumption plan) with
  Application Insights, system-assigned managed identity.
- **Key Vault** — stores the Entra ID client secret and Workday client
  ID/secret. Function App's managed identity is granted the `Key Vault
  Secrets User` role; app settings use `@Microsoft.KeyVault(...)` references
  — no plaintext secrets in app settings.
- **API Management** — API definition fronting the Function App, with a
  `validate-jwt` inbound policy checking the Entra ID token, and a policy
  injecting the Function's host key so direct-to-Function calls (bypassing
  APIM) are not possible without also holding that key.

Parameters file (`infra/main.bicepparam` or `.parameters.json`) for
environment-specific values (tenant ID, Entra app IDs, Workday tenant name,
resource naming).

## 8. Repository Layout

```
workday-mcp/
├── README.md
├── .gitignore
├── host.json
├── requirements.txt
├── local.settings.json.example
├── src/workday_mcp/
│   ├── function_app.py            # Azure Functions entry point, AsgiMiddleware(FastMCP app)
│   ├── mcp_server.py              # FastMCP app instance + tool registration
│   ├── auth/
│   │   ├── jwt_validator.py       # PyJWT + JWKS-cached bearer validation
│   │   ├── obo.py                 # MSAL OBO exchange → Graph token → resolved identity
│   │   └── protected_resource_metadata.py  # /.well-known/oauth-protected-resource
│   ├── workday/
│   │   ├── client.py              # Workday REST client, ISU client-credentials token cache
│   │   └── models.py              # response models
│   └── tools/
│       ├── get_worker.py
│       ├── search_workers.py
│       ├── get_worker_time_off.py
│       └── get_organization.py
├── tests/
│   ├── test_jwt_validator.py
│   ├── test_obo.py
│   ├── test_workday_client.py
│   └── test_tools.py
├── infra/
│   ├── main.bicep
│   └── modules/
│       ├── function-app.bicep
│       ├── apim.bicep
│       ├── key-vault.bicep
│       └── storage.bicep
└── scripts/
    └── register-entra-apps.sh
```

## 9. MCP Transport

`mcp` Python SDK's `FastMCP`, run with the streamable-HTTP ASGI transport,
mounted into the Azure Functions Python v2 programming model via
`azure.functions.AsgiMiddleware`, exposed through a single HTTP trigger
route. This is standards-compliant (works with any MCP client speaking
streamable HTTP), fully testable locally with `func start`, and keeps all
auth logic in plain Python middleware rather than depending on Functions'
platform-level Easy Auth (which is harder to unit test and less flexible for
the OBO + Graph identity-resolution step this design needs).

## 10. Testing & Local Dev

- `func start` runs the Function App locally.
- A local-only dev flag (`DEV_SKIP_AUTH=true` in `local.settings.json`, never
  set in deployed environments) bypasses JWT validation so tools can be
  exercised without a live Entra ID token during development.
- `pytest` unit tests mock Graph and Workday HTTP calls (no live network
  calls in tests).

## 11. Out of Scope (this spec)

- Write operations against Workday (this initial scope is read-only tools).
- Per-user Workday OAuth (Authorization Code) — deferred; client-credentials/
  ISU is the chosen model per design decision in §2.
- CI/CD pipeline — not requested; can be added as a follow-up.
- Automated Entra ID admin consent — the script issues the `az ad app
  permission grant`/admin-consent commands, but tenant admin approval is a
  manual step outside this repo's control.

## 12. GitHub Repository

`git init`, initial commit of the scaffold, then `gh repo create workday-mcp
--private --source=. --push` to create and push a private GitHub remote.
