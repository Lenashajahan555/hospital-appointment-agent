// APIM (Developer tier) fronting an Azure OpenAI deployment.
// The gateway authenticates to Azure OpenAI with its managed identity, so clients
// only ever hold an APIM subscription key.

targetScope = 'resourceGroup'

@description('Globally unique APIM name (becomes <name>.azure-api.net)')
param apimName string

@description('Globally unique Azure OpenAI account name (also its custom subdomain)')
param openAiName string

@description('Publisher email shown in APIM')
param publisherEmail string

param publisherName string = 'Agent Demo'
param location string = resourceGroup().location

@description('Region for Azure OpenAI (must offer the chosen model)')
param openAiLocation string = location

param modelName string = 'gpt-4o-mini'
param modelVersion string = '2024-07-18'
param deploymentName string = 'chat'
param deploymentCapacity int = 30

@description('Per-subscription token budget per minute enforced at the gateway')
param tokensPerMinute int = 20000

// ---------------------------------------------------------------- Azure OpenAI
resource aoai 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: openAiName
  location: openAiLocation
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: openAiName
    publicNetworkAccess: 'Enabled'
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: aoai
  name: deploymentName
  sku: {
    name: 'Standard'
    capacity: deploymentCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

// ------------------------------------------------------------------------ APIM
resource apim 'Microsoft.ApiManagement/service@2023-05-01-preview' = {
  name: apimName
  location: location
  sku: {
    name: 'Developer'
    capacity: 1
  }
  identity: { type: 'SystemAssigned' }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

// APIM managed identity -> "Cognitive Services OpenAI User" on the account
var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
resource apimToAoai 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aoai.id, apim.id, openAiUserRoleId)
  scope: aoai
  properties: {
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
  }
}

resource backend 'Microsoft.ApiManagement/service/backends@2023-05-01-preview' = {
  parent: apim
  name: 'aoai-backend'
  properties: {
    url: '${aoai.properties.endpoint}openai'
    protocol: 'http'
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' = {
  parent: apim
  name: 'azure-openai'
  properties: {
    displayName: 'Azure OpenAI (via APIM)'
    path: 'openai'
    protocols: [ 'https' ]
    subscriptionRequired: true
    // The Azure OpenAI SDK sends the key in the "api-key" header
    subscriptionKeyParameterNames: {
      header: 'api-key'
      query: 'subscription-key'
    }
    serviceUrl: '${aoai.properties.endpoint}openai'
  }
}

resource chatOp 'Microsoft.ApiManagement/service/apis/operations@2023-05-01-preview' = {
  parent: api
  name: 'chat-completions'
  properties: {
    displayName: 'Chat Completions'
    method: 'POST'
    urlTemplate: '/deployments/{deployment-id}/chat/completions'
    templateParameters: [
      {
        name: 'deployment-id'
        type: 'string'
        required: true
      }
    ]
  }
}

var policyTemplate = '''
<policies>
  <inbound>
    <base />
    <set-backend-service backend-id="aoai-backend" />
    <authentication-managed-identity resource="https://cognitiveservices.azure.com" output-token-variable-name="msi-token" ignore-error="false" />
    <set-header name="Authorization" exists-action="override">
      <value>@("Bearer " + (string)context.Variables["msi-token"])</value>
    </set-header>
    <set-header name="api-key" exists-action="delete" />
    <azure-openai-token-limit counter-key="@(context.Subscription.Id)" tokens-per-minute="__TPM__" estimate-prompt-tokens="true" remaining-tokens-header-name="x-remaining-tokens" />
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
</policies>'''

resource apiPolicy 'Microsoft.ApiManagement/service/apis/policies@2023-05-01-preview' = {
  parent: api
  name: 'policy'
  dependsOn: [ backend, apimToAoai ]
  properties: {
    format: 'rawxml'
    value: replace(policyTemplate, '__TPM__', string(tokensPerMinute))
  }
}

// Subscription scoped to this API only (the key the agent uses)
resource agentSub 'Microsoft.ApiManagement/service/subscriptions@2023-05-01-preview' = {
  parent: apim
  name: 'agent-sub'
  dependsOn: [ api ]
  properties: {
    displayName: 'Agent subscription'
    scope: '${apim.id}/apis/${api.name}'
    state: 'active'
  }
}

output gatewayUrl string = apim.properties.gatewayUrl
output apimName string = apim.name
output deploymentName string = chat.name
output openAiEndpoint string = aoai.properties.endpoint
output tokensPerMinute int = tokensPerMinute
