param name string
param location string
param skuName string = 'Standard'
param publicNetworkAccess string = 'Enabled'
param stagingEnvironmentPolicy string = 'Enabled'
param tags object = {}
param appSettings object = {}

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

output defaultHostname string = staticSite.properties.defaultHostname
output id string = staticSite.id
output name string = staticSite.name
output principalId string = staticSite.identity.principalId
