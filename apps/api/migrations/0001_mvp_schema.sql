CREATE TABLE dbo.users (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_users_id DEFAULT NEWID()
        CONSTRAINT PK_users PRIMARY KEY,
    primary_email NVARCHAR(320) NOT NULL,
    display_name NVARCHAR(200) NULL,
    profile_image_url NVARCHAR(2048) NULL,
    status NVARCHAR(32) NOT NULL
        CONSTRAINT DF_users_status DEFAULT N'active',
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_users_created_at DEFAULT SYSUTCDATETIME(),
    updated_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_users_updated_at DEFAULT SYSUTCDATETIME(),
    last_login_at DATETIME2(3) NULL,
    CONSTRAINT CK_users_status CHECK (status IN (N'active', N'disabled'))
);

CREATE UNIQUE INDEX UX_users_primary_email
    ON dbo.users (primary_email);

CREATE TABLE dbo.auth_provider_accounts (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_auth_provider_accounts_id DEFAULT NEWID()
        CONSTRAINT PK_auth_provider_accounts PRIMARY KEY,
    user_id UNIQUEIDENTIFIER NOT NULL,
    provider NVARCHAR(32) NOT NULL,
    provider_subject NVARCHAR(256) NOT NULL,
    email NVARCHAR(320) NOT NULL,
    email_verified BIT NOT NULL
        CONSTRAINT DF_auth_provider_accounts_email_verified DEFAULT 0,
    display_name NVARCHAR(200) NULL,
    profile_image_url NVARCHAR(2048) NULL,
    last_login_at DATETIME2(3) NULL,
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_auth_provider_accounts_created_at DEFAULT SYSUTCDATETIME(),
    updated_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_auth_provider_accounts_updated_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_auth_provider_accounts_users
        FOREIGN KEY (user_id) REFERENCES dbo.users (id),
    CONSTRAINT CK_auth_provider_accounts_provider
        CHECK (provider IN (N'google', N'microsoft'))
);

CREATE UNIQUE INDEX UX_auth_provider_accounts_provider_subject
    ON dbo.auth_provider_accounts (provider, provider_subject);

CREATE UNIQUE INDEX UX_auth_provider_accounts_user_provider
    ON dbo.auth_provider_accounts (user_id, provider);

CREATE TABLE dbo.leagues (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_leagues_id DEFAULT NEWID()
        CONSTRAINT PK_leagues PRIMARY KEY,
    platform NVARCHAR(32) NOT NULL,
    external_league_id NVARCHAR(128) NOT NULL,
    name NVARCHAR(256) NOT NULL,
    scoring_type NVARCHAR(64) NULL,
    is_private BIT NOT NULL
        CONSTRAINT DF_leagues_is_private DEFAULT 0,
    timezone NVARCHAR(128) NULL,
    first_season INT NULL,
    last_season INT NULL,
    created_by_user_id UNIQUEIDENTIFIER NOT NULL,
    data_completeness_status NVARCHAR(32) NOT NULL
        CONSTRAINT DF_leagues_data_completeness_status DEFAULT N'not_started',
    last_imported_at DATETIME2(3) NULL,
    last_computed_at DATETIME2(3) NULL,
    last_successful_refresh_at DATETIME2(3) NULL,
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_leagues_created_at DEFAULT SYSUTCDATETIME(),
    updated_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_leagues_updated_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_leagues_created_by_users
        FOREIGN KEY (created_by_user_id) REFERENCES dbo.users (id),
    CONSTRAINT CK_leagues_platform CHECK (platform IN (N'espn')),
    CONSTRAINT CK_leagues_data_completeness_status
        CHECK (data_completeness_status IN (N'not_started', N'partial', N'complete', N'stale'))
);

CREATE UNIQUE INDEX UX_leagues_platform_external_league_id
    ON dbo.leagues (platform, external_league_id);

CREATE TABLE dbo.user_leagues (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_user_leagues_id DEFAULT NEWID()
        CONSTRAINT PK_user_leagues PRIMARY KEY,
    user_id UNIQUEIDENTIFIER NOT NULL,
    league_id UNIQUEIDENTIFIER NOT NULL,
    role NVARCHAR(32) NOT NULL
        CONSTRAINT DF_user_leagues_role DEFAULT N'viewer',
    joined_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_user_leagues_joined_at DEFAULT SYSUTCDATETIME(),
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_user_leagues_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_user_leagues_users
        FOREIGN KEY (user_id) REFERENCES dbo.users (id),
    CONSTRAINT FK_user_leagues_leagues
        FOREIGN KEY (league_id) REFERENCES dbo.leagues (id),
    CONSTRAINT CK_user_leagues_role CHECK (role IN (N'owner', N'viewer'))
);

