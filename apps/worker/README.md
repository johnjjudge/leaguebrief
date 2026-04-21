# LeagueBrief Worker

Minimal Azure Functions queue-worker shell for LeagueBrief.

## Local settings

Copy `local.settings.example.json` to `local.settings.json` for local development.

Required local values:

- `FUNCTIONS_WORKER_RUNTIME`: must be `python`
- `AzureWebJobsStorage`: Azure Storage connection string, or `UseDevelopmentStorage=true` when Azurite is running
- `IMPORT_JOBS_QUEUE_NAME`: queue name for import jobs, normally `import-jobs`
- `LEAGUEBRIEF_ENVIRONMENT`: local environment label such as `local`, `dev`, or `prod`

The deployed Function App receives additional settings from Bicep, including storage container names, Key Vault references, and SQL placeholders. This phase-2 shell intentionally does not use auth, Key Vault, SQL, or ESPN settings yet.

## Run locally

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
func start
```

## Test

```bash
pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest
```

The deployed Azure Functions runtime is Python 3.13. Use Azure Functions Core Tools v4 for local `func start` validation.
