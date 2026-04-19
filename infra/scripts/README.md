# LeagueBrief Deployment Scripts

These Bash scripts support local macOS deployment of LeagueBrief infrastructure and application code.

## Prerequisites

- Azure CLI with an authenticated session
- Azure Bicep via `az bicep`
- `jq`
- `zip`
- `python3`
- `node`, `npm`, and `npx`
- Azure Functions Core Tools via `func`

Run the bootstrap check before the first deployment:

```bash
infra/scripts/bootstrap-env.sh \
  --env dev \
  --subscription <subscription-id> \
  --resource-group <resource-group>
```

## Shared flags

Azure-aware scripts accept:

- `--env dev|prod`
- `--subscription <subscription-id>`
- `--resource-group <resource-group>`

Environment variable fallbacks:

- `LB_ENV`
- `LB_SUBSCRIPTION_ID`
- `LB_RESOURCE_GROUP`

`deploy-infra.sh` also requires:

- `LB_SQL_ADMIN_PASSWORD`

## Scripts

### `bootstrap-env.sh`

Checks required local tooling, Azure login state, resource-group access, Bicep availability, and Azure provider registration status.

### `deploy-infra.sh`

Runs a direct `az deployment group create` against `infra/bicep/main.bicep` and `infra/bicep/parameters/<env>.bicepparam`.

Notes:

- deployment name is fixed to `leaguebrief-<env>-infra`
- no local deployment metadata is written
- no local Bicep outputs are cached
- Azure CLI errors are surfaced directly in the terminal

Example:

```bash
LB_SQL_ADMIN_PASSWORD='<strong-password>' \
infra/scripts/deploy-infra.sh \
  --env dev \
  --subscription <subscription-id> \
  --resource-group <resource-group>
```

### `package-api.sh`

Builds a clean local package for the API Function App under `infra/.artifacts/<env>/api/`.

It requires:

- `apps/api/host.json`
- `apps/api/requirements.txt`
- at least one Python source file

### `package-worker.sh`

Builds a clean local package for the worker Function App under `infra/.artifacts/<env>/worker/`.

It requires:

- `apps/worker/host.json`
- `apps/worker/requirements.txt`
- at least one Python source file

The repo currently includes `apps/worker/` only as a placeholder, so this script will fail with a clear message until the worker shell exists.

### `deploy-app-api.sh`

Packages the API app unless `--skip-package` is passed, reads `apiFunctionAppName` live from the last successful Azure deployment named `leaguebrief-<env>-infra`, and publishes with Azure Functions Core Tools.

Example:

```bash
infra/scripts/deploy-app-api.sh \
  --env dev \
  --subscription <subscription-id> \
  --resource-group <resource-group>
```

### `deploy-app-worker.sh`

Packages the worker app unless `--skip-package` is passed, reads `workerFunctionAppName` live from Azure deployment outputs, and publishes with Azure Functions Core Tools.

### `deploy-app-web.sh`

Runs `npm ci`, `npm run build`, detects `dist/` or `build/`, reads `staticWebAppName` live from Azure deployment outputs, fetches the deployment token from Azure, and deploys the built frontend with the Static Web Apps CLI via `npx`.

## Idempotency and repeatability

- Re-running `deploy-infra.sh` is safe under ARM incremental deployment behavior.
- Re-running package scripts replaces the local package artifacts for the selected environment.
- App deployment scripts always fetch fresh infrastructure outputs from Azure instead of relying on local cache files.
- No script requires manual editing for ordinary use.
