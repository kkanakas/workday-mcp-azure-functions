@description('Name of the Function App.')
param functionAppName string

@description('Azure region.')
param location string = resourceGroup().location

@description('Storage account name used by the Functions runtime.')
param storageAccountName string

@description('Key Vault URI for Key Vault reference app settings.')
param keyVaultUri string

@description('Application Insights connection string.')
param appInsightsConnectionString string

@description('Entra ID tenant ID.')
param entraTenantId string

@description('Expected `aud` claim of inbound access tokens. With requestedAccessTokenVersion=2 (see scripts/register-entra-apps.sh) Entra issues the app\'s client ID GUID as the audience, so in the single-app design this is the same GUID as entraClientId.')
param entraApiAudience string

@description('Client ID of the Entra ID app used as the OBO confidential client. In the single-app design this is the same GUID as entraApiAudience, but it is a distinct setting.')
param entraClientId string

@description('Entra ID API app scope, e.g. api://workday-mcp/access_as_user.')
param entraApiScope string

@description('Public resource URL of the deployed MCP endpoint.')
param mcpResourceUrl string

@description('Workday tenant REST API base URL.')
param workdayTenantBaseUrl string

@description('Workday OAuth2 token URL.')
param workdayTokenUrl string

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

resource hostingPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${functionAppName}-plan'
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: hostingPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'ENTRA_TENANT_ID', value: entraTenantId }
        { name: 'ENTRA_API_AUDIENCE', value: entraApiAudience }
        { name: 'ENTRA_API_SCOPE', value: entraApiScope }
        { name: 'ENTRA_CLIENT_ID', value: entraClientId }
        { name: 'ENTRA_CLIENT_SECRET', value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/entra-client-secret/)' }
        { name: 'MCP_RESOURCE_URL', value: mcpResourceUrl }
        { name: 'WORKDAY_TENANT_BASE_URL', value: workdayTenantBaseUrl }
        { name: 'WORKDAY_TOKEN_URL', value: workdayTokenUrl }
        { name: 'WORKDAY_CLIENT_ID', value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/workday-client-id/)' }
        { name: 'WORKDAY_CLIENT_SECRET', value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/workday-client-secret/)' }
        { name: 'DEV_SKIP_AUTH', value: 'false' }
      ]
    }
  }
}

output functionAppPrincipalId string = functionApp.identity.principalId
output functionAppHostName string = functionApp.properties.defaultHostName
output functionAppName string = functionApp.name
