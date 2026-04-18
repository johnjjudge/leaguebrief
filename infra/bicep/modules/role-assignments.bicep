param storageAccountName string
param keyVaultName string
param tenantId string
param keyVaultAdministratorObjectId string
param staticWebAppPrincipalId string
param functionPrincipalIds array

resource storageAccount 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: storageAccountName
}

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultName
}

var storageBlobDataContributorRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var storageQueueDataContributorRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '974c5e8b-45b9-4653-ba55-5f855dd0fb88')

resource blobRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in functionPrincipalIds: {
  name: guid(storageAccount.id, principalId, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataContributorRoleId
  }
}]

resource queueRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in functionPrincipalIds: {
  name: guid(storageAccount.id, principalId, storageQueueDataContributorRoleId)
  scope: storageAccount
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageQueueDataContributorRoleId
  }
}]

var baseAccessPolicies = [
  {
    objectId: keyVaultAdministratorObjectId
    permissions: {
      certificates: []
      keys: []
      secrets: [
        'Get'
        'List'
        'Set'
        'Delete'
        'Recover'
        'Purge'
      ]
      storage: []
    }
    tenantId: tenantId
  }
  {
    objectId: staticWebAppPrincipalId
    permissions: {
      certificates: []
      keys: []
      secrets: [
        'Get'
        'List'
      ]
      storage: []
    }
    tenantId: tenantId
  }
]

var functionAccessPolicies = [for principalId in functionPrincipalIds: {
  objectId: principalId
  permissions: {
    certificates: []
    keys: []
    secrets: [
      'Get'
      'List'
    ]
    storage: []
  }
  tenantId: tenantId
}]

var accessPolicies = concat(baseAccessPolicies, functionAccessPolicies)

resource keyVaultAccessPolicies 'Microsoft.KeyVault/vaults/accessPolicies@2024-11-01' = {
  parent: keyVault
  name: 'add'
  properties: {
    accessPolicies: accessPolicies
  }
}