CREATE UNIQUE INDEX UX_user_leagues_user_league
    ON dbo.user_leagues (user_id, league_id);

CREATE TABLE dbo.league_access_credentials (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_league_access_credentials_id DEFAULT NEWID()
        CONSTRAINT PK_league_access_credentials PRIMARY KEY,
    league_id UNIQUEIDENTIFIER NOT NULL,
    user_id UNIQUEIDENTIFIER NOT NULL,
    credential_type NVARCHAR(64) NOT NULL,
    key_vault_secret_name_s2 NVARCHAR(256) NOT NULL,
    key_vault_secret_name_swid NVARCHAR(256) NOT NULL,
    status NVARCHAR(32) NOT NULL
        CONSTRAINT DF_league_access_credentials_status DEFAULT N'active',
    is_preferred_for_refresh BIT NOT NULL
        CONSTRAINT DF_league_access_credentials_is_preferred_for_refresh DEFAULT 0,
    last_verified_at DATETIME2(3) NULL,
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_league_access_credentials_created_at DEFAULT SYSUTCDATETIME(),
    updated_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_league_access_credentials_updated_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_league_access_credentials_leagues
        FOREIGN KEY (league_id) REFERENCES dbo.leagues (id),
    CONSTRAINT FK_league_access_credentials_users
        FOREIGN KEY (user_id) REFERENCES dbo.users (id),
    CONSTRAINT CK_league_access_credentials_credential_type
        CHECK (credential_type IN (N'espn_cookie_pair')),
    CONSTRAINT CK_league_access_credentials_status
        CHECK (status IN (N'active', N'invalid', N'revoked', N'expired'))
);

CREATE UNIQUE INDEX UX_league_access_credentials_league_user_type
    ON dbo.league_access_credentials (league_id, user_id, credential_type);

CREATE TABLE dbo.import_jobs (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_import_jobs_id DEFAULT NEWID()
        CONSTRAINT PK_import_jobs PRIMARY KEY,
    league_id UNIQUEIDENTIFIER NOT NULL,
    requested_by_user_id UNIQUEIDENTIFIER NOT NULL,
    job_type NVARCHAR(64) NOT NULL,
    status NVARCHAR(32) NOT NULL
        CONSTRAINT DF_import_jobs_status DEFAULT N'queued',
    current_phase NVARCHAR(32) NULL,
    priority INT NOT NULL
        CONSTRAINT DF_import_jobs_priority DEFAULT 0,
    requested_seasons_json NVARCHAR(MAX) NULL,
    started_at DATETIME2(3) NULL,
    completed_at DATETIME2(3) NULL,
    last_heartbeat_at DATETIME2(3) NULL,
    error_summary NVARCHAR(MAX) NULL,
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_import_jobs_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_import_jobs_leagues
        FOREIGN KEY (league_id) REFERENCES dbo.leagues (id),
    CONSTRAINT FK_import_jobs_requested_by_users
        FOREIGN KEY (requested_by_user_id) REFERENCES dbo.users (id),
    CONSTRAINT CK_import_jobs_job_type
        CHECK (job_type IN (N'initial_import', N'attach_existing_league', N'refresh_current_data', N'recompute_metrics', N'ingest_fantasypros')),
    CONSTRAINT CK_import_jobs_status
        CHECK (status IN (N'queued', N'validating', N'running', N'partial_success', N'succeeded', N'failed', N'cancelled')),
    CONSTRAINT CK_import_jobs_current_phase
        CHECK (current_phase IS NULL OR current_phase IN (N'validate', N'fetch', N'normalize', N'compute', N'finalize'))
);

CREATE INDEX IX_import_jobs_league_status
    ON dbo.import_jobs (league_id, status);

