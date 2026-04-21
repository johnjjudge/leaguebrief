# leaguebrief

LeagueBrief is an ESPN fantasy football league history and draft prep analytics service.

## Local deployment workflow

Infrastructure and app deployment scripts live under [infra/scripts](infra/scripts/README.md).

Typical macOS flow:

```bash
infra/scripts/bootstrap-env.sh \
  --env dev \
  --subscription <subscription-id> \
  --resource-group <resource-group>

LB_SQL_ADMIN_PASSWORD='<strong-password>' \
infra/scripts/deploy-infra.sh \
  --env dev \
  --subscription <subscription-id> \
  --resource-group <resource-group>
```

After the app shells exist:

- `infra/scripts/package-api.sh --env dev`
- `infra/scripts/deploy-app-api.sh --env dev --subscription <subscription-id> --resource-group <resource-group>`
- `infra/scripts/deploy-app-worker.sh --env dev --subscription <subscription-id> --resource-group <resource-group>`
- `infra/scripts/deploy-app-web.sh --env dev --subscription <subscription-id> --resource-group <resource-group>`

The scripts do not persist local deployment metadata or Bicep outputs. App deploy scripts resolve the latest Azure deployment outputs live from the `leaguebrief-<env>-infra` deployment.

## Auth provider setup

Google and Microsoft sign-in for the production environment require manual provider registrations plus Key Vault secret seeding. The current contract uses the public host `https://www.leaguebrief.com` and Azure Static Web Apps callback paths.

See [infra/bicep/README.md](infra/bicep/README.md) for the exact registration fields, callback URLs, required Key Vault secret names, and the manual Squarespace DNS cutover steps for Front Door.
