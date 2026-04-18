param name string
param location string
param tenantId string
param tags object = {}
param enablePurgeProtection bool = false

resource vault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: name
  location: location
  properties: {
    accessPolicies: []
    enablePurgeProtection: enablePurgeProtection
    enableRbacAuthorization: false
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    publicNetworkAccess: 'Enabled'
    sku: {
      family: 'A'
      name: 'standard'
    }
    softDeleteRetentionInDays: 90
    tenantId: tenantId
  }
  tags: tags
}

output id string = vault.id
output name string = vault.name
output vaultUri string = vault.properties.vaultUri