CREATE TABLE dbo.job_tasks (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_job_tasks_id DEFAULT NEWID()
        CONSTRAINT PK_job_tasks PRIMARY KEY,
    job_id UNIQUEIDENTIFIER NOT NULL,
    task_type NVARCHAR(64) NOT NULL,
    season INT NULL,
    status NVARCHAR(32) NOT NULL
        CONSTRAINT DF_job_tasks_status DEFAULT N'queued',
    attempt_count INT NOT NULL
        CONSTRAINT DF_job_tasks_attempt_count DEFAULT 0,
    started_at DATETIME2(3) NULL,
    completed_at DATETIME2(3) NULL,
    error_message NVARCHAR(MAX) NULL,
    worker_instance_id NVARCHAR(256) NULL,
    CONSTRAINT FK_job_tasks_import_jobs
        FOREIGN KEY (job_id) REFERENCES dbo.import_jobs (id),
    CONSTRAINT CK_job_tasks_task_type
        CHECK (task_type IN (N'fetch_season', N'fetch_draft', N'fetch_matchups', N'normalize_season', N'compute_manager_metrics', N'compute_league_metrics')),
    CONSTRAINT CK_job_tasks_status
        CHECK (status IN (N'queued', N'running', N'succeeded', N'failed', N'skipped'))
);

CREATE INDEX IX_job_tasks_job_status
    ON dbo.job_tasks (job_id, status);

CREATE TABLE dbo.job_events (
    id BIGINT IDENTITY(1, 1) NOT NULL
        CONSTRAINT PK_job_events PRIMARY KEY,
    job_id UNIQUEIDENTIFIER NOT NULL,
    event_type NVARCHAR(128) NOT NULL,
    message NVARCHAR(MAX) NULL,
    payload_json NVARCHAR(MAX) NULL,
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_job_events_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_job_events_import_jobs
        FOREIGN KEY (job_id) REFERENCES dbo.import_jobs (id)
);

CREATE INDEX IX_job_events_job_created
    ON dbo.job_events (job_id, created_at);

CREATE TABLE dbo.raw_snapshots (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_raw_snapshots_id DEFAULT NEWID()
        CONSTRAINT PK_raw_snapshots PRIMARY KEY,
    league_id UNIQUEIDENTIFIER NOT NULL,
    season INT NULL,
    snapshot_type NVARCHAR(64) NOT NULL,
    blob_path NVARCHAR(1024) NOT NULL,
    source_hash NVARCHAR(128) NOT NULL,
    is_current BIT NOT NULL
        CONSTRAINT DF_raw_snapshots_is_current DEFAULT 1,
    fetched_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_raw_snapshots_fetched_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_raw_snapshots_leagues
        FOREIGN KEY (league_id) REFERENCES dbo.leagues (id),
    CONSTRAINT CK_raw_snapshots_snapshot_type
        CHECK (snapshot_type IN (N'league_meta', N'draft', N'matchups', N'rosters', N'transactions'))
);

CREATE INDEX IX_raw_snapshots_league_season_type
    ON dbo.raw_snapshots (league_id, season, snapshot_type);

CREATE TABLE dbo.reference_files (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_reference_files_id DEFAULT NEWID()
        CONSTRAINT PK_reference_files PRIMARY KEY,
    source NVARCHAR(64) NOT NULL,
    season INT NOT NULL,
    file_type NVARCHAR(64) NOT NULL,
    blob_path NVARCHAR(1024) NOT NULL,
    version_label NVARCHAR(128) NOT NULL,
    ingested_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_reference_files_ingested_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_reference_files_source CHECK (source IN (N'fantasypros')),
    CONSTRAINT CK_reference_files_file_type CHECK (file_type IN (N'adp', N'rankings', N'tiers'))
);

CREATE UNIQUE INDEX UX_reference_files_source_season_type_version
    ON dbo.reference_files (source, season, file_type, version_label);

CREATE TABLE dbo.seasons (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_seasons_id DEFAULT NEWID()
        CONSTRAINT PK_seasons PRIMARY KEY,
    league_id UNIQUEIDENTIFIER NOT NULL,
    season_year INT NOT NULL,
    settings_json NVARCHAR(MAX) NULL,
    team_count INT NULL,
    regular_season_weeks INT NULL,
    playoff_weeks INT NULL,
    champion_team_id UNIQUEIDENTIFIER NULL,
    runner_up_team_id UNIQUEIDENTIFIER NULL,
    import_status NVARCHAR(32) NOT NULL
        CONSTRAINT DF_seasons_import_status DEFAULT N'not_started',
    stats_fresh_as_of DATETIME2(3) NULL,
    last_import_job_id UNIQUEIDENTIFIER NULL,
    last_computed_job_id UNIQUEIDENTIFIER NULL,
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_seasons_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_seasons_leagues
        FOREIGN KEY (league_id) REFERENCES dbo.leagues (id),
    CONSTRAINT FK_seasons_last_import_jobs
        FOREIGN KEY (last_import_job_id) REFERENCES dbo.import_jobs (id),
    CONSTRAINT FK_seasons_last_computed_jobs
        FOREIGN KEY (last_computed_job_id) REFERENCES dbo.import_jobs (id),
    CONSTRAINT CK_seasons_import_status
        CHECK (import_status IN (N'not_started', N'partial', N'complete', N'stale'))
);

