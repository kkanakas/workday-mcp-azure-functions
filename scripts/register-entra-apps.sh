#!/usr/bin/env bash
set -euo pipefail

# Creates the Entra ID app registration for the workday-mcp API, exposes the
# access_as_user scope, and adds the delegated Microsoft Graph User.Read
# permission needed for the OBO identity-resolution step. Optionally also
# creates a client app registration pre-authorized for that scope.
#
# Requires: az cli, logged in (`az login`) with Application Administrator
# or Global Administrator rights.
#
# Usage:
#   ./scripts/register-entra-apps.sh <api-app-display-name> [client-app-display-name]
#
# Example:
#   ./scripts/register-entra-apps.sh workday-mcp-api workday-mcp-client

API_APP_NAME="${1:?Usage: $0 <api-app-display-name> [client-app-display-name]}"
CLIENT_APP_NAME="${2:-}"

GRAPH_USER_READ_SCOPE_ID="e1fe6dd8-ba31-4d61-89e7-88639da4683d" # Microsoft Graph User.Read
GRAPH_RESOURCE_APP_ID="00000003-0000-0000-c000-000000000000"   # Microsoft Graph

echo "Creating API app registration: ${API_APP_NAME}"
API_APP_ID=$(az ad app create \
  --display-name "${API_APP_NAME}" \
  --sign-in-audience AzureADMyOrg \
  --query appId -o tsv)

echo "API app created: appId=${API_APP_ID}"

az ad app update --id "${API_APP_ID}" --identifier-uris "api://${API_APP_ID}"

SCOPE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")

az ad app update --id "${API_APP_ID}" --set api="{
  \"oauth2PermissionScopes\": [
    {
      \"id\": \"${SCOPE_ID}\",
      \"adminConsentDescription\": \"Allow the app to call workday-mcp on behalf of the signed-in user.\",
      \"adminConsentDisplayName\": \"Access workday-mcp as the signed-in user\",
      \"userConsentDescription\": \"Allow the app to access workday-mcp on your behalf.\",
      \"userConsentDisplayName\": \"Access workday-mcp\",
      \"value\": \"access_as_user\",
      \"type\": \"User\",
      \"isEnabled\": true
    }
  ]
}"

echo "Exposed scope api://${API_APP_ID}/access_as_user"

echo "Adding delegated Microsoft Graph User.Read permission"
az ad app permission add \
  --id "${API_APP_ID}" \
  --api "${GRAPH_RESOURCE_APP_ID}" \
  --api-permissions "${GRAPH_USER_READ_SCOPE_ID}=Scope"

echo "Creating client secret (used as the confidential client for the OBO flow)"
CLIENT_SECRET=$(az ad app credential reset \
  --id "${API_APP_ID}" \
  --display-name "workday-mcp-obo-secret" \
  --years 1 \
  --query password -o tsv)

echo ""
echo "=== API app registration complete ==="
echo "ENTRA_CLIENT_ID (=ENTRA_API_AUDIENCE): ${API_APP_ID}"
echo "ENTRA_API_SCOPE: api://${API_APP_ID}/access_as_user"
echo "ENTRA_CLIENT_SECRET: ${CLIENT_SECRET}"
echo ""
echo "NOTE: a tenant admin must still grant admin consent for User.Read:"
echo "  az ad app permission admin-consent --id ${API_APP_ID}"
echo ""

if [[ -n "${CLIENT_APP_NAME}" ]]; then
  echo "Creating client app registration: ${CLIENT_APP_NAME}"
  CLIENT_APP_ID=$(az ad app create \
    --display-name "${CLIENT_APP_NAME}" \
    --sign-in-audience AzureADMyOrg \
    --query appId -o tsv)

  az ad app permission add \
    --id "${CLIENT_APP_ID}" \
    --api "${API_APP_ID}" \
    --api-permissions "${SCOPE_ID}=Scope"

  echo "=== Client app registration complete ==="
  echo "CLIENT_APP_ID: ${CLIENT_APP_ID}"
  echo ""
  echo "NOTE: a tenant admin must still grant admin consent for the client's access to workday-mcp:"
  echo "  az ad app permission admin-consent --id ${CLIENT_APP_ID}"
fi
