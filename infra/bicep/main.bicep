targetScope = 'resourceGroup'

@description('Short environment name used in resource tags and names.')
param environmentName string

@description('Azure region for regional resources.')
param location string = resourceGroup().location

@description('Resource name prefix. Keep this short to avoid Azure name-length limits.')
param namePrefix string

@description('Tags applied to all supported resources.')
param tags object = {}

@description('Whether to create and attach a public custom domain on Front Door.')
param enableCustomDomain bool = false

@description('Public host name served by Front Door when custom domains are enabled.')
param publicHostName string = ''

@description('Whether Azure DNS is expected to manage the Front Door custom domain.')
param manageDnsInAzure bool = false

@description('Optional Azure DNS zone resource ID used for Front Door custom-domain onboarding.')
param dnsZoneResourceId string = ''

@allowed([
  'Premium_AzureFrontDoor'
])
@description('Front Door SKU. Premium is required for managed WAF rules and bot protection.')
param frontDoorSku string = 'Premium_AzureFrontDoor'

@allowed([
  'Detection'
  'Prevention'
])
@description('Front Door WAF policy mode.')
param frontDoorWafMode string = 'Detection'

@description('Managed rule set version for Front Door WAF.')
param frontDoorDefaultRuleSetVersion string = '1.1'

@description('Bot Manager rule set version for Front Door WAF.')
param frontDoorBotManagerVersion string = '1.0'

@minValue(1)
@description('Per-client request threshold for the /api/* rate-limit WAF rule.')
param frontDoorApiRateLimitThreshold int = 600

@minValue(1)
@description('Rate-limit window in minutes for the /api/* WAF rule.')
param frontDoorApiRateLimitDurationMinutes int = 1

@allowed([
  'Standard'
])
@description('Static Web Apps SKU.')
param staticWebAppSku string = 'Standard'

@description('Azure region for the Static Web App. This may need to differ from the main workload region.')
param staticWebAppLocation string = 'westus2'

@allowed([
  'Enabled'
  'Disabled'
])
@description('Public network access for the Static Web App.')
param staticWebAppPublicNetworkAccess string = 'Enabled'

@allowed([
  'Enabled'
  'Disabled'
])
@description('Staging environment policy for the Static Web App.')
param staticWebAppStagingPolicy string = 'Enabled'

@description('Function runtime name for both Function Apps.')
param functionRuntimeName string = 'python'

@description('Function runtime version for both Function Apps.')
param functionRuntimeVersion string = '3.12'

@description('Azure region for Function Apps and Flex Consumption plans.')
param functionAppLocation string = resourceGroup().location

@minValue(512)
@description('Flex Consumption memory size per instance, in MB.')
param functionInstanceMemoryMb int = 2048

@minValue(40)
@description('Maximum elastic scale-out instance count per Function App.')
param functionMaximumInstanceCount int = 50

@minValue(1)
@description('HTTP concurrency per API Function App instance.')
param apiHttpPerInstanceConcurrency int = 20

@minValue(0)
@description('Optional always-ready HTTP instances for the API Function App.')
param apiAlwaysReadyInstances int = 0

@minValue(0)
@description('Optional always-ready instances for the worker Function App.')
param workerAlwaysReadyInstances int = 0

@description('Blob containers created in the shared Storage Account.')
param storageBlobContainerNames array = [
  'raw-espn'
  'fantasypros-source'
  'exports'
  'job-artifacts'
]

@description('Queues created in the shared Storage Account.')
param storageQueueNames array = [
  'import-jobs'
]

@description('SQL administrator username used for bootstrap SQL auth operations.')
param sqlAdministratorLogin string

@secure()
@description('SQL administrator password used for bootstrap SQL auth operations. Override this at deploy time.')
param sqlAdministratorPassword string = ''

@description('Microsoft Entra login name configured as the logical server administrator.')
param sqlEntraAdminLogin string

@description('Microsoft Entra object ID configured as the logical server administrator.')
param sqlEntraAdminObjectId string

@description('Microsoft Entra object ID that should have secret-management access in Key Vault.')
param keyVaultAdministratorObjectId string

@description('Tenant ID used for Key Vault and Azure SQL AAD administrator configuration.')
param tenantId string = subscription().tenantId

@description('Primary database name.')
param sqlDatabaseName string = 'leaguebrief'

@description('Serverless Azure SQL SKU name.')
param sqlSkuName string = 'GP_S_Gen5_1'

@description('Azure SQL SKU tier.')
param sqlSkuTier string = 'GeneralPurpose'

@description('Azure SQL SKU family.')
param sqlSkuFamily string = 'Gen5'

@minValue(1)
@description('Azure SQL serverless SKU capacity.')
param sqlSkuCapacity int = 1

