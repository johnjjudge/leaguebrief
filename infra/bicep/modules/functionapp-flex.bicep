param name string
param planName string
param location string
param runtimeName string = 'python'
param runtimeVersion string = '3.12'
param instanceMemoryMb int = 2048
param maximumInstanceCount int = 50
param httpPerInstanceConcurrency int = 20
param alwaysReadyHttpInstances int = 0
param managePlan bool = true
param tags object = {}
param appSettings object = {}
param deploymentStorageContainerUrl string
param deploymentStorageConnectionStringSettingName string = 'AzureWebJobsStorage'

resource plan 'Microsoft.Web/serverfarms@2024-11-01' = if (managePlan) {
  name: planName
  location: location
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    elasticScaleEnabled: true
    reserved: true
  }
  tags: tags
}

resource existingPlan 'Microsoft.Web/serverfarms@2024-11-01' existing = if (!managePlan) {
  name: planName
}

var effectiveScaleAndConcurrency = alwaysReadyHttpInstances > 0
  ? {
      alwaysReady: [
        {
          instanceCount: alwaysReadyHttpInstances
          name: 'http'
        }
      ]
      instanceMemoryMB: instanceMemoryMb
      maximumInstanceCount: maximumInstanceCount
      triggers: {
        http: {
          perInstanceConcurrency: httpPerInstanceConcurrency
        }
      }
    }
  : {
      instanceMemoryMB: instanceMemoryMb
      maximumInstanceCount: maximumInstanceCount
      triggers: {
        http: {
          perInstanceConcurrency: httpPerInstanceConcurrency
        }
      }
    }

resource functionApp 'Microsoft.Web/sites@2024-11-01' = {
  name: name
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
    serverFarmId: managePlan ? plan.id : existingPlan.id
    functionAppConfig: {
      deployment: {
        storage: {
          authentication: {
            storageAccountConnectionStringName: deploymentStorageConnectionStringSettingName
            type: 'StorageAccountConnectionString'
          }
          type: 'blobContainer'
          value: deploymentStorageContainerUrl
        }
      }
      runtime: {
        name: runtimeName
        version: runtimeVersion
      }
      scaleAndConcurrency: effectiveScaleAndConcurrency
    }
    siteConfig: {
      appSettings: [for setting in items(appSettings): {
        name: setting.key
        value: string(setting.value)
      }]
      ftpsState: 'Disabled'
      http20Enabled: true
      minTlsVersion: '1.2'
    }
  }
  tags: tags
}

output defaultHostName string = functionApp.properties.defaultHostName
output id string = functionApp.id
output name string = functionApp.name
output principalId string = functionApp.identity.principalId
output planId string = managePlan ? plan.id : existingPlan.id