CREATE UNIQUE INDEX UX_seasons_league_season_year
    ON dbo.seasons (league_id, season_year);

CREATE TABLE dbo.season_data_coverage (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_season_data_coverage_id DEFAULT NEWID()
        CONSTRAINT PK_season_data_coverage PRIMARY KEY,
    season_id UNIQUEIDENTIFIER NOT NULL,
    has_draft_data BIT NOT NULL
        CONSTRAINT DF_season_data_coverage_has_draft_data DEFAULT 0,
    has_matchup_data BIT NOT NULL
        CONSTRAINT DF_season_data_coverage_has_matchup_data DEFAULT 0,
    has_transaction_data BIT NOT NULL
        CONSTRAINT DF_season_data_coverage_has_transaction_data DEFAULT 0,
    has_roster_data BIT NOT NULL
        CONSTRAINT DF_season_data_coverage_has_roster_data DEFAULT 0,
    has_reference_rankings BIT NOT NULL
        CONSTRAINT DF_season_data_coverage_has_reference_rankings DEFAULT 0,
    last_validated_at DATETIME2(3) NULL,
    CONSTRAINT FK_season_data_coverage_seasons
        FOREIGN KEY (season_id) REFERENCES dbo.seasons (id)
);

CREATE UNIQUE INDEX UX_season_data_coverage_season
    ON dbo.season_data_coverage (season_id);

CREATE TABLE dbo.managers (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_managers_id DEFAULT NEWID()
        CONSTRAINT PK_managers PRIMARY KEY,
    league_id UNIQUEIDENTIFIER NOT NULL,
    external_manager_id NVARCHAR(128) NOT NULL,
    display_name NVARCHAR(200) NOT NULL,
    normalized_name NVARCHAR(200) NULL,
    first_seen_season INT NULL,
    last_seen_season INT NULL,
    CONSTRAINT FK_managers_leagues
        FOREIGN KEY (league_id) REFERENCES dbo.leagues (id)
);

CREATE UNIQUE INDEX UX_managers_league_external_manager
    ON dbo.managers (league_id, external_manager_id);

CREATE TABLE dbo.teams (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_teams_id DEFAULT NEWID()
        CONSTRAINT PK_teams PRIMARY KEY,
    season_id UNIQUEIDENTIFIER NOT NULL,
    manager_id UNIQUEIDENTIFIER NOT NULL,
    external_team_id NVARCHAR(128) NOT NULL,
    team_name NVARCHAR(256) NOT NULL,
    abbrev NVARCHAR(32) NULL,
    wins INT NULL,
    losses INT NULL,
    ties INT NULL,
    points_for DECIMAL(10, 2) NULL,
    points_against DECIMAL(10, 2) NULL,
    final_standing INT NULL,
    made_playoffs BIT NULL,
    is_champion BIT NULL,
    CONSTRAINT FK_teams_seasons
        FOREIGN KEY (season_id) REFERENCES dbo.seasons (id),
    CONSTRAINT FK_teams_managers
        FOREIGN KEY (manager_id) REFERENCES dbo.managers (id)
);

CREATE UNIQUE INDEX UX_teams_season_external_team
    ON dbo.teams (season_id, external_team_id);

ALTER TABLE dbo.seasons
    ADD CONSTRAINT FK_seasons_champion_teams
        FOREIGN KEY (champion_team_id) REFERENCES dbo.teams (id);

ALTER TABLE dbo.seasons
    ADD CONSTRAINT FK_seasons_runner_up_teams
        FOREIGN KEY (runner_up_team_id) REFERENCES dbo.teams (id);

