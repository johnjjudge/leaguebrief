# LeagueBrief API

Azure Functions API for LeagueBrief.

## Local settings

Copy `local.settings.example.json` to `local.settings.json` for local development.

Required local values:

- `FUNCTIONS_WORKER_RUNTIME`: must be `python`
- `AzureWebJobsStorage`: Azure Storage connection string, or `UseDevelopmentStorage=true` when Azurite is running
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

`GET /api/me` expects Azure Static Web Apps to forward an authenticated `x-ms-client-principal` header. For local tests, use the Static Web Apps CLI auth emulator or construct the header manually.

## Test

```bash
pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest
```

The deployed Azure Functions runtime is Python 3.13. Use Azure Functions Core Tools v4 for local `func start` validation.
