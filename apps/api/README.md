# LeagueBrief API

Azure Functions API for LeagueBrief.

## Local settings

Copy `local.settings.example.json` to `local.settings.json` for local development.

Required local values:

- `FUNCTIONS_WORKER_RUNTIME`: must be `python`
- `AzureWebJobsStorage`: Azure Storage connection string, or `UseDevelopmentStorage=true` when Azurite is running
- `IMPORT_JOBS_QUEUE_NAME`: queue name for import jobs, normally `import-jobs`
- `KEY_VAULT_URI`: Key Vault URI used for private ESPN credential storage
- `LEAGUEBRIEF_ENVIRONMENT`: local environment label such as `local`, `dev`, or `prod`
- `SQL_CONNECTION_STRING`: optional full pyodbc connection string
- `SQL_SERVER_FQDN`, `SQL_DATABASE_NAME`, `SQL_ADMIN_LOGIN`, `SQL_ADMIN_PASSWORD`: used when `SQL_CONNECTION_STRING` is not set
- `SQL_ODBC_DRIVER`: optional driver override; defaults to `ODBC Driver 18 for SQL Server`

The deployed Function App receives additional settings from Bicep, including `PUBLIC_BASE_URL`, `API_BASE_URL`, storage container names, Key Vault references, and SQL settings.

## Run locally

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
func start
```

Health check:

```bash
curl http://localhost:7071/api/health
```

Apply SQL migrations:

```bash
python -m leaguebrief.db.migrate
```

`GET /api/me` expects Azure Static Web Apps to forward an authenticated `x-ms-client-principal` header. League endpoints use the same authenticated principal:

- `GET /api/leagues`
- `POST /api/leagues`
- `GET /api/leagues/{leagueId}`
- `POST /api/leagues/{leagueId}/attach`
- `POST /api/leagues/{leagueId}/credentials`
- `POST /api/leagues/{leagueId}/imports`

For local tests, use the Static Web Apps CLI auth emulator or construct the header manually.

`POST /api/leagues/{leagueId}/credentials` accepts ESPN cookie fields as `espnS2`
or `espn_s2`, and `swid` or `SWID`. The API writes the raw cookie values to Key
Vault and stores only secret reference names in SQL.

`POST /api/leagues/{leagueId}/imports` creates an `import_jobs` row and sends one
queue message to `IMPORT_JOBS_QUEUE_NAME`. Supported `jobType` values are
`initial_import`, `attach_existing_league`, `refresh_current_data`,
`recompute_metrics`, and `ingest_fantasypros`.

## Test

```bash
pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest
```

Live SQL repository tests are opt-in. They create a uniquely named disposable
Azure SQL database, apply migrations, run repository coverage against it, close
connections, and drop the database in teardown.

Required environment values:

- `LEAGUEBRIEF_RUN_LIVE_SQL_TESTS=1`
- `LEAGUEBRIEF_TEST_SQL_SERVER_FQDN`
- `LEAGUEBRIEF_TEST_SQL_ADMIN_LOGIN`
- `LEAGUEBRIEF_TEST_SQL_ADMIN_PASSWORD`
- `LEAGUEBRIEF_TEST_SQL_ODBC_DRIVER` optional, defaults to `ODBC Driver 18 for SQL Server`

Run only the live SQL integration tests:

```bash
LEAGUEBRIEF_RUN_LIVE_SQL_TESTS=1 \
LEAGUEBRIEF_TEST_SQL_SERVER_FQDN='<server>.database.windows.net' \
LEAGUEBRIEF_TEST_SQL_ADMIN_LOGIN='<login>' \
LEAGUEBRIEF_TEST_SQL_ADMIN_PASSWORD='<password>' \
python -m pytest -m sql_integration
```

Use a non-production SQL logical server/login that can create and drop test
databases. If teardown fails, the test error includes the disposable database
name so it can be removed manually.

The deployed Azure Functions runtime is Python 3.13. Use Azure Functions Core Tools v4 for local `func start` validation.