CREATE TABLE dbo.matchups (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_matchups_id DEFAULT NEWID()
        CONSTRAINT PK_matchups PRIMARY KEY,
    season_id UNIQUEIDENTIFIER NOT NULL,
    week_number INT NOT NULL,
    matchup_type NVARCHAR(32) NOT NULL,
    home_team_id UNIQUEIDENTIFIER NOT NULL,
    away_team_id UNIQUEIDENTIFIER NOT NULL,
    home_score DECIMAL(10, 2) NULL,
    away_score DECIMAL(10, 2) NULL,
    winner_team_id UNIQUEIDENTIFIER NULL,
    is_complete BIT NOT NULL
        CONSTRAINT DF_matchups_is_complete DEFAULT 0,
    CONSTRAINT FK_matchups_seasons
        FOREIGN KEY (season_id) REFERENCES dbo.seasons (id),
    CONSTRAINT FK_matchups_home_teams
        FOREIGN KEY (home_team_id) REFERENCES dbo.teams (id),
    CONSTRAINT FK_matchups_away_teams
        FOREIGN KEY (away_team_id) REFERENCES dbo.teams (id),
    CONSTRAINT FK_matchups_winner_teams
        FOREIGN KEY (winner_team_id) REFERENCES dbo.teams (id),
    CONSTRAINT CK_matchups_matchup_type CHECK (matchup_type IN (N'regular', N'playoff'))
);

CREATE INDEX IX_matchups_season_week
    ON dbo.matchups (season_id, week_number);

CREATE TABLE dbo.weekly_team_scores (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_weekly_team_scores_id DEFAULT NEWID()
        CONSTRAINT PK_weekly_team_scores PRIMARY KEY,
    season_id UNIQUEIDENTIFIER NOT NULL,
    team_id UNIQUEIDENTIFIER NOT NULL,
    week_number INT NOT NULL,
    actual_points DECIMAL(10, 2) NULL,
    optimal_points DECIMAL(10, 2) NULL,
    bench_points DECIMAL(10, 2) NULL,
    lineup_efficiency DECIMAL(9, 6) NULL,
    all_play_wins INT NULL,
    all_play_losses INT NULL,
    CONSTRAINT FK_weekly_team_scores_seasons
        FOREIGN KEY (season_id) REFERENCES dbo.seasons (id),
    CONSTRAINT FK_weekly_team_scores_teams
        FOREIGN KEY (team_id) REFERENCES dbo.teams (id)
);

CREATE UNIQUE INDEX UX_weekly_team_scores_team_week
    ON dbo.weekly_team_scores (team_id, week_number);

CREATE TABLE dbo.drafts (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_drafts_id DEFAULT NEWID()
        CONSTRAINT PK_drafts PRIMARY KEY,
    season_id UNIQUEIDENTIFIER NOT NULL,
    draft_date DATETIME2(3) NULL,
    draft_type NVARCHAR(64) NULL,
    pick_count INT NULL,
    CONSTRAINT FK_drafts_seasons
        FOREIGN KEY (season_id) REFERENCES dbo.seasons (id)
);

CREATE UNIQUE INDEX UX_drafts_season
    ON dbo.drafts (season_id);

CREATE TABLE dbo.draft_picks (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_draft_picks_id DEFAULT NEWID()
        CONSTRAINT PK_draft_picks PRIMARY KEY,
    draft_id UNIQUEIDENTIFIER NOT NULL,
    team_id UNIQUEIDENTIFIER NOT NULL,
    overall_pick INT NOT NULL,
    round_number INT NULL,
    round_pick INT NULL,
    player_name NVARCHAR(256) NOT NULL,
    player_external_id NVARCHAR(128) NULL,
    position NVARCHAR(32) NULL,
    nfl_team NVARCHAR(32) NULL,
    fantasypros_rank_id UNIQUEIDENTIFIER NULL,
    fantasypros_adp DECIMAL(10, 3) NULL,
    reach_value DECIMAL(10, 3) NULL,
    value_delta DECIMAL(10, 3) NULL,
    CONSTRAINT FK_draft_picks_drafts
        FOREIGN KEY (draft_id) REFERENCES dbo.drafts (id),
    CONSTRAINT FK_draft_picks_teams
        FOREIGN KEY (team_id) REFERENCES dbo.teams (id)
);

CREATE UNIQUE INDEX UX_draft_picks_draft_overall_pick
    ON dbo.draft_picks (draft_id, overall_pick);

