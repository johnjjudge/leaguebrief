ALTER TABLE dbo.import_jobs
    DROP CONSTRAINT CK_import_jobs_job_type;
GO

ALTER TABLE dbo.import_jobs
    ADD CONSTRAINT CK_import_jobs_job_type
        CHECK (job_type IN (
            N'initial_import',
            N'attach_existing_league',
            N'refresh_current_data',
            N'recompute_metrics',
            N'ingest_fantasypros',
            N'normalize_raw_snapshots'
        ));
GO

ALTER TABLE dbo.matchups
    ADD source_key NVARCHAR(256) NULL;
GO

CREATE UNIQUE INDEX UX_matchups_season_source_key
    ON dbo.matchups (season_id, source_key)
    WHERE source_key IS NOT NULL;
GO

ALTER TABLE dbo.transactions
    ADD source_key NVARCHAR(256) NULL;
GO

CREATE UNIQUE INDEX UX_transactions_season_source_key
    ON dbo.transactions (season_id, source_key)
    WHERE source_key IS NOT NULL;