@minValue(1)
@description('Minimum serverless compute capacity.')
param sqlMinCapacity int = 1

@minValue(60)
@description('Auto-pause delay for Azure SQL serverless, in minutes.')
param sqlAutoPauseDelayMinutes int = 60

@minValue(2147483648)
@description('Maximum database size in bytes.')
param sqlMaxSizeBytes int = 34359738368

@description('Whether the SQL logical server should create the AllowAzureServices firewall rule.')
param sqlAllowAzureServices bool = true

@description('Whether Azure SQL should enforce Azure AD-only authentication.')
param sqlAzureAdOnlyAuthentication bool = false

@description('Retention period for the Log Analytics workspace.')
param logAnalyticsRetentionInDays int = 30

@description('Whether purge protection is enabled on Key Vault.')
param keyVaultEnablePurgeProtection bool = false

@description('Key Vault secret name for the bootstrap SQL administrator password.')
param sqlAdminPasswordSecretName string = 'sql-admin-password'

@description('Key Vault secret name for the Google OAuth client ID.')
param googleClientIdSecretName string = 'google-client-id'

@description('Key Vault secret name for the Google OAuth client secret.')
param googleClientSecretSecretName string = 'google-client-secret'

@description('Key Vault secret name for the Microsoft OAuth client ID.')
param microsoftClientIdSecretName string = 'microsoft-client-id'

@description('Key Vault secret name for the Microsoft OAuth client secret.')
param microsoftClientSecretSecretName string = 'microsoft-client-secret'

@description('Key Vault secret name for the Microsoft OAuth tenant ID.')
param microsoftTenantIdSecretName string = 'microsoft-tenant-id'

var mergedTags = union(tags, {
  environment: environmentName
  managedBy: 'bicep'
  project: 'LeagueBrief'
})

var safePrefix = toLower(replace(replace(namePrefix, '-', ''), '_', ''))
var safeEnvironment = toLower(replace(replace(environmentName, '-', ''), '_', ''))
var uniqueToken = substring(uniqueString(subscription().subscriptionId, resourceGroup().id, environmentName, namePrefix), 0, 6)
var shortPrefix = take('${safePrefix}${safeEnvironment}', 11)

var storageAccountName = take('${shortPrefix}st${uniqueToken}', 24)
var keyVaultName = take('${shortPrefix}kv${uniqueToken}', 24)
var sqlServerName = take('${shortPrefix}sql${uniqueToken}', 63)
var logAnalyticsName = '${namePrefix}-${environmentName}-logs'
var appInsightsName = '${namePrefix}-${environmentName}-appi'
var staticWebAppName = '${namePrefix}-${environmentName}-web-${uniqueToken}'
var apiFunctionAppName = '${namePrefix}-${environmentName}-api-${uniqueToken}'
var apiFunctionPlanName = '${namePrefix}-${environmentName}-api-plan-${uniqueToken}'
var workerFunctionAppName = '${namePrefix}-${environmentName}-worker-${uniqueToken}'
var workerFunctionPlanName = '${namePrefix}-${environmentName}-worker-plan-${uniqueToken}'
var frontDoorProfileName = '${namePrefix}-${environmentName}-fd'
var frontDoorEndpointName = '${namePrefix}-${environmentName}-edge'
var frontDoorWafPolicyName = '${namePrefix}-${environmentName}-waf'
var publicBaseUrl = enableCustomDomain && !empty(publicHostName) ? 'https://${publicHostName}' : ''
var apiFunctionDefaultHostName = '${apiFunctionAppName}.azurewebsites.net'
var functionDeploymentContainerNames = [
  'api-packages'
  'worker-packages'
]

module storage './modules/storage.bicep' = {
  name: 'storage'
  params: {
    blobContainerNames: concat(storageBlobContainerNames, functionDeploymentContainerNames)
    location: location
    name: storageAccountName
    queueNames: storageQueueNames
    tags: mergedTags
  }
}

module logAnalytics './modules/log-analytics.bicep' = {
  name: 'logAnalytics'
  params: {
    location: location
    name: logAnalyticsName
    retentionInDays: logAnalyticsRetentionInDays
    tags: mergedTags
  }
}

module appInsights './modules/app-insights.bicep' = {
  name: 'appInsights'
  params: {
    location: location
    name: appInsightsName
    tags: mergedTags
    workspaceResourceId: logAnalytics.outputs.workspaceResourceId
  }
}

module keyVault './modules/keyvault.bicep' = {
  name: 'keyVault'
  params: {
    enablePurgeProtection: keyVaultEnablePurgeProtection
    location: location
    name: keyVaultName
    tags: mergedTags
    tenantId: tenantId
  }
}