CREATE TABLE dbo.transactions (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_transactions_id DEFAULT NEWID()
        CONSTRAINT PK_transactions PRIMARY KEY,
    season_id UNIQUEIDENTIFIER NOT NULL,
    team_id UNIQUEIDENTIFIER NULL,
    week_number INT NULL,
    transaction_type NVARCHAR(32) NOT NULL,
    player_name NVARCHAR(256) NOT NULL,
    player_external_id NVARCHAR(128) NULL,
    created_at_source DATETIME2(3) NULL,
    CONSTRAINT FK_transactions_seasons
        FOREIGN KEY (season_id) REFERENCES dbo.seasons (id),
    CONSTRAINT FK_transactions_teams
        FOREIGN KEY (team_id) REFERENCES dbo.teams (id),
    CONSTRAINT CK_transactions_transaction_type
        CHECK (transaction_type IN (N'add', N'drop', N'trade', N'waiver'))
);

CREATE INDEX IX_transactions_season_week
    ON dbo.transactions (season_id, week_number);

CREATE TABLE dbo.player_reference (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_player_reference_id DEFAULT NEWID()
        CONSTRAINT PK_player_reference PRIMARY KEY,
    canonical_player_name NVARCHAR(256) NOT NULL,
    position NVARCHAR(32) NULL,
    nfl_team NVARCHAR(32) NULL,
    external_keys_json NVARCHAR(MAX) NULL
);

CREATE TABLE dbo.reference_rankings (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_reference_rankings_id DEFAULT NEWID()
        CONSTRAINT PK_reference_rankings PRIMARY KEY,
    season INT NOT NULL,
    source NVARCHAR(64) NOT NULL,
    ranking_type NVARCHAR(64) NOT NULL,
    [format] NVARCHAR(64) NULL,
    scoring NVARCHAR(64) NULL,
    published_label NVARCHAR(128) NOT NULL,
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_reference_rankings_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_reference_rankings_source CHECK (source IN (N'fantasypros')),
    CONSTRAINT CK_reference_rankings_ranking_type
        CHECK (ranking_type IN (N'overall_rank', N'adp', N'ppr_adp', N'half_ppr_adp'))
);

CREATE UNIQUE INDEX UX_reference_rankings_identity
    ON dbo.reference_rankings (season, source, ranking_type, [format], scoring, published_label);

CREATE TABLE dbo.reference_ranking_items (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_reference_ranking_items_id DEFAULT NEWID()
        CONSTRAINT PK_reference_ranking_items PRIMARY KEY,
    reference_ranking_id UNIQUEIDENTIFIER NOT NULL,
    player_reference_id UNIQUEIDENTIFIER NOT NULL,
    rank_value DECIMAL(10, 3) NULL,
    adp_value DECIMAL(10, 3) NULL,
    position_rank INT NULL,
    raw_player_name NVARCHAR(256) NOT NULL,
    raw_team NVARCHAR(32) NULL,
    raw_position NVARCHAR(32) NULL,
    CONSTRAINT FK_reference_ranking_items_reference_rankings
        FOREIGN KEY (reference_ranking_id) REFERENCES dbo.reference_rankings (id),
    CONSTRAINT FK_reference_ranking_items_player_reference
        FOREIGN KEY (player_reference_id) REFERENCES dbo.player_reference (id)
);

CREATE INDEX IX_reference_ranking_items_ranking
    ON dbo.reference_ranking_items (reference_ranking_id);

ALTER TABLE dbo.draft_picks
    ADD CONSTRAINT FK_draft_picks_reference_ranking_items
        FOREIGN KEY (fantasypros_rank_id) REFERENCES dbo.reference_ranking_items (id);

CREATE TABLE dbo.metric_definitions (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_metric_definitions_id DEFAULT NEWID()
        CONSTRAINT PK_metric_definitions PRIMARY KEY,
    metric_name NVARCHAR(128) NOT NULL,
    metric_version NVARCHAR(32) NOT NULL,
    description NVARCHAR(MAX) NULL,
    is_current BIT NOT NULL
        CONSTRAINT DF_metric_definitions_is_current DEFAULT 1,
    created_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_metric_definitions_created_at DEFAULT SYSUTCDATETIME()
);

CREATE UNIQUE INDEX UX_metric_definitions_name_version
    ON dbo.metric_definitions (metric_name, metric_version);

