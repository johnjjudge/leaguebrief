# leaguebrief

LeagueBrief is an ESPN fantasy football league history and draft prep analytics service.

## App shells

The deployable phase-2 shells live under:

- `apps/web`: React + TypeScript frontend built with Vite and deployed to Azure Static Web Apps.
- `apps/api`: Python Azure Functions API with `GET /api/health`.
- `apps/worker`: Python Azure Functions queue-worker placeholder bound to `IMPORT_JOBS_QUEUE_NAME`.

The shells intentionally do not implement auth, database access, ESPN ingestion, Key Vault reads, or analytics yet.

## Local app development

Frontend:

```bash
cd apps/web
npm ci
npm run dev
npm run build
```

Optional frontend environment value:

- `VITE_API_BASE_URL`: API base URL for local cross-origin development. Defaults to `/api`.

API:

```bash
cd apps/api
cp local.settings.example.json local.settings.json
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
func start
```

Health check:

```bash
curl http://localhost:7071/api/health
```

Worker:

```bash
cd apps/worker
cp local.settings.example.json local.settings.json
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
func start
```

Required local Function App settings:

- `FUNCTIONS_WORKER_RUNTIME=python`
- `AzureWebJobsStorage=<storage-connection-string>` or `UseDevelopmentStorage=true` with Azurite
- `IMPORT_JOBS_QUEUE_NAME=import-jobs` for the worker
- `LEAGUEBRIEF_ENVIRONMENT=local`

The Bicep infrastructure targets Python `3.13` and Azure Functions Core Tools v4, so local `func start` validation should use Python 3.13 plus the `func` CLI.

Azure injects the broader Bicep-provisioned settings for deployed environments, including `PUBLIC_BASE_URL`, `API_BASE_URL`, storage account/container names, Key Vault references, SQL placeholders, and Application Insights. The phase-2 shells only read environment labels and role values.

## Static Web Apps forwarding gateway

`apps/web/staticwebapp.config.json` restricts direct Static Web Apps access to Azure Front Door and requires the expected production Front Door header:

- forwarded hosts: `lbr-prod-edge-f9fzdsa7budefnhg.z01.azurefd.net`, `www.leaguebrief.com`
- required header: `X-Azure-FDID=b3ff2399-d615-40c3-935c-7f77deaffe64`

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