var staticWebAppSettings = {
  API_BASE_PATH: '/api'
  CUSTOM_DOMAIN_ENABLED: string(enableCustomDomain)
  FRONT_DOOR_PUBLIC_HOST: publicHostName
  GOOGLE_CLIENT_ID: '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=${googleClientIdSecretName})'
  GOOGLE_CLIENT_SECRET: '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=${googleClientSecretSecretName})'
  KEY_VAULT_URI: keyVault.outputs.vaultUri
  LEAGUEBRIEF_ENVIRONMENT: environmentName
  MICROSOFT_CLIENT_ID: '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=${microsoftClientIdSecretName})'
  MICROSOFT_CLIENT_SECRET: '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=${microsoftClientSecretSecretName})'
  MICROSOFT_TENANT_ID: '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=${microsoftTenantIdSecretName})'
  PUBLIC_APP_URL: publicBaseUrl
}

module staticWebApp './modules/staticwebapp.bicep' = {
  name: 'staticWebApp'
  params: {
    appSettings: staticWebAppSettings
    location: staticWebAppLocation
    name: staticWebAppName
    publicNetworkAccess: staticWebAppPublicNetworkAccess
    skuName: staticWebAppSku
    stagingEnvironmentPolicy: staticWebAppStagingPolicy
    tags: mergedTags
  }
}

module sql './modules/sql.bicep' = {
  name: 'sql'
  params: {
    administratorLogin: sqlAdministratorLogin
    administratorPassword: sqlAdministratorPassword
    allowAzureServices: sqlAllowAzureServices
    azureAdOnlyAuthentication: sqlAzureAdOnlyAuthentication
    autoPauseDelayMinutes: sqlAutoPauseDelayMinutes
    databaseName: sqlDatabaseName
    entraAdminLogin: sqlEntraAdminLogin
    entraAdminObjectId: sqlEntraAdminObjectId
    location: location
    maxSizeBytes: sqlMaxSizeBytes
    minCapacity: sqlMinCapacity
    name: sqlServerName
    skuCapacity: sqlSkuCapacity
    skuFamily: sqlSkuFamily
    skuName: sqlSkuName
    skuTier: sqlSkuTier
    tags: mergedTags
    tenantId: tenantId
  }
}

var sharedFunctionAppSettings = {
  APPLICATIONINSIGHTS_CONNECTION_STRING: appInsights.outputs.connectionString
  AzureWebJobsStorage: storage.outputs.connectionString
  FRONT_DOOR_PUBLIC_HOST: publicHostName
  FUNCTIONS_EXTENSION_VERSION: '~4'
  GOOGLE_CLIENT_ID_SECRET_NAME: googleClientIdSecretName
  GOOGLE_CLIENT_SECRET_SECRET_NAME: googleClientSecretSecretName
  IMPORT_JOBS_QUEUE_NAME: storageQueueNames[0]
  KEY_VAULT_URI: keyVault.outputs.vaultUri
  LEAGUEBRIEF_ENVIRONMENT: environmentName
  MICROSOFT_CLIENT_ID_SECRET_NAME: microsoftClientIdSecretName
  MICROSOFT_CLIENT_SECRET_SECRET_NAME: microsoftClientSecretSecretName
  MICROSOFT_TENANT_ID_SECRET_NAME: microsoftTenantIdSecretName
  PUBLIC_BASE_URL: publicBaseUrl
  SQL_ADMIN_LOGIN: sqlAdministratorLogin
  SQL_ADMIN_PASSWORD: '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=${sqlAdminPasswordSecretName})'
  SQL_AUTHENTICATION_MODE: sqlAzureAdOnlyAuthentication ? 'azuread-only' : 'hybrid'
  SQL_DATABASE_NAME: sql.outputs.databaseName
  SQL_SERVER_FQDN: sql.outputs.serverFullyQualifiedDomainName
  STORAGE_ACCOUNT_NAME: storage.outputs.accountName
  STORAGE_EXPORTS_CONTAINER: storageBlobContainerNames[2]
  STORAGE_FANTASYPROS_CONTAINER: storageBlobContainerNames[1]
  STORAGE_JOB_ARTIFACTS_CONTAINER: storageBlobContainerNames[3]
  STORAGE_RAW_ESPN_CONTAINER: storageBlobContainerNames[0]
}

