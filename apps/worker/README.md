# LeagueBrief Worker

Azure Functions queue worker for LeagueBrief import jobs.

## Local settings

Copy `local.settings.example.json` to `local.settings.json` for local development.

Required local values:

- `FUNCTIONS_WORKER_RUNTIME`: must be `python`
- `AzureWebJobsStorage`: Azure Storage connection string, or `UseDevelopmentStorage=true` when Azurite is running
- `IMPORT_JOBS_QUEUE_NAME`: queue name for import jobs, normally `import-jobs`
- `STORAGE_RAW_ESPN_CONTAINER`: blob container for raw ESPN payloads, normally `raw-espn`
- `FANTASYPROS_ADPREFERENCES_DIR`: optional override for local FantasyPros ADP CSVs; defaults to the packaged `adpreferences` directory
- `KEY_VAULT_URI`: Key Vault URI used to read stored ESPN credential values
- `LEAGUEBRIEF_ENVIRONMENT`: local environment label such as `local`, `dev`, or `prod`
- `SQL_CONNECTION_STRING`: optional full pyodbc connection string
- `SQL_SERVER_FQDN`, `SQL_DATABASE_NAME`, `SQL_ADMIN_LOGIN`, `SQL_ADMIN_PASSWORD`: used when `SQL_CONNECTION_STRING` is not set
- `SQL_ODBC_DRIVER`: optional driver override; defaults to `ODBC Driver 18 for SQL Server`

The queue trigger is configured with `maxDequeueCount = 3`. Failed worker
attempts below the retry limit are re-raised for Queue Storage retry. The third
failed attempt marks the SQL `import_jobs` row as `failed` and records a
`job_events` entry.

`initial_import` and `refresh_current_data` jobs fetch raw ESPN snapshots,
write canonical JSON payloads to the `raw-espn` blob container, and create
`raw_snapshots` rows. The worker reads active ESPN credential references from
SQL and retrieves the raw `espn_s2`/`SWID` values from Key Vault; raw credential
values are not stored in SQL or logged.

`ingest_fantasypros` jobs read the packaged static CSV files in
`apps/worker/adpreferences` and persist durable reference rows to SQL. These
CSV files are not copied to Blob Storage; `reference_files.blob_path` stores the
package-relative provenance path, for example
`adpreferences/FantasyPros_2024_Overall_ADP_Rankings-PPR.csv`.

FantasyPros ADP ingestion imports all bundled seasons from 2015 onward. It
selects ESPN ADP when that column is present and numeric, otherwise it falls
back to `AVG`. Reference scoring comes from the filename suffix: `STD` is
`standard`, `HALF` is `half_ppr`, and `PPR` is `ppr`. Downstream half-PPR
selection falls back to PPR when a season has no half-PPR reference.

Player matching uses normalized FantasyPros name plus base position. The
normalizer lowercases, strips accents and punctuation, removes suffix tokens
such as `Jr.`, `II`, and `III`, and collapses whitespace. Teams are stored as
row metadata, not as identity, because NFL teams change over time. This MVP can
still collide on same-name same-position players; those cases should be handled
by a future manual reconciliation workflow.

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
