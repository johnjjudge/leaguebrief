param name string
param location string
param skuName string = 'Standard'
param tags object = {}
param appSettings object = {}
param linkedBackendResourceId string = ''
param linkedBackendRegion string = ''

resource staticSite 'Microsoft.Web/staticSites@2023-12-01' = {
  name: name
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: skuName
    tier: skuName
  }
  properties: {
    allowConfigFileUpdates: true
  }
  tags: tags
}

resource appSettingsConfig 'Microsoft.Web/staticSites/config@2023-12-01' = {
  parent: staticSite
  name: 'appsettings'
  properties: appSettings
}

resource linkedBackend 'Microsoft.Web/staticSites/linkedBackends@2023-12-01' = if (!empty(linkedBackendResourceId)) {
  parent: staticSite
  name: 'linkedBackend'
  properties: {
    backendResourceId: linkedBackendResourceId
    region: linkedBackendRegion
  }
}

output defaultHostname string = staticSite.properties.defaultHostname
output id string = staticSite.id
output name string = staticSite.name
output principalId string = staticSite.identity.principalId