module apiFunction './modules/functionapp-flex.bicep' = {
  name: 'apiFunction'
  params: {
    alwaysReadyHttpInstances: apiAlwaysReadyInstances
    appSettings: union(sharedFunctionAppSettings, {
      APP_KIND: 'api'
      API_BASE_URL: publicBaseUrl == '' ? '' : '${publicBaseUrl}/api'
      FUNCTION_APP_ROLE: 'api'
    })
    httpPerInstanceConcurrency: apiHttpPerInstanceConcurrency
    instanceMemoryMb: functionInstanceMemoryMb
    deploymentStorageContainerUrl: '${storage.outputs.blobEndpoint}${functionDeploymentContainerNames[0]}'
    location: functionAppLocation
    maximumInstanceCount: functionMaximumInstanceCount
    name: apiFunctionAppName
    planName: apiFunctionPlanName
    runtimeName: functionRuntimeName
    runtimeVersion: functionRuntimeVersion
    tags: mergedTags
  }
}

module workerFunction './modules/functionapp-flex.bicep' = {
  name: 'workerFunction'
  params: {
    alwaysReadyHttpInstances: workerAlwaysReadyInstances
    appSettings: union(sharedFunctionAppSettings, {
      APP_KIND: 'worker'
      FUNCTION_APP_ROLE: 'worker'
    })
    httpPerInstanceConcurrency: 1
    instanceMemoryMb: functionInstanceMemoryMb
    deploymentStorageContainerUrl: '${storage.outputs.blobEndpoint}${functionDeploymentContainerNames[1]}'
    location: functionAppLocation
    maximumInstanceCount: functionMaximumInstanceCount
    name: workerFunctionAppName
    planName: workerFunctionPlanName
    runtimeName: functionRuntimeName
    runtimeVersion: functionRuntimeVersion
    tags: mergedTags
  }
}

module roleAssignments './modules/role-assignments.bicep' = {
  name: 'roleAssignments'
  params: {
    functionPrincipalIds: [
      apiFunction.outputs.principalId
      workerFunction.outputs.principalId
    ]
    keyVaultAdministratorObjectId: keyVaultAdministratorObjectId
    keyVaultName: keyVault.outputs.name
    staticWebAppPrincipalId: staticWebApp.outputs.principalId
    storageAccountName: storage.outputs.accountName
    tenantId: tenantId
  }
}

module frontDoor './modules/frontdoor-premium.bicep' = {
  name: 'frontDoor'
  params: {
    apiOriginHostName: apiFunctionDefaultHostName
    apiRateLimitDurationMinutes: frontDoorApiRateLimitDurationMinutes
    apiRateLimitThreshold: frontDoorApiRateLimitThreshold
    botManagerVersion: frontDoorBotManagerVersion
    defaultRuleSetVersion: frontDoorDefaultRuleSetVersion
    dnsZoneResourceId: dnsZoneResourceId
    enableCustomDomain: enableCustomDomain
    endpointName: frontDoorEndpointName
    location: 'global'
    logAnalyticsWorkspaceResourceId: logAnalytics.outputs.workspaceResourceId
    manageDnsInAzure: manageDnsInAzure
    profileName: frontDoorProfileName
    publicHostName: publicHostName
    skuName: frontDoorSku
    tags: mergedTags
    wafMode: frontDoorWafMode
    wafPolicyName: frontDoorWafPolicyName
    webOriginHostName: staticWebApp.outputs.defaultHostname
  }
}

output appInsightsConnectionString string = appInsights.outputs.connectionString
output appInsightsName string = appInsights.outputs.name
output frontDoorEndpointHostName string = frontDoor.outputs.endpointHostName
output frontDoorEndpointResourceId string = frontDoor.outputs.endpointResourceId
output frontDoorProfileName string = frontDoor.outputs.profileName
output frontDoorPublicUrl string = frontDoor.outputs.publicUrl
output keyVaultName string = keyVault.outputs.name
output keyVaultUri string = keyVault.outputs.vaultUri
output logAnalyticsWorkspaceName string = logAnalytics.outputs.name
output sqlDatabaseName string = sql.outputs.databaseName
output sqlServerFullyQualifiedDomainName string = sql.outputs.serverFullyQualifiedDomainName
output sqlServerName string = sql.outputs.serverName
output staticWebAppDefaultHostname string = staticWebApp.outputs.defaultHostname
output staticWebAppName string = staticWebApp.outputs.name
output storageAccountName string = storage.outputs.accountName
output storageBlobEndpoint string = storage.outputs.blobEndpoint
output storageQueueEndpoint string = storage.outputs.queueEndpoint
output userAssignedSecretNames object = {
  googleClientId: googleClientIdSecretName
  googleClientSecret: googleClientSecretSecretName
  microsoftClientId: microsoftClientIdSecretName
  microsoftClientSecret: microsoftClientSecretSecretName
  microsoftTenantId: microsoftTenantIdSecretName
  sqlAdminPassword: sqlAdminPasswordSecretName
}
output workerFunctionAppName string = workerFunction.outputs.name
output apiFunctionAppName string = apiFunction.outputs.name
