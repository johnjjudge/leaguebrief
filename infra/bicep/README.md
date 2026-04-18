# LeagueBrief Bicep

This folder defines the Azure MVP infrastructure for LeagueBrief at resource-group scope.

## Files
- `main.bicep`: top-level deployment entrypoint and shared parameter surface.
- `modules/storage.bicep`: shared Storage Account plus required blob containers and queues.
- `modules/log-analytics.bicep`: Log Analytics workspace for diagnostics.
- `modules/app-insights.bicep`: workspace-based Application Insights resource.
- `modules/keyvault.bicep`: Key Vault creation using the access-policy model.
- `modules/staticwebapp.bicep`: Static Web App plus app settings placeholders.
- `modules/functionapp-flex.bicep`: reusable Azure Functions Flex Consumption app module.
- `modules/sql.bicep`: Azure SQL logical server, Entra admin, firewall rule, and serverless database.
- `modules/role-assignments.bicep`: Storage RBAC and Key Vault access-policy wiring for app identities.
- `modules/frontdoor-premium.bicep`: Front Door Premium profile, endpoint, origins, routes, WAF, and diagnostics.

## Parameter files
- `parameters/dev.bicepparam`: development defaults. Custom domain is disabled by default.
- `parameters/prod.bicepparam`: production defaults. WAF mode is `Prevention`, purge protection is enabled, and custom domain remains opt-in until DNS is ready.

## Important inputs
- `sqlAdministratorPassword` is intentionally blank in the checked-in parameter files and should be overridden at deploy time.
- `sqlEntraAdminObjectId` and `keyVaultAdministratorObjectId` use placeholder GUIDs and must be replaced per environment.
- OAuth secret names are defined here, but the secret values are expected to be set in Key Vault separately.

## Expected outputs
- Front Door endpoint hostname and public URL
- Static Web App default hostname
- Function App names
- Storage account and endpoints
- SQL server FQDN and database name
- Key Vault URI
- Application Insights connection string
