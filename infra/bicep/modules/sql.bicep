param name string
param location string
param tags object = {}
param administratorLogin string
@secure()
param administratorPassword string
param tenantId string
param entraAdminLogin string
param entraAdminObjectId string
param databaseName string
param skuName string = 'GP_S_Gen5_1'
param skuTier string = 'GeneralPurpose'
param skuFamily string = 'Gen5'
param skuCapacity int = 1
param minCapacity int = 1
param autoPauseDelayMinutes int = 60
param maxSizeBytes int = 34359738368
param allowAzureServices bool = true
param azureAdOnlyAuthentication bool = false

resource sqlServer 'Microsoft.Sql/servers@2024-11-01-preview' = {
  name: name
  location: location
  properties: {
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    version: '12.0'
  }
  tags: tags
}

resource sqlServerAadAdmin 'Microsoft.Sql/servers/administrators@2024-11-01-preview' = {
  parent: sqlServer
  name: 'ActiveDirectory'
  properties: {
    administratorType: 'ActiveDirectory'
    login: entraAdminLogin
    sid: entraAdminObjectId
    tenantId: tenantId
  }
}

resource sqlAadOnlyAuth 'Microsoft.Sql/servers/azureADOnlyAuthentications@2024-11-01-preview' = if (azureAdOnlyAuthentication) {
  parent: sqlServer
  name: 'Default'
  properties: {
    azureADOnlyAuthentication: azureAdOnlyAuthentication
  }
}

resource database 'Microsoft.Sql/servers/databases@2024-11-01-preview' = {
  parent: sqlServer
  name: databaseName
  location: location
  sku: {
    name: skuName
    tier: skuTier
    family: skuFamily
    capacity: skuCapacity
  }
  properties: {
    autoPauseDelay: autoPauseDelayMinutes
    collation: 'SQL_Latin1_General_CP1_CI_AS'
    maxSizeBytes: maxSizeBytes
    minCapacity: minCapacity
    readScale: 'Disabled'
    requestedBackupStorageRedundancy: 'Local'
  }
}

resource allowAzureServicesRule 'Microsoft.Sql/servers/firewallRules@2024-11-01-preview' = if (allowAzureServices) {
  parent: sqlServer
  name: 'AllowAzureServices'
  properties: {
    endIpAddress: '0.0.0.0'
    startIpAddress: '0.0.0.0'
  }
}

output databaseName string = database.name
output serverFullyQualifiedDomainName string = sqlServer.properties.fullyQualifiedDomainName
output serverId string = sqlServer.id
output serverName string = sqlServer.name
