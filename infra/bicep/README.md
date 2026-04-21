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
- `modules/frontdoor-premium.bicep`: Front Door Premium profile, endpoint, origins, routes, optional WAF, and diagnostics.

## Parameter files
- `parameters/dev.bicepparam`: development defaults. Custom domain and Front Door WAF are disabled by default.
- `parameters/prod.bicepparam`: production defaults. Front Door custom-domain onboarding is enabled for `www.leaguebrief.com`, purge protection is enabled, Front Door WAF is disabled by default, and existing Flex plans are reused so repeat deployments are not blocked by the current Azure `ElasticWebApps` plan-update failure in this resource group.

## Important inputs
- `sqlAdministratorPassword` is intentionally blank in the checked-in parameter files and should be overridden at deploy time.
- `sqlEntraAdminObjectId` and `keyVaultAdministratorObjectId` use placeholder GUIDs and must be replaced per environment.
- OAuth secret names are defined here, but the secret values are expected to be set in Key Vault separately.

## Auth provider registration contract

The current production auth setup assumes Azure Static Web Apps custom auth running behind Azure Front Door on:

- `https://www.leaguebrief.com`

That means the external provider registrations should use the following callback contract.

### Google OAuth

Create a Google OAuth client with these values:

- App name: `LeagueBrief`
- Audience: `External`
- Client type: `Web application`
- Authorized domain: `leaguebrief.com`
- Authorized JavaScript origin: `https://www.leaguebrief.com`
- Authorized redirect URI: `https://www.leaguebrief.com/.auth/login/google/callback`

If the Google app is moved to production publishing, Google also expects real homepage, privacy-policy, and terms URLs on the `leaguebrief.com` domain.

### Microsoft Entra app registration

Create a Microsoft Entra app registration with these values:

- Name: `LeagueBrief`
- Supported account types: `Accounts in any organizational directory and personal Microsoft accounts`
- Web redirect URI: `https://www.leaguebrief.com/.auth/login/aad/callback`
- Front-channel logout URL: `https://www.leaguebrief.com/.auth/logout/aad/callback`

This callback path uses the Azure Static Web Apps built-in provider alias `aad`.

The API Function App is linked to the Static Web App as a bring-your-own backend. Front Door sends `/api/*` to the Static Web App origin so Static Web Apps can enforce auth rules and forward authenticated API requests with the `x-ms-client-principal` header. `GET /api/health` remains anonymous.

## DNS cutover for Squarespace

Production currently uses:

- Front Door custom domain: `www.leaguebrief.com`
- DNS provider workflow: manual, because `manageDnsInAzure = false`

Azure creates the Front Door custom-domain resource, but you still need to add the DNS records in Squarespace.

### Values to read from Azure

Two values are deployment-specific and should be fetched from Azure each time you need to validate or recreate the DNS setup:

- the Front Door endpoint hostname
- the Front Door custom-domain validation token

Fetch them with:

```bash
az deployment group show \
  --subscription <subscription-id> \
  --resource-group <resource-group> \
  --name leaguebrief-prod-infra \
  --query properties.outputs.frontDoorEndpointHostName.value \
  -o tsv

az afd custom-domain list \
  --subscription <subscription-id> \
  --resource-group <resource-group> \
  --profile-name <front-door-profile-name> \
  -o json
```

Use:

- `frontDoorEndpointHostName` for the production `www` CNAME target
- `validationProperties.validationToken` for the Front Door validation TXT record

### Squarespace DNS records

In the Squarespace DNS editor for `leaguebrief.com`, add:

1. TXT record for Front Door validation
   - Host: `_dnsauth.www`
   - Value/Text: `<validation-token-from-azure>`

2. CNAME record for the public web host
   - Host: `www`
   - Points to / Data: `<front-door-endpoint-hostname-from-azure>`

Important:

- Keep `www` as a DNS `CNAME` to Front Door.
- Do not create an `A` record for `www`.
- Do not add a forwarding rule for `www`.
- If a `www` record already exists, replace it so only one record owns that host.

### Apex forwarding

The current production contract serves the app on `https://www.leaguebrief.com`, not on the bare apex.

In Squarespace, add a forwarding rule for the apex host:

- Subdomain: `@`
- Destination: `www.leaguebrief.com`
- Redirect type: `301`
- Path forwarding: `Maintain paths`

This makes:

- `leaguebrief.com` redirect to `https://www.leaguebrief.com`
- `leaguebrief.com/<path>` redirect to `https://www.leaguebrief.com/<path>`

### Verification

After saving the DNS changes, verify them publicly:

```bash
dig TXT _dnsauth.www.leaguebrief.com +short
dig CNAME www.leaguebrief.com +short
```

Expected result:

- the TXT lookup returns the current Azure validation token
- the CNAME lookup returns the current Front Door endpoint hostname

Once those resolve publicly, Azure Front Door should move the custom domain from `Pending` to `Approved` or `Provisioned`. If validation stays stuck after propagation, regenerate the validation token in Azure and replace the TXT record.

### Key Vault secrets

The Bicep defaults expect the following secret names:

- `google-client-id`
- `google-client-secret`
- `microsoft-client-id`
- `microsoft-client-secret`
- `microsoft-tenant-id`
- `sql-admin-password`

The Function Apps and Static Web App reference these names through Key Vault-backed configuration, so the secret names must stay aligned with the values in `main.bicep` and the environment `.bicepparam` files.

Example secret creation commands:

```bash
az keyvault secret set --vault-name <vault-name> --name google-client-id --value '<GOOGLE_CLIENT_ID>'
az keyvault secret set --vault-name <vault-name> --name google-client-secret --value '<GOOGLE_CLIENT_SECRET>'
az keyvault secret set --vault-name <vault-name> --name microsoft-client-id --value '<MICROSOFT_CLIENT_ID>'
az keyvault secret set --vault-name <vault-name> --name microsoft-client-secret --value '<MICROSOFT_CLIENT_SECRET>'
az keyvault secret set --vault-name <vault-name> --name microsoft-tenant-id --value '<MICROSOFT_TENANT_ID>'
```

If the public host changes later, update the provider registrations and the related Azure Static Web Apps auth configuration together.

## Expected outputs
- Front Door endpoint hostname and public URL
- Static Web App default hostname
- Function App names
- Storage account and endpoints
- SQL server FQDN and database name
- Key Vault URI
- Application Insights connection string
