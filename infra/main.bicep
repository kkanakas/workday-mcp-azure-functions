@description('Base name used to derive resource names.')
param baseName string = 'workday-mcp'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Entra ID tenant ID.')
param entraTenantId string

@description('Expected `aud` claim of inbound access tokens. With requestedAccessTokenVersion=2 (see scripts/register-entra-apps.sh) Entra issues the app\'s client ID GUID as the audience, so in the single-app design this is the workday-mcp-api app\'s client ID GUID - not its api:// URI.')
param entraApiAudience string

@description('Client ID of the Entra ID app used as the OBO confidential client. Defaults to entraApiAudience because the single-app design uses one registration for both roles; override to split them.')
param entraClientId string = entraApiAudience

@description('Entra ID API app scope, e.g. api://workday-mcp/access_as_user.')
param entraApiScope string

@description('Public resource URL of the deployed MCP endpoint.')
param mcpResourceUrl string

@description('Workday tenant REST API base URL.')
param workdayTenantBaseUrl string

@description('Workday OAuth2 token URL.')
param workdayTokenUrl string

@description('APIM publisher email.')
param apimPublisherEmail string

@description('APIM publisher name.')
param apimPublisherName string

@description('Function App host key. Empty on first deploy; fetch with `az functionapp keys list` after the Function App exists, then redeploy passing it so APIM can call the Function.')
@secure()
param functionAppHostKey string = ''

// Storage accounts max out at 24 chars (lowercase alphanumeric only) and Key
// Vaults at 24 chars, so these deliberately do NOT embed baseName - only a
// short fixed prefix plus uniqueString() (13 chars today, but keep headroom).
var storageAccountName = toLower('wdmcp${uniqueString(resourceGroup().id)}')
var keyVaultName = 'kv-${uniqueString(resourceGroup().id)}'
var keyVaultUri = 'https://${keyVaultName}.vault.azure.net/'
var functionAppName = '${baseName}-func-${uniqueString(resourceGroup().id)}'
var apimName = '${baseName}-apim-${uniqueString(resourceGroup().id)}'
var appInsightsName = '${baseName}-appi'

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storageDeploy'
  params: {
    storageAccountName: storageAccountName
    location: location
  }
}

module functionApp 'modules/function-app.bicep' = {
  name: 'functionAppDeploy'
  params: {
    functionAppName: functionAppName
    location: location
    storageAccountName: storage.outputs.storageAccountName
    keyVaultUri: keyVaultUri
    appInsightsConnectionString: appInsights.properties.ConnectionString
    entraTenantId: entraTenantId
    entraApiAudience: entraApiAudience
    entraClientId: entraClientId
    entraApiScope: entraApiScope
    mcpResourceUrl: mcpResourceUrl
    workdayTenantBaseUrl: workdayTenantBaseUrl
    workdayTokenUrl: workdayTokenUrl
  }
}

module keyVault 'modules/key-vault.bicep' = {
  name: 'keyVaultDeploy'
  params: {
    keyVaultName: keyVaultName
    location: location
    tenantId: entraTenantId
    functionAppPrincipalId: functionApp.outputs.functionAppPrincipalId
  }
}

module apim 'modules/apim.bicep' = {
  name: 'apimDeploy'
  params: {
    apimName: apimName
    location: location
    publisherEmail: apimPublisherEmail
    publisherName: apimPublisherName
    functionAppHostName: functionApp.outputs.functionAppHostName
    functionAppHostKey: functionAppHostKey
    entraTenantId: entraTenantId
    entraApiAudience: entraApiAudience
  }
}

output functionAppName string = functionApp.outputs.functionAppName
output functionAppHostName string = functionApp.outputs.functionAppHostName
output keyVaultName string = keyVaultName
