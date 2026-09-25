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

```bash
./scripts/register-entra-apps.sh workday-mcp-api workday-mcp-client
```

This creates the `workday-mcp-api` app registration (exposes the
`access_as_user` scope, requests delegated `User.Read` on Microsoft Graph for
the OBO step, and creates a client secret), and optionally a client app
registration pre-authorized for that scope. A tenant admin must grant admin
consent using the `az ad app permission admin-consent` commands printed by
the script.

## 3. Local development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp local.settings.json.example local.settings.json
# fill in local.settings.json with the values from steps 1-2
func start
```

With `DEV_SKIP_AUTH=true` in `local.settings.json`, requests are treated as
an authenticated dev user without a real Entra ID token, so tools can be
exercised locally without a live OAuth flow.

## 4. Tests

```bash
pytest
```

All tests run offline — Graph and Workday HTTP calls are mocked.

## 5. Deploy infrastructure

```bash
az deployment group create \
  --resource-group <your-resource-group> \
  --template-file infra/main.bicep \
  --parameters entraTenantId=<tenant-id> \
               entraApiAudience=<workday-mcp-api-app-id> \
               entraClientId=<workday-mcp-api-app-id> \
               entraApiScope=api://<workday-mcp-api-app-id>/access_as_user \
               mcpResourceUrl=https://<function-app-host>/mcp \
               workdayTenantBaseUrl=<workday-rest-base-url> \
               workdayTokenUrl=<workday-oauth2-token-url> \
               apimPublisherEmail=<you@example.com> \
               apimPublisherName="<Your Org>"
```

`entraApiAudience` is the **client ID GUID** of the `workday-mcp-api` app, not
its `api://` URI: the registration requests v2 access tokens
(`requestedAccessTokenVersion: 2`), and v2 tokens carry the client ID GUID in
`aud`. `entraClientId` is the client ID used for the OBO confidential-client
flow; in this single-app design it is the same GUID, and it defaults to
`entraApiAudience` if omitted.

APIM's policy needs the deployed Function App's host key to call it directly.
After the first deploy, fetch it and redeploy so APIM can present it:

```bash
FUNCTION_KEY=$(az functionapp keys list \
  --resource-group <your-resource-group> \
  --name <function-app-name> \
  --query functionKeys.default -o tsv)

az deployment group create \
  --resource-group <your-resource-group> \
  --template-file infra/main.bicep \
  --parameters @<same params as above> functionAppHostKey="${FUNCTION_KEY}"
```

### Host header allow-list

The MCP streamable-HTTP transport enforces DNS-rebinding protection, which only
accepts requests whose `Host` header is on an allow-list. By default the server
allows the host of `MCP_RESOURCE_URL` (plus loopback addresses for local dev),
so keep `mcpResourceUrl` pointed at the host that actually receives the
request — APIM forwards to the Function App with the Function App's host name.
If the public resource URL and the receiving host differ, set the
`MCP_ALLOWED_HOSTS` app setting to a comma-separated list of the `Host` values
to accept; anything else gets HTTP 421.

Store the Entra client secret and Workday client ID/secret in the deployed
Key Vault under the secret names referenced by
`infra/modules/function-app.bicep` (`entra-client-secret`,
`workday-client-id`, `workday-client-secret`):

```bash
az keyvault secret set --vault-name <kv-name> --name entra-client-secret --value "<...>"
az keyvault secret set --vault-name <kv-name> --name workday-client-id --value "<...>"
az keyvault secret set --vault-name <kv-name> --name workday-client-secret --value "<...>"
```

## 6. Deploy application code

```bash
func azure functionapp publish <function-app-name>
```
