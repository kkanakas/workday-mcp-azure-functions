@description('Name of the API Management instance.')
param apimName string

@description('Azure region.')
param location string = resourceGroup().location

@description('Publisher email for APIM.')
param publisherEmail string

@description('Publisher name for APIM.')
param publisherName string

@description('Backend Function App host name.')
param functionAppHostName string

@description('Function App host key, so calls must go through APIM to reach the Function.')
@secure()
param functionAppHostKey string

@description('Entra ID tenant ID, for the validate-jwt policy.')
param entraTenantId string

@description('Entra ID API audience (client ID of the workday-mcp-api app).')
param entraApiAudience string

resource apim 'Microsoft.ApiManagement/service@2023-05-01-preview' = {
  name: apimName
  location: location
  sku: {
    name: 'Developer'
    capacity: 1
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' = {
  parent: apim
  name: 'workday-mcp'
  properties: {
    displayName: 'Workday MCP Server'
    path: 'workday-mcp'
    protocols: ['https']
    serviceUrl: 'https://${functionAppHostName}'
    subscriptionRequired: false
  }
}

resource wildcardOperation 'Microsoft.ApiManagement/service/apis/operations@2023-05-01-preview' = {
  parent: api
  name: 'proxy-all'
  properties: {
    displayName: 'Proxy all MCP traffic'
    method: '*'
    urlTemplate: '/*'
  }
}

resource apiPolicy 'Microsoft.ApiManagement/service/apis/policies@2023-05-01-preview' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'xml'
    value: format('''
<policies>
  <inbound>
    <base />
    <choose>
      <when condition="@(context.Request.Url.Path.EndsWith("/.well-known/oauth-protected-resource"))">
      </when>
      <otherwise>
        <validate-jwt header-name="Authorization" failed-validation-httpcode="401" require-expiration-time="true" require-signed-tokens="true">
          <openid-config url="https://login.microsoftonline.com/{0}/v2.0/.well-known/openid-configuration" />
          <audiences>
            <audience>{1}</audience>
          </audiences>
          <issuers>
            <issuer>https://login.microsoftonline.com/{0}/v2.0</issuer>
          </issuers>
        </validate-jwt>
      </otherwise>
    </choose>
    <set-header name="x-functions-key" exists-action="override">
      <value>{2}</value>
    </set-header>
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
''', entraTenantId, entraApiAudience, functionAppHostKey)
  }
}

output apimGatewayUrl string = apim.properties.gatewayUrl
