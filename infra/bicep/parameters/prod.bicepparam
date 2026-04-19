using '../main.bicep'

param environmentName = 'prod'
param location = 'westus3'
param namePrefix = 'lbr'
param tags = {
  environment: 'prod'
  project: 'LeagueBrief'
}

param enableCustomDomain = false
param publicHostName = 'www.leaguebrief.com'
param manageDnsInAzure = false
param dnsZoneResourceId = ''

param frontDoorWafMode = 'Prevention'
param frontDoorDefaultRuleSetVersion = '1.1'
param frontDoorBotManagerVersion = '1.0'
param frontDoorApiRateLimitThreshold = 600
param frontDoorApiRateLimitDurationMinutes = 1

param staticWebAppSku = 'Standard'
param staticWebAppLocation = 'eastus2'
param staticWebAppPublicNetworkAccess = 'Enabled'
param staticWebAppStagingPolicy = 'Disabled'

param functionRuntimeName = 'python'
param functionRuntimeVersion = '3.12'
param functionAppLocation = 'westus3'
param functionInstanceMemoryMb = 2048
param functionMaximumInstanceCount = 50
param apiHttpPerInstanceConcurrency = 20
param apiAlwaysReadyInstances = 0
param workerAlwaysReadyInstances = 0

param storageBlobContainerNames = [
  'raw-espn'
  'fantasypros-source'
  'exports'
  'job-artifacts'
]

param storageQueueNames = [
  'import-jobs'
]

param sqlAdministratorLogin = 'leaguebriefadmin'
param sqlAdministratorPassword = ''
param sqlEntraAdminLogin = 'judgejohn17_icloud.com#EXT#@judgejohn17icloud.onmicrosoft.com'
param sqlEntraAdminObjectId = '9ab46456-e7dd-45fe-a9da-e7d8773a3b8c'
param keyVaultAdministratorObjectId = '9ab46456-e7dd-45fe-a9da-e7d8773a3b8c'
param tenantId = '55ac6c0f-19b1-412e-b19e-9ab419c99a7c'

param sqlDatabaseName = 'leaguebrief'
param sqlSkuName = 'GP_S_Gen5_1'
param sqlSkuTier = 'GeneralPurpose'
param sqlSkuFamily = 'Gen5'
param sqlSkuCapacity = 1
param sqlMinCapacity = 1
param sqlAutoPauseDelayMinutes = 60
param sqlMaxSizeBytes = 34359738368
param sqlAllowAzureServices = true
param sqlAzureAdOnlyAuthentication = false

param logAnalyticsRetentionInDays = 30
param keyVaultEnablePurgeProtection = true

param sqlAdminPasswordSecretName = 'sql-admin-password'
param googleClientIdSecretName = 'google-client-id'
param googleClientSecretSecretName = 'google-client-secret'
param microsoftClientIdSecretName = 'microsoft-client-id'
param microsoftClientSecretSecretName = 'microsoft-client-secret'
param microsoftTenantIdSecretName = 'microsoft-tenant-id'