CREATE TABLE dbo.league_metrics (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_league_metrics_id DEFAULT NEWID()
        CONSTRAINT PK_league_metrics PRIMARY KEY,
    league_id UNIQUEIDENTIFIER NOT NULL,
    season_id UNIQUEIDENTIFIER NULL,
    metric_definition_id UNIQUEIDENTIFIER NOT NULL,
    metric_value_json NVARCHAR(MAX) NOT NULL,
    computed_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_league_metrics_computed_at DEFAULT SYSUTCDATETIME(),
    job_id UNIQUEIDENTIFIER NOT NULL,
    CONSTRAINT FK_league_metrics_leagues
        FOREIGN KEY (league_id) REFERENCES dbo.leagues (id),
    CONSTRAINT FK_league_metrics_seasons
        FOREIGN KEY (season_id) REFERENCES dbo.seasons (id),
    CONSTRAINT FK_league_metrics_metric_definitions
        FOREIGN KEY (metric_definition_id) REFERENCES dbo.metric_definitions (id),
    CONSTRAINT FK_league_metrics_import_jobs
        FOREIGN KEY (job_id) REFERENCES dbo.import_jobs (id)
);

CREATE INDEX IX_league_metrics_lookup
    ON dbo.league_metrics (league_id, season_id, metric_definition_id, computed_at);

CREATE TABLE dbo.manager_metrics (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_manager_metrics_id DEFAULT NEWID()
        CONSTRAINT PK_manager_metrics PRIMARY KEY,
    league_id UNIQUEIDENTIFIER NOT NULL,
    manager_id UNIQUEIDENTIFIER NOT NULL,
    season_id UNIQUEIDENTIFIER NULL,
    metric_definition_id UNIQUEIDENTIFIER NOT NULL,
    metric_value_numeric DECIMAL(18, 6) NULL,
    metric_value_json NVARCHAR(MAX) NULL,
    rank_within_league INT NULL,
    computed_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_manager_metrics_computed_at DEFAULT SYSUTCDATETIME(),
    job_id UNIQUEIDENTIFIER NOT NULL,
    CONSTRAINT FK_manager_metrics_leagues
        FOREIGN KEY (league_id) REFERENCES dbo.leagues (id),
    CONSTRAINT FK_manager_metrics_managers
        FOREIGN KEY (manager_id) REFERENCES dbo.managers (id),
    CONSTRAINT FK_manager_metrics_seasons
        FOREIGN KEY (season_id) REFERENCES dbo.seasons (id),
    CONSTRAINT FK_manager_metrics_metric_definitions
        FOREIGN KEY (metric_definition_id) REFERENCES dbo.metric_definitions (id),
    CONSTRAINT FK_manager_metrics_import_jobs
        FOREIGN KEY (job_id) REFERENCES dbo.import_jobs (id)
);

CREATE INDEX IX_manager_metrics_lookup
    ON dbo.manager_metrics (league_id, manager_id, season_id, metric_definition_id, computed_at);

CREATE TABLE dbo.team_metrics (
    id UNIQUEIDENTIFIER NOT NULL
        CONSTRAINT DF_team_metrics_id DEFAULT NEWID()
        CONSTRAINT PK_team_metrics PRIMARY KEY,
    team_id UNIQUEIDENTIFIER NOT NULL,
    season_id UNIQUEIDENTIFIER NOT NULL,
    metric_definition_id UNIQUEIDENTIFIER NOT NULL,
    metric_value_numeric DECIMAL(18, 6) NULL,
    metric_value_json NVARCHAR(MAX) NULL,
    computed_at DATETIME2(3) NOT NULL
        CONSTRAINT DF_team_metrics_computed_at DEFAULT SYSUTCDATETIME(),
    job_id UNIQUEIDENTIFIER NOT NULL,
    CONSTRAINT FK_team_metrics_teams
        FOREIGN KEY (team_id) REFERENCES dbo.teams (id),
    CONSTRAINT FK_team_metrics_seasons
        FOREIGN KEY (season_id) REFERENCES dbo.seasons (id),
    CONSTRAINT FK_team_metrics_metric_definitions
        FOREIGN KEY (metric_definition_id) REFERENCES dbo.metric_definitions (id),
    CONSTRAINT FK_team_metrics_import_jobs
        FOREIGN KEY (job_id) REFERENCES dbo.import_jobs (id)
);

CREATE INDEX IX_team_metrics_lookup
    ON dbo.team_metrics (team_id, season_id, metric_definition_id, computed_at);
